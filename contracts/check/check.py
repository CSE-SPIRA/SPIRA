"""Check that contracts/ is consistent. Run in CI on every PR: python contracts/check/check.py

1. enums.json == enum lists in schemas/common.json, and every enums.json used_in path exists.
2. kb/ lists: ids unique, related tags exist, counts.
3. Every fixture (fixtures/*/manifest.json) passes its schema and the cross-file rules below,
   including household types (known values, one per pick-one axis, no blocked combination).
4. Every case in check/bad/ fails (proves the checks bite).
5. openapi/*.yaml are valid OpenAPI 3.1 and all $refs resolve.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]          # contracts/
SCHEMAS = ROOT / "schemas"
ERRORS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def camel(s: str) -> str:
    return "".join(x.capitalize() for x in s.split("_"))


# ---------- schemas ----------
SCHEMA_DOCS = {p.name: load(p) for p in sorted(SCHEMAS.glob("*.json"))}
REGISTRY = Registry().with_resources(
    (name, Resource.from_contents(doc)) for name, doc in SCHEMA_DOCS.items()
)


def schema_errors(instance, schema_name: str) -> list[str]:
    v = Draft202012Validator({"$ref": schema_name}, registry=REGISTRY)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: [{e.validator}] {e.message[:160]}" for e in v.iter_errors(instance)]


# ---------- 1. enums ----------
ENUMS = load(ROOT / "enums.json")
COMMON = SCHEMA_DOCS["common.json"]["$defs"]


def check_enums() -> None:
    for key, spec in ENUMS.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("open"):
            continue
        d = COMMON.get(camel(key))
        if d is None:
            err(f"enums.json '{key}': no {camel(key)} in schemas/common.json")
        elif d.get("enum") != spec["values"]:
            err(f"enums.json '{key}' != common.json {camel(key)}: {spec['values']} vs {d.get('enum')}")
        for path in spec.get("used_in", []):
            if not path_exists(path):
                err(f"enums.json '{key}': used_in path not found: {path}")


def resolve(node: dict, base: str) -> tuple[dict, str]:
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        file, _, frag = ref.partition("#")
        base = file or base
        node = SCHEMA_DOCS[base]
        for part in [p for p in frag.split("/") if p]:
            node = node[part]
    return node, base


def children(node: dict, base: str):
    node, base = resolve(node, base)
    yield node, base
    for k in ("oneOf", "anyOf", "allOf"):
        for sub in node.get(k, []):
            yield from children(sub, base)
    for k in ("then", "else"):
        if k in node:
            yield from children(node[k], base)


def path_exists(path: str) -> bool:
    stem, _, rest = path.partition(".")
    base = f"{stem}.json"
    if base not in SCHEMA_DOCS:
        return False
    nodes = [(SCHEMA_DOCS[base], base)]
    for token in [t for t in re.split(r"\.", rest) if t] if rest else []:
        name, is_arr = (token[:-2], True) if token.endswith("[]") else (token, False)
        nxt = []
        for n, b in nodes:
            for c, cb in children(n, b):
                if name and name in c.get("properties", {}):
                    nxt.append((c["properties"][name], cb))
                elif not name and "items" in c:
                    nxt.append((c["items"], cb))
        if is_arr and name:
            nxt = [(c["items"], cb) for n, b in nxt for c, cb in children(n, b) if "items" in c]
        if not nxt:
            return False
        nodes = nxt
    return True


# ---------- 2. kb ----------
def check_kb() -> None:
    intents = load(ROOT / "kb/intents.json")
    tags = load(ROOT / "kb/calendar_tags.json")
    house = load(ROOT / "kb/household_types.json")
    ids = [i["id"] for i in intents["intents"]]
    if len(ids) != len(set(ids)):
        err("kb/intents.json: duplicate intent id")
    if set(ids) & set(intents["reserved"]):
        err("kb/intents.json: an intent id uses a reserved id")
    tag_names = {t["tag"] for t in tags["tags"]}
    for i in intents["intents"]:
        for t in i["related_tags"]:
            if t not in tag_names:
                err(f"kb/intents.json {i['id']}: related tag '{t}' not in calendar_tags.json")
    n_types = sum(len(a["types"]) for a in house["axes"].values())
    for name, got, want in (("intents", len(ids), 30), ("calendar tags", len(tag_names), 30), ("household types", n_types, 20)):
        if got != want:
            err(f"kb: expected {want} {name}, found {got}")
    for intent in house["intent_requirements"]:
        if intent not in ids:
            err(f"kb/household_types.json: intent_requirements '{intent}' not in intents.json")


# ---------- household types (kb/household_types.json) ----------
HOUSE = load(ROOT / "kb/household_types.json")


def min_people(t: set[str]) -> int:
    n = (2 if "부부·커플" in t else 1) + sum(c in t for c in HOUSE["child_types"]) + (1 if "부모 + 성인 자녀" in t else 0)
    return max(n, 3) if "3대 함께" in t else n


def household_problem(types: list[str]) -> str | None:
    """None if the app could store these types; else why not. Same rules as SPIRA_KB spira/household.py rule_level
    (blocked only; rare is allowed) and server/spira_server/kb/household.py."""
    known = {x for a in HOUSE["axes"].values() for x in a["types"]}
    unknown = [x for x in types if x not in known]
    if unknown:
        return f"unknown household type {unknown}"
    for axis, spec in HOUSE["axes"].items():
        if spec["pick"] == "one" and sum(x in spec["types"] for x in types) > 1:
            return f"more than one {axis}"
    t = set(types)
    size = next((x for x in HOUSE["axes"]["size"]["types"] if x in t), None)
    kids = {c for c in HOUSE["child_types"] if c in t}
    cap = HOUSE["size_max"].get(size)
    if cap is not None and min_people(t) > cap:
        return f"blocked: at least {min_people(t)} people but size is {size}"
    if "룸메이트·셰어하우스" in t and (t & {"부부·커플", "부모 + 성인 자녀", "3대 함께"} or kids):
        return "blocked: 룸메이트·셰어하우스 with a family type"
    if "맞벌이" in t and "부부·커플" not in t:
        return "blocked: 맞벌이 without 부부·커플"
    if "은퇴·노년" in t and t & {"맞벌이", "재택근무"}:
        return "blocked: 은퇴·노년 with 맞벌이 or 재택근무"
    return None


def household_types_of(schema: str, doc) -> list[list[str]]:
    if schema in ("household_create.json", "profile.json"):
        return [doc["household_types"]]
    if schema == "case_row.json":
        types = doc["household"]["types"]
        return [types] if types else []
    return []


# ---------- 3. cross-file rules ----------
def device_map(devices: dict) -> dict:
    return {d["id"]: d for d in devices["devices"]}


def check_value(where: str, action: dict, device: dict) -> None:
    cmds = {c["cmd"]: c for c in device["commands"]}
    cmd = action["cmd"]
    if cmd in device.get("never", []):
        err(f"{where}: {device['id']}.{cmd} is in never")
        return
    if cmd not in cmds:
        err(f"{where}: {device['id']} has no delegated command '{cmd}'")
        return
    vs = cmds[cmd].get("value_schema")
    val = action.get("value")
    if vs is None:
        if val is not None:
            err(f"{where}: {device['id']}.{cmd} takes no value")
    elif vs == "text":
        if not isinstance(val, str):
            err(f"{where}: {device['id']}.{cmd} needs a text value")
    else:
        if not isinstance(val, dict):
            err(f"{where}: {device['id']}.{cmd} needs an object value")
            return
        if set(val) != set(vs):
            err(f"{where}: {device['id']}.{cmd} parameters {sorted(val)} != {sorted(vs)}")
        for p, rule in vs.items():
            if p not in val:
                continue
            x = val[p]
            if "range" in rule:
                lo, hi = rule["range"]
                if not isinstance(x, (int, float)) or not lo <= x <= hi:
                    err(f"{where}: {device['id']}.{cmd}.{p}={x!r} outside {rule['range']}")
            elif x not in rule["enum"]:
                err(f"{where}: {device['id']}.{cmd}.{p}={x!r} not in {rule['enum']}")


def check_plan(name: str, plan: dict, devices: dict | None) -> None:
    seen = set()
    for t in plan["tasks"]:
        if t["task_id"] in seen:
            err(f"{name}: duplicate task {t['task_id']}")
        seen.add(t["task_id"])
        trg = t["trigger"]
        if ("released" in trg or "at" in trg) and trg.get("event") != "package.brought_in":
            err(f"{name} {t['task_id']}: released/at only for package.brought_in")
        if trg.get("at") and not trg.get("released"):
            err(f"{name} {t['task_id']}: at needs released true")
        if t["way"] == "notice" and any(a["cmd"] != "show_notice" for a in t["actions"]):
            pass  # notice is a usage hint; not every notice device is a fridge
        if devices:
            if plan["devices_revision"] != devices["revision"]:
                err(f"{name}: devices_revision {plan['devices_revision']} != devices revision {devices['revision']}")
            dm = device_map(devices)
            for a in t["actions"]:
                if a["device"] not in dm:
                    err(f"{name} {t['task_id']}: unknown device {a['device']}")
                else:
                    check_value(f"{name} {t['task_id']}", a, dm[a["device"]])
    for c in plan["cancelled"]:
        if c["task_id"] in seen:
            err(f"{name}: {c['task_id']} is both live and cancelled")


def check_events(name: str, events: list, devices: dict | None) -> None:
    dm = device_map(devices) if devices else {}
    ids = [e["event_id"] for e in events]
    if len(ids) != len(set(ids)):
        err(f"{name}: duplicate event_id")
    times = [e["at"] for e in events]
    if times != sorted(times):
        err(f"{name}: events are not in time order")
    for e in events:
        if e["source"] == "hub" or not dm:
            continue
        dev = dm.get(e["source"])
        if dev is None:
            err(f"{name} {e['event_id']}: unknown device {e['source']}")
            continue
        dtype, _, devent = e["type"].partition(".")
        if dtype != dev["type"]:
            err(f"{name} {e['event_id']}: type prefix '{dtype}' != device type '{dev['type']}'")
        if devent not in dev["events"]:
            err(f"{name} {e['event_id']}: '{devent}' not in {dev['id']} events {dev['events']}")


def check_scenario(folder: Path, manifest: dict, data: dict) -> None:
    devices = load(folder / manifest["devices"]) if manifest.get("devices") else None
    plans = [(n, d) for n, d in data.items() if manifest["files"][n]["schema"] == "plan.json"]
    versions = [p["plan_version"] for _, p in plans]
    if versions != sorted(versions) or len(set(versions)) != len(versions):
        err(f"{folder.name}: plan versions must increase in manifest order: {versions}")
    by_version = {p["plan_version"]: p for _, p in plans}
    for n, p in plans:
        check_plan(f"{folder.name}/{n}", p, devices)
    all_tasks = {t["task_id"]: t for _, p in plans for t in p["tasks"]}
    for n, d in data.items():
        schema = manifest["files"][n]["schema"]
        where = f"{folder.name}/{n}"
        for types in household_types_of(schema, d):
            problem = household_problem(types)
            if problem:
                err(f"{where}: household types {types}: {problem}")
        if schema == "plan_pull.json":
            for p in d["plans"]:
                check_plan(where, p, devices)
        if schema == "event_batch.json":
            check_events(where, d, devices)
        if schema == "card.json":
            for ln in d["lines"]:
                if ln["state"] != "held" and ln["task_id"] not in all_tasks:
                    err(f"{where}: line {ln['task_id']} not in any plan")
                elif ln["task_id"] in all_tasks and all_tasks[ln["task_id"]]["source"] != "situation":
                    err(f"{where}: line {ln['task_id']} is not a situation task")
        if schema == "reaction.json":
            for r in d:
                if r.get("task_id") and r["task_id"] not in all_tasks:
                    err(f"{where}: reaction for unknown task {r['task_id']}")
        if schema == "execution_result.json":
            ids = [r["result_id"] for r in d]
            if len(ids) != len(set(ids)):
                err(f"{where}: duplicate result_id")
            for r in d:
                plan = by_version.get(r["plan_version"])
                if plan is None:
                    err(f"{where} {r['result_id']}: no plan version {r['plan_version']} in this scenario")
                    continue
                task = next((t for t in plan["tasks"] if t["task_id"] == r["task_id"]), None)
                if task is None:
                    err(f"{where} {r['result_id']}: {r['task_id']} not in plan v{r['plan_version']}")
                    continue
                pairs = {(a["device"], a["cmd"]) for a in task["actions"]}
                if r["kind"] == "run" and (r["device"], r["cmd"]) not in pairs:
                    err(f"{where} {r['result_id']}: {r['device']}.{r['cmd']} not an action of {r['task_id']}")
                if r["kind"] == "restore" and not {i["device"] for i in r["items"]} <= {a for a, _ in pairs}:
                    err(f"{where} {r['result_id']}: restore of a device outside {r['task_id']}")


def run_folder(folder: Path, expect_ok: bool = True) -> list[str]:
    """Validate one manifest folder. Returns the errors found (also recorded when expect_ok)."""
    global ERRORS
    saved, ERRORS = ERRORS, []
    manifest = load(folder / "manifest.json")
    data = {}
    for name, spec in manifest["files"].items():
        inst = load(folder / name)
        items = inst if spec.get("array") else [inst]
        for i, item in enumerate(items):
            for e in schema_errors(item, spec["schema"]):
                err(f"{folder.name}/{name}{f'[{i}]' if spec.get('array') else ''}: {e}")
        data[name] = inst
    if not ERRORS:
        check_scenario(folder, manifest, data)
    found, ERRORS = ERRORS, saved
    return found


def check_fixtures() -> None:
    folders = sorted(p.parent for p in (ROOT / "fixtures").glob("*/manifest.json"))
    if not folders:
        err("no fixtures found")
    for f in folders:
        ERRORS.extend(run_folder(f))


def check_bad() -> None:
    bad_root = ROOT / "check/bad"
    for case in sorted(p.parent for p in bad_root.glob("*/manifest.json")):
        found = run_folder(case)
        want = load(case / "manifest.json").get("expect", "")
        if not found:
            err(f"check/bad/{case.name}: expected a failure ({want}) but it passed")
        elif want and not any(want in f for f in found):
            err(f"check/bad/{case.name}: failed, but not with '{want}': {found[:2]}")


# ---------- 5. openapi ----------
def check_openapi() -> None:
    from openapi_spec_validator import validate
    from openapi_spec_validator.readers import read_from_filename

    for p in sorted((ROOT / "openapi").glob("*.yaml")):
        spec, base_uri = read_from_filename(str(p))
        try:
            validate(spec, base_uri=base_uri)
        except Exception as e:  # noqa: BLE001
            err(f"openapi/{p.name}: {str(e).splitlines()[0][:300]}")
        text = p.read_text(encoding="utf-8")
        for ref in set(re.findall(r"\$ref:\s*['\"]?([^'\"\s#]+)", text)):
            if not (p.parent / ref).resolve().exists():
                err(f"openapi/{p.name}: $ref file not found: {ref}")


def main() -> int:
    for step in (check_enums, check_kb, check_fixtures, check_bad, check_openapi):
        step()
    if ERRORS:
        print(f"FAILED ({len(ERRORS)})")
        for e in ERRORS:
            print(" -", e)
        return 1
    print("contracts OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
