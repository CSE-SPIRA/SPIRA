"""Hub installation and Simulator profile for the demo home, written from the same DEMO_HOME the server seeds.

    cd server
    python scripts/demo_peers.py --home dev/home.yaml --household "$SPIRA_HOUSEHOLD_ID"

The hub registers its own device list (`PUT /v1/hub/households/{id}/devices`) and the server plans with that list,
so the hub, the server's demo home and the Simulator must name the same devices with the same commands and values.
This writes, into `out/peers/` (git-ignored):

- `installation.json` for the hub's `--installation`: the demo home's devices (same ids, rooms, commands and
  revision; virtual) with the bindings of `hub/installation.example.json`, and bindings derived from the command
  for anything that file does not cover.
- `profile.json` for the Simulator's `WORLD_PROFILE`: `simulator/spira_simulator/profiles/ep_9031.json` with this
  household id; devices the demo home adds get properties for their commands (no 3D place yet).
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

# Simulator room codes (demo-shell/design/vocabulary.json "rooms"); other rooms keep a code of their own.
ROOMS = {"현관": "entrance", "거실": "living_room", "주방": "kitchen", "침실": "bedroom",
         "드레스룸": "dressing_room", "다용도실": "utility_room"}
OFF = {"fixed": {"power": False}}


def _field_schema(rule: dict) -> tuple[dict, object]:
    """(JSON schema, initial) for one value field of a device command (`enum` or `range`, with `default`)."""
    if "enum" in rule:
        return {"enum": list(rule["enum"])}, rule.get("default", rule["enum"][0])
    lo, hi = rule["range"]
    kind = "integer" if all(isinstance(x, int) for x in (lo, hi)) else "number"
    return {"type": kind, "minimum": lo, "maximum": hi}, rule.get("default", lo)


def _binding(cmd: dict) -> object:
    """Hub mapping for a command the example installation has no binding for (hub config.check_mapping):
    no value -> a fixed property (`off` -> power false), text -> one property, fields -> one property each."""
    schema = cmd.get("value_schema")
    if schema is None:
        return OFF if cmd["cmd"] == "off" else {"fixed": {cmd["cmd"]: True}}
    if schema == "text":
        return cmd["cmd"]
    return {"properties": {name: name for name in schema}}


def _properties(device: dict, bindings: dict) -> dict:
    """Simulator properties that accept every value the hub's mappings for this device can write."""
    props: dict = {}
    for cmd in device["commands"]:
        mapping, schema = bindings[cmd["cmd"]], cmd.get("value_schema")
        if isinstance(mapping, str):
            if mapping != "course_standby":                    # the styler's own object property stays
                props.setdefault(mapping, {"initial": "", "schema": {"type": "string"}})
        elif "fixed" in mapping:
            for name, value in mapping["fixed"].items():
                props.setdefault(name, {"initial": not value if isinstance(value, bool) else value,
                                        "schema": {"type": "boolean"} if isinstance(value, bool) else {}})
        else:
            for field, prop in mapping["properties"].items():
                sch, initial = _field_schema(schema[field])
                props.setdefault(prop, {"initial": initial, "schema": sch})
    return props


def installation(devices: dict) -> dict:
    """Same ids, rooms, commands and revision as the demo home; `substrate` virtual (the Simulator's devices are,
    and the hub refuses a physical device it has no driver for). Bindings: `hub/installation.example.json` where it
    has one for that command, else derived from the command (`_binding`)."""
    base = json.loads(HUB_BASE.read_text(encoding="utf-8"))
    bindings = {}
    body = copy.deepcopy(devices)
    body.setdefault("updated_at", "2026-10-01T10:00:00+09:00")
    for d in body["devices"]:
        d["substrate"] = "virtual"
        known = base["bindings"].get(d["id"], {})
        commands = {c["cmd"]: known.get("commands", {}).get(c["cmd"]) or _binding(c) for c in d["commands"]}
        if d["type"] == "styler":                              # the Simulator's styler takes {"course": …}
            commands["set_course_standby"] = "course_standby"
        bindings[d["id"]] = {"target": known.get("target", f"mqtt:{d['id']}"), "commands": commands}
    return {"devices": body, "bindings": bindings, "home_signals": base["home_signals"]}


def profile(devices: dict, household_id: str, bindings: dict) -> dict:
    """The Simulator's ep_9031 house with this household id. A device the house already has keeps its look and gets
    the properties the demo home's commands need; a device it lacks is added (state and commands work; it has no
    place in the 3D house until the Simulator draws one). Devices the demo home lacks (the air conditioner) stay."""
    out = copy.deepcopy(json.loads(SIM_BASE.read_text(encoding="utf-8")))
    out["household_id"] = household_id
    by_id = {dev["logical_id"]: dev for dev in out["devices"]}
    for d in devices["devices"]:
        need = _properties(d, bindings[d["id"]]["commands"])
        dev = by_id.get(d["id"])
        if dev is None:
            dev = {"target": bindings[d["id"]]["target"], "logical_id": d["id"], "device_type": d["type"],
                   "room": ROOMS.get(d["room"], "other_room"),
                   "label": d.get("label"), "substrate": "virtual", "available": True,
                   "local_operation_reporting": False, "commands": [], "properties": {}}
            out["devices"].append(dev)
        for name, prop in need.items():
            old = dev["properties"].get(name)
            if old is None:
                dev["properties"][name] = prop
            elif "enum" in prop["schema"]:                      # widen to the demo home's values
                old["schema"]["enum"] = prop["schema"]["enum"]
                if old["initial"] not in prop["schema"]["enum"]:
                    old["initial"] = prop["initial"]
        if d["type"] == "styler" and "course_standby" in dev["properties"]:
            courses = [c for c in d["commands"] if c["cmd"] == "set_course_standby"]
            if courses:
                rule = dev["properties"]["course_standby"]["schema"]["properties"]["course"]
                rule["enum"] = list(courses[0]["value_schema"]["course"]["enum"])
        dev["commands"] = [c["cmd"] for c in d["commands"]]
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
    inst = installation(devices)
    (args.out / "installation.json").write_text(
        json.dumps(inst, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out / "profile.json").write_text(
        json.dumps(profile(devices, hid, inst["bindings"]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{hid}: {len(devices['devices'])} devices -> {args.out}/installation.json, profile.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
