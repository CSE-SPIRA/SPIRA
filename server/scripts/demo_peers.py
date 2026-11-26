"""Hub installation and Simulator profile for the demo home, written from the same DEMO_HOME the server seeds.

    cd server
    python scripts/demo_peers.py --home dev/home.yaml --household "$SPIRA_HOUSEHOLD_ID"

The hub registers its own device list (`PUT /v1/hub/households/{id}/devices`) and the server plans with that list,
so the hub, the server's demo home and the Simulator must name the same devices with the same commands and values.
This writes, into `out/peers/` (git-ignored):

- `installation.json` for the hub's `--installation`: the demo home's devices (same ids, rooms, commands and
  revision; `substrate` as in the Simulator) with the bindings of `hub/installation.example.json`, plus bindings
  for the extra devices below.
- `profile.json` for the Simulator's `WORLD_PROFILE`: `simulator/spira_simulator/profiles/ep_9031.json` with this
  household id, and the extra devices' property schemas widened to the demo home's values.

Devices the Simulator has but the demo home does not (the air conditioner) stay in the Simulator, not delegated.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
ROOT = SERVER.parent
sys.path.insert(0, str(SERVER))

HUB_BASE = ROOT / "hub" / "installation.example.json"
SIM_BASE = ROOT / "simulator" / "spira_simulator" / "profiles" / "ep_9031.json"

# cmd -> hub binding for the devices installation.example.json does not have
EXTRA_BINDINGS = {
    "styler": {"set_course_standby": "course_standby"},
    "purifier": {"mode": {"properties": {"mode": "mode"}}, "off": {"fixed": {"power": False}}},
}


def _enum(device: dict, cmd: str, field: str) -> list:
    for c in device.get("commands", []):
        if c["cmd"] == cmd:
            return list(((c.get("value_schema") or {}).get(field) or {}).get("enum") or [])
    return []


def installation(devices: dict) -> dict:
    """Same ids, rooms and commands as the demo home; `substrate` from the Simulator (its devices are virtual: the
    hub refuses a physical device it has no driver for)."""
    base = json.loads(HUB_BASE.read_text(encoding="utf-8"))
    sim = {d["logical_id"]: d for d in json.loads(SIM_BASE.read_text(encoding="utf-8"))["devices"]}
    bindings = {}
    for d in devices["devices"]:
        if d["id"] in base["bindings"]:
            bindings[d["id"]] = base["bindings"][d["id"]]
            continue
        extra = EXTRA_BINDINGS.get(d["type"])
        if extra is None:
            raise SystemExit(f"no hub binding for {d['id']} ({d['type']}): add it to EXTRA_BINDINGS")
        bindings[d["id"]] = {"target": f"mqtt:{d['id']}",
                             "commands": {c["cmd"]: extra[c["cmd"]] for c in d["commands"]}}
    body = copy.deepcopy(devices)
    body.setdefault("updated_at", "2026-10-01T10:00:00+09:00")
    for d in body["devices"]:
        if d["id"] in sim:
            d["substrate"] = sim[d["id"]]["substrate"]
    return {"devices": body, "bindings": bindings, "home_signals": base["home_signals"]}


def profile(devices: dict, household_id: str) -> dict:
    base = json.loads(SIM_BASE.read_text(encoding="utf-8"))
    out = copy.deepcopy(base)
    out["household_id"] = household_id
    home = {d["id"]: d for d in devices["devices"]}
    for dev in out["devices"]:
        d = home.get(dev["logical_id"])
        if d is None:
            continue
        props = dev["properties"]
        if d["type"] == "styler":
            courses = _enum(d, "set_course_standby", "course")
            if courses:
                props["course_standby"]["schema"]["properties"]["course"]["enum"] = courses
        if d["type"] == "purifier":
            modes = _enum(d, "mode", "mode")
            if modes:
                props["mode"]["schema"]["enum"] = modes
                if props["mode"]["initial"] not in modes:
                    props["mode"]["initial"] = modes[0]
            if any(c["cmd"] == "off" for c in d["commands"]):
                props.setdefault("power", {"initial": True, "schema": {"type": "boolean"}})
            dev["commands"] = [c["cmd"] for c in d["commands"]]
    missing = sorted(set(home) - {dev["logical_id"] for dev in out["devices"]})
    if missing:
        raise SystemExit(f"the Simulator has no device for {missing}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home", required=True, type=Path)
    p.add_argument("--household", help="household id instead of the one in the yaml")
    p.add_argument("--out", type=Path, default=SERVER / "out" / "peers")
    args = p.parse_args(argv)

    from spira_server import clock
    from spira_server.dev.seed import HomeError, load_home

    try:
        home = load_home(args.home, clock.now())
    except HomeError as e:
        print(f"home.yaml: {e}", file=sys.stderr)
        return 2
    hid = args.household or home.household_id
    devices = {**home.devices, "household_id": hid}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "installation.json").write_text(
        json.dumps(installation(devices), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "profile.json").write_text(
        json.dumps(profile(devices, hid), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{hid}: {len(devices['devices'])} devices -> {args.out}/installation.json, profile.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
