# Simulator design notes

> **Non-normative.** These notes preserve useful implementation choices from the
> earlier Simulator specification. Agents may use them as guidance, but they are
> not product requirements or acceptance criteria. If these notes conflict with
> [`spec.md`](spec.md), [`protocol.md`](protocol.md), or [`contracts/`](../contracts/README.md),
> those normative sources win.

## 1. Suggested shape

The existing walking skeleton uses Python, FastAPI/Uvicorn, and SQLite. MQTT can
be added through an independent broker. Keeping the World in its own process and
letting the Hub, viewer composition, and test harness communicate only through
ports makes the independent-household claim easy to inspect.

One possible responsibility split is:

| Area | Guidance |
| --- | --- |
| World/bootstrap | process lifetime, settings, device transitions, jobs, wall-clock scheduling |
| Profiles | declared rooms, devices, capabilities, initial values, substrate, Class A assumption labels |
| Storage | snapshots, operation receipts, property witnesses, jobs, private truth journal |
| MQTT transport | convert protocol requests and signals without owning state or attribution |
| HTTP transport | snapshot, operator, judge, and bounded engineering controls |
| Viewer | read-only household projection and optional source-labelled Hub overlay |
| Operator | actor selection, home occurrences, and bounded fault controls |

The current compact `api.py`/`storage.py` arrangement can remain until a real
dependency conflict justifies extraction. If it grows, a reasonable direction is
`domain/{world,device,job,clock}`, `application/{commands,observations,faults}`,
`storage/`, `transport/{http,mqtt}`, and `ui/{viewer,operator}`. Parallel
`new`/`v2` execution trees tend to hide which implementation is authoritative.

Suggested dependency direction:

```text
composition/UI/transport -> application -> domain -> storage interface
```

Storage does not need to import HTTP, MQTT, or UI. Profiles do not need Hub or
fixture-Server imports. A composed viewer can read another process through HTTP
rather than sharing mutable objects or databases.

## 2. Configuration and profiles

The previous design used the following settings:

| Setting | Use |
| --- | --- |
| `WORLD_DB` | dedicated SQLite path |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_PREFIX` | isolated device namespace |
| `WORLD_PROFILE` | household/device declaration |
| `WORLD_OPERATOR` | bounded local operator surface |
| `WORLD_PRESSURE` | opt-in engineering fault controls |

Resolving settings before state is opened avoids partially initialized worlds.
Each development run benefits from a unique database path and MQTT prefix.
Profiles can label assumptions and expose only capabilities they actually model;
selecting a profile is not physical qualification.

Product/demo behavior uses wall time. A deterministic injected clock can still
be useful inside isolated unit tests, but it is not a demo profile, does not
cross MQTT, and does not replace COM-15 Server `DEMO_MODE`.

## 3. Internal model

The following internal objects remain useful implementation concepts:

| Object | Consequential content |
| --- | --- |
| World | schema version, epoch, revision, profile, device collection |
| Device | native target, type, room, substrate, properties, capability, availability, local-operation reporting flag |
| Property | actual value and opaque revision witness |
| Command | request/operation identity, target, desired values, optional expected witnesses |
| Receipt | durable status, operation identity, optional job identity |
| Job | target, stable identity, run state, due frontier |
| State report | protocol-safe values, witnesses, times, availability, command correlation, local-operation boolean |
| Truth record | private actor, device/event/time, before and after values |
| Snapshot | versioned read-only projection of committed World state |

Truth and protocol state are deliberately different types. The World transition
can store the private actor and then call a signal projector that removes it. A
protocol DTO should have nowhere to put `actor`, `provenance`, or `by`.

Substrate and actor are also independent. `virtual` does not imply SPIRA, and
`physical` does not imply a person.

## 4. Persistence option

SQLite remains a practical local choice. The earlier design proposed these
additive records:

| Table/key | Suggested durable content |
| --- | --- |
| `state(id PRIMARY KEY)` | target values and per-property witnesses |
| `ops(id PRIMARY KEY)` | original command receipt for operation deduplication |
| `control(id PRIMARY KEY)` | profile, epoch, schema version, World revision |
| `jobs(id PRIMARY KEY)` | target, stable job identity, state, due time |
| `world_journal(seq INTEGER PRIMARY KEY)` | ordered before/after transition facts without public attribution DTOs |
| `truth_journal(seq INTEGER PRIMARY KEY)` | Simulator-private actor/device/type/time facts used by the judge |
| `pressure_journal(seq INTEGER PRIMARY KEY)` | separately enabled fault-actor facts |

A state transition, its property-witness changes, World revision, and private
truth row are easiest to reason about when committed in one local transaction.
Snapshot JSON is then a projection, not a second writer. Operation receipts can
be committed before the effect so a crash stays explicit rather than inviting a
blind repeat.

Additive schema migrations can preserve state, witnesses, receipts, jobs, epoch,
and truth history. A future unsupported schema can fail before transport starts
and leave the database intact. Journal pagination by monotonically increasing
sequence is useful for bounded diagnostics; wall time should not be the sole
ordering key.

Possible future compaction can use an explicit checkpoint/replay boundary while
retaining live operation identities. Deleting deduplication identities as routine
garbage collection would weaken restart behavior.

## 5. Transition guards

The previous state-machine sketch is still helpful as design guidance:

```text
World:      absent -> initialized -> serving -> stopped -> serving
Command:    unseen -> rejected | accepted
Command:    known operation ID -> original receipt, no second effect
Effect:     accepted -> applied | no effect | uncertain
Job:        idle/stopped/completed -> running -> completed | stopped
Observation current -> stale/unavailable/contradictory -> current
Fault:      armed -> reached -> released/expired -> consumed
Viewer:     loading -> current | stale | unavailable
```

Important guards behind the product-level behavior include:

- compare every supplied property witness before changing anything;
- validate all properties before a multi-property mutation;
- replace a witness for independent equal-value and away-and-back writes;
- complete a due job only if the current device still holds that same running
  job identity;
- keep accepted/no-effect and accepted/effect-observation as separate facts;
- avoid implicit reset on startup.

An explicit reset tool can create a new World epoch so old operation identities
are not silently reused.

## 6. Workflows

```text
Boot:
  settings -> open storage -> verify/migrate -> load state/receipts/jobs
  -> initialize only missing profile devices -> connect MQTT -> serve

Command:
  protocol envelope -> operation lookup -> validate target/capability/value/CAS
  -> durable receipt -> effect/job -> state + journal + truth commit
  -> protocol-safe state report

Operator device action:
  choose actor -> validate transition -> commit state/witness/private truth
  -> project signal from device class -> update operator/viewer

Judge:
  private truth -> read fixture Server's received C-3 record
  -> join logical device + type + occurrence time -> operator-only verdict

Restart:
  reopen same storage -> preserve witnesses/receipts/jobs/epoch
  -> resume only the current due job -> do not replay old command effects
```

The household viewer can use World reads for actual state and a separate
source-labelled Hub projection for faint planned work and restore results. The
World database should not become the integration API.

## 7. Failure and transport guidance

Useful failure distinctions from the earlier specification are:

- malformed envelope versus unsupported target/property/value;
- offline device versus explicit rejection;
- accepted but unchanged versus changed but unavailable to read back;
- stale, missing-key, incomplete, or contradictory observation;
- command uncertainty across process death;
- broker gap versus a proven absence of an event.

The protocol starts with QoS 1 and visible gaps, not a claim of lossless event
delivery. A future durable signal outbox can preserve signal identity and payload
across retry. Until then, diagnostics can state the gap rather than synthesize
events.

Retained command requests are unsafe and can be ignored. Replies belong only on
the request's configured reply topic. A repeated operation identity returns its
stored receipt even when fault mode, state, or capability later changes.

Fault controls can cover delay, rejection, unchanged effect, offline target, and
lost readback after an accepted effect. Long waits are easier to cancel when they
do not hold the World state lock.

## 8. Concurrency and recovery option

One process owning one database and one application lock is a simple starting
point. MQTT callbacks, operator mutations, job progression, and snapshots can
serialize their short local state changes. Network waits and held-fault delays
stay outside the lock and outside SQLite transactions.

On reopen, the implementation can load schema/profile/epoch/revision and all
property witnesses before transport connects. Profile defaults should initialize
only absent devices. Due jobs can verify current job identity before completion.
Ephemeral delay timers and fault arms may expire across restart if that loss is
reported instead of replayed.

Corrupt or unsupported storage is best preserved for investigation. Two
processes sharing a World database or namespace is an operator error; a lock file
or explicit owner record can make it fail earlier than a SQLite write collision.

## 9. Security and privacy guidance

World, operator, fault, truth, and judge HTTP endpoints are engineering surfaces,
not a production provisioning design. Loopback/private binding, deployment-level
access control, and distinct credentials for the Hub device namespace help keep
truth-side data unreachable to the Hub.

Database files, broker credentials, physical-device tokens, raw evidence, and
keys stay outside Git. Viewer assets do not need mutable credentials or write
controls. Evidence exports can be bounded to the claim being tested and omit
household content and secrets.

## 10. Diagnostics and evidence

Read-only World and device snapshots can expose schema/epoch/revision, actual
state, jobs, receipt counts, broker connection, observation freshness, substrate,
and assumption labels. Ordered journal pages help reproduce a bounded failure.
A healthy HTTP listener is not proof of broker delivery, and a virtual fixture
pass is not physical qualification.

The operator side may expose private actor truth and judge verdicts. The
household viewer and every Hub-readable diagnostic remain truth-free. Evidence
receipts are most useful when they record code revision, environment, commands,
scope, process identities, and known gaps.

## 11. Pseudocode sketches

```text
apply_operator_change(target, values, actor):
  lock World
  read current state; validate every key
  replace witnesses for supplied properties, even when values are equal
  transaction:
    write state; increment World revision
    append public-safe transition facts and private truth(actor)
  project state_report:
    operation_id = null
    local_operation = device reports local operation AND actor is resident/child/guest
    omit actor/provenance/by
  publish; return actual state to operator

apply_command(operation, target, desired, expected):
  lock World
  if operation exists: return original receipt
  validate capability/value/availability and every expected witness
  persist receipt
  if accepted and effect occurs:
    apply effect or create stable job
    report operation_id only on that effect's report
  return receipt; a separate read remains necessary

complete_due_job(job):
  if current.job_id != job.id or current.run_state != running:
    discard stale due item
  else:
    persist completed state and journal
    emit device-self report with operation_id = null

snapshot():
  lock World; read committed state/profile/epoch/revision/jobs/receipt count
  return a versioned projection without advancing jobs or writing
```

## 12. Design-level checks moved out of the product catalogue

These remain useful implementation checks but support no product claim directly:

| Former acceptance ID | Non-normative implementation check |
| --- | --- |
| SIM-AT-11 | Fault-control routes are unavailable when the engineering fault switch is off |
| SIM-AT-12 | Additive migration preserves old state, receipts, jobs, and witnesses |
| SIM-AT-13 | An unsupported future schema fails before transport starts and leaves storage intact |
| SIM-AT-15 | Journal pagination is ordered, bounded, and read-only |
| SIM-AT-17 | Reset/replay creates an explicit new epoch and deterministic fact sequence |

Other useful checks include enforcing storage/UI/transport dependency rules and
ensuring local endpoints and evidence exports do not reveal credentials.

Reset/replay, durable signal outbox, persistent fault timers, automatic journal
compaction, and multi-process database ownership enforcement remain possible
increments. Ordinary snapshot/restart evidence should not be stretched into
claims that those increments already exist.
