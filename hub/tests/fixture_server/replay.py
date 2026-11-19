"""State for one deterministic contract episode."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from spira_contracts.ack import Ack
from spira_contracts.calendar import Calendar
from spira_contracts.card import Card, Line, Summary
from spira_contracts.common import EpisodeStatus, ExecutionStatus, LineState
from spira_contracts.devices import Devices
from spira_contracts.episode import Episode
from spira_contracts.event import Event
from spira_contracts.execution_result import ExecutionResult, RunResult
from spira_contracts.household_created import HouseholdCreated
from spira_contracts.memory import Memory
from spira_contracts.plan import Cancelled, Plan
from spira_contracts.reaction import Reaction

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
FIXTURES = CONTRACTS / "fixtures"
EPISODES = ("ep_9031", "ep_9150", "ep_9120")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wire(model):
    return model.model_dump(mode="json", by_alias=True, exclude_unset=True)


def valid_household_types(household_types: list[str]) -> bool:
    rules = read_json(CONTRACTS / "kb" / "household_types.json")
    selected = set(household_types)
    allowed = {value for axis in rules["axes"].values() for value in axis["types"]}
    if selected - allowed or any(
        axis["pick"] == "one" and len(selected.intersection(axis["types"])) > 1
        for axis in rules["axes"].values()
    ):
        return False

    # The contract's profile values are user-facing labels.
    couple, adult_child, generations, roommates = (
        "부부·커플",
        "부모 + 성인 자녀",
        "3대 함께",
        "룸메이트·셰어하우스",
    )
    dual_income, remote_work, retired = "맞벌이", "재택근무", "은퇴·노년"
    children = selected.intersection(rules["child_types"])
    min_people = 1 + (couple in selected) + len(children) + (adult_child in selected)
    if generations in selected:
        min_people = max(min_people, 3)
    return not (
        any(
            size in selected and maximum is not None and min_people > maximum
            for size, maximum in rules["size_max"].items()
        )
        or (
            roommates in selected
            and (children or selected.intersection({couple, adult_child, generations}))
        )
        or (dual_income in selected and couple not in selected)
        or (retired in selected and selected.intersection({dual_income, remote_work}))
    )


class Replay:
    def __init__(self, episode_id: str):
        if episode_id not in EPISODES:
            raise ValueError(f"Unknown fixture episode {episode_id}")
        folder = FIXTURES / episode_id
        manifest = read_json(folder / "manifest.json")
        self.files = {name: read_json(folder / name) for name in manifest["files"]}
        self.devices = Devices.model_validate(read_json(folder / manifest["devices"]))
        self.household_id = self.devices.household_id
        self.plan = Plan.model_validate(self.files["plan.v1.json"])
        self.card = self.load(Card, "card.v1.json") or self.load(Card, "card.held.json")
        self.final_card = self.load(Card, "card.final.json")
        self.calendar = self.load(Calendar, "calendar.json")
        self.calendar_applied = False
        self.finished = False
        self.paused = False
        self.clock = datetime.fromisoformat(self.plan.sent_at)
        self.onboarding = HouseholdCreated.model_validate(
            read_json(FIXTURES / "ep_9031" / "household.created.json")
        ).model_copy(update={"household_id": self.household_id})
        self.memory = Memory(household_id=self.household_id, intents=[])
        self.source_ids: set[str] = set()
        self.acks: dict[int, Ack] = {}
        self.profile: list[str] = []

        self.receipts = {"events": [], "executions": []}
        self.events: dict[str, dict] = {}
        self.results: dict[str, ExecutionResult] = {}
        self.result_bodies: dict[str, dict] = {}

        self.episode = self.load(Episode, "episode.json") or Episode(
            episode_id=episode_id,
            household_id=self.household_id,
            shared_at=self.plan.sent_at,
            status=EpisodeStatus.HELD,
            item_count=0,
            masked_count=0,
            items=[],
            item_tasks=[],
            card_ids=[self.card.card_id],
        )
        if self.final_card:
            self.episode = self.episode.model_copy(
                update={
                    "status": EpisodeStatus.NOTIFIED,
                    "item_tasks": [
                        task.model_copy(update={"state": LineState.SCHEDULED})
                        for task in self.episode.item_tasks
                    ],
                }
            )

    def load(self, model, name):
        if name in self.files:
            return model.model_validate(self.files[name])
        return None

    def tick(self):
        self.clock += timedelta(microseconds=1)
        return self.clock.isoformat()

    def set_plan(self, plan: Plan):
        self.plan = plan
        self.clock = max(self.clock, datetime.fromisoformat(plan.sent_at))

    def replace_plan(self, **changes):
        self.set_plan(
            self.plan.model_copy(
                update={
                    **changes,
                    "plan_version": self.plan.plan_version + 1,
                    "sent_at": self.tick(),
                }
            )
        )

    def started(self, task_id: str):
        return any(
            isinstance(result.root, RunResult)
            and result.root.task_id == task_id
            and result.root.status
            in (ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED)
            for result in self.results.values()
        )

    def cancel_tasks(self, task_ids: set[str], *, restore_started: bool):
        cancelled = [
            Cancelled(
                task_id=task.task_id,
                restore=restore_started and self.started(task.task_id),
            )
            for task in self.plan.tasks
            if task.task_id in task_ids
        ]
        if cancelled:
            self.replace_plan(
                tasks=[
                    task for task in self.plan.tasks if task.task_id not in task_ids
                ],
                cancelled=[*self.plan.cancelled, *cancelled],
            )

    def update_card(
        self, lines: list[Line], *, stopped: bool = False, updated_at: str | None = None
    ):
        self.card = self.card.model_copy(
            update={
                "lines": lines,
                "stopped": stopped,
                "buttons": [] if stopped else self.card.buttons,
                "notify": False,
                "updated_at": updated_at or self.tick(),
                "summary": Summary(
                    done=sum(
                        line.state
                        in (LineState.DONE, LineState.PARTIAL, LineState.USER_CHANGED)
                        for line in lines
                    ),
                    total=sum(
                        line.state
                        not in (LineState.OFF, LineState.STOPPED, LineState.CANCELLED)
                        for line in lines
                    ),
                    waiting_for=None,
                ),
            }
        )

    def react(self, reaction: Reaction):
        if self.card.stopped:
            return self.card
        if reaction.reaction == "stop":
            self.cancel_tasks(
                {line.task_id for line in self.card.lines}, restore_started=True
            )
            self.update_card(
                [
                    line.model_copy(
                        update={"checked": False, "state": LineState.STOPPED}
                    )
                    for line in self.card.lines
                ],
                stopped=True,
            )
            return self.card

        line = next(
            (line for line in self.card.lines if line.task_id == reaction.task_id), None
        )
        if line is None:
            raise LookupError("Card line is absent from this fixture")
        updated_at = None
        if reaction.reaction == "line_on":
            if self.started(line.task_id):
                raise ValueError(
                    "The fixture has received a started result for this line"
                )
            if line.state != LineState.OFF or self.paused:
                return self.card
            replacement = self.enable_line(line)
        else:
            if line.state == LineState.OFF:
                return self.card
            canonical = (
                wire(reaction) in self.files.get("reactions.json", [])
                and wire(self.plan) == self.files["plan.v1.json"]
                and not self.started(line.task_id)
            )
            if canonical:
                self.set_plan(self.load(Plan, "plan.v2.json"))
                updated_at = self.plan.sent_at
            else:
                self.cancel_tasks({line.task_id}, restore_started=True)
            replacement = line.model_copy(
                update={"checked": False, "state": LineState.OFF}
            )

        self.update_card(
            [replacement if entry is line else entry for entry in self.card.lines],
            updated_at=updated_at,
        )
        return self.card

    def enable_line(self, line: Line):
        # The held card already reserves its line IDs even though v1 omits them.
        ids = [
            task.task_id
            for task in [*self.plan.tasks, *self.plan.cancelled, *self.card.lines]
        ]
        next_number = max(int(task_id.rsplit("#", 1)[1]) for task_id in ids) + 1
        new_id = f"{line.task_id.split('#')[0]}#{next_number}"
        task = next(
            (
                task
                for plan in self.card_templates()
                for task in plan.tasks
                if task.task_id.split("#")[0] == line.task_id.split("#")[0]
            ),
            None,
        )
        if line.when is None and self.calendar_applied:
            found = self.load(Card, "card.found.json")
            line = next(
                entry
                for entry in found.lines
                if entry.task_id.split("#")[0] == line.task_id.split("#")[0]
            )
        if line.when is not None and task is not None:
            self.replace_plan(
                tasks=[*self.plan.tasks, task.model_copy(update={"task_id": new_id})]
            )
        state = LineState.SCHEDULED if line.when is not None else LineState.HELD
        return line.model_copy(
            update={"task_id": new_id, "checked": True, "state": state}
        )

    def card_templates(self):
        return [
            Plan.model_validate(body)
            for name, body in self.files.items()
            if name.startswith("plan.v")
        ]

    def pause(self, paused: bool):
        if paused and not self.paused and not self.finished:
            task_ids = {
                task.task_id
                for task in self.plan.tasks
                if not self.started(task.task_id)
            }
            self.cancel_tasks(task_ids, restore_started=False)
            if self.card:
                lines = [
                    line.model_copy(
                        update={"checked": False, "state": LineState.CANCELLED}
                    )
                    if line.task_id in task_ids or line.state == LineState.HELD
                    else line
                    for line in self.card.lines
                ]
                if lines != self.card.lines:
                    self.update_card(lines)
        self.paused = paused

    def put_calendar(self, calendar: Calendar):
        found = self.load(Card, "card.found.json")
        if (
            not found
            or self.calendar_applied
            or self.paused
            or self.calendar != calendar
        ):
            return
        plan = self.load(Plan, "plan.v2.json")
        if (
            wire(self.plan) == self.files["plan.v1.json"]
            and wire(self.card) == self.files["card.held.json"]
        ):
            self.set_plan(plan)
            self.card = found
        elif not self.card.stopped:
            # Only held, enabled lines can enter the new schedule.
            held = {
                line.task_id.split("#")[0]: line
                for line in self.card.lines
                if line.state == LineState.HELD
            }
            scheduled = {
                line.task_id.split("#")[0]: line
                for line in found.lines
                if line.task_id.split("#")[0] in held
            }
            added = [
                task.model_copy(
                    update={"task_id": held[task.task_id.split("#")[0]].task_id}
                )
                for task in plan.tasks
                if task.task_id.split("#")[0] in scheduled
            ]
            if not added:
                return
            self.clock = max(self.clock, datetime.fromisoformat(plan.sent_at))
            self.replace_plan(
                tasks=[
                    *added,
                    *self.plan.tasks,
                ]
            )
            self.card = self.card.model_copy(
                update={"starts_at": found.starts_at, "text": found.text}
            )
            self.update_card(
                [
                    scheduled[line.task_id.split("#")[0]].model_copy(
                        update={"task_id": line.task_id}
                    )
                    if line.task_id.split("#")[0] in scheduled
                    else line
                    for line in self.card.lines
                ]
            )
            self.card = self.card.model_copy(update={"notify": True})
        else:
            return
        self.calendar_applied = True
        self.episode = self.episode.model_copy(
            update={"status": EpisodeStatus.NOTIFIED}
        )

    def release_package(self, event: Event):
        if (
            event.type != "package.brought_in"
            or self.paused
            or self.finished
            or "plan.v3.json" not in self.files
        ):
            return False
        released = self.load(Plan, "plan.v3.json")
        if wire(self.plan) == self.files["plan.v2.json"]:
            self.set_plan(released)
            return True
        triggers = {
            task.task_id: task.trigger
            for task in released.tasks
            if task.source == "item"
        }
        tasks = [
            task.model_copy(update={"trigger": triggers[task.task_id]})
            if task.task_id in triggers
            else task
            for task in self.plan.tasks
        ]
        if tasks == self.plan.tasks:
            return False
        self.clock = max(self.clock, datetime.fromisoformat(released.sent_at))
        self.replace_plan(tasks=tasks)
        return True

    def finish_if_replayed(self):
        if (
            self.finished
            or not self.final_card
            or wire(self.plan) != self.files["plan.v3.json"]
        ):
            return False
        if any(
            self.events.get(event["event_id"]) != event
            for event in self.files["events.json"]
        ):
            return False
        if any(
            self.result_bodies.get(result["result_id"]) != result
            for result in self.files["executions.json"]
        ):
            return False
        self.finished = True
        self.card = self.final_card
        self.episode = self.load(Episode, "episode.json")
        self.memory = self.load(Memory, "memory.json")
        self.clock = max(self.clock, datetime.fromisoformat(self.card.updated_at))
        return True
