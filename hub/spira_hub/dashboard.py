"""Read-only Hub evidence for operators."""

from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .contracts import offset_time, packet_body
from .plans import action_keys
from .store import encode


def create_app(runtime, *, lifespan=None):
    app = FastAPI(title="SPIRA Home Hub", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok", "server_confirmed": runtime.reconciled
                and runtime.last_pull_error is None, "device_online": runtime.device.online}

    @app.get("/api/state")
    async def state():
        return state_view(runtime)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return render(state_view(runtime))

    return app


def state_view(runtime):
    store = runtime.store
    devices = []
    for device in runtime.installation.devices.devices:
        target = runtime.installation.bindings[device.id].target
        capability = runtime.capabilities.get(target)
        devices.append({
            "device": device.id, "target": target, "substrate": device.substrate.value,
            "observed_substrate": capability.substrate if capability else None,
            "assumption": capability.assumption if capability else None,
        })
    waiting = []
    attempts = store.attempts()
    now = runtime.clock()
    snapshot = store.get("snapshot", {})
    for task in store.tasks():
        if (not task["active"] or task["closed"] or not task["body"]
                or task["plan"] not in snapshot.get("plans", [])):
            continue
        trigger = task["body"]["trigger"]
        window = trigger.get("window")
        if (task["triggered_at"] is None and window and now > offset_time(window["to"])):
            continue
        tried = {row["action_key"] for row in attempts
                 if (row["plan"], row["task"]) == (task["plan"], task["id"])}
        remaining = [action for key, action in action_keys(task) if key not in tried]
        if remaining:
            waiting.append({
                "plan_id": task["plan"], "plan_version": task["version"], "task_id": task["id"],
                "actions": remaining, "trigger": trigger, "triggered_at": task["triggered_at"],
            })
    commands = [
        {
            "plan": row["plan"], "task": row["task"], "device": row["action"]["device"],
            "substrate": row["substrate"], "target": row["target"], "binding": row["epoch"],
            "operation_id": row["op"], "kind": row["kind"], "at": row["sent_at"],
            "desired": row["desired"], "acknowledgement": row["ack"],
            "read_back": row["read_back"], "status": row["status"], "reason": row.get("reason"),
        }
        for row in reversed(attempts[-100:])
    ]
    events = [evidence(row) for row in store.evidence("event")]
    restores = [evidence(row) for row in store.evidence("execution", limit=-1)
                if packet_body(row)["kind"] == "restore"][:100]
    return {
        "waiting": waiting, "commands": commands, "events": events, "restoration": restores,
        "devices": devices, "paused": snapshot.get("paused"),
        "server_peer": runtime.server.fixture, "server_error": runtime.last_pull_error,
        "registry_error": runtime.config_error, "observation_gap_at": runtime.observations.gap_at,
        "device_online": runtime.device.online,
    }


def evidence(row):
    return {"delivered": bool(row["delivered"]), "delivery_error": row["error"],
            "packet": packet_body(row)}


def render(state):
    def text(value):
        return escape(str(value))

    def details(value):
        return f"<pre>{text(encode(value))}</pre>"

    def section(title, cards, empty):
        content = "".join(cards) or f'<p class="empty">{text(empty)}</p>'
        return f"<section><h2>{text(title)}</h2>{content}</section>"

    waiting = [
        f'<article><h3>{text(row["task_id"])}</h3><p>{text(row["plan_id"])} · v{row["plan_version"]}</p>'
        f'<p>{text(", ".join(action["device"] + " · " + action["cmd"] for action in row["actions"]))}</p>'
        f'<h4>Trigger</h4>{details(row["trigger"])}</article>'
        for row in state["waiting"]
    ]
    commands = [
        f'<article><h3>{text(row["device"])} <span>{text(row["substrate"])}</span></h3>'
        f'<p>{text(row["kind"])} · {text(row["status"])}'
        f'{text(" · " + row["reason"] if row["reason"] else "")}</p>'
        f'<p class="mono">{text(row["target"])} · {text(row["operation_id"])}</p>'
        f'<dl><dt>Acknowledgement</dt><dd>{text(row["acknowledgement"]["status"] if row["acknowledgement"] else "—")}</dd>'
        f'<dt>Desired properties</dt><dd>{details(row["desired"]) if row["desired"] else "—"}</dd>'
        f'<dt>Read-back</dt><dd>{details(row["read_back"]) if row["read_back"] else "—"}</dd></dl></article>'
        for row in state["commands"]
    ]
    events = []
    for row in state["events"]:
        event = row["packet"][0]
        by = event["payload"].get("by")
        badge = f"<span>{text(by)}</span>" if by else ""
        events.append(
            f'<article><h3>{text(event["type"])} {badge}</h3>'
            f'<p>{text(event["source"])} · {delivery(row)}</p>'
            f'<h4>C-3 payload</h4>{details(row["packet"])}</article>'
        )
    restores = [
        f'<article><h3>{text(row["packet"]["task_id"])}</h3><p>{delivery(row)}</p>'
        f'<ul>{"".join(f"<li>{text(item['device'])} · {text(item['status'])}</li>" for item in row["packet"]["items"])}</ul>'
        f'<p class="mono">{text(row["packet"]["at"])}</p></article>'
        for row in state["restoration"]
    ]
    devices = [
        f'<article><h3>{text(row["device"])} <span>{text(row["substrate"])}</span></h3>'
        f'<p class="mono">{text(row["target"])}</p>'
        + (f'<p><span class="assumption">Class A assumption</span> {text(row["assumption"])}</p>'
           if row["assumption"] else "")
        + (f'<p>Discovered substrate: {text(row["observed_substrate"])}</p>'
           if row["observed_substrate"] is not None and row["observed_substrate"] != row["substrate"] else "")
        + '</article>'
        for row in state["devices"]
    ]
    peer = state["server_peer"] or "Server"
    if state["server_error"]:
        peer += " · pull failed"
    if state["paused"]:
        peer += " · household paused"
    if state["registry_error"]:
        peer += " · installation configuration invalid"
    body = (
        section("Waiting work", waiting, "No tasks waiting.")
        + section("Command acknowledgement and read-back", commands, "No commands or execution blocks recorded.")
        + section("Person actions and C-3 events", events, "No device or home events recorded.")
        + section("Restoration and skips", restores, "No restoration results recorded.")
        + section("Device bindings", devices, "No delegated devices.")
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5"><title>SPIRA Home Hub</title><style>
:root {{ color-scheme: light; color: #172a25; background: #f3f6f1; font: 16px system-ui, sans-serif; }}
body {{ margin: 0; }} header {{ padding: 1.8rem max(1rem, calc((100vw - 1120px) / 2)); background: #143a32; color: #fff; }}
h1 {{ margin: 0 0 .5rem; }} header p {{ margin: .25rem 0; color: #daebe4; }}
main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 400px), 1fr)); gap: 1.25rem;
        max-width: 1120px; padding: 1.25rem; margin: auto; align-items: start; }}
section {{ background: #e9efe8; padding: 1rem; border-radius: .75rem; min-width: 0; }}
h2 {{ margin: .25rem 0 1rem; font-size: 1.15rem; }} h3, h4 {{ margin: 0 0 .4rem; }}
article {{ padding: .85rem; margin: .5rem 0; border: 1px solid #cbdad2; border-radius: .5rem; background: white; }}
p, dl {{ margin: .35rem 0; }} dt {{ font-weight: 600; }} dd {{ margin: .2rem 0 .6rem; }}
span {{ display: inline-block; font-size: .78rem; background: #dfefe7; padding: .16rem .4rem; border-radius: .25rem; }}
.assumption {{ background: #f9e7b8; }} pre, .mono {{ white-space: pre-wrap; overflow-wrap: anywhere; font: .82rem ui-monospace, monospace; }}
pre {{ background: #f3f6f3; padding: .5rem; margin: .4rem 0 0; }} .empty {{ color: #43564e; }}
</style></head><body><header><h1>SPIRA Home Hub</h1><p>{text(peer)}</p>
<p>Observation gap last marked at {text(state["observation_gap_at"])}</p></header><main>{body}</main></body></html>"""


def delivery(row):
    if row["delivered"]:
        return "Received by Server"
    if row["delivery_error"]:
        return f'Pending · {escape(row["delivery_error"])}'
    return "Pending delivery"
