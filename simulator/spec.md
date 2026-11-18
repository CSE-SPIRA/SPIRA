# Simulator specification

This is the normative product specification for `simulator/`. `MUST`, `MUST
NOT`, `SHOULD`, and `MAY` are normative. Shared Server-facing values remain
authoritative in [`contracts/`](../contracts/README.md). The Hub↔Simulator
device boundary is defined in [`protocol.md`](protocol.md), which is normative
for both parts. Implementation guidance is non-normative and lives in
[`design-notes.md`](design-notes.md).

This specification does not certify an implementation, real Server integration,
or physical-device equivalence. Those claims require separate evidence.

## 1. Purpose and boundaries

The Simulator is an independent household with three roles:

1. **Stage:** accept device commands, change device state, and show the observed
   home by room and device.
2. **People:** let the operator act as a resident, child, guest, or external
   automation without telling the Hub which actor was chosen.
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

<a id="e5"></a>

### E5. Household viewer (PC-2, PC-4, PC-5, PC-6)

**E5-R1.** The stage viewer MUST fill in only observed device state. Planned or
waiting work MAY be shown only as a visually faint, distinct overlay. Stale,
missing, or unavailable observations MUST remain visibly so; disconnection MUST
NOT change World state.

**E5-R2.** The viewer MUST identify virtual versus physical substrate per device,
show Class A local-operation reporting as an explicit assumption, and avoid any
aggregate claim that virtual success qualifies a physical device.

**E5-R3.** A no-preparation episode, such as ordinary groceries, MUST be able to
show no planned or applied household preparation. Viewer controls MUST NOT create
execution success. Operator writes and judge output MUST remain on the operator
side, not the household viewer.

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
join World truth to that event by device, event type, and occurrence time, and
produce exactly one of: `match`, `person-reported-unknown`,
`non-person-reported-user`, or `person-not-decision-maker` (child or guest).
Judge results and truth details MUST be visible only on the operator side.

<a id="e7"></a>

### E7. End and restore observation (PC-5)

**E7-R1.** The World MUST accept a restore only as an ordinary conditional device
command. It MUST NOT read Hub ownership or decide which properties should be
restored.

**E7-R2.** The viewer MUST show actual observed state separately from Hub-supplied
restore outcomes, preserving restored, skipped-user-changed, failed, and unknown
distinctions. An unknown external change MUST NOT be displayed as a known user.

<a id="e8"></a>

### E8. Mixed virtual and physical stage (PC-4)

**E8-R1.** The physical target for this gate is one Tapo light. Its handover and
qualification are separate from selecting it as the target. All other reference
devices may remain virtual, and the full reference flow MUST remain demonstrable
with virtual devices only.

**E8-R2.** A virtual fallback MUST be labelled virtual and MUST NOT impersonate
the physical target. Each displayed device and result MUST retain its actual
substrate and qualification status.

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
| SIM-AT-16 | Compose physical Tapo, virtual Class A, and virtual Matter devices | Every tile/result shows physical or virtual per device; assumptions are labelled; Tapo and Matter report `local_operation=false`; no physical qualification is inferred | E5-R2, E6-R2, E8-R1, E8-R2 | PC-4, PC-5, PC-6 | **Provisional only for the Class A comparison, pending PQ-01** |
| SIM-AT-18 | Run the demo with Server `DEMO_MODE=1` | App/Hub/Simulator observations use offset wall-clock timestamps; shortened waits come from Server data and no virtual demo-clock control is present | E9-R1 | PC-4 | Required |

## 4. Open items

- **O-01 / PQ-01:** professor confirmation of the Class A local-operation
  reporting assumption. Keep the assumption visible and its dependent acceptance
  evidence provisional.
- **O-04 / SP-11:** the Server/contract representation for releasing protection
  only after observed `event_end` remains open. The Simulator emits observations;
  it does not decide release policy.
- **O-07:** physical Tapo handover, driver/control path, and qualification evidence
  are pending. Do not claim a physical pass from the virtual fallback.
- **SP-14:** the real Server contract routes and end-to-end C-3 receipt are not yet
  available. G1/G2 judge evidence uses `hub/tests/fixture_server`; do not relabel
  that as real-Server interoperability.
