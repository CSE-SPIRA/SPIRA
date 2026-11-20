# Demo shell

Two pages served by the Simulator at `/demo`.

| Page | Left | Middle / right | Bottom |
| --- | --- | --- | --- |
| 1 · 판단 | Phone (share → reading → card) | Server flow strip, and the current stage's output | 이전 / 다음 |
| 2 · 집 | 3D house (living room, kitchen, entrance) | What the Hub saw (ledger) | Timeline of world events |

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

Open the printed `http://127.0.0.1:8730/demo`. Press 예시 주문으로 (or share a
screenshot), then 다음 / → through the stages. 집으로 → opens page 2; click the
timeline steps in order.

Deep links for rehearsal and screenshots: `/demo?episode=ep_9031&step=3`,
`/demo?episode=ep_9031&page=house` (after an order was shared once).

## Where to change what

| To change | Edit | Do not need to touch |
| --- | --- | --- |
| Colours, fonts, spacing, motion speed | `spira_simulator/ui/demo/tokens.css` | anything else |
| The Server flow animation | `ui/demo/flow.js` (keep `createFlow(root, nodes)` → `{ setStage(n) }`) | `demo.js` |
| Stage titles, leads, order; timeline steps and cameras | `ui/demo/scenes.json` | code |
| Layout and component styles | `ui/demo/demo.css` | |
| 3D models, camera positions, device faces | `ui/demo/house.js` (`update(snapshot)` is the only input for device looks) | |
| Data fetching, proxy, page logic | `ui/demo/demo.js`, `spira_simulator/demo.py` | |

Rules the demo keeps:

- Device looks come from World values, never from the timeline. A step only
  moves the camera, shows the people its world event brought, and sends that event.
- The reasoning page shows contract fields only. Fixture judgments are labelled
  in the header (판단: 예시(fixture)).
- Three.js 0.160.0 is vendored (`three.module.min.js`, `orbit-controls.js`), so the
  demo runs without network.

## Settings (set by `demo-up`)

| Variable | Meaning |
| --- | --- |
| `WORLD_DEMO=1` | Mount `/demo` |
| `DEMO_SERVER_URL`, `DEMO_APP_TOKEN` | Server for the contract reads and the order share |
| `DEMO_FIXTURE_EPISODE` | Fixture only: the recorded judgment to replay on share |
| `DEMO_STARTS_IN` | Fixture only: seconds from share to the event start (default 90) |
| `DEMO_HUB_URL` | Hub for the ledger (`/state`) |
