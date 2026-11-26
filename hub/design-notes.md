# Home Hub design notes

This file is **non-normative**. It preserves useful implementation choices from
the earlier Hub specification after gate-G0 triage. Agents may follow it as
guidance, but conformance is determined only by [`spec.md`](spec.md), shared
[`contracts/`](../contracts/README.md), and the externally observable acceptance
catalogue. A different implementation is valid when it meets those sources.

The notes deliberately omit or correct earlier choices that conflict with owner
decisions: same-version plan conflicts, Hub quiet-hours/room policy, attribution
copied from world provenance, a separate demo clock, and time-fallback protective
release are not retained.

## 1. Suggested domain model

The following objects have proved useful without being required shapes:

| Object | Suggested consequential content |
| --- | --- |
| Installation | Household ID, installation revision, logical-to-native bindings, and separate credential references |
| Registry entry | Logical device ID/type, room, label, admitted flag, delegated commands/value schemas, `never`, events, substrate, local-operation capability, and binding epoch |
| Plan batch | `(plan_id, plan_version)`, validated contract body, admission result, and per-plan highest version |
| Task/action | Stable task/action identity, native target, desired values, trigger, end, current control, and restore class when the contract can express it |
| Attempt | Stable operation ID, reservation/start time, before observation, command acknowledgement, read-back, and outcome |
| Observation | Native target, source time, availability, property values/revisions, substrate, echoed operation ID, and local-operation flag; never actor truth |
| Ownership | One `(native target, property)` claim containing task, before/desired values, post-effect revision, and owned flag |
| Outgoing packet | Immutable event/result identity, exact contract packet, and delivery standing |

A structured tuple/JSON value is safer than delimiter-concatenated strings for
internal task keys. Carry metadata can preserve a started unchanged action across
plan versions. A binding epoch can prevent old ownership from following a logical
ID onto a replacement device. Discovery can yield candidates that are revalidated
before binding. Room/label/delegation edits can preserve logical identity while
incrementing the devices projection revision.

## 2. Process and dependency boundary

A useful high-level flow is:

```text
Server plan -> contract adapter -> admission -> durable store -> scheduler
                                                          -> device port
Server sink <- stable outgoing packets <- verification <- fresh observation
```

The Hub, App, fixture Server, and Simulator should remain separate processes and
state owners. The Hub should use protocol I/O rather than importing Simulator or
App packages, and a cached Hub projection should not masquerade as an independent
device observation. An integration harness can compose the processes only through
their public ports.

One possible module split is retained as guidance:

| Area | Responsibility |
| --- | --- |
| `api.py` / `bootstrap.py` | Lifespan, configuration, local dashboard/health, connector and Server composition |
| `domain.py` | Internal task, trigger, observation, receipt, event, ownership, and result types |
| `runtime.py` | Version/control gate, waits, dispatch, verification, lifecycle, ownership, and restoration |
| `clock.py` / `durations.py` | Wall-clock access and explicit duration validation |
| `rules.py` | Pure source/order/window matching and next trigger frontier |
| `store.py` | Durable schema, migrations, transactions, and outgoing packets |
| `registry.py` | Installation, binding, capability, delegation, and substrate projection |
| `connectors/` | Device discovery/read/command/event protocol adapters |
| `server_adapter.py` | Generated-contract validation and C-1/C-2/C-3/C-4 conversion |

Keeping one canonical execution engine avoids fixture/demo behavior drifting into
a second product runtime. Splits are most useful when they remove a real dependency
conflict rather than mirror this table mechanically.

## 3. Platform and configuration baseline

The previous implementation selected Python 3.12+, pinned dependencies,
FastAPI/Uvicorn, SQLite, an HTTP client, and MQTT. These remain reasonable choices,
not product requirements.

Useful configuration profiles include:

- a no-device local profile with a dedicated DB;
- a team/fixture Server profile with Server URL, household ID, Hub-key reference,
  installation state, and generated contract models;
- an isolated Simulator test profile with a unique DB and MQTT namespace; and
- an explicitly named physical-candidate adapter with separate qualification.

The presentation/demo path uses wall time and Server `DEMO_MODE`. An injected
virtual clock remains useful for isolated deterministic tests, but should not be
exposed as a second running-demo clock. Unknown profiles can fail startup. Secrets
belong in a local secret-store abstraction or environment reference, never plans,
SQLite evidence, fixtures, or logs. HTTPS is appropriate outside loopback test
peers.

A person enters the household connection code in local Hub setup. The Hub
process reads it from `SPIRA_HUB_KEY` and uses it to authenticate to the Server.

## 4. Durable-store sketch

SQLite with one writer, WAL, and `synchronous=FULL` is a conservative starting
point. A previous target schema was:

| Table / identity | Suggested retained contents |
| --- | --- |
| `plans(plan_id)` | Highest accepted version, retained across task expiry |
| `plan_batches(plan_id, version)` | Validated body, admission result, receive time, and saved ack |
| `tasks(task_key)` | Internal body, status, before/after observation, operation ID, trigger/end times, restore standing, and result |
| `events(event_id)` | Raw source-bound event and ingress ordering |
| `controls(control_id)` | Pause and plan/card/task cancellation state |
| `ownership(native_target, property)` | Task, before/desired/revision witness, binding epoch, and owned flag |
| `outbox(result_id)` | Immutable C-4 body and delivery standing |
| `event_outbox(event_id)` | Immutable C-3 body and delivery standing |
| `bridge_state(id)` | Household/installation fences, devices revision, stable Hub ID, and exact pending packets |

Primary/unique identities are natural indexes. Additional status/end/target indexes
can wait for measured scale. Additive transactional migrations with populated-old-
schema tests are safer than destructive rewrites. DDL and any conservative cursor
backfill should roll back together.

The prior 14-day compaction suggestion is only a possible operational default.
If used, it should never remove undelivered packets, active rule history,
operation/task identities, ownership, or plan-version floors. No product retention
period has been decided.

## 5. State-machine sketch

These internal names are illustrative:

```text
batch: received -> rejected | admitted
       equal/lower version -> ignored
work:  WAITING -> EXECUTING -> VERIFIED | RUNNING | MISMATCH
       WAITING -> CANCELLED | EXPIRED | BLOCKED | UNSUPPORTED
       EXECUTING -> UNVERIFIABLE | INDETERMINATE
job:   RUNNING -> COMPLETED | OVERRIDDEN | STOPPED | UNVERIFIABLE
restore: pending -> RESTORING -> RESTORED | SKIPPED_OVERRIDE
                              | SKIPPED_UNSAFE | FAILED | UNKNOWN
```

Receipt alone never reaches `VERIFIED` or `COMPLETED`. Product effect status and
lifecycle closure should remain distinct. Pause or cancellation should not let an
old admitted version revive on resume. A pre-I/O restore failure can be retried;
uncertainty after a write reservation should remain explicit.

A first-event delay can bind to the first eligible occurrence. If an implementation
uses stable-state predicates, gaps, contradictions, and process downtime should
reset unwitnessed continuity rather than credit time the Hub did not observe.

Mood restoration and protective release should be separate lifecycle branches.
The latter has no time-fallback transition: it stays protected until an observed
`event_end`. Until SP-11 changes the shared contract, avoid inventing a wire field;
keep any fixture-only classification clearly bounded to test support.

## 6. Suggested workflows

```text
admit(plan):
  validate generated C-1 model, household, plan ID, version, and addressable IDs
  if version <= durable per-plan floor: ignore
  validate each line against declared binding/delegation/schema without world reads
  preserve cumulative cancellations and released=false waiting
  transaction: floor + batch + valid tasks + cancellation + saved ack
  deliver the saved ack

execute(task):
  discover/read target and Hub-owned execution gates
  pull current Server snapshot
  recheck version/control/delegation/binding/availability/in-use
  do not add quiet-hours, room, or intent policy
  transaction: reserve a unique operation ID and before observation
  dispatch; persist the correlated acknowledgement
  require a fresh same-target report echoing operation ID for a SPIRA effect
  for jobs, also require the same stable run/job identity
  reconcile property revisions and retain only still-owned changed properties
  transaction: effect outcome + immutable C-4 packet

attribute(device_report):
  if echoed operation ID matches this target and an owned Hub operation: spira
  else if declared local-operation capability and local_operation is true: user
  else: unknown
  if no matching SPIRA operation: release affected property ownership regardless
  never consult actor/provenance/by, door, presence, or proximity

restore(task):
  obtain a fresh independent read and release changed ownership
  if no owned properties: report skipped
  if protective and no observed event_end: remain protected
  conditionally write only owned properties against current revision witnesses
  preserve outside values on missing protection or revision conflict
  read back, then persist outcome + immutable C-4 restore packet
```

The device report fields and MQTT topics are intentionally not specified here;
[`simulator/protocol.md`](../simulator/protocol.md) owns them. Gate evidence showed
that direct `operation_id` reflection is preferable to guessing from desired-value
equality, and that local operation belongs on the same state transition rather
than requiring a separate actor-bearing message.

## 7. Retry and timeout defaults

Contract timing remains normative: pull every 15 seconds, immediately when an
event response says `plans_changed`, and immediately before a run. Earlier local
defaults can be retained as configurable starting points only:

- exponential pre-dispatch retry capped at 60 seconds, default one attempt and a
  configurable maximum of 10;
- 1-second deferral after a current-authority failure;
- 5-second HTTP timeout with adapter backoff capped at 10 seconds;
- finite monotonic device-verification timeout with 100 ms sampling;
- 5-second retry for a restore that failed before any device I/O; and
- no retry for accepted mismatch, ambiguous dispatch, or any write whose lack of
  effect is not proven.

The per-plan version floor is not a household-global cursor. Contract/schema
rejection should stay visible. Equal/lower plan versions are ignored even when a
same-version body differs; they are not a local conflict extension.

## 8. Concurrency and transaction guidance

One process/event loop owning the store is the simplest supported model. A runtime
lock can serialize eligibility, execution lifecycle, and restore; a separate pull
lock can serialize Server snapshots. If both are used, a consistent order such as
runtime then pull avoids inversion, and pull should not await a runtime tick while
holding its lock.

Never hold a SQLite transaction across HTTP or device I/O. Because controls and
versions can change while a read awaits, the final synchronous gate immediately
before reservation is important. A guarded unique reservation is the final
dispatch arbiter. Device observations should be able to revoke ownership while
verification waits. A worker/thread redesign needs an explicit locking review.

## 9. Recovery guidance

One conservative startup sequence is:

```text
open and migrate the DB; validate household/installation fences
load per-plan floors, tasks, controls, attempts, ownership, and pending packets
mark unresolved EXECUTING/RESTORING writes indeterminate
discard unwitnessed stability continuity
compose Server/device/secret-store/wall-clock ports
pull current Server state; on failure block only new effects
fresh-read devices before lifecycle/restore work
resend exact saved C-3/C-4 packets with their original identities
```

The dispatch-after-I/O crash window cannot promise exactly-once physical effects.
Durable pre-dispatch reservation prevents blind duplicate dispatch and exposes the
remaining uncertainty. Operator reconciliation may inspect independent state but
should not turn a guess into verified history or delete a version floor to retry.

## 10. Security, privacy, and operations

Reasonable engineering guidance retained from the earlier spec:

- bind local APIs to loopback/private interfaces and authenticate control/state
  surfaces; health should expose no secrets;
- keep tokens, raw orders, fabric keys, and full DB bundles out of logs/evidence;
- isolate virtual fault APIs from normal and physical-device paths;
- report process liveness separately from Server/device readiness;
- diagnose outgoing backlog, last current-pull failure, and rejected packets; and
- record code revision, process identity, bounds, and known evidence gaps in test
  receipts.

Transport/software PASS does not qualify a physical device. Thin SDK surface,
discovery, or a virtual adapter is not proof of live capability or authority.

## 11. Ports and conversion ownership

Narrow internal ports remain useful:

| Port | Suggested semantics |
| --- | --- |
| Plan source | Generated-contract pull/ack and fresh controls; no device reads during admission |
| Device connector | Discover capability, read observation, command with operation ID/revision witnesses, stream protocol signals, close |
| Result/event sink | Deliver immutable saved packet IDs/bodies and retain until a matching response |
| Secret store | Resolve named references during composition; no new provisioning wire implied |
| Clock | Wall time in running scenarios; injectable time only in isolated tests |

The Server adapter should own C-1/C-2/C-3/C-4 DTO conversion and use generated
`spira_contracts` models. Internal models need not import wire DTOs. The fixture
Server is a replaceable test peer, not a second contract owner. Hub-to-device
transport follows the Simulator protocol.

## 12. Additional implementation checks

These checks moved out of the product acceptance catalogue because they validate
an implementation choice rather than a product claim:

- open and migrate a populated older DB twice; fail each backfill step and confirm
  atomic rollback and idempotent rerun;
- compact acknowledged old history while retaining pending packets, active rule
  history, task/operation identities, ownership, and plan floors;
- boot a Server profile with a missing secret reference and fail before admission
  without revealing a secret value;
- send concurrent eligibility ticks and prove only one operation reservation;
- crash between reservation, command, acknowledgement, read-back, and packet send,
  checking explicit uncertainty at every boundary; and
- exercise conditional-restore races, missing revision protection, rebind, and
  observation gaps while preserving outside values.

Arbitrary natural-language plans, purchase-intent inference, KB/S7 behavior,
multi-node consensus, blind job retry, deployment automation, full-device reboot,
and contract redefinition remain outside the Hub implementation. Adding a device
family is an adapter/qualification task and cannot weaken the normative delegation,
read-back, attribution, ownership, or restoration behavior.
