"""Read-only household ledger and Hub diagnostics."""

from bisect import bisect_right
from hashlib import blake2s
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
from .dashboard_words import device_words
from .design_vocabulary import ROOM_NAMES
from .store import encode

HOUSEHOLD_TIME = ZoneInfo("Asia/Seoul")
SOURCE_LABELS = {"command": "SPIRA가 시킴", "report": "기기가 알림", "restore": "집이 되돌림"}


def create_app(runtime, *, lifespan=None, hub_key=None, home_name="우리 집"):
    app = FastAPI(title="SPIRA Home Hub", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/assets", StaticFiles(directory=Path(__file__).with_name("dashboard_assets")), name="dashboard-assets")

    def installed_devices() -> Devices | None:
        return None if runtime.config_error else runtime.installation.devices

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
        devices = installed_devices()
        if devices is None:
            error = Error(code="internal", message="Hub installation is unavailable")
            return JSONResponse(wire(error), status_code=503)
        response.headers["Cache-Control"] = "no-store"
        return devices

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        return render(state_view(runtime, dashboard=True), home_name=home_name, devices=installed_devices())

    return app


def seen(state, home_name):
    plans = "받은 준비" if state["plan_history"] else "받은 준비 없음"
    connection = ("서버 연결됨" if state["server_confirmed"] else
                  "서버 연결 실패" if state["server_error"] else "서버 연결 확인 중")
    legend = "".join(f'<li>{source_mark(source)}{label}</li>' for source, label in SOURCE_LABELS.items())
    body = preparation_groups(state) or '<p class="subtext">기록을 기다리고 있어요.</p>'
    return f"""<section class="ledger" aria-labelledby="seen-title">
<header class="ledger-head"><h1 id="seen-title">이 집이 본 것</h1>
<a href="#detail">자세한 기록</a>
<p id="ledger-summary">{escape(home_name)} · {plans} · {connection}</p></header>
<ul class="source-legend" role="list" aria-label="기록 표시 안내">{legend}</ul>
<div id="ledger" aria-live="polite">{body}</div></section>"""


def ledger_time(value, *, short=False):
    at = offset_time(value).astimezone(HOUSEHOLD_TIME)
    weekday = "월화수목금토일"[at.weekday()]
    if short:
        return f'<time datetime="{escape(value)}" title="{at:%Y-%m-%d} ({weekday})">{at:%H:%M}</time>'
    return f'<time datetime="{escape(value)}">{weekday} {at:%H:%M}</time>'


def preparation_groups(state):
    ledger = state["ledger"]
    receipts = [row for row in ledger if row["kind"] == "plan"]
    receipt_times = [offset_time(row["at"]) for row in receipts]
    groups = {(row["plan_id"], row["plan_version"]): [] for row in receipts}
    household_rows = []
    for row in reversed(ledger):
        if row["kind"] == "plan":
            if row["what"] or delivery_mark(row):
                groups[row["plan_id"], row["plan_version"]].append(row)
            continue
        preparation = row.get("preparation")
        if preparation is None:
            # Place ordinary household activity in the matching time period.
            index = bisect_right(receipt_times, offset_time(row["at"])) - 1
            if index >= 0:
                receipt = receipts[index]
                preparation = (receipt["plan_id"], receipt["plan_version"])
        groups.get(preparation, household_rows).append(row)

    sections = []
    for index, receipt in enumerate(reversed(receipts)):
        plan_id, version = receipt["plan_id"], receipt["plan_version"]
        count = receipt["task_count"]
        tasks = f' · 할 일 {count}' if count is not None else ""
        title = f'받은 준비 · 받은 시각 {ledger_time(receipt["at"], short=True)}{tasks}'
        key = blake2s(f"{plan_id}/{version}".encode(), digest_size=8).hexdigest()
        sections.append(ledger_group(key, title, groups[plan_id, version], newest=index == 0))
    if household_rows:
        sections.append(ledger_group("household", "집에서 일어난 일", household_rows, newest=not receipts))
    return "".join(sections)


def ledger_group(key, title, rows, *, newest):
    body = "".join(ledger_row(row) for row in rows)
    body = (f'<ol class="ledger-rows" role="list">{body}</ol>' if body else
            '<p class="subtext">기록을 기다리고 있어요.</p>')
    opened = ' data-newest open' if newest else ''
    return f'<details class="ledger-group" data-group="{key}"{opened}><summary>{title}</summary>{body}</details>'


def source_mark(source, label=None):
    accessibility = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return f'<span class="source-mark source-{source}" {accessibility}></span>'


def delivery_mark(row):
    pending = [report for report in row["reports"] if not report["delivered"]]
    if any(report["delivery_error"] for report in pending):
        return '<span class="delivery delivery-failed">전송 실패 · 다시 보내는 중</span>'
    if pending:
        return '<span class="delivery">서버에 보내는 중</span>'
    return ""


def ledger_row(row):
    label = f'{escape(row["label"])} · ' if row["label"] != "—" else ""
    kind, by = row["kind"], row["by"]
    source = {"restore": "restore", "event": "report"}.get(kind, "command")
    actor = SOURCE_LABELS[source]
    if kind == "plan":
        actor = "준비를 받음"
    elif kind == "event" and by == "hub":
        actor = "집이 감지함"
    detail = ' <span class="person">· 사람이 조작함</span>' if by == "user" else ""
    status = row.get("status")
    tone = f' class="outcome-{status}"' if status in {"unverifiable", "failed"} else ""
    return (
        f'<li class="ledger-row">{source_mark(source, actor)}{ledger_time(row["at"])}'
        f'<div><strong{tone}>{label}{escape(row["what"] or "받은 준비")}</strong>{detail}'
        f'{delivery_mark(row)}</div></li>'
    )


def device_list(inventory):
    body = '<p class="subtext">기기 목록을 불러오지 못했어요.</p>'
    if inventory is not None:
        devices = {device.id: device for device in inventory.devices}
        items = []
        for device in inventory.devices:
            room = f'<span>{escape(ROOM_NAMES.get(device.room, device.room))}</span>' if device.room else ""
            items.append(f'<li><span>{escape(device_words(device.id, devices))}</span>{room}</li>')
        body = (f'<ul role="list">{"".join(items)}</ul>' if items else
                '<p class="subtext">등록된 기기가 없어요.</p>')
    return f'<aside class="device-panel" aria-labelledby="device-title"><h2 id="device-title">이 집의 기기</h2><div id="device-list">{body}</div></aside>'


def render(state, *, home_name="우리 집", devices=None):
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
    bindings = [
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
        + section("Device bindings", bindings, "No delegated devices.")
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content=""><title>SPIRA Home Hub</title>
<link rel="stylesheet" href="/assets/tokens.css"><link rel="stylesheet" href="/assets/dashboard.css"><script src="/assets/dashboard.js" defer></script>
</head><body><main><div class="overview">{seen(state, home_name)}{device_list(devices)}</div>
<section id="detail" tabindex="-1" aria-labelledby="detail-title">
<h2 id="detail-title">자세한 기록</h2><p><a href="#seen-title">장부로 돌아가기</a> · <a href="/state">JSON</a></p>
<div id="detail-content" lang="en"><p>{text(peer)}</p>
<p>Household {text(state["household"])}</p>
<p>Observation gap last marked at {text(state["observation_gap_at"])}</p>
<div class="details-grid">{body}</div></div></section></main></body></html>"""


def delivery(row):
    if row["delivered"]:
        return "Received by Server"
    if row["delivery_error"]:
        return f'Pending · {escape(row["delivery_error"])}'
    return "Pending delivery"
