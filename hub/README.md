# Home Hub

Owner: Yejoon Kim

The Home Hub is the adapter that executes SPIRA Server plans in the home.
It waits for triggers, checks current device state and delegation, reads back
effects, and reports observations and results to the Server. It preserves
changes made by people. The Hub has no direct App connection.
Folder layout inside is decided by the owner. See [`spec.md`](spec.md).

## Run locally

### Contract fixture server

`hub/tests/fixture_server` is **non-inference test support** for the App, Hub,
and Simulator. It replays committed payloads for H10-R1 and HUB-AT19. OCR, LLM,
KB retrieval, device execution, and S7 inference are outside this test peer.

From the repository root, run one episode with `uv` and Python 3.12.

```bash
PYTHONPATH=contracts/generated/python uv run --no-project --python 3.12 \
  --with-requirements hub/tests/fixture_server/requirements.txt \
  python -m hub.tests.fixture_server --episode ep_9031
```

Set the clients' API base URL to `http://127.0.0.1:8000`. Use any nonempty
App Bearer placeholder and the fixture key from `POST /v1/households` for
`X-API-Key`. The same placeholder key is in
[`household.created.json`](../contracts/fixtures/ep_9031/household.created.json).
Select `ep_9150` or `ep_9120` with `--episode`. The first two episodes use
`h_042`, and `ep_9120` uses `h_051`. For clients in another local process or
emulator, configure the host and port with `--host` and `--port`.

Add `--default-scene ep_9031` or set `SPIRA_FIXTURE_DEFAULT_SCENE=ep_9031`
to start unpublished and run the live birthday replay on each new
`POST /v1/orders` upload. The live replay keeps the recorded schedule and uses
the Server's normal quiet window on the story clock.
See the [live scene options](tests/fixture_server/README.md).

Each instance starts at the first plan and card fixtures for its selected
episode. Restart to replay from the beginning. Turning off the birthday
cleaning line `t_clean#1` advances to v2. A package event advances the fixture
to its released plan. The committed birthday event and execution transcript
unlocks the final card, episode, and memory snapshots. Posting the committed
family calendar advances the held card and plan. Initial and derived polling timestamps use
fixture time. The task trigger times stay at their committed values.

Stop, line on, unrecorded line off, and pause derive cancellations or re-enable
an existing fixture task using a fresh task ID. For cancellation, a received
`running` or `completed` run result counts as started. Resume keeps cumulative
cancellations. Order uploads and edits return acknowledgement for the selected
episode. Profile writes and device registrations exercise their contract
responses without re-planning the fixture. The onboarding response uses the
selected household ID and the committed demo key. `ep_9150` starts with the
clam and strawberry item notices and its no-intent rationale. Rationale returns
404 when there is no committed snapshot for the published episode. The birthday
and groceries episodes serve their committed rationale as soon as they are
published. Memory is empty before the
birthday final snapshot and in the other episodes. The family episode detail
uses the initial plan timestamp and held card ID with empty item lists.

The Simulator judge can read `GET /_fixture/receipts`. Its `events` array
contains posted JSON batches and its `executions` array contains posted JSON
result bodies, in receive order per route. The log starts empty and preserves
each decoded JSON body from an authenticated request, including retries and
schema-rejected bodies. Read attribution directly from each event's
`payload.by`. Responses carry the `X-SPIRA-Fixture` header with the
non-inference label.

### Hub process

From the repository root, use Python 3.12 through `uv`. Start the fixture
Server above in one terminal. Start the local MQTT broker in another.

```sh
/opt/homebrew/sbin/mosquitto -p 1883
```

Export the variables in [`.env.example`](.env.example) from a local secret
source. Set `SPIRA_SERVER_URL` to the fixture listener and `SPIRA_HOUSEHOLD` to
its household. Enter the household connection code locally as `SPIRA_HUB_KEY`.
The code is the key returned by `POST /v1/households` and displayed by the App.
The demo launcher sets `SPIRA_HUB_KEY` when it starts the Hub. Use the same
MQTT prefix as the device peer. MQTT defaults to loopback,
port 1883, and prefix `spira/g0`. Set `SPIRA_MQTT_PREFIX` to override the
prefix. Start the Hub in a third terminal.

```sh
PYTHONPATH=contracts/generated/python uv run --no-project --python 3.12 \
  --with-requirements hub/requirements.txt python -m hub.spira_hub \
  --installation hub/installation.example.json --db hub/hub.sqlite3
```

The dashboard listens on loopback at port 8088. Use `--home-name` to name the
household on the ledger. It defaults to **우리 집**. The ledger groups activity by
preparation and shows the installed device list alongside it on desktop.
Open **자세한 기록** for waiting work, command receipts and read-backs, C-3 delivery,
and restore or skip results. Start the Simulator separately with the same MQTT prefix. The
example installation declares virtual devices using `mqtt:<logical_id>`.
The Hub uses wall time by default. The demo launcher sets
`SPIRA_DEMO_CLOCK_URL` so the Hub polls the fixture story clock once per second
and shares the state with the Simulator over MQTT.

## Tests

### Runtime acceptance tests

```sh
PYTHONPATH=contracts/generated/python uv run --no-project --python 3.12 \
  --with-requirements hub/requirements.txt \
  --with-requirements hub/tests/fixture_server/requirements.txt \
  python -m pytest -q hub/tests
```

Tests use the committed fixture Server, targeted HTTP fault stubs, and a fake
device implementing the MQTT protocol. The real-broker transport test runs when
Mosquitto is installed. The Class A cases are provisional pending O-01/PQ-01.

### Contract fixture Server tests

In-process tests can pass `hub.tests.fixture_server.create_app("ep_9031")` to
the FastAPI test client. Run the replay and OpenAPI schema checks with:

```bash
PYTHONPATH=contracts/generated/python uv run --no-project --python 3.12 \
  --with-requirements hub/tests/fixture_server/requirements.txt \
  python -m pytest -q hub/tests/fixture_server
```

## Where to change what

| Change | File |
| --- | --- |
| Installed devices, bindings and home signals | [`installation.example.json`](installation.example.json) |
| Shared design and vocabulary | [`design/`](../design/README.md) |
| Runtime and dashboard implementation | [`spira_hub/`](spira_hub) |
| Fixture Server replay | [`tests/fixture_server/`](tests/fixture_server) |

### Installation and lifecycle

- `devices` contains the device types and rooms registered as C-2. Set the
  user's delegation in `commands` and `never` until the Server provides a path
  for these settings. Discovery only reports capabilities. For each logical ID,
  `bindings` names the native `target` and maps delegated commands to desired properties.
  A mapping can name a single property for the complete command value, rename
  every parameter with `{"properties": {...}}`, or supply `{"fixed": {...}}`
  for a command that takes no C-1 value.
- An optional `native_identity` distinguishes a replacement behind a reused
  target. Change it before assigning the reused target to the replacement.
  Save installation edits atomically so the Hub sees a complete snapshot when
  it rechecks delegation just before dispatch. C-2 revision increases on
  projection changes and the receiver's current revision is reconciled on startup.
- `home_signals` binds a home fact to exact native targets and event types.
  The example maps `camera.package_removed` from `mqtt:sim_camera` to
  `package.brought_in` using `removed_count`. It maps the ordered sequence
  `doorbell.pressed` from `mqtt:sim_doorbell`, `door_lock.opened` from
  `mqtt:sim_door_lock`, and `presence.room_occupied` from `mqtt:sim_presence`
  to `guest_arrived`. It maps `presence.room_empty` from `mqtt:sim_presence`
  to `event_end`. The plan supplies the trigger window. The Server owns
  package-to-order release. `fridge.door_opened` keeps its device event name.
- At a time fallback, tasks with `protective: true` keep their protection and
  report `withheld_end_not_observed`. Other tasks with `end.restore: true`
  restore still-owned effects. An observed end honors the plan's `after`
  delay. Cancellation with `restore: true` releases still-owned effects
  immediately, including an owned cleaner job via conditional `clean: null`.
- Keep the SQLite database when restarting. It holds version floors, waiting
  work, reservations, ownership, and immutable C-3/C-4 bytes. A dispatch
  interrupted after reservation is exposed as unknown. The Hub reconciles
  Server authority and fresh device evidence before resuming restore writes.

## Contract boundaries

See the [Hub specification](spec.md#1-purpose-and-boundaries) for the Server
boundary, [delegation and capabilities](spec.md#h2-delegation-and-capabilities)
for C-2 registration, and the [Simulator device protocol](../simulator/protocol.md)
for the device boundary.

### Open questions

- The current C-1 home trigger names an event and window, with native sources
  left to installation configuration. C-1 also has no recurring-action identity
  when `first_only` is false. Each admitted action dispatches once under its
  stable task identity.
- O-24 tracks whether a late end event releases an already-withheld protective
  effect. The Hub closes its scheduled lifecycle at fallback and retains any
  still-owned property for explicit cancellation with `restore: true`.
- A state report contains a state snapshot rather than a changed-property list.
  When there is no earlier observation and multiple fields are present, the Hub
  needs an identifiable property before it can emit a contract-valid
  `.changed` event.
- The fixture final-card transition matches the exact committed transcript.
  Hub-generated C-3/C-4 IDs and live timestamps exercise receipt and delivery.
  Live app-card projection from those observations needs the real Server
  contract routes (SP-14).
