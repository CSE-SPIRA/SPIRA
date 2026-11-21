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
are running. Omit both `--scene-controls` and `--default-scene` for fixed-date replay.

Add `--default-scene ep_9031` (or set `SPIRA_FIXTURE_DEFAULT_SCENE=ep_9031`)
to start unpublished and publish a live birthday replay on every valid new
`POST /v1/orders` upload. The default scene must belong to the fixture's
household. Start with `--scene-controls` as well to allow a one-shot override
through `next-order`. After that upload, the default applies again.

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

The live launcher passes `--guest-window` (600 seconds by default). The guest
trigger still opens `guest_window_before_min` before the scheduled event start,
as the Server writes it; only its end moves to that many seconds after the start. A fixture started directly without that override keeps
the COM-15 window. In demo mode the linked event in WHY uses the replay's
scheduled start. It keeps the original calendar duration for replay windows
shorter than one minute and uses the replay duration for longer windows.

A live `package.brought_in` selects the most recently shared episode with a
live task still waiting for the package. It releases every such task in that
episode at the event timestamp and publishes a new plan version. A package
with no waiting task is recorded without publishing a version.

Live cards update as the fixture receives Hub acknowledgements, events and
execution results. A line waits for all expected actions to reach final
results before projecting a final execution outcome. `partial` requires at
least one `completed` action. Card polling uses its usual `since` cursor for
updates, including the final card after an episode closes. The fixture keeps
earlier episode details, committed rationale snapshots and cards until
restart. Each template uses its committed episode and card IDs on first use.
Repeating a template with a new order allocates fresh IDs to retain history.

Live rationale starts with empty observations. At party end or the fallback
deadline, the fixture uses the received events, execution results and card
reactions to publish S7 feedback and household memory immediately.

`GET /_fixture/scene/acks` uses the fixture Hub key from onboarding and returns
the active episode's acknowledgements by version. `GET /_fixture/receipts`
retains its original shape across orders.

## Open questions

- The family fixture has no committed rationale or episode item-detail
  snapshot. A calendar match uses the committed event identity and title.
- The scene controls normally serve the newest episode's plan. When §12.4
  selects an older episode, its updated plan stays available alongside the
  newest plan until restart so the Hub can confirm work from both.
- When a previously running line has only non-completed final results and
  still has a pending action, the fixture retains `running` as requested.
  The Server implementation falls back to `scheduled` in this case.
- Fixed-date replay retains its existing timestamp check for packages
  observed before the order and the committed birthday release timestamp.
