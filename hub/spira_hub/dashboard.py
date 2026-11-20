"""Read-only household ledger and Hub diagnostics."""

from html import escape
from pathlib import Path
from secrets import compare_digest
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from spira_contracts.devices import Devices
from spira_contracts.error import Error

from .contracts import offset_time, wire
from .dashboard_state import state_view
from .store import encode

HOUSEHOLD_TIME = ZoneInfo("Asia/Seoul")
BY_LABEL = {"spira": "SPIRA", "user": "사람", "unknown": "기기 보고", "hub": "집"}


def create_app(runtime, *, lifespan=None, hub_key=None):
    app = FastAPI(title="SPIRA Home Hub", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/assets", StaticFiles(directory=Path(__file__).with_name("dashboard_assets")), name="dashboard-assets")

    @app.get("/health")
    async def health():
        return {"status": "ok", "server_confirmed": runtime.reconciled
                and runtime.last_pull_error is None, "device_online": runtime.device.online}

    @app.get("/state")
    @app.get("/api/state")
    async def state():
        return state_view(runtime)

    @app.get("/home/onboarding/devices", response_model=Devices, response_model_exclude_unset=True)
    async def home_devices(request: Request, response: Response):
        supplied = request.headers.get("X-API-Key", "")
        if not hub_key or not compare_digest(supplied.encode(), hub_key.encode()):
            error = Error(code="unauthorized", message="Household Hub key required")
            return JSONResponse(wire(error), status_code=401)
        if runtime.config_error:
            error = Error(code="internal", message="Hub installation is unavailable")
            return JSONResponse(wire(error), status_code=503)
        response.headers["Cache-Control"] = "no-store"
        return runtime.installation.devices

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return render(state_view(runtime))

    return app


def seen(state):
    plans = " · ".join(
        f'계획 v{plan["plan_version"]} · 할 일 {plan["task_count"]}'
        for plan in state["current_plans"]
    ) or "현재 계획 없음 · 할 일 0"
    connection = ("서버 연결됨" if state["server_confirmed"] else
                  "서버 연결 실패" if state["server_error"] else "서버 연결 확인 중")
    dated_rows = [(row, offset_time(row["at"]).astimezone(HOUSEHOLD_TIME)) for row in reversed(state["ledger"])]
    multi_day = bool(dated_rows and dated_rows[0][1].date() != dated_rows[-1][1].date())
    body = "".join(ledger_row(row, at, multi_day) for row, at in dated_rows)
    if not body:
        body = '<li class="subtext">기록을 기다리고 있어요.</li>'
    return f"""<section class="ledger" aria-labelledby="seen-title">
<header class="ledger-head"><h1 id="seen-title">Hub · 이 집이 본 것</h1>
<a href="#detail">자세한 기록</a>
<p id="ledger-summary">{escape(state["household"])} · {plans} · {connection}</p></header>
<ol id="ledger" role="list" aria-label="이 집의 장부" aria-live="polite" tabindex="0">{body}</ol></section>"""


def ledger_row(row, at, multi_day):
    label = f'{escape(row["label"])} · ' if row["label"] != "—" else ""
    day = f'<span>{at:%m/%d}</span> ' if multi_day else ""
    delivery = ""
    if row["reports"]:
        if all(report["delivered"] for report in row["reports"]):
            delivery = '<p><span class="sent"><span aria-hidden="true">↗ </span>서버에 보냄</span></p>'
        else:
            delivery = '<p>보내는 중</p>'
    return (
        f'<li class="ledger-row"><div><time datetime="{escape(row["at"])}" title="{at:%Y-%m-%d %H:%M:%S %Z}">'
        f'{day}{at:%H:%M}</time><strong>{label}{escape(row["what"])}</strong>'
        f'<span class="pill actor">{BY_LABEL[row["by"]]}</span></div>{delivery}</li>'
    )


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
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f6f5ee"><title>SPIRA Home Hub</title>
<link rel="stylesheet" href="/assets/dashboard.css"><script src="/assets/dashboard.js" defer></script>
</head><body><main>{seen(state)}
<section id="detail" tabindex="-1" aria-labelledby="detail-title">
<h2 id="detail-title">자세한 기록</h2><p><a href="#seen-title">장부로 돌아가기</a> · <a href="/state">JSON</a></p>
<div id="detail-content" lang="en"><p>{text(peer)}</p>
<p>Observation gap last marked at {text(state["observation_gap_at"])}</p>
<div class="details-grid">{body}</div></div></section></main></body></html>"""


def delivery(row):
    if row["delivered"]:
        return "Received by Server"
    if row["delivery_error"]:
        return f'Pending · {escape(row["delivery_error"])}'
    return "Pending delivery"
