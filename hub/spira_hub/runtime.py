"""Hub scheduling and effect lifecycle. One scheduler owns device writes."""

import asyncio
from collections import defaultdict
from pathlib import Path

import httpx2 as httpx
from spira_contracts.devices import Devices
from spira_contracts.execution_result import ExecutionResult, RestoreResult, RunResult
from spira_contracts.plan import Action

from .config import Installation
from .contracts import identity, no_earlier_than, offset_time, packet, value_reason, wall_time, wire
from .observations import Observations
from .plans import action_keys, admit, delegated, end_status, trigger_time

IO_FAILURES = (httpx.HTTPError, ValueError, TypeError, OverflowError)
PULL_INTERVAL = 15


class Runtime:
    def __init__(self, store, server, device, installation_path: Path, *,
                 clock=wall_time, verify_seconds=3, verify_interval=0.1):
        self.store, self.server, self.device = store, server, device
        self.installation_path = installation_path
        self.clock = clock
        self.verify_seconds, self.verify_interval = verify_seconds, verify_interval
        self.installation = Installation.load(self.installation_path, server.household)
        self.bindings = {}
        self.capabilities = {}
        self.observations = Observations(store, server.household, clock)
        self.device.on_signal = self.signal
        self.device.on_gap = self.gap
        self.pull_lock = asyncio.Lock()
        self.step_lock = asyncio.Lock()
        self.reconciled = False
        self.last_pull_error = None
        self.config_error = None
        self.registered = False
        self.refresh_bindings()
        self.recover()

    def refresh_bindings(self):
        saved = self.store.get("bindings", {})
        current = {}
        for device in self.installation.devices.devices:
            binding = self.installation.bindings[device.id]
            old = saved.get(device.id)
            identity_fields = [binding.target, binding.native_identity, device.type, device.substrate.value]
            epoch = old["epoch"] if old and old["identity"] == identity_fields else identity("binding")
            current[device.id] = {"identity": identity_fields, "epoch": epoch}
        if current != self.bindings:
            with self.store.db:
                self.store.put("bindings", current)
            if self.bindings and current != saved:
                self.observations.gap()
            self.bindings = current

    def reload_installation(self):
        try:
            installation = Installation.load(self.installation_path, self.server.household)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            self.config_error = type(error).__name__
            return
        self.config_error = None
        if installation != self.installation:
            self.installation = installation
            self.observations.sequences.clear()
            self.refresh_bindings()

    def gap(self):
        self.observations.gap()
        self.capabilities = {}

    def signal(self, message):
        self.observations.ingest(message, self.installation, self.capabilities, self.bindings)

    def recover(self):
        with self.store.db:
            for attempt in self.store.attempts():
                if attempt["status"] == "dispatching":
                    if attempt["kind"] == "run":
                        self.run_result(attempt, "unknown")
                    else:
                        self.record_restore(attempt, "unknown")

    async def discover(self):
        generation = self.device.generation
        capabilities = await self.device.discover()
        if capabilities is not None and generation == self.device.generation:
            self.capabilities = capabilities

    async def refresh(self, *, before_effect=False):
        async with self.pull_lock:
            try:
                revision = await self.pull_snapshot()
                if await self.register(revision) and before_effect:
                    # A device registration round trip can outlive a Stop or pause.
                    await self.pull_snapshot()
                self.reconciled = True
                self.last_pull_error = None
                return True
            except IO_FAILURES as error:
                self.last_pull_error = type(error).__name__
                return False

    async def pull_snapshot(self):
        self.reload_installation()
        pull, malformed = await self.server.pull()
        self.reload_installation()
        now = self.clock()
        with self.store.db:
            for plan in pull.plans:
                admit(self.store, plan, malformed[plan.plan_id], self.installation, now)
            self.store.put("snapshot", {
                "paused": pull.paused, "plans": [plan.plan_id for plan in pull.plans],
                "devices_revision": pull.devices_revision,
            })
        return pull.devices_revision

    async def register(self, remote_revision):
        if self.config_error:
            return
        configured = self.installation.devices
        projection = self.installation.projection()
        saved = self.store.get("registry")
        if (not saved or projection != saved["devices"]
                or remote_revision > saved["revision"]
                or configured.revision > saved["revision"]):
            revision = max(configured.revision, remote_revision + 1)
            if saved:
                revision = max(revision, saved["revision"] + 1)
            devices = Devices(
                household_id=configured.household_id, revision=revision,
                updated_at=self.clock().isoformat(), devices=configured.devices,
            )
            saved = wire(devices)
            with self.store.db:
                self.store.put("registry", saved)
            self.registered = False
        if not self.registered or remote_revision != saved["revision"]:
            try:
                revision = await self.server.register(Devices.model_validate(saved))
                self.registered = revision == saved["revision"]
            except IO_FAILURES:
                self.registered = False
            return True
        return False

    async def flush(self):
        for kind in ("ack", "event", "execution"):
            for item in self.store.pending(kind):
                try:
                    response = await self.server.send(item)
                except httpx.HTTPStatusError as error:
                    status = error.response.status_code
                    self.store.delivery(item, False, f"HTTP {status}")
                    if status in (401, 403) or status >= 500:
                        break
                    continue
                except IO_FAILURES as error:
                    self.store.delivery(item, False, type(error).__name__)
                    break
                accepted = response is None or item["id"] in response.accepted
                reject = None if accepted else next(
                    (entry.code.value for entry in response.rejected if entry.event_id == item["id"]),
                    "Missing receipt",
                )
                self.store.delivery(item, accepted, reject)
                if response is not None and response.plans_changed:
                    await self.refresh()

    async def step(self):
        async with self.step_lock:
            if not self.reconciled:
                return
            await self.finish_jobs()
            for task in self.store.tasks():
                task = self.store.task(task["plan"], task["id"])
                if not task["body"]:
                    continue
                await self.lifecycle(task)
                task = self.store.task(task["plan"], task["id"])
                now = self.clock()
                snapshot = self.store.get("snapshot")
                if (task["closed"] or not task["active"] or snapshot["paused"]
                        or task["plan"] not in snapshot["plans"]):
                    continue
                triggered = trigger_time(self.store, task, now)
                if triggered is None:
                    continue
                if not task["triggered_at"]:
                    task["triggered_at"] = triggered.isoformat()
                    with self.store.db:
                        self.store.save_task(task)
                if end_status(self.store, task, now, started_at=triggered):
                    if not any(attempt["before"] for attempt in self.store.attempts(task=task)):
                        self.close_task(task)
                    continue
                attempted = {attempt["action_key"] for attempt in self.store.attempts(task=task)}
                for key, raw_action in action_keys(task):
                    if key not in attempted:
                        await self.dispatch(task, key, Action.model_validate(raw_action))

    def target(self, action):
        device = self.installation.delegates.get(action.device)
        binding = self.installation.bindings.get(action.device)
        if device is None or binding is None:
            return None
        capability = self.capabilities.get(binding.target)
        if capability and (capability.device_type != device.type or capability.substrate != device.substrate):
            return None
        return device, binding, self.bindings[action.device]["epoch"], capability

    async def dispatch(self, task, key, action):
        target = self.target(action)
        if target and target[3] is None:
            await self.discover()
            target = self.target(action)
        generation = self.device.generation
        before = await self.read(target[1].target) if target and target[3] else None
        confirmed = await self.refresh(before_effect=True)
        self.reload_installation()
        current = self.store.task(task["plan"], task["id"])
        snapshot = self.store.get("snapshot")
        if not confirmed:
            return self.block(task, key, action, target, "plan_unconfirmed")
        if snapshot["paused"]:
            return self.block(current, key, action, target, "paused")
        if not current["active"] or current["plan"] not in snapshot["plans"]:
            return self.block(current, key, action, target, "plan_cancelled")
        now = self.clock()
        triggered = trigger_time(self.store, current, now)
        if key not in dict(action_keys(current)) or not triggered:
            return
        if end_status(self.store, current, now, started_at=triggered):
            return
        active = self.target(action)
        if self.config_error or not active:
            return self.block(current, key, action, target, "not_delegated")
        device, binding, epoch, capability = active
        command = delegated(device, action.cmd)
        if not command or value_reason(action, command):
            return self.block(current, key, action, active, "not_delegated")
        desired = binding.desired(action)
        if (desired is None or (capability and (action.cmd not in capability.commands
                                               or desired.keys() - capability.properties))):
            return self.block(current, key, action, active, "not_delegated")
        if not target or target[2] != epoch or generation != self.device.generation:
            return self.block(current, key, action, active, "offline")
        if before is None or not before["available"] or not capability:
            return self.block(current, key, action, active, "offline")
        registry = self.store.get("registry")
        if (not self.registered or snapshot["devices_revision"] != registry["revision"]
                or self.installation.projection() != registry["devices"]):
            return self.block(current, key, action, active, "plan_unconfirmed")
        latest = self.observations.latest.get(binding.target)
        if latest is not before:
            # An intervening observation requires another read and authority check.
            return
        if in_use(before) and not self.owns_job(before, epoch):
            reason = "in_use_by_person" if self.observations.in_use_by_person(before) else None
            return self.block(current, key, action, active, reason)
        expected = witnesses(before, desired.keys() | {"in_use"})
        if (desired.keys() - expected.keys()
                or current["body"]["end"]["restore"] and desired.keys() - before["values"].keys()
                or not job_guard_available(capability, before, expected)):
            return self.block(current, key, action, active, None)
        attempt = self.attempt(current, key, action, active, before=before, desired=desired)
        with self.store.db:
            self.store.reserve(attempt)
        await self.apply(attempt, expected, generation)

    def attempt(self, task, key, action, target, *, before=None, desired=None):
        return {
            "op": identity("op"), "plan": task["plan"], "task": task["id"], "action_key": key,
            "version": task["version"], "action": wire(action), "kind": "run",
            "target": target[1].target if target else None, "epoch": target[2] if target else None,
            "substrate": target[0].substrate.value if target else None,
            "sent_at": self.clock().isoformat(), "status": "dispatching", "before": before,
            "desired": desired, "ack": None, "read_back": None, "claims": {},
        }

    def block(self, task, key, action, target, reason):
        if target is None:
            # Retain the substrate of work admitted before this binding was revoked.
            admitted = task.get("substrates", {})
            if action.device not in admitted:
                return
        attempt = self.attempt(task, key, action, target)
        if target is None:
            attempt["substrate"] = admitted[action.device]
        with self.store.db:
            self.store.reserve(attempt)
            self.run_result(attempt, "blocked" if reason else "unknown", reason)

    async def read(self, target):
        started, generation = self.clock(), self.device.generation
        observation = await self.device.read(target)
        if generation != self.device.generation or not observation:
            return None
        observed_at = observation["observed_at"]
        if not no_earlier_than(observed_at, started) or offset_time(observed_at) > self.clock():
            return None
        previous = self.observations.latest.get(target)
        if previous and previous["world_revision"] > observation["world_revision"]:
            return None
        self.observations.record(observation, self.installation, self.capabilities, self.bindings)
        return observation if self.observations.latest.get(target) is observation else None

    async def apply(self, attempt, expected, generation):
        operation = attempt["op"]
        ack = await self.device.command(attempt["target"], operation, attempt["desired"], expected)
        with self.store.db:
            attempt = self.store.operation(operation)
            attempt["ack"] = ack
            self.store.save_attempt(attempt)
        status = ack["status"] if ack else "UNKNOWN"
        if status != "ACCEPTED":
            failure = "unknown" if status == "UNKNOWN" else "failed"
            if attempt["kind"] == "restore" and status == "CONFLICT":
                failure = "skipped_user_changed"
            with self.store.db:
                self.finish(attempt, failure)
            return

        deadline = asyncio.get_running_loop().time() + self.verify_seconds
        while generation == self.device.generation:
            observation = await self.read(attempt["target"])
            attempt = self.store.operation(operation)
            attempt["read_back"] = observation
            if observation and self.verify_effect(attempt, observation):
                with self.store.db:
                    self.finish(attempt, "running" if ack["job_id"] else "completed")
                return
            with self.store.db:
                self.store.save_attempt(attempt)
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(self.verify_interval)
        with self.store.db:
            self.finish(self.store.operation(operation), "unverifiable")

    def verify_effect(self, attempt, observation):
        before, desired = attempt["before"], attempt["desired"]
        action = Action.model_validate(attempt["action"])
        current = self.target(action)
        if not current or current[2] != attempt["epoch"]:
            return False
        if (not observation["available"] or observation["world_revision"] <= before["world_revision"]
                or observation["local_operation"]
                or not no_earlier_than(observation["observed_at"], offset_time(attempt["sent_at"]))
                or not same_values(observation, desired)
                or desired.keys() - witnesses(observation, desired).keys()):
            return False
        operation = observation["operation_id"]
        if operation is not None and operation != attempt["op"]:
            return False
        effect = observation if operation else attempt.get("effect")
        if (not effect or not effect["available"] or not same_values(effect, desired)
                or effect["world_revision"] > observation["world_revision"]
                or witnesses(observation, desired) != witnesses(effect, desired)
                or not no_earlier_than(effect["occurred_at"] or effect["observed_at"],
                                       offset_time(attempt["sent_at"]))):
            return False
        job_id = attempt["ack"]["job_id"]
        return (observation["job_id"] == job_id and effect["job_id"] == job_id
                and (job_id is None or in_use(observation)))

    def finish(self, attempt, status):
        if attempt["kind"] == "restore":
            translated = {"completed": "restored", "unverifiable": "unknown", "running": "unknown"}
            self.record_restore(attempt, translated.get(status, status))
            return
        if status in ("completed", "running"):
            task = self.store.task(attempt["plan"], attempt["task"])
            if task["cancel"] is not False:
                attempt["claims"] = claims_for(attempt)
        self.run_result(attempt, status)

    def run_result(self, attempt, status, reason=None):
        now = self.clock()
        kwargs = {}
        if attempt["before"] is not None:
            kwargs["saved_state"] = attempt["before"]["values"]
        if attempt["read_back"] is not None:
            kwargs["observed"] = attempt["read_back"]["values"]
        result = RunResult(
            result_id=identity("rs"), kind="run", operation_id=attempt["op"], plan_id=attempt["plan"],
            plan_version=attempt["version"], task_id=attempt["task"], device=attempt["action"]["device"],
            cmd=attempt["action"]["cmd"], substrate=attempt["substrate"], status=status, reason=reason,
            at=now.isoformat(), **kwargs,
        )
        attempt["status"] = status
        attempt["reason"] = reason
        self.store.save_attempt(attempt)
        self.store.queue(result.result_id, "execution", "/v1/hub/executions", now.timestamp(),
                         packet(ExecutionResult(result), "execution_result.json"))

    def owns_job(self, observation, epoch, *, operation=None):
        job = observation["job_id"]
        return job is not None and any(
            attempt["kind"] == "run" and attempt["epoch"] == epoch
            and attempt["status"] == "running" and attempt["ack"]["job_id"] == job
            and (operation is None or attempt["op"] == operation)
            for attempt in self.store.attempts(target=observation["target"])
        )

    async def finish_jobs(self):
        for attempt in self.store.attempts():
            if attempt["kind"] != "run" or attempt["status"] != "running":
                continue
            active = self.target(Action.model_validate(attempt["action"]))
            if not active or active[2] != attempt["epoch"]:
                with self.store.db:
                    self.run_result(attempt, "unknown")
                continue
            observation = await self.read(attempt["target"])
            if not observation or not observation["available"]:
                continue
            attempt = self.store.operation(attempt["op"])
            job = attempt["ack"]["job_id"]
            device_type = active[0].type
            recent = self.observations.completed_jobs.get(attempt["target"])
            running_revision = attempt["read_back"]["world_revision"]
            finished = observation["event_type"] == f"{device_type}.completed" or (
                recent and recent["job_id"] == job
                and running_revision < recent["world_revision"] <= observation["world_revision"]
                and witnesses(recent, {"in_use"}) == witnesses(observation, {"in_use"})
            )
            same_job = observation["job_id"] == job
            if same_job and in_use(observation):
                continue
            complete = (finished and same_job and observation["operation_id"] is None
                        and observation["world_revision"] > running_revision)
            attempt["read_back"] = observation
            with self.store.db:
                self.run_result(attempt, "completed" if complete else "unknown")

    async def lifecycle(self, task):
        if task["closed"] == "final":
            return
        attempts = [attempt for attempt in self.store.attempts(task=task)
                    if attempt["kind"] == "run" and attempt["before"] is not None]
        triggered = offset_time(task["triggered_at"]) if attempts else None
        end = end_status(self.store, task, self.clock(), started_at=triggered)
        if end is None:
            return
        if not attempts or end == "relinquished":
            self.close_task(task)
            return
        if end == "withheld_end_not_observed":
            task["closed"] = end
            self.report_restore(task, end, [
                {"device": device, "status": end}
                for device in dict.fromkeys(attempt["action"]["device"] for attempt in attempts)
            ])
            return
        for attempt in attempts:
            current = self.store.task(task["plan"], task["id"])
            end = end_status(self.store, current, self.clock(), started_at=triggered)
            if end == "relinquished":
                self.close_task(current)
                return
            if end != "restore":
                return
            if attempt["op"] not in current["restore_items"]:
                await self.restore(attempt, current)
        current = self.store.task(task["plan"], task["id"])
        if end_status(self.store, current, self.clock(), started_at=triggered) != "restore":
            return
        by_device = defaultdict(list)
        for attempt in attempts:
            outcome = current["restore_items"].get(attempt["op"])
            by_device[attempt["action"]["device"]].append(outcome or "unknown")
        statuses = ("failed", "unknown", "skipped_user_changed", "restored", "not_needed")
        items = [{"device": device, "status": next(status for status in statuses if status in outcomes)}
                 for device, outcomes in by_device.items()]
        done = all(attempt["op"] in current["restore_items"] for attempt in attempts)
        self.report_restore(current, "observed_end" if done else "waiting_for_read", items, close=done)

    def close_task(self, task):
        with self.store.db:
            task["closed"] = "final"
            for attempt in self.store.attempts(task=task):
                for claim in attempt["claims"].values():
                    claim["owned"] = False
                self.store.save_attempt(attempt)
            self.store.save_task(task)

    async def restore(self, attempt, task):
        action = Action.model_validate(attempt["action"])
        active = self.target(action)
        if not active or active[2] != attempt["epoch"]:
            return self.save_restore_item(task, attempt["op"], "unknown")
        if not delegated(active[0], action.cmd):
            return self.save_restore_item(task, attempt["op"], "unknown")
        if not active[3]:
            await self.discover()
            active = self.target(action)
            if not active or active[2] != attempt["epoch"]:
                return self.save_restore_item(task, attempt["op"], "unknown")
            if not active[3]:
                return
        generation = self.device.generation
        observation = await self.read(attempt["target"])
        if not observation or not observation["available"]:
            return
        self.reload_installation()
        active = self.target(action)
        task = self.store.task(task["plan"], task["id"])
        triggered = offset_time(task["triggered_at"])
        if end_status(self.store, task, self.clock(), started_at=triggered) != "restore":
            return
        if not active or active[2] != attempt["epoch"] or generation != self.device.generation:
            return self.save_restore_item(task, attempt["op"], "unknown")
        if in_use(observation) and not self.owns_job(observation, active[2], operation=attempt["op"]):
            return self.save_restore_item(task, attempt["op"], "skipped_user_changed")
        attempt = self.store.operation(attempt["op"])
        claims = attempt["claims"]
        desired = {prop: claim["before"] for prop, claim in claims.items() if claim["owned"]}
        skipped = any(not claim["owned"] for claim in claims.values())
        if not desired:
            status = "skipped_user_changed" if skipped else (
                "not_needed" if attempt["status"] in ("completed", "running", "failed") else "unknown"
            )
            return self.save_restore_item(task, attempt["op"], status)
        device, binding, _, capability = active
        command = delegated(device, action.cmd)
        current_mapping = binding.desired(action)
        if (self.config_error or not command or value_reason(action, command) or not capability
                or action.cmd not in capability.commands or desired.keys() - capability.properties
                or current_mapping is None or desired.keys() - current_mapping.keys()):
            return self.save_restore_item(task, attempt["op"], "unknown")
        expected = witnesses(observation, desired.keys() | {"in_use"})
        if (not job_guard_available(capability, observation, expected)
                or any(expected.get(prop) != claims[prop]["witness"] for prop in desired)):
            return self.save_restore_item(task, attempt["op"], "unknown")
        restoration = self.attempt(task, "restore/" + attempt["op"], action, active,
                                   before=observation, desired=desired)
        restoration.update(kind="restore", original=attempt["op"], partially_released=skipped)
        with self.store.db:
            self.store.reserve(restoration)
        await self.apply(restoration, expected, generation)

    def save_restore_item(self, task, operation, status):
        with self.store.db:
            task["restore_items"][operation] = status
            self.store.save_task(task)

    def record_restore(self, attempt, status):
        if status == "restored" and attempt["partially_released"]:
            status = "skipped_user_changed"
        task = self.store.task(attempt["plan"], attempt["task"])
        task["restore_items"][attempt["original"]] = status
        attempt["status"] = status
        self.store.save_attempt(attempt)
        self.store.save_task(task)

    def report_restore(self, task, stage, items, *, close=False):
        if stage not in task["restore_reported"]:
            now = self.clock()
            result = RestoreResult(
                result_id=identity("rs"), kind="restore", plan_id=task["plan"],
                plan_version=task["version"], task_id=task["id"], at=now.isoformat(), items=items,
            )
            with self.store.db:
                task["restore_reported"].append(stage)
                self.store.save_task(task)
                self.store.queue(result.result_id, "execution", "/v1/hub/executions", now.timestamp(),
                                 packet(ExecutionResult(result), "execution_result.json"))
        if close:
            self.close_task(task)


def witnesses(observation, properties):
    return {prop: observation["revisions"][prop] for prop in properties
            if prop in observation["revisions"] and observation["revisions"][prop] is not None}


def same_values(observation, desired):
    return all(prop in observation["values"] and observation["values"][prop] == value
               for prop, value in desired.items())


def claims_for(attempt):
    before, after = attempt["before"]["values"], attempt["read_back"]["values"]
    return {
        prop: {"before": before[prop], "desired": after[prop], "owned": True,
               "witness": attempt["read_back"]["revisions"][prop]}
        for prop in attempt["desired"] if prop in before and before[prop] != after[prop]
    }


def in_use(observation):
    value = observation["values"].get("in_use")
    if type(value) is bool:
        return value
    return observation["job_id"] is not None and not (observation["event_type"] or "").endswith(".completed")


def job_guard_available(capability, observation, expected):
    if "in_use" in capability.properties or in_use(observation):
        return type(observation["values"].get("in_use")) is bool and "in_use" in expected
    return True
