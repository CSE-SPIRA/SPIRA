# Simulator specification

This is the normative product specification for `simulator/`. `MUST`, `MUST
NOT`, `SHOULD`, and `MAY` are normative. Shared Server-facing values remain
authoritative in [`contracts/`](../contracts/README.md). The Hub↔Simulator
device boundary is defined in [`protocol.md`](protocol.md), which is normative
for both parts. Implementation guidance is non-normative and lives in
[`design-notes.md`](design-notes.md).
The [screen reference](screens.md) describes the pages and their current behavior.

This specification does not certify an implementation, real Server integration,
or physical-device equivalence. Those claims require separate evidence.

## 1. Purpose and boundaries

The Simulator is an independent household with three roles:

1. **Stage:** accept device commands, change device state, and show the observed
   home by room and device.
2. **People:** let a person act from the house or the operator act as a
   resident, child, guest, or external automation. The Hub observes device
   effects without receiving the actor identity.
3. **Judge:** privately compare who acted with the `by` value that the fixture
   Server actually received from the Hub.

The Simulator owns World truth, virtual-device effects, the operator surface,
the household viewer, and judge results. The Hub owns attribution and all C-3
events sent to the Server. The Server owns intent, plans, household memory, and
whether an observation changes future preparation.

The Simulator MUST NOT infer purchase intent, create plans, decide Hub success,
write Hub or Server result state, expose actor truth on a Hub-readable channel,
or present virtual behavior as physical qualification. It is not a daily-control
app or a 3D digital twin.

The Simulator has no required Server dependency. Its only operational peer is
the Hub through the [device protocol](protocol.md). World state and person actions
work with optional evidence inputs unset. On this branch the viewer and operator
can read C-1 for display from a local file or a configured HTTP source,
including a direct plan-pull URL supplied by the demo launcher. The judge and
restore overlay can use the Hub dashboard or configured test evidence.
See [Simulator startup wiring](spira_simulator/api.py) and the
[demo launcher](../scripts/demo_up.py).

## 2. Numbered requirements

<a id="e1"></a>

### E1. Household and device configuration (PC-4)

**E1-R1.** The World MUST exist independently of App, Hub, and Server process
state. A configured household's devices, capabilities, availability, room,
device type, substrate, and initial state MUST be observable without importing
another part's implementation.

**E1-R2.** Device inventory and plans MUST be replaceable without changing the
World engine. The seven `ep_9031` devices are a fixture, not a closed device
model. Discovery MUST report actual capability; it MUST NOT register a device or
grant delegation in the Hub.

<a id="e2"></a>

### E2. Commands and independently observed state (PC-4, PC-5)

**E2-R1.** Command acknowledgement and device effect MUST remain distinct. The
World MUST represent accepted-but-unchanged, rejected, unavailable, unsupported,
and conditional-write-conflict outcomes, and a fresh state report MUST be
available independently of the acknowledgement.

**E2-R2.** An `operation_id` MUST identify one dispatch. Repeating it MUST return
the original receipt without another effect, including after restart. A report
MAY echo that ID only for the effect caused by that exact Hub command, as defined
by [`protocol.md`](protocol.md).

**E2-R3.** Property revision witnesses MUST change for an independent write,
including an away-and-back or equal-value local write. A conditional command with
an obsolete witness MUST have no effect. Multi-property commands MUST either
apply as one valid effect or leave every property unchanged.

**E2-R4.** Restart MUST preserve observable device state, operation identity,
property witnesses, and unfinished job identity. Restart MUST NOT replay an old
effect or reset the household implicitly.

<a id="e3"></a>

### E3. Long-running jobs (PC-4, PC-5)

**E3-R1.** A started job MUST have stable identity correlated with its command,
and running and completed MUST be separately observable. Completion MUST apply
only to the still-current running job.

**E3-R2.** Stopping or replacing a job MUST prevent a stale completion from the
old job. A job started outside SPIRA MUST remain distinguishable from the job
created by a prior SPIRA command so that the latter cannot stop it.

<a id="e4"></a>

### E4. Operator actions and faults (PC-4, PC-5, PC-6)

In the demo, the enabled operator and its API MUST allow access without credentials for a Simulator bound only to `127.0.0.1`, and MUST require HTTP Basic credentials when bound for LAN access. The server's bind configuration determines this policy.

**E4-R1.** The operator MUST provide package brought in, guest arrival, and event
end occurrences, plus device changes by resident, child, guest, or external
automation. For a device action, the operator chooses only who acted; the
configured device class decides which Hub-readable signal is emitted.

**E4-R2.** The World MUST privately record the actual actor for every relevant
transition, including resident, child, guest, external automation, the device
itself, and SPIRA. The action and truth record MUST survive long enough for the
judge to evaluate the corresponding received C-3 event.

**E4-R3.** The operator MUST be able to demonstrate offline, command rejection,
accepted-but-unchanged effect, and unavailable readback without manufacturing a
Hub completion or changing Server result state.

**SM-3.** A person MUST be able to switch off a running cleaner at the house.
World MUST stop the cleaner and expose the device change for Hub observation.
The Hub reports a user-attributed stop and an `unknown` result for the
interrupted run. The card and memory demonstration MUST use person changes
after a completed run, such as light colour or music.

**SM-4.** The operator MUST offer music and light colour changes as named
person actions on capable devices. These actions MUST use the same World and
Hub observation path as other person changes.

<a id="e5"></a>

### E5. Household viewer (PC-2, PC-4, PC-5, PC-6)

**E5-R1.** The stage viewer MUST show observed device state, with provisional
feedback for person actions as specified in D-5-R2. Planned or
waiting work MUST be shown only as a visually faint, distinct overlay. Stale,
missing, or unavailable observations MUST remain visibly so; disconnection MUST
NOT change World state.

**E5-R2.** The viewer MUST mark physical devices and display their qualification
status. The operator MUST identify substrate per device and show Class A
local-operation reporting as an explicit assumption. The viewer MUST avoid any
aggregate claim that virtual success qualifies a physical device.

**E5-R3.** A no-preparation episode, such as ordinary groceries, MUST be able to
show no planned or applied household preparation. Viewer controls MUST NOT create
execution success. Faults and judge output MUST remain on the operator side.

**E5-R4.** The household viewer MUST draw a 3D household with the
profile's rooms, each device placed in its room, and the entrance as the place
of home events (package, doorbell, door). A viewer MUST be able to
link to the viewers of the other configured households, so the presenter can
switch homes.

**E5-R5.** Each device tile MUST state its observed value as household content,
not raw fields: for example the oven's set temperature, remaining time and
whether it is baking, the light's colour or colour temperature, the display's
scene, and the fridge notices. Each observed fridge notice has its own row,
with an item label when supplied by the device and the full notice available
from the row. The same tile MUST still follow E5-R1 and E5-R2.

**E5-R6.** The viewer MAY mark who made the latest change to a device from World
truth (SPIRA, or a person's display name and path). It MUST NOT show the Hub's
attribution, the judge's verdict, or SPIRA's reasoning, order details, intents,
rationale or card text. Planned overlays show the device, the action with its
device-level target value, and its trigger or time. The viewer and operator
show the plan's guest trigger window. If the guest window passes without a
matching trigger, the viewer shows that the action did not run.

**E5-R7.** The viewer MUST show the wall-clock day of week and time (E9-R1).

**E5-R8.** The operator MUST offer person actions as single controls that name
the person, the path and the act (for example "resident · device panel · start
oven"), built from the profile's people and device commands, never from a plan.

**E5-R9.** The Simulator MUST provide an appliance-app page: a phone-sized page,
openable on its own URL on another phone, that lists the household's devices and
lets a person change their values. A change from it MUST travel the
`other_app` path (no local-operation report), so it reads as Class B to the Hub.

**SM-1.** The default camera MUST frame the entire house prominently. Devices
changed in the same moment MUST receive simultaneously visible markers. A
device starting a run MUST receive a marker. Off devices MUST remain free of
device labels.

**SM-2.** Selecting a change marker or its device MUST open a room or device
close-up with a short explanation of the observed change. Selecting it again,
pressing Escape, or advancing to another moment MUST restore the overview and
hide the explanation. Markers MUST be keyboard-focusable buttons with Korean
labels. Advancing MUST work without selecting a marker.

**D-5-R1.** In the Simulator viewer and demo shell house, selecting a device
MUST open its SM-2 close-up and an adjacent person-action panel. The panel MUST
use the operator's device-specific controls and household people. The birthday
house MUST offer mother, father, child, and guest, default to mother, and
remember the last person selected. Actions MUST use the operator person-action
path through World and the Hub's device observation. The operator page MUST
remain available as a backup. Device selection and actions MUST work by
keyboard. Escape MUST close both the panel and the close-up.

**D-5-R2.** Choosing an action MUST update the house immediately and show that
a World read-back is pending. A fresh World reading MUST replace the provisional
state. If the read fails, the house MUST restore its last observed state and
show the failure. The house MUST use actual data waits for action feedback.

**SM-5.** The demo shell MUST keep the active card visible to the left of the
house throughout the house stage. Server judgment text MUST stay out of
Simulator screens and World state.

<a id="e6"></a>

### E6. Actor signals, Hub attribution, and judge (PC-5, PC-6)

**E6-R1.** Actor handling MUST have exactly three layers:

| Layer | Owner | Allowed content |
| --- | --- | --- |
| Truth | Simulator World only | resident, child, guest, external automation, device itself, SPIRA |
| Observable signal | device → Hub | state/event facts, time, `operation_id`, and Class A `local_operation` only |
| Attribution | Hub | contract `by`: `user`, `spira`, or `unknown` |

No Hub-readable discovery, state, event, acknowledgement, diagnostic, or viewer
projection may contain World `actor`, `ground_truth_actor`, `provenance`, or
precomputed `by`.

**E6-R2.** Devices MUST declare one of these behaviors through
`local_operation_reporting`:

| Class | Behavior | Gate-G0 devices |
| --- | --- | --- |
| A | Reports a local operation without identity. This is an explicit assumption and MUST be labelled as such on screen. | Virtual LG appliances and a virtual light panel |
| B | Does not report a local operation. | Physical Tapo light; Matter virtual devices |

Class A is an explicit product assumption pending PQ-01; requirements remain in
force as an assumption, while acceptance tests that depend on it are provisional.
The Matter classification is confirmed only for the tested matter.js 0.18
virtual-device profile; other Matter capabilities require their own evidence.

**E6-R3.** The judge MUST read `by` from the C-3 event record that
`hub/tests/fixture_server` actually received, not from a Hub audit claim. It MUST
join World truth to that event by logical device ID, event type, and occurrence
time; the household configuration MUST carry, for each native target, the same
logical device ID that the Hub registry uses, and
produce exactly one of: `match`, `person-reported-unknown`,
`non-person-reported-user`, or `person-not-decision-maker` (child or guest).
Judge results and truth details MUST be visible only on the operator side.

<a id="e7"></a>

### E7. End and restore observation (PC-5)

**E7-R1.** The World MUST accept a restore only as an ordinary conditional device
command. It MUST NOT read Hub ownership or decide which properties should be
restored.

**E7-R2.** The viewer MUST show actual observed state separately from Hub-supplied
restore outcomes, preserving the contract's `restore_item_status` distinctions,
including `withheld_end_not_observed`. An unknown external change MUST NOT be
displayed as a known user. Protective release follows
[the shared execution rules](../contracts/rules.md#execution-results-hub-08).

<a id="e8"></a>

### E8. Mixed virtual and physical stage (PC-4)

**E8-R1.** The physical target for this gate is one Tapo light. Its handover and
qualification are separate from selecting it as the target. All other reference
devices may remain virtual, and the full reference flow MUST remain demonstrable
with virtual devices only.

**E8-R2.** A virtual fallback MUST be labelled virtual in the operator
inventory and MUST NOT impersonate the physical target. Displayed device
metadata and results MUST use the actual substrate and qualification status.

<a id="e9"></a>

### E9. Clock (PC-4)

**E9-R1.** Product and demo operation MUST use wall-clock time. Server
`DEMO_MODE` shortens the scenario's starting waits under COM-15; the Simulator
MUST NOT provide or require a separate virtual demo clock.

## 3. Acceptance catalogue

Every test below is observable through process boundaries, protocol messages,
fixture-Server records, or the viewer/operator surfaces. A target row is not a
passing claim until an implementation change supplies bounded evidence.

| ID | Initial state and input | Required observable exit | Checks | PCs | Status |
| --- | --- | --- | --- | --- | --- |
| SIM-AT-01 | Start a configured World while App, Hub, and Server are stopped and unavailable | Discovery and the viewer show the configured devices and actual state without another process or shared state | E1-R1, E1-R2 | PC-4 | Required |
| SIM-AT-02 | For Class A and B devices, perform resident, child, guest, external-automation, device-self, and SPIRA transitions; let Hub send C-3 events to the fixture Server | Hub-readable messages contain no truth fields; fixture records contain Hub-created `by`; the operator judge shows the required result for each row of the actor matrix | E4-R1, E4-R2, E6-R1, E6-R2, E6-R3 | PC-5, PC-6 | **Provisional where Class A is required, pending PQ-01** |
| SIM-AT-03 | Make an independent device change, then stop and restart the same World | Public read and viewer retain state and a changed witness; no duplicate transition or reset appears | E2-R3, E2-R4 | PC-4, PC-5 | Required |
| SIM-AT-04 | Send one command twice with the same `operation_id`, including once after restart | Both calls return the original receipt and only one effect is observable | E2-R2, E2-R4 | PC-4 | Required |
| SIM-AT-05 | Arm accepted-but-unchanged, then command a different desired value | Receipt is accepted while a fresh read still shows the old value; no surface reports completion from the receipt | E2-R1, E4-R3 | PC-4 | Required |
| SIM-AT-06 | Capture a property witness, change away and back independently, then send a restore with the old witness | Restore conflicts and the independent value remains; the viewer does not call the actor known unless the Hub established it | E2-R3, E7-R1, E7-R2 | PC-5 | Required |
| SIM-AT-07 | Start a long-running virtual job and wait through its due frontier | Reports show one stable job first running, then completed; the command acknowledgement is separately observable | E2-R1, E3-R1 | PC-4 | Required |
| SIM-AT-08 | Stop or replace a running job, then pass the old due frontier | No completion for the stale job appears and the current job/state is unchanged by the old timer | E3-R2 | PC-5 | Required |
| SIM-AT-09 | Inject stale, missing, and unavailable readback after a command | Each condition is explicit while independent World state persists; none is shown as verified completion | E2-R1, E4-R3, E5-R1 | PC-4 | Required |
| SIM-AT-10 | Open the stage for an active plan and an ordinary-groceries episode | Observed state is filled, waiting work is faint, stale state is marked, and the groceries episode adds no preparation; viewer interaction creates no effect | E5-R1, E5-R3 | PC-2, PC-4 | Required |
| SIM-AT-14 | Send a multi-property command containing one invalid property | The command is rejected and every value and witness remains unchanged | E2-R3 | PC-4 | Required |
| SIM-AT-16 | Compose physical Tapo, virtual Class A, and virtual Matter devices | The viewer marks physical devices; the operator identifies each device's substrate and reporting assumption; Tapo and Matter report `local_operation=false`; no physical qualification is inferred | E5-R2, E6-R2, E8-R1, E8-R2 | PC-4, PC-5, PC-6 | **Provisional only for the Class A comparison, pending PQ-01** |
| SIM-AT-18 | Run the demo with Server `DEMO_MODE=1` | App/Hub/Simulator observations use offset wall-clock timestamps; shortened waits come from Server data and no virtual demo-clock control is present | E9-R1 | PC-4 | Required |
| SIM-AT-19 | Open both households' viewers during the birthday scene | Each shows a 3D household with devices in their rooms and home events at the entrance; device labels read as content (oven temperature and time, light colour, display scene, fridge notice); weekday and wall-clock time are shown; a link reaches the other home | E5-R4, E5-R5, E5-R7 | PC-4 | Required |
| SIM-AT-20 | Inspect the viewer page and its data during an active plan | Order details, intent, rationale, card text, Hub `by` and judge verdict stay private. Overlays show the planned action and trigger, including any guest window. Fridge notice labels come from observed device values. | E5-R6 | PC-4, PC-5 | Required |
| SIM-AT-21 | Use a named person control, then change the same device from the appliance-app page | The control emits the panel path with the person's name; the appliance-app change uses `other_app` with `local_operation=false`; both are in the truth journal | E5-R8, E5-R9, E6-R2 | PC-5, PC-6 | **Provisional for the Class A panel signal, pending PQ-01** |
| SM-AT-1 | Guests arrive and multiple devices change | The overview stays in place and all changed devices show markers together | SM-1 | PC-4 | Required |
| SM-AT-2 | Select a marker, then select it again | The camera closes in and an explanation appears. The camera returns to the overview and the explanation disappears | SM-2 | PC-4 | Required |
| SM-AT-3 | A person switches off the running cleaner | The cleaner stops in World, the Hub reports `cleaner.stopped` with `by: user`, and the interrupted run has an `unknown` result | SM-3 | PC-5 | **Provisional for the Class A panel signal, pending PQ-01** |
| SM-AT-4 | Inspect Simulator screens and World state | Server judgment text is absent | E5-R6, SM-5 | PC-4, PC-5 | Required |
| SM-AT-5 | Start the cleaner at its scheduled time | The running cleaner has a change marker in the house overview | SM-1 | PC-4 | Required |
| SIM-AT-22 | Select the light by mouse or keyboard and choose a person's yellow colour action | The close-up and its action panel open together. The house shows yellow immediately, then confirms yellow from World. Hub observes the change with `by: user`. Escape closes both views | D-5-R1, D-5-R2, SM-2, SM-4 | PC-4, PC-5 | **Provisional for the Class A panel signal, pending PQ-01** |
| SIM-AT-23 | Choose a person action with an unavailable World read-back | The house shows pending feedback immediately, then restores the last observed value and reports the failure | D-5-R2 | PC-4 | Required |

## 4. Open items

- **O-01 / PQ-01:** professor confirmation of the Class A local-operation
  reporting assumption. Keep the assumption visible and its dependent acceptance
  evidence provisional.
- **O-07:** physical Tapo handover, driver/control path, and qualification evidence
  are pending. Do not claim a physical pass from the virtual fallback.
- **SP-14:** the real Server contract routes and end-to-end C-3 receipt are not yet
  available. G1/G2 judge evidence uses `hub/tests/fixture_server`; do not relabel
  that as real-Server interoperability.
