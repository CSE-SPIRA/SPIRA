# Independent Simulator implementation specification

This document is the normative implementation specification for `simulator/`.
`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. Shared Server-facing
identifiers, events, enums, and state meanings remain authoritative in
[`contracts/`](../contracts/README.md). The Simulator has no direct Server API;
its device transport remains an owner-internal boundary until separately adopted.

This specification does not certify a runtime, integrated demo, or physical
device equivalence. Those claims require the corresponding implementation and
evidence.

## 1. Purpose, scope and owners

The Simulator MUST own an independent virtual household truth that can challenge
Home commands rather than mirror Home expectations. It MUST run without App,
Home, or Server implementation imports. It owns devices, state, receipts,
jobs, clock, transition history, operator occurrences and observation projections.
It MUST NOT infer order intent, generate plans, assign Home execution success,
perform Server/KB reasoning or treat virtual effects as physical evidence.

E1–E8 below preserve the adopted product responsibilities. Scenario identifiers,
vendor assumptions and one demonstration device set are fixtures, not a closed world
model. Shared wire contracts remain external; local MQTT/HTTP is an explicitly
bounded device test port. App↔Hub provisioning remains an unresolved joint port.

## 2. Glossary and object ownership

| Object | Simulator-owned fields and meaning |
| --- | --- |
| World | schema version, world revision, profile, clock mode and device collection |
| Room | stable room identifier and display metadata; no automation authority |
| Device | native target, type, room, properties, supported commands and availability |
| Capability | writable keys, value restrictions, families, prohibited operations and assumption label |
| Property | actual value and opaque revision witness; unrelated properties have separate witnesses |
| Command | operation ID, target, desired values and optional expected property witnesses |
| Receipt | operation ID, accepted/rejected/unsupported/unavailable/conflict status and optional job ID |
| Job | stable job ID, target, run state and completion frontier |
| Observation | target, present values, witnesses, observed time, availability, provenance and substrate |
| Event | stable event ID, source, type, occurrence time, provenance and factual payload |
| Transition | monotonic journal sequence/revision, kind, target, before/after state and occurrence time |
| Snapshot | versioned durable world projection at a revision; independent of a Home database |
| Scenario | explicit initial conditions, operator events and deterministic time advances |

Home owns task/action/restore authority. Server owns plans, preparation meaning,
history and memory interpretation. The Simulator MAY expose actual Home results
in a composed viewer but MUST preserve their source and identity.

## 3. Component and process boundary

```text
Home connector -- MQTT command/read --> independent World process + WORLD_DB
operator ------ HTTP occurrence ----> World
viewer -------- GET observation ----> World or qualified Home observation port
scenario actor - explicit time/fault -> World
```

No shared mutable Python object/database may connect production components.
Simulator's database, MQTT prefix and virtual clock MUST be isolated per run.
A bounded composition peer belongs in the integration harness. Simulator MUST
neither import it nor require its lifetime for standalone state/read/viewer operation.

## 4. Architecture and responsibility map

| Target module owner | Responsibility | Direction |
| --- | --- | --- |
| `world.py` / `bootstrap.py` | Process lifespan, configuration, command/job application and clock | composition calls profiles/storage; no Home source dependency |
| `profiles.py` | declared world objects/capability validation | pure data and validation |
| `storage.py` | additive schema, versioned state snapshots and transition journal | SQLite only; no transport dependencies |
| `pressure.py` | bounded opt-in fault actor and separate pressure journal | calls world public application operations |
| `transport/http.py`, `transport/mqtt.py` | local API and device-port transport | convert at boundary; no state ownership |
| `viewer.py`, static viewer assets | standalone or composed observation view | HTTP GET projections; no product write |
| `operator.py` | bounded engineering occurrence controls | authenticated separate write routes |

The compact application/transport composition MAY remain together until a split
removes a demonstrated responsibility conflict. Empty folders for symmetry are
not required. §16 is the growth direction, not permission to duplicate actors.

## 5. Platform, runtime and profiles

Python 3.12+, FastAPI/Uvicorn, SQLite and an MQTT client are selected. MQTT requires an
independent broker. Configuration MUST be resolved before opening process state:
`WORLD_DB`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_PREFIX`, `WORLD_PROFILE`, `WORLD_CLOCK`,
`WORLD_START` and `WORLD_PRESSURE`. Profile defaults are local demo conveniences.
Fresh development databases MUST use an explicitly unique prefix and path.

Wall-clock mode is the ordinary Server-connected demo profile. Virtual clock is
an isolated replay/test profile; it MUST NOT silently replace wall time. A profile
MUST label declared vendor assumptions and narrow exposed capabilities explicitly.
Selecting a profile MUST NOT invent physical qualification.

## 6. Domain model and invariants

<a id="e1"></a>

### E1. Household and device configuration

The World MUST create declared devices and their initial values once, persist
them independently and retain their targets across restart. Discovery MUST expose
actual configured capabilities/availability, room, device type, assumptions and
conditional-write support. Discovery MUST NOT register a device or grant standing
delegation in Home. Profiles MUST permit other fixture households without engine
changes. A reference composition may include cleaner, light, display, cooktop, oven,
fridge and kettle plug; actual native profile target names belong to adapters.

<a id="e2"></a>

### E2. Commands and independent state

Command acceptance MUST remain distinct from observed effect. An accepted
`unchanged` command MUST be representable. A receipt MUST preserve operation ID;
a duplicate ID MUST return the original receipt without another effect. Property
writes MUST validate capability and value restrictions before effect. Conditional
writes MUST compare supplied witnesses and mutate atomically under the World
lock. Conflict MUST have no effect. A manual change away and back MUST still
replace the property's witness. A successful SPIRA no-op MAY keep its witness.

Unknown target/property MUST fail without partial property mutation. A target
read MUST return only that target, present keys and current freshness. Neither
an old matching value nor command receipt proves fresh effect. World provenance
MUST remain a factual actor/substrate field; Home owns conversion to external
`payload.by` values such as user/spira/unknown. World MUST NOT import C-3 DTOs.

<a id="e3"></a>

### E3. Stable long-running jobs

A started job MUST have a stable ID correlated to the command operation. Running
and completed MUST be distinct observations. A job MUST expose independently
observed progress while running; progress MAY be coarse declared stages rather
than an invented continuous physical percentage. An already running exclusive device
MUST reject another start. Completion MUST apply only when the current device
job ID still matches the due job and its state is running. A stopped/replaced job
MUST NOT later emit a false same-job completion. The due frontier MUST survive
restart and progress only with the selected world clock.

<a id="e4"></a>

### E4. Events, operator and faults

Operator occurrences MUST pass through the World application API, durably record
event ID, source, occurrence time and provenance in ordered history, and exercise
normal observation paths. Durable history is separate from guaranteed transport
delivery; an unavailable broker MUST NOT erase the committed occurrence. Supported bounded
examples include package arrival, guest arrival, event end, manual device change,
offline, reject, delay, unchanged and unavailable readback. Lost readback after an
accepted effect MUST be separately reproducible: World actual state may change
while the connector is unable to observe it. An operator MUST NOT
write Home task/result databases or manufacture planned success. Fault actor
routes MUST refuse access unless `WORLD_PRESSURE=1`. Held pressure responses MUST
be bounded and MUST NOT hold the World lock while waiting.

<a id="e5"></a>

### E5. Read-only household viewer

The standalone viewer MUST render World room/device actual values, revision,
clock mode and virtual substrate without Home. Its routes/assets MUST expose
only GET projection behavior. Composed viewer MAY overlay admitted registry,
Home observations, execution/restore results and event timeline via HTTP, with
sources separate. The composed layout MUST use admitted registry room/name data,
show a generic tile for unknown valid device types, and preserve source/fault/
offline/manual-change badges plus an event timeline. Planned and observed state
MUST have distinct labels. A stale
or unavailable source MUST remain visibly stale/unavailable; disconnect MUST NOT
change World state. Operator write controls MUST be a separate route/surface.

<a id="e6"></a>

### E6. Manual interference and provenance

Manual property transitions MUST replace revision witnesses even on equal-value
writes, persist before acknowledgement, and be observable after restart.
Explicit user-origin operator actions MAY assert USER; unidentified interference
MUST remain UNKNOWN or SIMULATOR as appropriate. No mismatch or revision conflict
alone may be upgraded to USER. Substrate VIRTUAL_MQTT and actor provenance are
separate fields. Home decides whether ownership is revoked.

<a id="e7"></a>

### E7. End and restore visualization

The World MUST accept a restore only as a normal conditional command; it MUST NOT
read Home ownership or choose which properties to restore. The viewer MUST
preserve restored/skipped-user-changed/failed/unknown distinctions supplied by
Home and show actual observed values separately. Example: pink light → explicit
user warm white → event end leaves warm white. An unknown actor conflict MUST
not be displayed as a known user change.

<a id="e8"></a>

### E8. Mixed virtual and physical composition

A composed household MAY bind one qualified physical light and virtual siblings
through Home. Each result MUST retain its actual substrate and qualification.
The World MUST NOT impersonate the physical target; a fallback MUST be visibly
virtual. Tapo remains a candidate until model/connector/readback qualification.
The full reference scenario MUST remain possible with virtual devices alone. Viewer
presence or a local fixture PASS MUST NOT imply physical equivalence.

## 7. Persisted state, identity, indexes and migrations

The World MUST use a dedicated SQLite database. Selected additive tables are:

| Table/key | Durable content |
| --- | --- |
| `state(id PRIMARY KEY)` | JSON target/value/property-witness snapshot |
| `ops(id PRIMARY KEY)` | original command receipt; operation IDs remain deduplicated |
| `control(id PRIMARY KEY)` | profile, virtual time, world schema version and revision |
| `jobs(id PRIMARY KEY)` | target and completion due time |
| `world_journal(seq INTEGER PRIMARY KEY)` | transition kind/time/target/before/after |
| `pressure_journal(seq INTEGER PRIMARY KEY)` | separately enabled adversary ground-truth facts |

Each state transition MUST commit the state and its journal entry/revision in one
SQLite transaction. Existing databases MUST migrate additively without replacing
state, opaque property witnesses, receipts, jobs or virtual time. Schema version
1 is the initial explicit World schema. A future unsupported version MUST fail
closed before connecting transport or modifying existing state. Revision is a
monotonic durable integer; property witnesses remain opaque strings and MUST NOT
be converted into the global revision.

Snapshot export MUST name schema version and world revision. The authoritative
snapshot is the committed `state` table plus durable control/receipt/job records;
JSON export is a projection, not a second writer. Journal MUST support ordered
bounded pagination by sequence. Default walking-skeleton retention MUST preserve
all transitions and operation identities. Future compaction MUST retain an
explicit checkpoint and replay boundary; deleting dedup IDs is not ordinary GC.

## 8. State machines and transition guards

| Machine | Transition | Guard / durable result |
| --- | --- | --- |
| World | absent → initialized → serving → stopped → serving | schema supported; committed state survives |
| Command | unseen → rejected or accepted | target/capability/value/availability/CAS checked under lock |
| Command | known ID → original receipt | no second dispatch/effect regardless of current state |
| Effect | accepted → applied / no effect / uncertain | fault mode determines effect; receipt is unchanged |
| Job | idle/stopped/completed → running | new accepted start, no exclusive running job |
| Job | running → completed | clock reaches due AND current same-job identity |
| Job | running → stopped | accepted explicit stop; old timer cannot complete it |
| Observation | current → stale/unavailable/contradictory → current | explicit faults/recovery; no success inference |
| Clock | t → t' | virtual mode and finite t' ≥ t; jobs observe due frontier |
| Fault | armed → reached → released/expired → consumed | bounded one-use occurrence; clear releases waits |
| Viewer | loading → current / stale / unavailable | GET result freshness; no state-transition authority |

Operator reset MUST be explicit, scoped to an isolated World and produce a new
world epoch rather than silently reusing old command identities. Persistent reset
and full deterministic journal replay are target extensions (§19), not current
restart behavior. There MUST be no implicit reset on process start or failure.

## 9. Primary workflows

```text
Boot: settings → open SQLite → verify/migrate schema → restore profile/time/state
      → initialize only missing devices → connect MQTT → serve observations
Command: MQTT envelope → ID lookup → validate → durable receipt → effect/job
         → persist state+journal → factual event → reply
Manual: operator POST → validate all keys → state+witness+journal commit
        → factual state event → independent Home read
Restart: stop process → reopen SAME World DB → preserve revisions/ops/jobs/time
         → resume current due jobs → no automatic replay of old command effects
Viewer: GET asset → GET /sim/snapshot → render actual world with source/clock/revision
```

The World emits facts; Home owns acceptance of evidence and restoration. In the
Server-free slice, the integration harness starts independent processes and drives public ports.
App receives fixture/result projections through its own adapter, never World DB.

## 10. Failure, retry, timeout and idempotency

Malformed envelopes MUST fail without effect. Unsupported desired keys/values,
offline target, explicit reject and witness conflict MUST have distinct receipt
outcomes. A repeated operation ID MUST return the stored status even after a
fault mode or property value changes. MQTT retained requests MUST be ignored;
responses MUST only publish to the configured prefix's reply namespace.

Delayed effects MAY be intentionally uncertain across process death. The World
MUST NOT replay an already accepted command on restart to hide that uncertainty.
Readback unavailable, stale or incomplete MUST remain representable separately
from command failure. Broker outage MUST NOT authorize new state assumptions;
state/journal persistence remains independent. A future durable transport outbox
MUST preserve event identity and payload across retries; until implemented,
non-durable event transport MUST remain an explicit limitation rather than being
represented as lossless delivery.

## 11. Concurrency, ordering and transactions

A single World process MUST own a database. One reentrant application lock
serializes MQTT callbacks, HTTP mutations, clock advancement and job progression.
No network wait/held fault delay may occur while the lock is held. SQLite writes
MUST commit before publishing observations/events. Journal sequence defines
transition order; wall time is not an ordering substitute. Multi-property
mutation MUST validate every key before updating any value. Read-only snapshot
projection MUST take the same lock and MUST NOT advance timers or alter state.

Command receipt and effect are deliberately separate durability boundaries: a
crash between them yields accepted/no verified effect, not an invitation to
reissue. SQLite storage MUST roll back a failed state+journal transaction.
Two processes MUST NOT share a World DB or virtual clock. The runtime SHOULD
reject accidental concurrent ownership rather than rely on SQLite write errors.

## 12. Restart, recovery and reconciliation

On reopen, schema/profile/revision and all prior property witnesses MUST be
loaded before transport connects. Existing state MUST NOT be overwritten by
profile defaults. Due jobs MUST verify current job identity; persisted virtual
time MUST NOT jump to host time. Restart MUST preserve duplicate receipts.
Ephemeral delay timers and fault arms MAY expire across restart and MUST be
reported as such rather than silently replayed. On corrupt/unsupported storage,
startup MUST fail visibly and preserve the database for investigation.

## 13. Security, privacy and secrets

World/operator/fault HTTP endpoints are local engineering surfaces, not public
product authorization. Deployment MUST bind them to an isolated loopback/private
network and protect any remote access at the deployment boundary. No shared team
provisioning protocol is adopted here. DBs, broker credentials, raw payload logs,
packages and keys MUST remain outside Git. Evidence export MUST be bounded and
exclude secrets and household content not needed for the asserted claim.
The standalone viewer MUST not embed mutable credentials or offer operator POSTs.

## 14. Observability, health and bounded evidence

`/world` and `/devices` expose current device/command/clock state; `/sim/snapshot`
MUST expose schema/revision and persisted actual state without mutation;
`/sim/journal?after=N&limit=L` MUST return a bounded ordered transition page.
Diagnostics MUST distinguish process availability, broker connection, state
freshness and physical qualification. A healthy HTTP listener alone does not
prove broker delivery. Events/journal SHOULD identify command/job/target and time;
raw evidence stays ignored. Receipts MUST record environment, commands and scope.

## 15. Ports, adapters and conversion ownership

| Port | Input/output | Owner |
| --- | --- | --- |
| Device MQTT | discover/read/command/clock with request/reply IDs | local connector boundary; joint protocol, not team Server wire |
| World HTTP | explicit mutation, world/clock/profile observation/control | Simulator application boundary |
| Snapshot/journal GET | versioned actual world and transition history | Simulator storage projection |
| Composed view HTTP | Home registry/states/events/tasks/health | viewer converts source-labelled display DTOs |
| Operator HTTP | bounded manual/event/fault occurrences | engineering operator only |

Home Server DTOs MUST NOT enter Simulator models. Native targets and command
shapes are interpreted by the local transport adapter, not inferred from App
labels. MQTT conditional-write behavior is a virtual qualification property;
physical devices require independent native guarantees.

## 16. Module layout and dependency rules

Growth MAY split `domain/{world,device,job,event,clock}`,
`application/{commands,observations,scenarios,faults,reset}`,
`storage/{snapshots,journal}`, `transport/{http,mqtt}` and
`ui/{viewer,operator,static}` when there is substantive code to own. Today §4's
files are canonical; new parallel `new`/`v2`/`skeleton` packages are prohibited.
Storage MUST NOT import UI/HTTP/MQTT. Profiles MUST NOT import Home or the
integration harness. The
viewer may read another component through HTTP only. Existing process entries,
resources and compatibility forwards MUST be preserved until callers transition.

## 17. Consequential algorithms

```text
apply_manual(target, values, actor):
  lock World
  read current state; validate all keys before changing anything
  for each supplied key: replace witness, even when value is equal
  begin transaction
    replace state; increment world revision; append before/after transition
  commit
  emit factual event; return actual state

conditional_command(operation, target, desired, expected):
  lock World
  if operation known: return durable original receipt
  validate capability/value/availability and compare every expected witness
  persist receipt before any effect
  if accepted and not unchanged:
    create stable job identity when required; apply effect according to fault
  return receipt; independent read remains necessary

complete_due_job(job):
  if current.job_id != job.id OR current.run_state != running: discard old due
  else persist completed state+journal; emit same-job completion fact

snapshot():
  lock World; read durable revision/state/profile/time/jobs/receipt count
  return versioned projection; do not progress jobs or write
```

## 18. Numbered acceptance tests

Each row specifies initial state, public input, required observation and exit.
A target test is not automatically an executed PASS; the implementation PR must
name the test and bounded evidence that closes it.

| ID | Initial state → input | Required observation → exit |
| --- | --- | --- |
| SIM-AT-01 | fresh dedicated DB/profile → start standalone process | version1 snapshot/devices/revision → serving with no Home import |
| SIM-AT-02 | light off → explicit USER mutate on | new property witness, greater world revision and journal before/after → snapshot persisted |
| SIM-AT-03 | committed manual state → kill/restart same DB | identical state/witness/revision/history → no duplicate transition on boot |
| SIM-AT-04 | known operation → same command ID twice | original receipt; one effect only → durable ops identity after restart |
| SIM-AT-05 | off → accepted unchanged fault command | accepted receipt and independently still-off read → no effect success invented |
| SIM-AT-06 | captured witness → manual away/back → conditional command with old witness | conflict; final manual value remains → no stale restoration |
| SIM-AT-07 | cleaner idle → start → advance isolated clock | stable job running then same-job completed after due → completion observed |
| SIM-AT-08 | cleaner running → stop → advance past old due | stopped state; no false completion of old job → idle execution frontier |
| SIM-AT-09 | current sample → stale/omitted/unavailable fault read | explicit stale/missing/error while independent world persists → Home must not infer completion |
| SIM-AT-10 | no Home/Server process → GET standalone viewer/snapshot | virtual actual devices visible; POST to viewer/snapshot/journal denied → world revision unchanged |
| SIM-AT-11 | pressure disabled → POST pressure control | 404 and unchanged world → no fault armed |
| SIM-AT-12 | existing previous-schema DB → start migration | old state/ops/jobs/witnesses preserved; schema/revision/journal added → restart succeeds |
| SIM-AT-13 | unsupported future schema DB → start | explicit startup error and bytes/state preserved → transport never starts |
| SIM-AT-14 | one valid and one invalid property → mutate | atomic rejection, no changed property/witness/journal → initial snapshot remains |
| SIM-AT-15 | revision N → paginated journal reads | ordered bounded sequence after cursor, no mutation → same revision |
| SIM-AT-16 | mixed qualified/unqualified sources → composed view | physical/virtual and known/unknown remain distinct → no aggregate physical claim |
| SIM-AT-17 | isolated scenario snapshot → reset/replay request | explicit epoch and deterministic fact sequence → requires a separately implemented reset/replay increment |

## 19. Extensions and deliberate limits

New rooms/devices/capabilities SHOULD extend profiles plus validation tests.
Physics/3D models, resident daily control, Server inference/KB, real hardware
emulation equivalence, remote fleet management and production provisioning are
unsupported. Durable scenario reset/replay, persistent event delivery outbox,
persistent delay timers/faults, automatic journal compaction and multi-process DB
ownership enforcement remain explicit increments. They MUST NOT be claimed from
ordinary snapshot/restart evidence. Virtual timestamp determinism does not imply
deterministic UUIDs or real-time broker delivery.
