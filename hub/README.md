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
episode. Restart to replay from the beginning. The birthday line-off advances
to v2 and a package event advances the fixture to its released plan. The
committed birthday event and execution transcript unlocks the final card,
episode, and memory snapshots. Posting the committed family calendar
advances the held card and plan. Initial and derived polling timestamps use
fixture time. The task trigger times stay at their committed values.

Stop, line on, unrecorded line off, and pause derive cancellations or re-enable
an existing fixture task using a fresh task ID. For cancellation, a received
`running` or `completed` run result counts as started. Resume keeps cumulative
cancellations. Order uploads and edits return acknowledgement for the selected
episode. Profile writes and device registrations exercise their contract
responses without re-planning the fixture. The onboarding response uses the
selected household ID and the committed demo key. Rationale returns 404 when
there is no committed snapshot for the published episode. The birthday and
groceries episodes serve their committed rationale as soon as they are published.
Memory is empty before the birthday final snapshot and in the other episodes.
The family episode detail uses the initial plan timestamp and held card ID with
empty item lists.

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
