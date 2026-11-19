"""Read-only Hub evidence for operators."""

from html import escape

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .dashboard_state import state_view
from .store import encode


def create_app(runtime, *, lifespan=None):
    app = FastAPI(title="SPIRA Home Hub", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok", "server_confirmed": runtime.reconciled
                and runtime.last_pull_error is None, "device_online": runtime.device.online}

    @app.get("/state")
    @app.get("/api/state")
    async def state():
        return state_view(runtime)

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return render(state_view(runtime))

    return app


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
        + (f'<p>Window passed · {text(row["window_passed_at"])}</p>' if row["status"] == "window_passed" else "")
        + f'<h4>Trigger</h4>{details(row["trigger"])}</article>'
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
    history = [
        f'<article><h3>{text(row["plan_id"])} · v{row["plan_version"]}</h3>'
        f'<p>Received {text(row["received_at"])}</p>'
        f'<p>Acknowledgement · {delivery(row["ack"])}</p>{details(row["ack"]["packet"])}'
        + (f'<p>Compared with v{row["previous_version"]}</p>' if row["previous_version"] else '')
        + (f'<h4>Changes</h4>{details(row["changes"])}' if row["changes"] is not None
           else '<p>Version changes unavailable.</p>')
        + '</article>'
        for row in state["plan_history"]
    ]
    summaries = [
        f'<article><h3>{text(row["plan_id"])} · v{row["plan_version"]}</h3>'
        f'<p>device actions {row["device_actions"]} · notices {row["notices"]}</p>'
        f'<p>Waiting {row["waiting"]} · window passed {row["window_passed"]} · triggered {row["triggered"]} '
        f'· completed {row["completed"]} · failed/unknown/unverifiable {row["failed_unknown_unverifiable"]} '
        f'· restored {row["restored"]} · withheld {row["withheld"]}</p></article>'
        for row in state["plan_summaries"]
    ]
    stories = []
    for story in state["task_stories"]:
        steps = "".join(
            f'<li>{text(step["kind"].replace("_", " ").capitalize())}'
            f'{details({key: value for key, value in step.items() if key != "kind"})}</li>'
            for step in story["steps"]
        )
        stories.append(f'<article><h3>{text(story["task_id"])}</h3>'
                       f'<p>{text(story["plan_id"])}</p><ol>{steps}</ol></article>')
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
        + section("Plan summaries", summaries, "No plans admitted.")
        + section("Plan history", history, "No plan versions recorded.")
        + section("Task stories", stories, "No task stories recorded.")
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
