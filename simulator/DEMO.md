# Demo shell

Two pages served by the Simulator at `/demo`.

| Page | Left | Middle / right | Bottom |
| --- | --- | --- | --- |
| 1 · 판단 | Phone with the shared order, preparation card and 우리 집 map | 주문 → 추출 → 맥락 → 의도 → 할 일 → 계획 → 허브 | 이전 / 다음 |
| 2 · 집 | 3D house with the entrance, living room, kitchen and seven devices | What the Hub saw and reported (ledger) | Timeline stepped with 다음 |

Page 1 reads the team contract: `GET /v1/episodes/{id}` (S1 items),
`GET /v1/episodes/{id}/rationale` (S2 evidence, S3 intents, S4 tasks) and the
household's cards (S5). The fixture Server answers today. The real Server uses the
same contract, so only `DEMO_SERVER_URL` changes. The reasoning page shows device
parameters from the plan received by the Hub. Page 2 paints devices only from
`/sim/snapshot`; the timeline's 택배 · 손님 · 끝 buttons are the same world events
as the operator's.

## Run

```bash
simulator/scripts/demo-up          # needs uv and mosquitto
```

Open the printed `http://127.0.0.1:8730/demo`. Choose 생일 주문 or 평소 장보기,
then share the sample or upload a screenshot. Once an order is open, selecting
the other sample shares it and updates the current stage. Use 다음 or the right
arrow to progress. 집으로 → checks for the Hub's receipt and opens page 2.
Continue with 다음 to send the home events in order.

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
| Colours, fonts, spacing, motion speed | `spira_simulator/ui/demo/tokens.css` | anything else |
| The active stage and flow strip | `ui/demo/flow.js` (`createFlow(root, nodes)` returns `setStage(n)` and `setCounts(counts)`, with one optional count label per node, shown when reached) | |
| Stage titles, leads, order; timeline steps and cameras | `ui/demo/scenes.json` | code |
| Layout and component styles | `ui/demo/index.html`, `ui/demo/demo.css` | |
| 3D models, device faces and lamp anchor | `ui/demo/house.js` (`createHouse` reads values through `update(snapshot)` and plan emphasis through `setChain(chain)`) | |
| Web evidence chain shape and joins | `ui/demo/chain.js` | Panel renderers |
| Data fetching, stage output, phone and handoff | `ui/demo/demo.js` | |
| Story clock and time formatting | `ui/demo/story-time.js` | |
| Allowed assets, upstream routes and fixture sample upload selection | `spira_simulator/demo.py` | |

`buildChain({ episode, rationale, card, hubPlan, hubLedger, snapshot, storyTime })`
is the one place that defines the evidence-chain shape on the web. It takes one
card or the episode's card list, the Hub's received actions by task ID, the Hub
ledger, the World snapshot, and `{ timing, guestWindows }` for the story clock.

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

Run `node --test tests/demo_chain.test.mjs` from `simulator/` for the birthday
and grocery fixture checks. Pytest runs them when Node.js is available.

Rules the demo keeps:

- Device looks come from World values. A timeline step moves the camera and, for
  delivery, arrival and end, sends the corresponding World event. Ledger times
  and delivery status come from the Hub.
- Once the Hub has received the plan, devices outside preparation rest without
  labels. A changed preparation device adds a task, situation slot and item
  from the evidence chain below its observed value. The fridge can still show
  its observed item notice.
- `GET /demo/api/hub` reads only the Hub's `/state`. Waiting actions and recorded
  run commands from received plans supply the device count and settings. The
  handoff swatch uses the matching plan's light colour. Fixture judgments are
  labelled 예시 판단 in the header.
- Plan, card, timeline and ledger times use the linked rationale calendar for
  display. In `DEMO_MODE`, scheduled leads and fallback times show the normal
  Server values. Live events keep their offset from the start where it fits the
  restored schedule, and otherwise use an event or relative-time label.
- Three.js 0.160.0 is vendored (`three.module.min.js`, `orbit-controls.js`), so the
  demo runs without network.

## Settings (set by `demo-up`)

| Variable | Meaning |
| --- | --- |
| `WORLD_DEMO=1` | Mount `/demo` |
| `DEMO_SERVER_URL`, `DEMO_APP_TOKEN` | Server for the contract reads and the order share |
| `DEMO_FIXTURE_EPISODE` | Fixture only: the default recorded judgment for a screenshot share |
| `DEMO_STARTS_IN` | Fixture only: seconds from share to the event start (default 90) |
| `DEMO_HUB_URL` | Hub for received plan actions and the ledger (`/state`) |
| `DEMO_NUMBERS_PATH` | Path to the Server's `config/numbers.yaml` when using `DEMO_MODE=1` |
