# Demo shell

Two pages served by the Simulator at `/demo`.

| Page | Left | Middle / right | Bottom |
| --- | --- | --- | --- |
| 1 · 판단 | Phone with the shared order, preparation card and 우리 집 map | 주문 → 추출 → 맥락 → 의도 → 할 일 → 계획 → 허브 | 이전 / 다음 |
| 2 · 집 | 3D house with the entrance, living room, kitchen and seven devices | What the Hub saw and reported (ledger) | Timeline stepped with 다음 |

Page 1 reads only the team contract: `GET /v1/episodes/{id}` (S1 items),
`GET /v1/episodes/{id}/rationale` (S2 evidence, S3 intents, S4 tasks) and the
household's cards (S5). The fixture Server answers today; the real Server is the
same contract, so only `DEMO_SERVER_URL` changes. Page 2 paints devices only from
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

## Where to change what

| To change | Edit | Do not need to touch |
| --- | --- | --- |
| Colours, fonts, spacing, motion speed | `spira_simulator/ui/demo/tokens.css` | anything else |
| The active stage and flow strip | `ui/demo/flow.js` (keep `createFlow(root, nodes)` → `{ setStage(n) }`) | `demo.js` |
| Stage titles, leads, order; timeline steps and cameras | `ui/demo/scenes.json` | code |
| Layout and component styles | `ui/demo/index.html`, `ui/demo/demo.css` | |
| 3D models, device faces and lamp anchor | `ui/demo/house.js` (`createHouse` exposes `resize` and `update(snapshot)`) | |
| Data fetching, stage output, phone and handoff | `ui/demo/demo.js` | |
| Allowed assets, upstream routes and fixture sample upload selection | `spira_simulator/demo.py` | |

Rules the demo keeps:

- Device looks come from World values. A timeline step moves the camera and, for
  delivery, arrival and end, sends the corresponding World event. Ledger times
  and delivery status come from the Hub.
- The reasoning page shows contract fields. The Hub handoff uses the matching
  plan's waiting light action for its flying swatch when that value is available.
  Fixture judgments are labelled 예시 판단 in the header.
- Three.js 0.160.0 is vendored (`three.module.min.js`, `orbit-controls.js`), so the
  demo runs without network.

## Settings (set by `demo-up`)

| Variable | Meaning |
| --- | --- |
| `WORLD_DEMO=1` | Mount `/demo` |
| `DEMO_SERVER_URL`, `DEMO_APP_TOKEN` | Server for the contract reads and the order share |
| `DEMO_FIXTURE_EPISODE` | Fixture only: the default recorded judgment for a screenshot share |
| `DEMO_STARTS_IN` | Fixture only: seconds from share to the event start (default 90) |
| `DEMO_HUB_URL` | Hub for the ledger (`/state`) |
