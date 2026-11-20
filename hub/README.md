# Home Hub

Owner: Yejoon Kim

Pulls the plan from the SPIRA Server, waits for triggers, checks current device state, executes, reads results back, and restores what it changed.
Folder layout inside is decided by the owner. See [`spec.md`](spec.md).

## Contract fixture server

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

In-process tests can pass `hub.tests.fixture_server.create_app("ep_9031")` to
the FastAPI test client. Run the replay and OpenAPI schema checks with:

```bash
PYTHONPATH=contracts/generated/python uv run --no-project --python 3.12 \
  --with-requirements hub/tests/fixture_server/requirements.txt \
  python -m pytest -q hub/tests/fixture_server
```

## Run the Hub

From the repository root, use Python 3.12 through `uv`. Start the fixture
Server above in one terminal. Start the local MQTT broker in another.

```sh
/opt/homebrew/sbin/mosquitto -p 1883
```

Export the variables in [`.env.example`](.env.example) from a local secret
source. Set `SPIRA_SERVER_URL` to the fixture listener and `SPIRA_HOUSEHOLD` to
its household. Set `SPIRA_HUB_KEY` to the key returned by fixture onboarding
and use the same MQTT prefix as the device peer. MQTT defaults to loopback,
port 1883, and prefix `spira/g0`. Set `SPIRA_MQTT_PREFIX` to override the
prefix. Start the Hub in a third terminal.

```sh
PYTHONPATH=contracts/generated/python uv run --no-project --python 3.12 \
  --with-requirements hub/requirements.txt python -m hub.spira_hub \
  --installation hub/installation.example.json --db /private/tmp/spira-hub.sqlite3
```

The dashboard listens on loopback at port 8088. It shows waiting work,
command receipts and read-backs, C-3 delivery, and restore or skip
results. Start the Simulator separately with the same MQTT prefix. The
example installation declares virtual devices using `mqtt:<logical_id>`.
The fixture's dates are fixed. The live Hub uses wall time, so past windows
and elapsed lifecycles remain past. The acceptance tests
exercise those snapshots at their original scenario times.

### App onboarding over the home network

Set `SPIRA_SIMULATOR_URL` to the selected test home's HTTP origin and
`WORLD_OPERATOR_TOKEN` to the token configured on that Simulator. Enable
its operator service. The Hub sends HTTP Basic credentials with username
`operator` to `GET /lg/devices`. Start the Hub with `--host` set to
its LAN address for a phone on the same home network. Both App routes use
the Hub's port and require `X-API-Key` with the household Hub key.

`GET /home/onboarding/devices` takes no body. It returns source metadata
and the Hub's current settings separately. The command's `value_schema`
is null for a no-value command and `basis` is null when unknown. An
unconfigured candidate has null room and label and an empty delegation
under `stored`.

```json
{
  "devices": [
    {
      "id": "fridge_01",
      "type": "fridge",
      "label": "냉장고",
      "room": null,
      "source": "lg_account",
      "commands": [
        {"cmd": "show_notice", "value_schema": "text", "basis": "lg_assumed"},
        {"cmd": "clear_notice", "value_schema": null, "basis": "lg_assumed"}
      ],
      "never": [],
      "stored": {"room": null, "label": null, "delegated_commands": []}
    }
  ]
}
```

`PUT /home/onboarding/devices` takes the following body. Each submitted
device replaces its settings. Devices omitted from the request keep theirs.
Null clears a stored room or label and an empty command array revokes all
delegation for that device. A successful write returns HTTP 200 and
`{"revision": 4}`, with the actual published C-2 revision in place of 4.

```json
{
  "devices": [
    {
      "id": "fridge_01",
      "room": "주방",
      "label": "우리 집 냉장고",
      "delegated_commands": ["show_notice"]
    }
  ]
}
```

Errors use `{"code": "...", "message": "..."}`. The routes return 401 for
authentication failure, 422 for invalid settings, 503 for missing discovery
configuration or an unavailable installation, and 502 for peer failure. If
the Hub saves settings but the C-2 upload fails, the response says the upload
is pending and normal Server reconciliation retries it.

### Installation and lifecycle

- `devices` contains the C-2 devices admitted and delegated by the installation
  owner. Discovery only reports capabilities. For each logical ID, `bindings`
  names the native `target` and maps delegated commands to desired properties.
  A mapping can name a single property for the complete command value, rename
  every parameter with `{"properties": {...}}`, or supply `{"fixed": {...}}`
  for a command that takes no C-1 value.
- `lg_account_devices` marks seeded installation entries that come from
  LG discovery for onboarding. The other installation entries provide the
  manual candidates. The test LG account supplies the offered commands and
  their basis for each returned LG device. Rooms for those candidates
  come from stored settings and never from the LG account.
- An optional `native_identity` distinguishes a replacement behind a reused
  target. Change it before assigning the reused target to the replacement.
  Editing the installation changes live delegation. Save the JSON atomically
  so a reader sees a complete snapshot. C-2 revision increases on projection
  changes and the receiver's current revision is reconciled on startup.
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
- A dispatched item notice ends with a conditional write of
  `{"show_notice": null}` to the fridge when its C-1 end condition is met.
  The Hub verifies the empty slot by fresh readback and sends a C-4 run
  result with `cmd: "clear_notice"` and the original item task ID.
- Keep the SQLite database when restarting. It holds version floors, waiting
  work, reservations, ownership, and immutable C-3/C-4 bytes. A dispatch
  interrupted after reservation is exposed as unknown. The Hub reconciles
  Server authority and fresh device evidence before resuming restore writes.

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
