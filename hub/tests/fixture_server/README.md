# Live scene controls

The contract fixture is non-inference test support. Run it from the repository
root with Python 3.12 and `uv`.

```bash
TMPDIR=/private/tmp DEMO_MODE=1 PYTHONPATH=contracts/generated/python \
  uv run --no-project --python 3.12 \
  --with-requirements hub/tests/fixture_server/requirements.txt \
  python -m hub.tests.fixture_server --episode ep_9031 --scene-controls
```

The default address is `http://127.0.0.1:8000`. Scene controls require loopback
and start with no published episode. Use one fixture process per household.
`--episode ep_9031` or `--episode ep_9150` serves `h_042`. Use
`--episode ep_9120` to serve `h_051`, and a separate `--port` if both processes
are running. Omit `--scene-controls` for fixed-date replay.

1. With the App's Bearer placeholder, send `POST /_fixture/scene/next-order`
   with `{"episode_id":"ep_9031"}` or `{"episode_id":"ep_9150"}` for `h_042`,
   or `{"episode_id":"ep_9120"}` for `h_051`.
2. Share an order using the App or `POST /v1/orders`. The next valid new
   upload activates the selected episode. Invalid, duplicate and paused uploads
   leave the selection queued. The image content is unused.
3. For `ep_9120`, the initial card is held. Send `POST /_fixture/scene/calendar`
   with the same Bearer placeholder and an empty request body. The fixture
   applies the rebased committed calendar through the same path as the App's
   `PUT /v1/households/h_051/calendar`. The App route also accepts the
   committed calendar body directly and rebases its original dates.

`next-order` accepts integer `starts_in_seconds` and `duration_seconds` in
the range 1–3600, with defaults of 65 and 30 seconds. The offsets are measured
from order activation for the birthday and from calendar application for the
family gathering. Plan times use the Server's COM-15 offsets. Turn off the
cleaning line before running the Hub if the chosen offset puts cleaning in the
past.

An eligible `package.brought_in` publishes a newer plan with released item
notices. Live cards update as the fixture receives Hub acknowledgements,
events and execution results. Card polling uses its usual `since` cursor for
updates, including the final card after an episode closes. The fixture keeps
earlier episode details, committed rationale snapshots and cards until
restart. Only the newest episode's plan is returned. Each template uses
its committed episode and card IDs on first use. Repeating a template with a
new order allocates fresh IDs to retain history.

`GET /_fixture/scene/acks` uses the fixture Hub key from onboarding and returns
the active episode's acknowledgements by version. `GET /_fixture/receipts`
retains its original shape across orders.

## Open questions

- Live episode closure follows the card lines. The S7 memory, verdict and
  confirmation-signal projection belongs to the Server. Fixed birthday
  replay still serves its committed final transcript and memory.
- The family fixture has no committed rationale or episode item-detail
  snapshot. A calendar match uses the committed event identity and title.
- The fixture links package events only to the newest episode. The contract's
  latest-waiting-order lookup across older orders would require serving their
  plans alongside the newest one.
