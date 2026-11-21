# Simulator

Owner: Yejoon Kim

The Simulator runs one household per process, with its own SQLite state and an MQTT device interface. It provides a read-only room viewer and a private operator for household occurrences, device actions, faults, and C-3 comparisons. [Specification](spec.md) · [Device protocol](protocol.md)

## Run locally

From `simulator/`, use Python 3.12 or newer. Substitute your Python executable if it has a different name.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ../contracts/generated/python -e '.[dev]'
```

Set `WORLD_OPERATOR_TOKEN` in your local environment to enable the operator. Its HTTP Basic username is `operator` and its password is the configured token. A viewer-only run can omit both operator settings. The process commands use loopback defaults.

| Process | Command |
| --- | --- |
| MQTT broker | `/opt/homebrew/sbin/mosquitto -p 1883` |
| Simulator, `h_042` | `WORLD_DB=/private/tmp/spira-h_042.db WORLD_OPERATOR=1 WORLD_PLANS=../contracts/fixtures/ep_9031/plan.v3.json .venv/bin/uvicorn spira_simulator.api:app --host 127.0.0.1 --port 8730` |
| Simulator, `h_051` | `WORLD_PROFILE=spira_simulator/profiles/ep_9120.json WORLD_DB=/private/tmp/spira-h_051.db MQTT_PREFIX=spira/h_051 WORLD_OPERATOR=1 WORLD_PLANS=../contracts/fixtures/ep_9120/plan.v2.json .venv/bin/uvicorn spira_simulator.api:app --host 127.0.0.1 --port 8731` |

Open `/sim/viewer` on the household's port for the Korean test home. The 3D household shows the profile's rooms, observed device values, entrance events, and the Seoul wall clock. The viewer and `/demo` share the house, design tokens, and locally bundled IBM Plex Sans KR fonts. Set `WORLD_PEER_VIEWERS` to show links to the other homes. In the local environment for `h_042`, set it to `부모님 댁=http://127.0.0.1:8731/sim/viewer`. On `h_051`, point a `지아네` link to port 8730. Separate multiple label and URL pairs with commas. Use addresses reachable by the presenting device.

Open `/operator` for **Bring package inside**, **Guests arrive**, **Event ends**, and the named panel buttons under **Person actions**. The `demo_people` profile field supplies the names and roles. The generic controls below still take an optional display name and a **Device panel** or **Other app** path. Class A panel changes report a local operation under PQ-01. The truth journal records the name and path, and the operator snapshot keeps the latest operator action per device. These fields are available under `/operator/truth` and `/operator/snapshot`.

Open `/app` for the phone-sized Korean appliance app. Use the operator login and select who is acting. It defaults to 아빠 on `h_042` and the first configured person on `h_051`. Appliance changes use `other_app` with `local_operation: false`. To run it on a second phone, bind Uvicorn to a reachable interface with `--host 0.0.0.0` and use the simulator host's LAN address and port on a trusted demo network.

Select the inventory at startup with `WORLD_PROFILE`. It defaults to [`h_042`](spira_simulator/profiles/ep_9031.json) with nine virtual devices. The [`h_051`](spira_simulator/profiles/ep_9120.json) profile has four virtual devices and the same home event controls. Give each process a separate `WORLD_DB`, MQTT prefix, and HTTP port when running both homes. Reopen the same database for that household to retain device state, offline state, receipts, witnesses, jobs, and truth. Command and readback fault arms are in memory. A physical entry is labelled physical and unqualified and stays unavailable until a driver is provided.

## Peer inputs and binding

Set the Hub's MQTT endpoint and prefix to match the Simulator. `MQTT_HOST`, `MQTT_PORT`, and `MQTT_PREFIX` default to loopback, `1883`, and `spira/g0`. MQTT credentials, if configured, are separate from the operator credentials.

The [`h_042` protocol](protocol.md#11-default-h_042-profile) and [`h_051` protocol](protocol.md#12-h_051-profile) define the Hub command mappings and operator raw signals.

Read replies carry `operation_id: null` and `local_operation: false`. A stale read retains its cached observation time. Missing readback has empty values and revisions with `available: true`. Unavailable readback uses empty values and revisions with `available: false`. The viewer shows the MQTT connection and last observed gap. Device event delivery after a gap starts with new observations.

| Setting | Input |
| --- | --- |
| `WORLD_PLANS_URL` | Live Server `GET /v1/hub/plans?household=h_042` URL. This takes precedence over `WORLD_PLANS`. Set `WORLD_PLANS_TOKEN` to the household's Hub key, sent in `X-API-Key`. |
| `WORLD_PLANS` | Local path or GET URL returning a generated C-1 `Plan` or `PlanPull`. Existing URLs continue to accept `WORLD_PLANS_TOKEN`. |
| `WORLD_HUB_STATE_URL` | Hub dashboard `GET /state` URL for the same household. When set, it supplies both the judge's C-3 events and the viewer's execution overlay. |
| `WORLD_PEER_VIEWERS` | Optional comma-separated viewer links in `label=URL` form. |
| `WORLD_EXECUTIONS` | Local path or GET URL returning the fixture Server's `/_fixture/receipts` object with a C-4 `executions` array. A standalone C-4 array also works. `WORLD_EXECUTIONS_TOKEN` adds an optional Bearer header. |
| `WORLD_RECEIVED_URL` | Fixture Server `/_fixture/receipts` GET URL. The judge reads the received C-3 batches in `events`. A flat C-3 array also works. `WORLD_RECEIVED_TOKEN` adds an optional Bearer header. Compare the events under **Private evidence** on the operator page. |

Leave `WORLD_HUB_STATE_URL` unset to use fixture receipts for evidence. For a live demo, set it to the Hub dashboard's `/state` URL and set `WORLD_PLANS_URL` to the Server's plan-pull URL for the selected household. Use `household=h_051` with the family-gathering profile. Supply the Hub key via `WORLD_PLANS_TOKEN` in your local environment and start the Simulator with the same process command above. A configured input that fails reports an error without switching to fixture data.

The attribution judge labels its source as `fixture_receipts` or `hub_state`. In Hub mode, it compares only device events the Hub marks delivered. Pending device events appear under `not_delivered` with the Hub's delivery error when available. In the viewer, local run outcomes from Hub task stories clear the corresponding waiting entries. Restore reports retain their outcome and show **pending delivery** when the Hub has yet to confirm delivery.

The grocery fixture `../contracts/fixtures/ep_9150/plan.v1.json` shows two planned fridge actions and no household preparation. Planned actions show the device, action, and trigger or time. The fridge label shows notice text once World observes it. The birthday fixture keeps the protective actions in the plan after the cleaning line is switched off. The viewer shows withheld releases in the Hub restore reports. Its filled device labels come from World readback, and their latest-change labels come from World truth.

Under **Private evidence**, set a command marker before an episode, then select **Count Hub commands**. Enter both offset timestamps to count over an explicit interval instead. The API is `POST /operator/judge/marker` and `GET /operator/judge/commands`, optionally with `start` and `end` query parameters. The count includes the start time and excludes the end time. A marker uses journal order so it works even when a command shares its timestamp. It persists in `WORLD_DB`.

Counts cover the first valid command arrival for each operation ID, including rejected commands and accepted commands with no effect. A write to only `show_notice` goes in `notices`; every other command goes in `other_commands`. For groceries, check for zero other commands and look for the notices under `fridge_01`. The report lists `recording_since` because databases opened before this feature have no command-arrival history before that time. Command counts are available without a received C-3 source.

## Demo

Run the fixture Server, MQTT broker, Hub, and Simulator together from the
repository root of one checkout.

```bash
simulator/scripts/demo-up --episode ep_9031
```

The launcher uses its own repository root and prints the `/demo`, Hub dashboard,
and fixture URLs. Use `--port` if the default port 8730 is occupied. Page 1
projects the Server's reasoning from the contract. Page 2 shows the house in
3D with the Hub's ledger. Press Ctrl-C to stop the stack. See [DEMO.md](DEMO.md)
for the demo flow and the [App README](../app/README.md#run-in-the-browser) for
the Flutter browser preview from this checkout.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest
```

Tests use in-process protocol fakes, HTTP stubs for both evidence sources, and a fixture Server receipt captured from the live birthday scene. The Mosquitto test uses a separate local broker when available. Tests marked `provisional` include Class A evidence pending PQ-01.

| Acceptance | Simulator evidence |
| --- | --- |
| SIM-AT-01, 03, 04, 05, 06, 07, 08, 09, 10, 14 | Passing locally. |
| SIM-AT-02 | The actor matrix passes against a stub. The live Hub → fixture Server birthday scene matched resident light and oven actions against received C-3 events. Class A rows are provisional pending PQ-01. |
| SIM-AT-16 | Stage labels and Class B behavior pass with configured targets. Class A comparisons are provisional. Physical Tapo and native Matter interoperability need integration. |
| SIM-AT-18 | Simulator emits offset wall-clock observations. Full Server `DEMO_MODE=1` run needs integration. |
| SIM-AT-19 | Both profiles render their rooms, device values, entrance, wall clock, and configured links in HTTP tests. |
| SIM-AT-20 | HTTP tests check the viewer and its data for World change labels and action-only overlays. They check that items, intents, rationale, card text, Hub attribution, and judge output stay out of the viewer. |
| SIM-AT-21 | HTTP tests submit the named panel and appliance-app forms and check the emitted signals and truth journal. The Class A panel signal is provisional pending PQ-01. |

## Needs integration

- Connect the Hub device adapter using the default profile protocol. Verify guest-window waiting, package release, independent readback, conditional restore, and operator actions with the Hub running. Exercise both an observed protective end and a time fallback that withholds release.
- Run the birthday flow through all peers with the production Server implementation in `DEMO_MODE=1`.
- Qualify the physical Tapo handover and native Matter driver path separately. The mixed-stage test exercises metadata and virtual behavior.

## Open questions

- E6-R3 and protocol §10 still describe fixture Server receipts as the required judge evidence. Should the Hub dashboard projection count toward SIM-AT-02, or should acceptance continue to require a Server-side receipt?
- `/state` exposes the latest 100 event records and latest 100 restore reports with their delivery flags. Task stories expose run outcomes without C-4 run delivery status. Would future acceptance need run delivery evidence or older dashboard records?
- For reads of undiscovered targets, the Simulator returns an unavailable report with `substrate: null`. The protocol leaves the substrate for such reads unspecified.
- The judge vocabulary has no verdict for combinations such as a resident reported as `spira` or a SPIRA effect reported as `unknown`. The operator lists those as unresolved. A child or guest reported as `unknown` uses `person-reported-unknown`.
- PQ-01 is pending. The fixture timestamps are historical and are only used as plan inputs or test evidence. Live scheduling comes from Server timestamps and the Hub's wall clock.
- The entrance protocol reports a door opening. The viewer labels the observed opening with its time. A current closed-door indication needs a close observation.
- The oven profile exposes a person start and automatic completion. A stop button needs a supported oven stop operation.
- E5-R6 allows a latest-change display label from World truth, while E6-R1 keeps truth fields out of viewer projections. The viewer renders the label and keeps raw truth fields in the operator. A named appliance-app action is shown as a person change based on World truth.
- Whether a late end event releases an already-withheld protective effect remains open in the Hub spec (O-24). Physical Tapo qualification (O-07) and real Server interoperability (SP-14) also remain open.
