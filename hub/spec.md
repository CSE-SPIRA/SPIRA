# Home Hub gate-G0 specification

This is the normative product specification for `hub/`. `MUST`, `MUST NOT`,
`SHOULD`, and `MAY` are normative. Shared HTTP bodies, identifiers, enums,
polling, version handling, and state meanings remain authoritative in
[`contracts/`](../contracts/README.md). The Hub-to-device protocol is owned by
[`simulator/protocol.md`](../simulator/protocol.md); this document consumes that
protocol and does not redefine it. Non-normative implementation guidance is in
[`design-notes.md`](design-notes.md).
The [screen reference](screens.md) describes the ledger and its engineering detail.

## 1. Purpose and boundaries

The Hub is an adapter that carries out the Server's judgments in the home
without making its own. It executes versioned plans at the specified time,
preserves person-made changes, and reports observations and execution results
to the Server. It retains waiting work independently of the App and Simulator
processes. (PC-4, PC-5, PC-6)

The Hub does not infer purchase intent, create preparation work, choose a
different target or value, judge household preference, or implement Server
plan-time policy such as quiet hours or room suitability. The Server owns those
judgments and S7 memory. The Hub MUST initiate communication with the Server
through the device registration, plan pull and acknowledgement, event, and
execution routes in `contracts/openapi/hub.yaml`. The Server never calls the
Hub or Simulator. The Hub MUST NOT communicate directly with the App. The
local dashboard serves engineering diagnostics. (PC-1, PC-2, PC-4, PC-6)

### Server routes this part relies on

Current availability follows the [Hub OpenAPI file](../contracts/openapi/hub.yaml),
the real Server's [Hub router](../server/spira_server/api/hub_routes.py), and its
[readiness route](../server/spira_server/main.py). The Hub behavior below comes
from [the HTTP client](spira_hub/contracts.py) and
[`Runtime.refresh`, `Runtime.register`, and `Runtime.flush`](spira_hub/runtime.py).

| Server route | Served by the real Server on this branch | Hub behavior if absent |
| --- | --- | --- |
| `GET /health` | Yes | The Hub runtime does not call Server readiness. Its own `/health` reflects successful plan reconciliation and MQTT availability. |
| `PUT /v1/hub/households/{household_id}/devices` | Yes | Registration stays unconfirmed and is retried on later refreshes. A successful plan pull can still reconcile. |
| `GET /v1/hub/plans?household={household_id}` | Yes | The Hub records a pull error, retains the saved snapshot, and retries. Before any new effect, a failed recheck blocks execution as `plan_unconfirmed`. |
| `POST /v1/hub/plans/{plan_id}/ack` | Yes, returns 204 | A 404 leaves the acknowledgement queued with `HTTP 404`. Later flushes retry the stored packet. |
| `POST /v1/hub/events` | No | A 404 leaves the C-3 packet pending with `HTTP 404`. Later flushes retry the same packet, and a failed delivery yields no `plans_changed` response. Normal plan polling continues. |
| `POST /v1/hub/executions` | No | A 404 leaves the C-4 run or restore packet pending with `HTTP 404`. Later flushes retry the same packet. The dashboard still shows the local outcome and its outstanding delivery. |

For replay, the Hub optionally reads the demo clock from
`SPIRA_DEMO_CLOCK_URL`. It uses wall time until the first valid clock response
and retains the last valid clock anchors through read failures. The Hub
publishes configured demo-clock state to the Simulator on MQTT `P/clock`.
The real Server has no demo-clock route on this branch. With the variable unset,
the Hub uses wall time. See [Hub startup](spira_hub/__main__.py),
[MQTT clock publication](spira_hub/device.py), and the
[real Server demo routes](../server/spira_server/api/demo_routes.py).

## 2. Requirements

### H1. Installation identity

**HUB-14.** The Server creates the Hub API key in response to
`POST /v1/households`. The App displays it as a connection code. A person
MUST enter the key in the Hub's local setup. The demo launcher provides it
through `SPIRA_HUB_KEY`. The App MUST NOT send the key to the Hub over the
network.

**H1-R3.** A replacement native device MUST NOT inherit an earlier device's
temporary-property ownership or restoration authority merely because it has the
same logical device ID, room, or label. (PC-5)

### H2. Delegation and capabilities

**H2-R1.** The Hub MUST publish admitted devices in C-2 with the installed
device type and room, the user's delegated `commands` and their value schemas,
any `never` prohibitions, and the current devices revision. It MUST NOT execute
a command that is no longer delegated. (PC-3, PC-5)

**H2-R2.** Discovery or order sharing MUST NOT grant delegation. A valid,
previously unseen device type MUST remain usable as data when its declared
capabilities satisfy the contract; virtual success MUST NOT be presented as
physical-device qualification. (PC-3, PC-4)

**H2-R3.** Delegation MUST come from the user. Until the Server provides a path
for the user's delegation settings, the Hub MUST read `commands` and `never`
from the installation file. The installation records device types and rooms as
facts about the home.

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
card-Stop cancellation, household pause, and the latest user delegation,
regardless of its source. While delegation comes from the installation, the
Hub MUST reload that file for this check. If the pull fails, it MUST start no
new effect and report `blocked: plan_unconfirmed`; lifecycle and restoration
of effects already started continue. (PC-4, PC-5)

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
appliance). The plan contract marks protective tasks with `protective: true`
(agreed with the Server on 2026-11-19; contracts PR pending). The Hub MUST NOT
classify tasks itself; it uses only that flag.
- A protective task MUST be released only after an actually observed
  `event_end`. A time fallback (`or_time`, `or_after`, elapsed time, missing
  evidence, or an inferred end) MUST end its lifecycle without releasing, and
  the item is reported `withheld_end_not_observed`, never `restored` or
  `not_needed`.
- A non-protective task (mood) follows the contract: at its end, including a
  time fallback, still-owned properties are restored.
- Until the contract carries the flag and the status, the Hub MUST treat every
  task as protective: a time fallback restores nothing, and the withheld item
  is reported `unknown`.

Every restoration MUST preserve non-owned values and report each restored,
withheld or skipped device. (PC-5)

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

**H8-R3.** The engineering detail MUST put these four views first: waiting work and
its trigger; command acknowledgement versus read-back; person actions with the
Hub-computed `by` and the C-3 payload sent to the Server; and restoration versus
skip outcomes. It MUST identify each device as virtual or physical and visibly
mark the class-A local-operation assumption. (PC-4, PC-5, PC-6)

**H8-R4.** The first screen MUST group the ledger by preparation (plan ID),
with the newest preparation kept open and older preparations collapsed on arrival.
Each group shows its first receipt time and the latest available counts for
situation tasks and item notices. Rows from all versions appear newest first,
with version changes shown as subdued rows.
Rows show local wall time, the device or home event, household wording, and a
source marker explained in the legend. Outstanding deliveries show a pending
or failed mark. The ledger MUST include unverified runs and restoration outcomes.
The header names the household. At 1100 px and above, the read-only installed
device list appears beside the ledger. The detail link MUST open H8-R3 and give
access to individual report types and delivery records. (PC-4, PC-6)

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
| HB-AT-1 | The Hub discovers ten Simulator devices | The Server receives a C-2 registration for all ten devices. No plan targets a device while it has no delegation | PC-3 | H2-R1, H2-R2 |
| HB-AT-2 | The user changes delegation in the App after a Server path is available | The Hub learns the change only through the Server. The App sends zero requests to the Hub | PC-3, PC-5 | H2-R3, H5-R1 |
| HB-AT-3 | A delegated task reaches its scheduled time | The Hub runs it and reports completion only for effects confirmed by read-back | PC-4, PC-5 | H5-R1, H6-R1 |
| HB-AT-4 | A person changes a light in the Simulator | The Hub posts `light.changed` with `by: user` and leaves that property at the person's value when restoring the task | PC-5, PC-6 | H4-R1, H4-R2, H7-R1, H8-R1 |
| HB-AT-5 | The user turns off a running line in the App | The Hub receives a newer Server plan version and restores only eligible effects it still owns | PC-4, PC-5 | H3-R3, H3-R4, H7-R1, H7-R2 |
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
| HUB-AT16 | `ep_9031` with protective (child lock, kettle off) and mood actions active, in two runs: (a) an observed `event_end` arrives before `or_time`; (b) wall time passes `or_time` without `event_end` | (a) still-owned protective properties are released and mood properties restored. (b) no protective release command is sent and those items are reported `withheld_end_not_observed`; still-owned mood properties are restored. Under the interim rule, (b) sends no restore command at all and reports `unknown` | PC-5 | H4-R3, H7-R2 |
| HUB-AT17 | Waiting, accepted-but-unverified, attributed person change, Server event delivery, restored, and skipped cases are present | The detail opens with the four H8-R3 groups, including exact `by`, sent C-3 content, virtual/physical labels, and assumption badge | PC-4, PC-5, PC-6 | H8-R2, H8-R3 |
| HUB-AT18 | The three demo surfaces run with Server `DEMO_MODE` off and on | All timestamps advance on wall time; only Server-supplied absolute/duration values shorten in demo mode; Hub exposes no separate demo-clock control | PC-4 | H4-R4 |
| HUB-AT19 | App and Hub clients replay all three contract episodes, including card reactions, C-3 events, and C-4 results | The fixture answers every App/Hub OpenAPI route with schema-valid responses; the Simulator judge reads `by` from the fixture's received C-3 records; surfaces label the peer as a fixture with no inference claim | PC-1, PC-2, PC-3, PC-4, PC-5, PC-6 | H10-R1 |
| HUB-AT20 | Run the ep_9031 birthday scene against the fixture and open the dashboard | The ledger groups happenings by plan receipt, newest first. The source legend identifies the row markers and outstanding deliveries are marked. Report types and H8-R3 diagnostics are available through the detail link | PC-4, PC-6 | H8-R4 |

## 4. Open items

- **Agreed with the Server, contracts PR pending (2026-11-19):** plan tasks get
  `protective: true` (chosen by the Server from a command list, not by the LLM);
  `restore_item_status` gets `withheld_end_not_observed`; card line `end_state`
  gets `withheld`. H7-R2 states both the agreed rule and the interim rule used
  until that PR lands.
- **O-24 — owner:** whether a withheld protective item is released when its
  `event_end` is observed after the time fallback ended the task.
- **O-01 / PQ-01 — professor:** confirm whether class-A appliances may be
  modelled as reporting local panel operation. Until answered, this is a visible
  virtual-device assumption; Matter and unverified physical devices are class B.
- **O-02 / SP-01 — Server:** decide how one card Stop affects future S7 memory.
  The answer does not change H7-R4's immediate Hub behavior.
- **Agreed fixture changes, contracts PR pending:** the `ep_9031` line-off example
  becomes the cleaning line `t_clean#1`; `ep_9150` gets a rationale and a
  strawberry line for the same-item contrast. The fixture Server follows the
  committed contract fixtures until that PR lands.
- **Agreed Server rule:** shared-display text (fridge, TV) carries item guidance
  only, never intent, event names, guests or themes. The Hub displays
  Server-supplied values and does not judge text content.
- **SP-14 — Server:** the Server exposes device registration, plan pull, and
  plan acknowledgement. C-3 event and C-4 execution receipt routes remain
  Server work. H10-R1 verifies delivery against the fixture Server.
