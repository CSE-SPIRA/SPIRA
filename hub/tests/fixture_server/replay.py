"""State for one deterministic contract episode."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spira_contracts.ack import Ack
from spira_contracts.calendar import Calendar
from spira_contracts.card import Card, Line, Summary
from spira_contracts.common import AckStatus, EpisodeStatus, ExecutionStatus, LineState, TriggerEvent
from spira_contracts.devices import Devices
from spira_contracts.episode import Episode
from spira_contracts.event import Event
from spira_contracts.execution_result import ExecutionResult, RestoreResult, RunResult
from spira_contracts.household_created import HouseholdCreated
from spira_contracts.memory import Memory
from spira_contracts.plan import Cancelled, EventTrigger, Plan
from spira_contracts.reaction import Reaction

from .projection import action_results, line_end, matching_trigger, run_state, task_end, user_changed

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
FIXTURES = CONTRACTS / "fixtures"
EPISODES = ("ep_9031", "ep_9150", "ep_9120")
INACTIVE = (LineState.OFF, LineState.STOPPED, LineState.CANCELLED)


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
        self.plans: dict[int, Plan] = {}
        self.plan = self.load(Plan, "plan.v1.json")
        self.clock = datetime.fromisoformat(self.plan.sent_at)
        self.set_plan(self.plan)
        self.card = self.load(Card, "card.v1.json") or self.load(Card, "card.held.json")
        self.final_card = self.load(Card, "card.final.json")
        self.calendar = self.load(Calendar, "calendar.json")
        self.calendar_applied = False
        self.finished = False
        self.paused = False
        self.onboarding = HouseholdCreated.model_validate(
            read_json(FIXTURES / "ep_9031" / "household.created.json")
        ).model_copy(update={"household_id": self.household_id})
        self.memory = Memory(household_id=self.household_id, intents=[])
        self.live = False
        self.acks: dict[int, Ack] = {}
        self.profile: list[str] = []

        self.receipts = {"events": [], "executions": []}
        self.events: dict[str, Event] = {}
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

    def now(self):
        return max(self.clock, datetime.now(timezone.utc)) if self.live else self.clock

    def tick(self):
        self.clock = max(self.clock + timedelta(microseconds=1), self.now())
        return self.clock.isoformat()

    def set_plan(self, plan: Plan):
        self.plan = plan
        self.plans[plan.plan_version] = plan
        self.clock = max(self.clock, datetime.fromisoformat(plan.sent_at))

    def replace_plan(self, *, sent_at: str | None = None, **changes):
        self.set_plan(
            self.plan.model_copy(
                update={
                    **changes,
                    "plan_version": self.plan.plan_version + 1,
                    "sent_at": sent_at or self.tick(),
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
                    total=sum(line.state not in INACTIVE for line in lines),
                    waiting_for=self.waiting_for(lines) if self.live else None,
                ),
            }
        )

    def waiting_for(self, lines: list[Line]):
        scheduled = {
            line.task_id for line in lines
            if line.state == LineState.SCHEDULED and line.end_state is None
        }
        waits = set()
        now = self.now()
        events = sorted(self.events.values(), key=lambda event: datetime.fromisoformat(event.at))
        for task in self.plan.tasks:
            trigger = task.trigger
            if task.task_id not in scheduled or not isinstance(trigger, EventTrigger):
                continue
            if trigger.window and not (
                datetime.fromisoformat(trigger.window.from_) <= now
                <= datetime.fromisoformat(trigger.window.to)
            ):
                continue
            admitted = self.admitted_at(task.task_id)
            end = task_end(task, events, admitted)
            if (end is None or end > now) and matching_trigger(trigger, events, admitted) is None:
                waits.add(trigger.event)
        return next((event for event in TriggerEvent if event in waits), None)

    def admitted_at(self, task_id: str):
        return next(
            datetime.fromisoformat(plan.sent_at)
            for plan in self.plans.values()
            if any(task.task_id == task_id for task in plan.tasks)
        )

    def project(self):
        """Refresh the projection after a receipt or when the App polls wall time."""
        tasks = {task.task_id: task for plan in self.plans.values() for task in plan.tasks}
        cancelled = {entry.task_id: entry.restore for entry in self.plan.cancelled}
        rejected = set()
        for version, plan in self.plans.items():
            if (ack := self.acks.get(version)) is not None:
                submitted = {task.task_id for task in plan.tasks}
                if ack.status == AckStatus.REJECTED:
                    rejected.update(submitted)
                else:
                    rejected.update(submitted.intersection(item.task_id for item in ack.rejected_tasks))

        runs: dict[str, list[RunResult]] = {}
        restores: dict[str, RestoreResult] = {}
        packets = sorted((result.root for result in self.results.values()), key=lambda packet: datetime.fromisoformat(packet.at))
        for packet in packets:
            if isinstance(packet, RunResult):
                runs.setdefault(packet.task_id, []).append(packet)
            else:
                restores[packet.task_id] = packet

        item_tasks = []
        for item in self.episode.item_tasks:
            task = tasks[item.task_id]
            latest = action_results(task, runs.get(item.task_id, []))
            state, _ = run_state(task, latest, item.task_id in rejected)
            if item.task_id in cancelled and not self.started(item.task_id):
                state = LineState.CANCELLED
            item_tasks.append(item.model_copy(update={"state": state}))
        self.episode = self.episode.model_copy(update={"item_tasks": item_tasks})
        if not self.live or not self.card:
            return

        events = sorted(self.events.values(), key=lambda event: datetime.fromisoformat(event.at))
        now = self.now()
        lines = []
        all_ended = True
        for line in self.card.lines:
            task_id = line.task_id
            task = tasks.get(task_id)
            if task is None:
                lines.append(line)
                all_ended &= line.state in INACTIVE
                continue
            results = runs.get(task_id, [])
            latest = action_results(task, results)
            ended_at = task_end(task, events, self.admitted_at(task_id))
            state, note = line.state, line.note
            if state not in INACTIVE:
                state, note = run_state(task, latest, task_id in rejected)
                if state in (LineState.DONE, LineState.PARTIAL) and user_changed(task, results, events, ended_at):
                    state = LineState.USER_CHANGED

            ended, end_state = line_end(
                task, ended_at, now, latest, restores.get(task_id), cancelled.get(task_id),
            )
            all_ended &= ended or task_id in rejected
            lines.append(line.model_copy(update={
                "state": state, "note": note, "end_state": end_state or line.end_state,
            }))

        status = EpisodeStatus.NOTIFIED
        if all_ended:
            status = EpisodeStatus.CLOSED
        elif all(line.when is None for line in lines):
            status = EpisodeStatus.HELD
        if (
            lines != self.card.lines
            or self.waiting_for(lines) != self.card.summary.waiting_for
            or self.episode.status != status
        ):
            self.update_card(lines, stopped=self.card.stopped)
        self.episode = self.episode.model_copy(update={"status": status})

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
                and not self.live
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
            update={"task_id": new_id, "checked": True, "state": state, "end_state": None, "note": None}
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

    def find_calendar_time(self):
        found = self.load(Card, "card.found.json")
        if (
            not found
            or self.calendar_applied
            or self.paused
        ):
            return
        plan = self.load(Plan, "plan.v2.json")
        if (
            not self.live
            and wire(self.plan) == self.files["plan.v1.json"]
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
                sent_at=plan.sent_at if self.live else None,
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
        brought_in = datetime.fromisoformat(event.at)
        if (
            event.type != "package.brought_in"
            or self.paused
            or self.finished
            or brought_in < datetime.fromisoformat(self.episode.shared_at)
        ):
            return False
        release_at = event.at
        if not self.live and "plan.v3.json" in self.files:
            # The fixed birthday replay uses the committed release time even
            # when a virtual Hub supplies its own event ID and timestamp.
            if wire(self.plan) == self.files["plan.v2.json"]:
                self.set_plan(self.load(Plan, "plan.v3.json"))
                return True
            release_at = self.files["events.json"][0]["at"]
        tasks = [
            task.model_copy(update={
                "trigger": task.trigger.model_copy(update={"released": True, "at": release_at})
            })
            if task.source == "item"
            and isinstance(task.trigger, EventTrigger)
            and task.trigger.event == event.type
            and task.trigger.released is False
            else task
            for task in self.plan.tasks
        ]
        if tasks == self.plan.tasks:
            return False
        if not self.live:
            self.clock = max(self.clock, brought_in)
        self.replace_plan(tasks=tasks)
        return True

    def finish_if_replayed(self):
        if (
            self.finished
            or self.live
            or not self.final_card
            or wire(self.plan) != self.files["plan.v3.json"]
        ):
            return False
        if any(
            event["event_id"] not in self.events or wire(self.events[event["event_id"]]) != event
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
