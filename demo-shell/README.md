Temporary tool, not a product part.

# Demo shell

The shell serves two pages at its own `/demo` URL.

| Page | Left | Middle / right | Bottom |
| --- | --- | --- | --- |
| 1 · 판단 | Phone with the shared order, preparation card and 우리 집 map | 주문 → 추출 → 맥락 → 의도 → 할 일 → 계획 → 허브 | 이전 / 다음 |
| 2 · 집 | 3D house with the entrance, living room, kitchen and nine devices | What the Hub saw and reported (ledger) | Timeline stepped with 다음 |

Page 1 reads the team contract: `GET /v1/episodes/{id}` (S1 items),
`GET /v1/episodes/{id}/rationale` (S2 evidence, S3 intents, S4 tasks) and the
household's cards (S5). The fixture Server answers today. The real Server uses the
same contract, so only `DEMO_SERVER_URL` changes. The reasoning page shows device
parameters from the plan received by the Hub. Page 2 paints device state from
the Simulator's `/sim/snapshot` and reads labels from its viewer fragment. The
timeline's 택배 · 손님 · 끝 buttons send the same world events as the operator
through `POST /operator/home`.

## Run

```bash
scripts/demo-up          # from the repository root, needs uv and mosquitto
```

Open the printed **Demo** URL. Choose 생일 주문 or 평소 장보기,
then share the sample or upload a screenshot. Once an order is open, selecting
the other sample shares it and updates the current stage. Use 다음 or the right
arrow to progress. 집으로 → checks for the Hub's receipt and opens page 2.
Continue with 다음 to send the home events in order.

The shell selects sample scenes through `POST /_fixture/scene/next-order` and
shares them through `POST /v1/orders`. An uploaded screenshot uses the fixture's
default birthday scene. The [Android live path](../README.md#run-the-demo) shares
directly to the fixture Server.

The launcher starts with an empty fixture and fresh Hub and World databases.
Use `--keep` to resume the last run for this checkout, episode, and Simulator
port. `--port` sets the Simulator port (default 8730), `--shell-port` sets the
shell's port, and `--peer-ports FIXTURE MQTT HUB` selects the other ports.
Use `--no-shell` to start the live stack by itself. Press Ctrl-C to stop the stack.

To open the shell beside already running services, set the origins and operator
credential listed below and start its server from the repository root.

```bash
uv run --no-project --python 3.12 \
  --with-requirements demo-shell/requirements.txt \
  --with-editable contracts/generated/python \
  uvicorn demo:app --app-dir demo-shell --host 127.0.0.1 --port 8733
```

Deep links for rehearsal and screenshots: `/demo?episode=ep_9031&step=3`,
`/demo?episode=ep_9031&page=house` (after an order was shared once).

Add `owners=1` to the query string to show the owner tags. They are hidden by default.

| Panel or region | Owner tag |
| --- | --- |
| Phone order screen and share stage | 앱 · 공유 |
| Phone preparation screen and plan stage | 앱 · 카드 |
| 추출, 맥락, 의도, 할 일 stages | 앱 · 판단 근거 |
| Phone 우리 집 map | 앱 · 우리 집 |
| 3D house, device labels and house timeline | 시뮬레이터 · 집 |
| Hub handoff stage and ledger | Hub 기록 |
| Flow strip, funnel counts and KB counts | 서버 창 |

## Where to change what

| To change | Edit | Do not need to touch |
| --- | --- | --- |
| Shared colours, spacing, type and motion | [`design/tokens.json`](../design/tokens.json), then run `python3 design/build.py` | Generated stylesheets |
| The active stage and flow strip | `ui/flow.js` (`createFlow(root, nodes)` returns `setStage(n)` and `setCounts(counts)`, with one optional count label per node, shown when reached) | |
| Stage titles, leads, order; timeline steps and cameras | `ui/scenes.json` | code |
| Layout and component styles | `ui/index.html`, `ui/demo.css` | |
| World inventory, room placement and initial values for `h_042` | [`simulator/spira_simulator/profiles/ep_9031.json`](../simulator/spira_simulator/profiles/ep_9031.json) | Recorded plans |
| Hub device registration and command bindings | [`scripts/demo-devices.json`](../scripts/demo-devices.json), added to `hub/installation.example.json` by `scripts/demo_up.py` | Shared contract fixtures |
| 3D models, device faces and lamp anchor | [`simulator/spira_simulator/ui/house/house.js`](../simulator/spira_simulator/ui/house/house.js) | |
| Web evidence chain shape, joins and fixed map devices | `ui/chain.js` | Panel renderers |
| Data fetching, stage output, phone and handoff | `ui/demo.js` | |
| Story clock and time formatting | `ui/story-time.js` | |
| Allowed assets, upstream routes and fixture sample upload selection | `demo.py` | |

`buildChain({ episode, rationale, card, hubPlan, hubLedger, snapshot, storyTime })`
is the one place that defines the evidence-chain shape on the web. It takes one
card or the episode's card list, the Hub's received actions by task ID, the Hub
ledger, the World snapshot, and `{ timing, guestWindows, fixtureShares }` for the
story clock. Fixture shares come from the recorded episode contracts.

- `items` are keyed by item type and carry name, quantity and the unbundled flag.
  `slots` carry a field key, label, value and basis IDs for items or calendar
  entries, with `가구 유형` for household evidence. `evidence` keeps the contract's
  calendar, unusual items, KB counts and KB examples.
- Each intent links its `slotIds` and `calendarEvent` ID. `intent` is the first
  judgment in `intents`. When the Server finds no intent, the chain has `none.reason`
  and empty slots, needs and preparation tasks. `item_tasks` still carry the
  fridge notices.
- `needs` group task IDs by the Server's need text. Each task links its
  `intentId` and logical device IDs, with its line, need, way, story time and
  derivation, and received Hub action values. Each device carries its observed
  state and `traces` back to the preparation task IDs that chose it.
- `reports` keep the ledger rows with story-time labels and any known plan,
  task and device IDs. Task IDs are scoped to their plan. `funnel` supplies the
  strip counts, including distinct devices in the received plan for item
  notices as well as preparation. Card, timeline and house views use the same
  chain.

Run the shell tests from the repository root. The evidence-chain tests use
Node.js 22.15 or newer and also run directly via
`node --test demo-shell/tests/demo_chain.test.mjs`.

```bash
PYTHONPATH=demo-shell uv run --no-project --python 3.12 \
  --with-requirements demo-shell/requirements.txt --with-editable contracts/generated/python \
  --with pytest --with httpx2 \
  python -m pytest -q demo-shell/tests
```

Rules the demo keeps:

- Device looks come from World values. A timeline step moves the camera and, for
  delivery, arrival and end, sends the corresponding World event. The Hub
  supplies ledger order and delivery status.
- Once the Hub has received the plan, devices outside preparation rest without
  labels in the 3D house and phone map. The living-room air purifier and
  entrance styler rest for the birthday, and every device rests for groceries.
  The 3D fridge can still show an observed item notice. The current timeline
  step's devices can add a task below their observed values. A slot and its basis
  item require a clear mention of the slot's value or basis item in the task or
  need. Other changed devices show compact value tags where they fit. On the
  delivery step, an observed fridge notice can show its source item when the
  notice text identifies a single item task.
- `GET /demo/api/hub` reads only the Hub's `/state`. Waiting actions and recorded
  run commands from received plans supply the device count and settings. The
  handoff swatch uses the matching plan's light colour. Fixture judgments are
  labelled 예시 판단 in the header.
- Plan, card, timeline and ledger times use the linked rationale calendar for
  display. In `DEMO_MODE`, scheduled leads and fallback times show the normal
  Server values. Live events keep their offset from the start where it fits the
  restored schedule, and otherwise use an event or relative-time label.
- Plan receipts use the order's first capture plus the normal Server quiet
  window, rounded up to the next display minute if needed. The delivery step,
  package release and fridge notice rows use `파티 전`.
- The shell proxies the Simulator's public `/sim/assets/house/` route for the
  house module, design tokens, vendored Three.js 0.160.0, and IBM Plex Sans KR
  fonts. The shell supplies story time and the chain annotations.

## Settings (set by `demo-up`)

| Variable | Meaning |
| --- | --- |
| `DEMO_SIMULATOR_URL` | Simulator origin for house assets, snapshot and viewer fragment |
| `DEMO_OPERATOR_TOKEN` | Simulator operator credential for the timeline's home events |
| `DEMO_SERVER_URL`, `DEMO_APP_TOKEN` | Server for the contract reads and the order share |
| `DEMO_HOUSEHOLD` | Household for contract reads and shares (default `h_042`) |
| `DEMO_FIXTURE_EPISODE` | Set to the default episode when the fixture Server has `--scene-controls` enabled |
| `DEMO_STARTS_IN` | Fixture only: seconds from sample share to the event start (default 90) |
| `DEMO_HUB_URL` | Hub for received plan actions and the ledger (`/state`) |
| `DEMO_NUMBERS_PATH` | Path to the Server's `config/numbers.yaml` when using `DEMO_MODE=1` |
