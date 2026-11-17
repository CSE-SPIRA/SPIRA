# SPIRA Home Hub Specification

Implementation specification for `hub/`. It defines the Hub's execution responsibility and contract use; it does not certify an existing runtime or physical-device integration.

- **Sources.** The owner Hub design formerly maintained in Notion, the current integration contract, and the Server specification.
- **Authority.** [`contracts/`](../contracts/README.md) is authoritative for shared HTTP bodies, identifiers, enums, and state meanings. If this document conflicts with a shared contract, the contract wins.
- **Implementation.** Python. Use models/validators in [`contracts/generated/python/`](../contracts/generated/python/) rather than redefining wire models.
- **This change.** Requirements only: no Hub runtime, contract revision, deployment claim, or device qualification.

## 1. Role and boundary

The Hub is the household execution authority between the Server and delegated devices. It registers delegated capabilities, pulls versioned plans, waits for triggers, checks authority and current state immediately before work, dispatches commands, reads state back, reports results, and restores only properties it still owns.

The Hub does **not** read screenshots, infer intent, generate/rewrite plans, call the KB, calculate App card state, or treat command acknowledgement as proof of physical outcome. The Server never calls the Hub; the Hub initiates every Server request.

## 2. Shared contract surface

The Hub uses [`contracts/openapi/hub.yaml`](../contracts/openapi/hub.yaml), [`contracts/rules.md`](../contracts/rules.md), and their linked schemas.

| Concern | Contract source | Hub responsibility |
| --- | --- | --- |
| Authentication | `hubKey` | Send the household API key; keep it outside logs/source control. |
| Device projection | `devices.json` | Publish delegated devices with a monotonic revision. |
| Plan pull | `plan_pull.json`, `plan.json` | Pull latest unfinished plans and apply replacement/cancellation. |
| Admission | `ack.json` | Admit valid tasks independently; reject only malformed tasks with contract reasons. |
| Events | `event_batch.json`, `event_response.json` | Send ordered idempotent events with explicit provenance. |
| Execution | `execution_result.json` | Send one run result per action and distinct restore results. |
| Identity/enums | `rules.md`, `enums.json` | Preserve identities across retries and restarts. |

The Hub-to-device/Simulator protocol is internal until a shared contract is adopted. Internal models need not mirror Server wire models, but adapters perform explicit conversion.

## 3. Required behaviour

### H1. Provisioning and household isolation

- Store one `household_id`, Hub API key, Server endpoint, and local device registry per provisioned household.
- Reject or quarantine data for another household.
- The API key is issued once by household creation. Local App-to-Hub handoff remains a joint contract gap, not a public API invented here.
- Keep secrets, fabric/controller material, and device credentials outside source control and ordinary logs.

### H2. Device registry and projection

- Discover/configure devices through adapters; expose only delegated devices and supported capabilities to the Server.
- Assign stable contract-valid device IDs. Reconnect/restart must not create a new identity for the same binding.
- Send the full delegated list at startup and whenever device, room, capability, or delegation changes; increment `revision` once per accepted local change.
- Offline devices remain in the projection. Availability is runtime state, not grounds to remove delegation or reject a well-formed task.

### H3. Plan synchronization and versioning

- Pull every 15 seconds, when an event response says `plans_changed: true`, and immediately before an action starts.
- Keep the latest observed version while retaining execution history needed to reconcile older started work.
- A newer version replaces unstarted old work and applies its cumulative `cancelled` list; it does not erase started-work identity/results.
- `paused: true` prevents new starts; it does not report already-started work as cancelled or restored.
- A pull/persistence failure retains the last confirmed plan but cannot authorize a new action at run time.

### H4. Task admission and acknowledgement

- Validate each task against shared schema and command/capability rules.
- Admission is task-level. Admit every well-formed representable task; put malformed tasks in `rejected_tasks` with a contract reason.
- Do not reject merely because a device is busy, offline, already in the requested state, or waiting for an event. Those are execution-time facts.
- Persist admission before acknowledging. Re-sent acknowledgement must not create another task.

### H5. Trigger scheduling

- Support absolute-time and contract event triggers, including `package.brought_in`, `guest_arrived`, and `event_end`.
- Persist trigger waits and wake-up identity so restart neither loses nor duplicates a due action.
- Recheck plan version, pause, cancellation, and delegation when an action is about to start.
- One event may satisfy one task's start and another task's end; process both against one durable event identity.

### H6. Pre-dispatch gate

Immediately before each action, the Hub must:

1. pull plans successfully;
2. confirm plan/version/task remains live and not cancelled;
3. confirm the household is not paused for new work;
4. confirm target capability remains delegated; and
5. read current target state from the device/world adapter.

If the final pull fails, start no new effect and report `blocked` with `plan_unconfirmed`. Other failures use contract blocked/failed/unknown meanings. Admission itself does not read world state or manufacture an outcome.

### H7. Dispatch, operation identity, and readback

- Allocate one stable `operation_id` per dispatch; all updates for it reuse that ID.
- Capture pre-action values for properties the Hub may restore.
- Keep transport acknowledgement separate from observed device state.
- Report `running` only for work with an actual started phase.
- Report `completed` only after fresh readback shows the requested postcondition. ACK, accepted job, elapsed timer, or cached state is insufficient.
- When observation is unavailable/contradictory, report the correct `failed`, `unknown`, `unverifiable`, or `blocked` outcome.
- Send one execution-result request per device action with stable `result_id` on retry.

### H8. Event provenance and outbox

- Convert local changes to contract events preserving occurrence time and source.
- Use `payload.by: user` only with independent user-action evidence; Hub-issued changes are `spira`; ambiguity is `unknown`.
- Never convert `unknown` into user feedback or a successful confirmation signal.
- Persist events/results in an outbox before delivery. Retry in order with the same `event_id`/`result_id`.
- After durably processing `plans_changed: true`, schedule an immediate pull.

### H9. Restore ownership

- Restore only properties changed by this Hub task and recorded with pre-action values.
- Read current state first. Restore only when it still matches the Hub's known post-action value; otherwise preserve it and report `skipped_user_changed`.
- Keep `not_needed`, `restored`, `skipped_user_changed`, `failed`, and `unknown` distinct.
- New work may supersede old restore only through explicit per-property ownership; never write an entire old snapshot over unrelated changes.
- Send a stable restore result with contract-required per-device outcomes.

### H10. Restart and reconciliation

- Persist provisioned identity, bindings/revision, plan versions, admitted tasks, waits, operation IDs, saved state, outbox, and terminal results.
- After restart, query the adapter/world before resolving dispatched-but-not-terminal operations.
- Do not issue a second physical command solely because the process missed the first response.
- Single-dispatch identity survives process and host restart.

### H11. Diagnostics and safety

- Log task, operation, device, plan version, adapter, transition, and time without secrets/private household content.
- Distinguish process readiness, Server reachability, and adapter/device availability.
- Unsupported commands fail closed; adapters may narrow capability but not silently reinterpret commands.
- Use timezone-aware timestamps; retries retain original event occurrence time.

## 4. Execution state machine

```text
pulled -> validated -> admitted -> waiting -> pre-dispatch gate
                                           | blocked -> reported
                                           | authorized
                                           v
                                  dispatched -> fresh readback
                                           -> terminal run result
                                           -> end rule/restore result
```

The durable boundary is not “command sent”; it is a journaled operation plus independently observed state and an idempotent outbox record.

## 5. Acceptance cases

Component tests must cover at least:

1. full device projection, revision increments, and stable binding identity;
2. periodic, event-driven, and immediate pre-run pulls;
3. version replacement, cumulative cancellation, pause, and partial admission;
4. admission while offline followed by an execution-time outcome;
5. `plan_unconfirmed` with no device effect on failed pre-run pull;
6. command ACK without matching readback never becoming `completed`;
7. stable operation/result/event IDs across retry and restart;
8. user, SPIRA, and unknown provenance kept distinct;
9. per-property restore preserving an intervening user change; and
10. crash recovery after dispatch without a duplicate command.

Contract review also runs repository checks/fixtures. External conformance requires a real Server run. Physical qualification requires independent device/controller evidence; virtual MQTT evidence is not a physical-device pass.

## 6. Open joint decisions and non-claims

Separate adoption is required for the local App-to-Hub setup/discovery protocol; shared Hub-to-Simulator/device wire; production secret rotation/multi-household provisioning; and named physical-device/controller support with conditional-write guarantees.

This specification does not claim deployed-Server interoperability, production provisioning, or qualification of any physical appliance.
