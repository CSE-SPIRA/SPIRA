"""ep_9031 ready for S4: household, devices (revision 3), items with groups, the S3 intent, and the S4 recording."""

from __future__ import annotations

import copy

from spira_server import clock
from spira_server.config import get_config
from spira_server.db.engine import session_scope
from spira_server.db.models import DeviceList, Episode, OrderItem
from spira_server.llm import prompts
from spira_server.pipeline import s4_tasks
from spira_server.pipeline.s1_extract import postprocess

from .factories import data, fixture, household

JUDGED = clock.parse("2026-10-15T21:11:40+09:00")
SHARED = clock.parse("2026-10-15T21:00:08+09:00")


def intent_ep9031() -> dict:
    d = data("s3_ep_9031.json")["decision"]["bundles"][0]
    bundle = {**copy.deepcopy(d), "calendar_tags": ["생일"],
              "use_window": {"start": "2026-10-17T14:00:00+09:00", "end": "2026-10-17T17:00:00+09:00"}}
    return {"bundles": [bundle], "unbundled": ["세탁 세제", "로션"], "none_reason": None, "error": None}


def devices(hid: str = "h_042", body: dict | None = None) -> None:
    body = body or fixture("ep_9031/devices.json")
    with session_scope() as s:
        s.merge(DeviceList(household_id=hid, revision=body["revision"], body=body))


def episode(eid: str = "ep_9031", intent: dict | None = None, raw_items: list[dict] | None = None,
            hid: str = "h_042", shared=SHARED) -> str:
    rows = postprocess(raw_items or data("s1_ep_9031.json")["output"]["items"], get_config())
    with session_scope() as s:
        s.add(Episode(id=eid, household_id=hid, status="reading", shared_at=shared, received_at=shared,
                      source_ids=[], judged=False, stage="s2", plan_version=0, next_item_n=len(rows) + 1,
                      next_task_n=1, next_card_ordinal=1, rerun_pending=False,
                      intent=intent if intent is not None else intent_ep9031()))
        s.flush()
        for n, r in enumerate(rows, start=1):
            s.add(OrderItem(episode_id=eid, id=f"it_{n}", **r))
    return eid


def ep9031(with_devices: bool = True) -> str:
    household()
    if with_devices:
        devices()
    return episode()


def record(mock_llm, episode_id: str, output: dict, now=JUDGED, retry_errors=None, retry_output=None) -> str:
    p = s4_tasks.prepare(episode_id, now=now)
    mock_llm.record("s4", prompts.system("s4"), p.message, output=output)
    if retry_errors is not None:
        from spira_server.llm.client import retry_text
        msg2 = p.message + "\n\n" + retry_text(prompts.text("s4_retry.txt"), retry_errors)
        mock_llm.record("s4", prompts.system("s4"), msg2, output=retry_output)
    return p.message


def plan_v1_tasks() -> list[dict]:
    tasks = copy.deepcopy(fixture("ep_9031/plan.v1.json")["tasks"])
    for t in tasks:
        t.pop("protective", None)                      # set by S5 (command policy)
    return tasks


def output() -> dict:
    return copy.deepcopy(data("s4_ep_9031.json")["output"])
