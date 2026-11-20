"""Read-only Hub evidence for operators."""

from html import escape
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .contracts import offset_time
from .dashboard_state import state_view
from .onboarding import add_onboarding
from .store import encode

HOUSEHOLD_TIME = ZoneInfo("Asia/Seoul")
BY_LABEL = {"spira": "SPIRA", "user": "사람", "unknown": "모름", "hub": "집"}
REPORT_LABEL = {"ack": "ack", "event": "event", "run": "결과", "restore": "restore"}


def create_app(runtime, *, lifespan=None, hub_key=None, lg_http=None):
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

    add_onboarding(app, runtime, hub_key=hub_key, lg_http=lg_http)
    return app


def seen(state):
    plans = " · ".join(
        f'{escape(plan["plan_id"])} 계획 v{plan["plan_version"]} · 할 일 {plan["task_count"]}'
        for plan in state["current_plans"]
    ) or "현재 계획 없음 · 할 일 0"
    connection = ("연결됨" if state["server_confirmed"] else
                  "연결 실패" if state["server_error"] else "연결 확인 중")
    dated_rows = [(row, offset_time(row["at"]).astimezone(HOUSEHOLD_TIME)) for row in state["ledger"]]
    multi_day = bool(dated_rows and dated_rows[0][1].date() != dated_rows[-1][1].date())
    rows = []
    for index, (row, at) in enumerate(dated_rows):
        time_label = at.strftime("%m/%d %H:%M" if multi_day else "%H:%M")
        by = row["by"]
        reports = " ".join(report_badge(report) for report in row["reports"]) or "—"
        recent = ' class="recent"' if index >= len(dated_rows) - 3 else ""
        rows.append(
            f'<tr{recent}><td><time datetime="{escape(row["at"])}" title="{at:%Y-%m-%d %H:%M:%S %Z}">'
            f'{time_label}</time></td><td>{escape(row["label"])}</td><td>{escape(row["what"])}</td>'
            f'<td class="by {by}">{BY_LABEL[by]}</td><td>{reports}</td></tr>'
        )
    body = "".join(rows) or '<tr><td class="empty" colspan="5">아직 기록된 일이 없어요.</td></tr>'
    return f"""<section class="seen" aria-labelledby="seen-title">
<header><h1 id="seen-title">Hub · 이 집이 본 것</h1>
<p>{escape(state["household"])} · {plans} · Server {connection}</p>
<a href="#detail">자세한 기록</a></header>
<div class="ledger"><table aria-labelledby="seen-title"><thead>
<tr><th scope="col">시각</th><th scope="col">기기</th><th scope="col">일</th>
<th scope="col">누가</th><th scope="col">Server로</th></tr>
</thead><tbody>{body}</tbody></table></div></section>"""


def report_badge(report):
    label = REPORT_LABEL[report["kind"]]
    if report["delivered"]:
        return f'<span class="sent">{label} {"204" if report["kind"] == "ack" else "보냄"}</span>'
    if report["delivery_error"]:
        return f'<span class="retry" title="{escape(report["delivery_error"])}">{label} 재전송 대기</span>'
    return f'<span class="pending">{label} 전송 대기</span>'


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
<meta http-equiv="refresh" content="5"><title>SPIRA Home Hub</title><style>
:root {{ color-scheme: light; color: #15191b; background: #f4f4f2; font: 16px system-ui, sans-serif; }}
body {{ margin: 0; }} main {{ max-width: 1120px; padding: clamp(.75rem, 3vw, 1.5rem); margin: auto; }}
.seen {{ background: #fff; border: 1.5px solid #b9bebb; border-radius: 8px; padding: clamp(.65rem, 2vw, 1rem); }}
.seen header {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem 1rem; padding-bottom: .55rem; }}
.seen h1 {{ margin: 0; font-size: 1.1rem; }} .seen header p {{ color: #6b7378; font-size: .875rem; }}
.seen header a {{ color: #1f4fb8; font-size: .875rem; margin-left: auto; }}
.ledger {{ overflow-x: auto; }}
.ledger table {{ width: 100%; min-width: 350px; border-spacing: 0 .15rem; font-size: .9rem; }}
.ledger th {{ border-bottom: 1px solid #dadedb; color: #6b7378; text-align: left; font-size: .8rem; font-weight: 500; }}
.ledger th, .ledger td {{ padding: .3rem .45rem; vertical-align: baseline; }}
.ledger time {{ color: #6b7378; font: .82rem ui-monospace, monospace; white-space: nowrap; }}
.ledger td:nth-child(2), .ledger td:nth-child(4) {{ white-space: nowrap; }}
.ledger .recent td {{ background: #fff8ec; font-weight: 600; }}
.ledger .recent td:first-child {{ border-radius: 4px 0 0 4px; }}
.ledger .recent td:last-child {{ border-radius: 0 4px 4px 0; }}
.ledger .by {{ font-weight: 600; }} .by.spira {{ color: #1f4fb8; }} .by.user {{ color: #a84f0c; }}
.by.unknown, .ledger .retry {{ color: #b42318; }} .by.hub, .ledger .sent {{ color: #0f6e66; }}
.ledger span {{ font-size: .8rem; display: inline-block; }} .ledger .pending {{ color: #6b7378; }}
#detail {{ margin-top: 1.5rem; }}
.details-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 400px), 1fr)); gap: 1.25rem;
                 align-items: start; }}
.details-grid section {{ background: #e9efe8; padding: 1rem; border-radius: .75rem; min-width: 0; }}
h2 {{ margin: .25rem 0 1rem; font-size: 1.15rem; }} h3, h4 {{ margin: 0 0 .4rem; }}
article {{ padding: .85rem; margin: .5rem 0; border: 1px solid #cbdad2; border-radius: .5rem; background: white; }}
p, dl {{ margin: .35rem 0; }} dt {{ font-weight: 600; }} dd {{ margin: .2rem 0 .6rem; }}
.details-grid span {{ display: inline-block; font-size: .78rem; background: #dfefe7; padding: .16rem .4rem; border-radius: .25rem; }}
.details-grid .assumption {{ background: #f9e7b8; }}
pre, .mono {{ white-space: pre-wrap; overflow-wrap: anywhere; font: .82rem ui-monospace, monospace; }}
pre {{ background: #f3f6f3; padding: .5rem; margin: .4rem 0 0; }} .empty {{ color: #43564e; }}
</style></head><body><main>{seen(state)}
<section id="detail"><h2>자세한 기록</h2><div lang="en"><p>{text(peer)}</p>
<p>Observation gap last marked at {text(state["observation_gap_at"])}</p>
<div class="details-grid">{body}</div></div></section></main></body></html>"""


def delivery(row):
    if row["delivered"]:
        return "Received by Server"
    if row["delivery_error"]:
        return f'Pending · {escape(row["delivery_error"])}'
    return "Pending delivery"
