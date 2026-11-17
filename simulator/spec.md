# SPIRA Simulator Specification

Implementation specification for `simulator/`. It defines an independent virtual household for App–Server–Hub development and demonstration; it does not replace contract tests or establish physical-device conformance.

- **Sources.** The owner Simulator design formerly maintained in Notion, the current integration contract, and the App/Hub responsibilities in this repository.
- **Authority.** [`contracts/`](../contracts/README.md) remains authoritative for shared Server-facing identifiers/events/meanings. The Simulator has no direct Server API.
- **This change.** Requirements only: no Simulator runtime, Hub wire contract, deployment claim, or physical-device qualification.

## 1. Role and boundary

The Simulator is an independent world actor with its own device state, time, jobs, manual actions, and observable history. The Hub interacts with it through a device adapter. A 2D viewer/operator surface exposes the world but does not own execution truth.

The Simulator:

1. models a small household and delegated capabilities;
2. accepts commands and separates transport/job receipts from state;
3. changes and exposes world state independently of the Hub;
4. produces package, guest, and event-end household events;
5. permits manual changes that can race with SPIRA action; and
6. provides deterministic scenarios/evidence for development.

It does **not** infer intent, generate plans, calculate card state, call the Server/KB, share Hub persistence, or mark Hub tasks successful.

## 2. Boundary and identity

The repository contracts specify Hub-to-Server events/results, not Hub-to-Simulator wire. Therefore:

- MQTT may be the component's internal transport as stated in the README, but topics/payloads are not a team-wide contract until adopted separately.
- The Simulator owns world/device state; the Hub owns scheduling, operation journals, Server events/results, and contract conversion.
- Simulator device IDs map explicitly to stable Hub contract IDs. Restart must not silently remap a household.
- Receipts, observations, and changes carry enough correlation data to distinguish one dispatch from a retry.
- The viewer consumes a read-only projection. Rendering an animation cannot make an action true.

## 3. Required behaviour

### S1. World model and persistence

- Maintain versioned state for rooms, devices, capabilities, properties, availability, and active jobs.
- Persist atomically enough that restart yields either the state before or after a transition, never a fabricated mixture.
- Keep world state independent from Hub task/plan storage and test assertions.
- Expose a snapshot with monotonic revision and observation time so stale reads are detectable.
- Keep the demo world small and contract-relevant: lighting, environment, media/screen, a long-running job, and fixture-required standby/care devices.

### S2. Device command processing

- Validate target, capability, property, and value before accepting a command.
- Distinguish rejected, accepted, and accepted-as-job receipts. A receipt is not final state proof.
- Apply instantaneous commands as explicit before/after transitions.
- Model long-running actions with stable job identity, progress/status, supported cancellation, and terminal state.
- Duplicate delivery with the same dispatch correlation must not create another job or double-apply a transition.
- Unsupported/unavailable operations fail explicitly rather than becoming a nearby command.

### S3. Independent observation

- Expose fresh device/property reads independent of command response.
- A read includes observation time and world revision or an equivalent freshness signal.
- Support delayed application, rejection, unavailable observation, and contradictory state so Hub failure paths are testable.
- Cached viewer state cannot satisfy Hub readback acceptance.

### S4. Household and device events

- Let an operator/scenario cause `package.brought_in`, `guest_arrived`, and `event_end` at explicit times.
- Emit property changes with actor provenance: `user` for manual action, `spira` for correlated Hub action, `unknown` when actor cannot be established.
- Preserve occurrence time and stable local identity across redelivery.
- The Hub adapter, not the Simulator, converts events to [`event.json`](../contracts/schemas/event.json) and sends them to the Server.

### S5. Manual change and interference

- Operator controls may change a property while a task waits, runs, or awaits restore.
- Manual change is a world transition, not mutation of Hub storage.
- Allow user change after SPIRA action so restore can prove it preserves the intervening value.
- Allow device offline/online changes and command/read failures without restarting the Hub.

### S6. Time and scenarios

- Normal team demo uses wall-clock, timezone-aware time consistent with the shared contract.
- Deterministic tests may use a local controllable clock only when all participating processes use the same isolated test profile. Do not present virtual-clock results as the wall-clock demo.
- A fixture declares initial state, scheduled external events/faults, and expected observations. It never injects a Server plan or Hub result directly.
- Same fixture, initial snapshot, and seed should produce the same ordered world transitions.

### S7. Viewer and operator surface

- Show rooms, device identity, availability, properties, active jobs, world revision/time, and latest transitions.
- Visually distinguish user, SPIRA, scenario, and unknown changes.
- Provide controls for household events, supported manual changes, and bounded fault injection.
- Animate only after a world transition/job exists; show failed/unknown operations as such.
- Viewer disconnect must not stop or alter the world actor.

### S8. Evidence and reset

- Record an ordered non-secret journal of receipts, jobs, changes, observations, household events, faults, provenance, and correlations.
- Export a bounded receipt with scenario/profile version, initial/final snapshot hashes, and relevant transitions.
- Reset is explicit and targets a named fixture; it never occurs automatically to make an assertion pass.
- Preserve original counterexamples when a scenario fails; do not rewrite journal/expectation in place.

## 4. Development profiles

| Profile | Purpose | Permitted claim |
| --- | --- | --- |
| `demo` | Wall-clock App–Server–Hub walkthrough | The virtual scenario was demonstrated. |
| `deterministic` | Repeatable development with controlled time/faults | The named virtual fixture passed. |
| `adversarial` | Manual change, delay, stale read, restart, conflict | The tested invariant held for named cases. |

No profile qualifies a physical appliance, native controller, mobile release, or production deployment.

## 5. Reference scenario

```text
initial virtual home
  -> operator: package brought in
  -> Hub reports event and pulls changed plans
  -> trigger due -> Hub pre-dispatch read
  -> Simulator receipt -> independent transition/job
  -> Hub fresh readback/result
  -> operator changes one owned property
  -> event end -> Hub restores only unchanged owned properties
  -> viewer/journal show the preserved user change
```

The Server produces App-visible cards/results from Hub reports. The Simulator never writes App or Server state to complete this chain.

## 6. Acceptance cases

Component tests must cover at least:

1. restart persistence and monotonic world revision;
2. command receipt separated from fresh observation;
3. idempotent duplicate delivery and stable long-running job identity;
4. successful, delayed, rejected, unavailable, and contradictory outcomes;
5. stable household-event redelivery and actor provenance;
6. manual change after SPIRA action surviving Hub restore;
7. offline/online and read failure without Hub-storage mutation;
8. deterministic fixture replay from a named snapshot;
9. viewer disconnect leaving the world unchanged; and
10. bounded evidence export without tokens/device credentials.

Integrated review uses public component boundaries and repository Hub–Server contracts. Tests may observe both sides but cannot manufacture a passing Hub event, execution result, or physical readback.

## 7. Open joint decisions and non-claims

Separate adoption is required for MQTT topics/payload/QoS/auth/discovery; exact initial device catalogue and mapping; isolated virtual-clock control; and evidence bundle retention.

This specification does not claim a current Simulator implementation, end-to-end deployment, production security, or physical-device equivalence.
