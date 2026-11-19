# Simulator

Owner: Yejoon Kim

The Simulator runs a household with its own SQLite state and an MQTT device interface. It provides a read-only room viewer and a private operator for household occurrences, device actions, faults, and C-3 comparisons. The default profile contains the seven logical devices from the `ep_9031` household `h_042`, all virtual. [Specification](spec.md) · [Device protocol](protocol.md)

## Run locally

From `simulator/`, set up Python 3.12 or newer.

```bash
python3 -m venv .local/venv
.local/venv/bin/pip install -e ../contracts/generated/python -e '.[dev]'
```

Set `WORLD_OPERATOR_TOKEN` in your local environment to enable the operator. Its HTTP Basic username is `operator` and its password is the configured token. A viewer-only run can omit both operator settings. The process commands use loopback defaults.

| Process | Command |
| --- | --- |
| MQTT broker | `/opt/homebrew/sbin/mosquitto -p 1883` |
| Simulator | `WORLD_OPERATOR=1 WORLD_PLANS=../contracts/fixtures/ep_9031/plan.v3.json .local/venv/bin/uvicorn spira_simulator.api:app --host 127.0.0.1 --port 8730` |

Open `/sim/viewer` and `/operator` on port 8730. Select an actor before using **Set warm white** on the light or **Start oven** on the oven. The operator also has **Bring package inside**, **Guests arrive**, and **Event ends** controls. The fixture plan above supplies a stage overlay. With a live peer, point the overlay at its current plan and execution sources. The Hub decides when to act and dispatches via MQTT.

Use `WORLD_DB` to give a household its own database. Reopen the same file to retain device state, offline state, receipts, witnesses, jobs, and truth. Command and readback fault arms are in memory. `WORLD_PROFILE` selects a native device profile. The supplied [profile](spira_simulator/profiles/ep_9031.json) shows the configurable inventory, property validation, job timings, and home sensor mappings. A physical entry is labelled physical and unqualified and stays unavailable until a driver is provided.

## Peer inputs and binding

Set the Hub's MQTT endpoint and prefix to match the Simulator. `MQTT_HOST`, `MQTT_PORT`, and `MQTT_PREFIX` default to loopback, `1883`, and `spira/g0`. MQTT credentials, if configured, are separate from the operator credentials.

The [default `h_042` profile protocol](protocol.md#11-default-h_042-profile) defines the Hub command mappings and operator raw signals.

Read replies carry `operation_id: null` and `local_operation: false`. A stale read retains its cached observation time. Missing readback has empty values and revisions with `available: true`. Unavailable readback uses empty values and revisions with `available: false`. The viewer shows the MQTT connection and last observed gap. Device event delivery after a gap starts with new observations.

| Setting | Input |
| --- | --- |
| `WORLD_PLANS` | Local path or GET URL returning a generated C-1 `Plan` or `PlanPull`. `WORLD_PLANS_TOKEN` adds a Bearer header for a protected projection. |
| `WORLD_EXECUTIONS` | Local path or GET URL returning a list of generated C-4 execution records. `WORLD_EXECUTIONS_TOKEN` adds a Bearer header. |
| `WORLD_RECEIVED_URL` | Fixture Server GET endpoint returning an array of received C-3 events. `WORLD_RECEIVED_TOKEN` adds a Bearer header. Compare these under **Private evidence** on the operator page. |

The grocery fixture `../contracts/fixtures/ep_9150/plan.v1.json` shows two item notices and no household preparation. The birthday fixture keeps the protective line in the plan after the cleaning line is switched off. The stage labels planned protective actions and shows withheld releases in the Hub restore reports. Its device tiles come from World readback.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 .local/venv/bin/pytest
```

Tests use in-process protocol fakes and C-3 source stubs. The Mosquitto test uses a separate local broker when available. Tests marked `provisional` include Class A evidence pending PQ-01.

| Acceptance | Simulator evidence |
| --- | --- |
| SIM-AT-01, 03, 04, 05, 06, 07, 08, 09, 10, 14 | Passing locally. |
| SIM-AT-02 | Actor matrix and received-record comparisons pass against a stub. Class A rows are provisional pending PQ-01. Real Hub → fixture Server delivery needs integration. |
| SIM-AT-16 | Stage labels and Class B behavior pass with configured targets. Class A comparisons are provisional. Physical Tapo and native Matter interoperability need integration. |
| SIM-AT-18 | Simulator emits offset wall-clock observations. Full Server `DEMO_MODE=1` run needs integration. |

## Needs integration

- Connect the Hub device adapter using the default profile protocol. Verify guest-window waiting, package release, independent readback, conditional restore, and operator actions with the Hub running. Exercise both an observed protective end and a time fallback that withholds release.
- Connect the judge to the fixture Server's actual C-3 receipt endpoint and the viewer to live plan and restore sources. Run the birthday flow through all peers, including Server `DEMO_MODE=1`.
- Qualify the physical Tapo handover and native Matter driver path separately. The mixed-stage test exercises metadata and virtual behavior.

## Open questions

- For reads of undiscovered targets, the Simulator returns an unavailable report with `substrate: null`. The protocol leaves the substrate for such reads unspecified.
- The fixture Server receipt endpoint and live overlay formats/authentication still need confirmation. Overlays accept generated C-1 and C-4 payloads, with restore substrate from its corresponding C-4 run record when available.
- The judge vocabulary has no verdict for combinations such as a resident reported as `spira` or a SPIRA effect reported as `unknown`. The operator lists those as unresolved. A child or guest reported as `unknown` uses `person-reported-unknown`.
- PQ-01 is pending. The fixture timestamps are historical and are only used as plan inputs or test evidence. Live scheduling comes from Server timestamps and the Hub's wall clock.
- Whether a late end event releases an already-withheld protective effect remains open in the Hub spec (O-24). Physical Tapo qualification (O-07) and real Server interoperability (SP-14) also remain open.
