# Home Hub gate-G0 specification

This is the normative product specification for `hub/`. `MUST`, `MUST NOT`,
`SHOULD`, and `MAY` are normative. Shared HTTP bodies, identifiers, enums,
polling, version handling, and state meanings remain authoritative in
[`contracts/`](../contracts/README.md). The Hub-to-device protocol is owned by
[`simulator/protocol.md`](../simulator/protocol.md); this document consumes that
protocol and does not redefine it. Non-normative implementation guidance is in
[`design-notes.md`](design-notes.md).

## 1. Purpose and boundaries

The Hub turns the Server's versioned plans into effects at the specified home
and time, observes what actually happened, preserves person-made changes, and
reports evidence that the Server can use for household memory. It runs
independently of the App and Simulator process, so closing the App does not stop
waiting work. (PC-4, PC-5, PC-6)

The Hub does not infer purchase intent, create preparation work, choose a
different target or value, judge household preference, or implement Server
plan-time policy such as quiet hours or room suitability. The Server owns those
judgments and S7 memory. The Hub communicates with the Server only by the pull,
acknowledgement, event, and result routes in `contracts/openapi/hub.yaml`; the
Server never calls the Hub or Simulator. (PC-1, PC-2, PC-4, PC-6)

## 2. Requirements

### H1. Installation identity

**H1-R3.** A replacement native device MUST NOT inherit an earlier device's
temporary-property ownership or restoration authority merely because it has the
same logical device ID, room, or label. (PC-5)

### H2. Delegation and capabilities

**H2-R1.** The Hub MUST publish only admitted devices and explicitly delegated
commands/value schemas in C-2, including `never` prohibitions and the current
devices revision. It MUST NOT execute a command that is no longer delegated.
(PC-3, PC-5)

**H2-R2.** Discovery or order sharing MUST NOT grant delegation. A valid,
previously unseen device type MUST remain usable as data when its declared
capabilities satisfy the contract; virtual success MUST NOT be presented as
physical-device qualification. (PC-3, PC-4)

### H3. Plans, admission, and versions

**H3-R1.** The Hub MUST pull and validate current C-1 plans without using current
house state to reinterpret the plan. It MUST retain accepted work until its
trigger, including across Hub restart. (PC-4)

**H3-R2.** The Hub MUST reject only malformed addressable tasks for the contract
reasons and MUST admit valid siblings. Admission MUST NOT reject a task because
the device is currently offline, busy, in use, or already in the requested
state; those are execution-time observations. (PC-4, PC-5)

**H3-R3.** For each plan, a higher `plan_version` MUST replace the held version.
An equal or lower version MUST be ignored, as required by the contract, without
creating work, sending another device command, or lowering the held version.
(PC-4)

**H3-R4.** Cumulative cancellation MUST take precedence and preserve its
`restore` value. Work with `released: false` MUST wait until a higher Server
version explicitly releases it; the Hub MUST NOT link a package to an order or
release the task itself. Started unchanged work MUST NOT be dispatched again
when a higher version arrives. (PC-4, PC-5)

### H4. Triggers, events, attribution, and time

**H4-R1.** The Hub MUST compute every device-event `payload.by` itself. A device
effect that echoes an `operation_id` matching the Hub's own operation record is
`spira`; otherwise a class-A `local_operation` report is `user`; every other
case is `unknown`. It MUST NOT accept or copy device/world `actor`, `provenance`,
or `by`, and MUST NOT infer a person from door, presence, proximity, or other
indirect signals. Class-A local-operation reporting is an explicit assumption
pending O-01/PQ-01 and MUST be declared as a capability, not presumed for a
device family. (PC-6)

**H4-R2.** The Hub MUST deduplicate events and match only the plan's explicit
event kind, source binding, occurrence time, order, and window. A fact observed
before admission MUST NOT wake newly admitted work. Relevant home and device
events MUST be sent to the Server as C-3 with stable `event_id` values. (PC-4,
PC-6)

**H4-R3.** The Hub MUST wait for explicit plan triggers and MUST NOT infer
purchase intent, synthesize package release, or turn an unobserved home event
into observed evidence. Any time fallback in a plan is a lifecycle fallback,
not evidence that `event_end` occurred. (PC-4, PC-6)

**H4-R4.** The running demo MUST use one clock: the Hub's wall clock and the
absolute values supplied by the Server. Only Server `DEMO_MODE` shortens the
scenario's starting values under COM-15; the Hub MUST NOT run a separate demo
clock. (PC-4)

### H5. Final authority and dispatch

**H5-R1.** Immediately before a new effect, after awaited device reads, the Hub
MUST pull the current Server snapshot and recheck the current plan, line,
card-Stop cancellation, household pause, and delegation. If that pull fails, it
MUST start no new effect and report `blocked: plan_unconfirmed`; lifecycle and
restoration of effects already started continue. (PC-4, PC-5)

**H5-R2.** At execution time the Hub MUST check the active target binding,
delegated capability and value schema, fresh availability, and
`in_use_by_person`. It MUST NOT substitute a device/value or re-legislate Server
plan-time judgments such as quiet hours, room suitability, or intent safety.
(PC-4, PC-5)

**H5-R3.** The Hub MUST assign one stable `operation_id` before dispatch and MUST
prevent concurrent eligibility checks, a higher version, reconnect, or restart
from dispatching the same action twice. (PC-4, PC-5)

### H6. Receipts, observations, and jobs

**H6-R1.** Command acknowledgement and effect are different facts. The Hub MUST
record accepted/rejected acknowledgement separately and MUST report completion
only after a fresh read-back of the same target verifies the effect. A missing,
stale, unavailable, contradictory, or wrong-operation observation MUST remain
`unverifiable` or `unknown`, never completed. (PC-4)

**H6-R2.** A job MUST distinguish command acceptance, observed running, and
fresh completion of the same job. The Hub MUST NOT stop or restore over a job a
person started, or over a replacement/foreign job. (PC-4, PC-5, PC-6)

**H6-R3.** Dispatch uncertainty or process death MUST NOT cause a blind command
retry. Only a failure proven to have produced no effect may be retried while the
task remains current. (PC-4, PC-5)

### H7. Ownership, Stop, and restoration

**H7-R1.** After a verified temporary effect, the Hub MUST track ownership per
changed property. Any later change not matched to that SPIRA operation releases
ownership, whether its attribution is `user` or `unknown`. Ownership MUST NOT be
reacquired when the value later happens to equal SPIRA's desired value, and a
released property MUST NOT be overwritten during restoration. (PC-5)

**H7-R2.** Restoration has two product meanings, mood restoration and
protective release (for example unlocking a child lock or re-enabling a disabled
appliance). Protective release MUST occur only after an actually observed
`event_end`. Because the current plan contract does not mark which lines are
protective (O-04/SP-11), the Hub MUST NOT classify lines itself; until the
contract does, a time fallback (`or_time`, `or_after`, elapsed time, missing
evidence, or an inferred end) MUST end the line's lifecycle without restoring
anything, mood included, and restoration of still-owned properties happens only
on an observed `event_end`. A withheld restoration MUST NOT be reported as
`restored` or `not_needed`; until the contract has a value for it (SP-15) the
Hub reports `unknown`. Every restoration MUST preserve non-owned values and
report each restored or skipped device. (PC-5)

**H7-R3.** A device rebind MUST preserve the old device from writes to its
replacement. `restore: false` MUST relinquish restoration authority without
erasing the observed effect. Person-started jobs and all non-SPIRA changes MUST
remain untouched. (PC-5)

**H7-R4.** Card Stop MUST end that card's preparation now: cancel its unstarted
work, request restoration only for effects SPIRA still owns subject to H7-R2,
and preserve person changes and person-started jobs. It MUST NOT stop other
cards, the whole house, or item notices outside the card. The Hub MUST expose no
Stop All or Server-less stop path; Stop reaches it only as the Server's newer
plan version. (PC-5, PC-6)

### H8. Evidence and dashboard

**H8-R1.** C-3 events and C-4 run/restore results MUST use stable
`event_id`/`result_id` values. A resend MUST carry the same identity and body;
delivery failure MUST NOT erase the observation. (PC-4, PC-6)

**H8-R2.** Hub evidence MUST distinguish attempted command, acknowledgement,
fresh read-back, current binding/substrate, Hub-computed `by`, failure or
uncertainty, and restoration outcome. It MUST NOT claim a ground-truth actor,
preference, or successful physical qualification that it did not observe.
(PC-4, PC-6)

**H8-R3.** The Hub dashboard MUST put these four views first: waiting work and
its trigger; command acknowledgement versus read-back; person actions with the
Hub-computed `by` and the C-3 payload sent to the Server; and restoration versus
skip outcomes. It MUST identify each device as virtual or physical and visibly
mark the class-A local-operation assumption. (PC-4, PC-5, PC-6)

### H9. Restart and reconciliation

**H9-R1.** On restart the Hub MUST resume future waiting work and still-owned
restoration, first reconcile the current Server version/Stop/pause/cancellation,
and preserve uncertain dispatch as uncertain rather than executing it again.
(PC-4, PC-5)

**H9-R2.** Reconnect MUST NOT reset plan floors, operation identity, ownership,
or pending C-3/C-4 identity. Before resuming restoration the Hub MUST obtain a
fresh device observation. (PC-4, PC-5)

### H10. Contract fixture Server (test support only)

**H10-R1.** `hub/tests/fixture_server` MUST provide deterministic test support
for `ep_9031`, `ep_9150`, and `ep_9120`. It MUST answer every route and method in
`contracts/openapi/hub.yaml` and `contracts/openapi/app.yaml` with contract-valid
fixture behavior, including plan versions produced by App reactions. It MUST
record the C-3 event bodies it actually receives so the Simulator judge can
compare their `by` values with Simulator-only actor truth. This fixture MUST be
clearly identified as non-inference test support and MUST NOT be presented as
evidence that the real Server, OCR, LLM, KB, or S7 memory is implemented.
(PC-1, PC-2, PC-3, PC-4, PC-5, PC-6; test support only)

## 3. Acceptance catalogue

Every test below is judged through public HTTP/device-protocol surfaces,
persisted fixture-Server receipts, and observed device state; reading Hub
internals is not acceptance evidence.

| ID | Initial state and input | Required external observation | PCs | Requirements |
| --- | --- | --- | --- | --- |
| HUB-AT01 | A plan is accepted; the same version with identical or changed content and then a lower version are pulled | No additional device command or work appears; the held version never regresses; a later higher version is the only replacement | PC-4 | H3-R3, H5-R3 |
| HUB-AT02 | One plan contains a valid delegated line, a malformed/unsupported sibling, an offline valid line, and a valid previously unseen device type | Ack admits valid lines and rejects only the malformed sibling with a contract reason; admission performs no device effect; offline is decided only at execution | PC-3, PC-4, PC-5 | H2-R1, H2-R2, H3-R1, H3-R2 |
| HUB-AT03 | A temporary effect exists on a native device; the logical device is rebound before end | No restore command is sent to the replacement; the old effect/uncertainty remains attributed to the old binding | PC-5 | H1-R3, H7-R3 |
| HUB-AT04 | A task waits for a source-bound event; an old fact, wrong source, out-of-window event, restart, and then one eligible event occur; a package task starts unreleased | Only the eligible event wakes the task once after restart; the package task waits until a higher Server version sets `released: true` | PC-4, PC-6 | H3-R1, H3-R4, H4-R2, H9-R1 |
| HUB-AT05 | A device read is delayed while Stop, pause, a newer plan, delegation revocation, or Server outage arrives; separately, the Server sends a cleaner action during local quiet hours | Revoked/unconfirmed work sends no command and reports the contract block; the current cleaner action is not blocked by a Hub quiet-hours/room policy | PC-4, PC-5 | H5-R1, H5-R2 |
| HUB-AT06 | A command is accepted, followed by stale, failed, missing-property, wrong-operation, and finally fresh matching read-backs | Dashboard and C-4 keep acknowledgement separate; no completion is reported before the fresh matching read-back | PC-4 | H6-R1, H8-R2, H8-R3 |
| HUB-AT07 | A SPIRA standby is followed by a class-A local oven start and later by a foreign replacement job | C-3 reports the local start as `by: user`; Hub sends no stop/restore over either person-started or replacement job | PC-4, PC-5, PC-6 | H4-R1, H6-R2, H7-R3 |
| HUB-AT08 | SPIRA owns two mood properties; one gets a class-A change and the other an unmatched class-B away-and-back change before end | Both changes release ownership; end preserves both final outside values, reports skips, and equality never reacquires either property | PC-5, PC-6 | H7-R1, H7-R2, H8-R1 |
| HUB-AT09 | A process dies after dispatch and while C-3/C-4 packets are unacknowledged, then restarts/reconnects | The device effect is not blindly repeated; uncertainty remains visible; each packet is resent with byte-equivalent identity/body | PC-4, PC-5, PC-6 | H6-R3, H8-R1, H9-R1, H9-R2 |
| HUB-AT12 | Two cards have waiting/running work; Stop is posted for one card through the fixture Server while a person has changed one property and started one job | Only that card's unstarted work is cancelled; its still-owned eligible mood property restores; the person change/job, the other card, and item notices remain; no Hub Stop All or direct stop endpoint exists | PC-5, PC-6 | H3-R4, H7-R1, H7-R2, H7-R4 |
| HUB-AT15 | Five device effects occur: matching echoed operation, class-A local operation, class-B person change, external automation, and unmatched device transition; door/presence signals surround the changes | Fixture Server records `spira`, `user`, `unknown`, `unknown`, `unknown` respectively; removing door/presence signals does not change the outputs | PC-6 | H4-R1, H8-R1, H8-R2 |
| HUB-AT16 | `ep_9031` plan v1 protective and mood actions are active; wall time passes their `or_time` without `event_end`, then an observed `event_end` arrives | At fallback no restore command is sent: child lock, disabled appliance and mood values all remain and are reported `unknown`, never `restored`/`not_needed`; only the observed `event_end` restores still-owned properties | PC-5 | H4-R3, H7-R2 |
| HUB-AT17 | Waiting, accepted-but-unverified, attributed person change, Server event delivery, restored, and skipped cases are present | The dashboard's first views show the four H8-R3 groups, including exact `by`, sent C-3 content, virtual/physical labels, and assumption badge | PC-4, PC-5, PC-6 | H8-R2, H8-R3 |
| HUB-AT18 | The three demo surfaces run with Server `DEMO_MODE` off and on | All timestamps advance on wall time; only Server-supplied absolute/duration values shorten in demo mode; Hub exposes no separate demo-clock control | PC-4 | H4-R4 |
| HUB-AT19 | App and Hub clients replay all three contract episodes, including card reactions, C-3 events, and C-4 results | The fixture answers every App/Hub OpenAPI route with schema-valid responses; the Simulator judge reads `by` from the fixture's received C-3 records; surfaces label the peer as a fixture with no inference claim | PC-1, PC-2, PC-3, PC-4, PC-5, PC-6 | H10-R1 |

## 4. Open items

- **O-01 / PQ-01 — professor:** confirm whether class-A appliances may be
  modelled as reporting local panel operation. Until answered, this is a visible
  virtual-device assumption; Matter and unverified physical devices are class B.
- **O-02 / SP-01 — Server:** decide how one card Stop affects future S7 memory.
  The answer does not change H7-R4's immediate Hub behavior.
- **O-04 / SP-09 / SP-11 — Server and contract:** the current plan contract does
  not identify mood restoration versus protective release, while `or_time` is
  generic. A separate contract PR must express the distinction; the Hub MUST NOT
  weaken H7-R2 in the meantime.
- **O-05 / SP-06 / SP-07 / SP-12 — Server and shared fixtures:** decide the
  `ep_9150` rationale/same-item contrast and change the `ep_9031` line-off example
  from child safety to a mood display. The fixture Server follows committed
  contract fixtures until that separate contract change lands.
- **SP-15 — contract:** a restore item status for "restoration withheld because
  the end was not observed"; until then H7-R2 reports `unknown`.
- **SP-16 — Server:** shared displays (fridge, TV) must never show intent text,
  only item guidance and mood. The text is produced at plan time by the Server;
  the Hub displays Server-supplied values and does not judge text content.
- **SP-14 — Server:** the real Server at gate G0 exposes only `/health`; core
  schema and App/Hub contract routes remain Server work. Passing H10-R1 is not
  real-Server interoperability evidence.
