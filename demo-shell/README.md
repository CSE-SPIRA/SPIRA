# Demo shell

**ACTIVE** · This guide describes operation and inputs for the demo shell.
The phone mirrors [the App specification](../app/spec.md) and
[shared vocabulary](design/vocabulary.json).

At `/demo`, the phone stays on the left and the Server's judgment plays on the
right. With a fixture, choose 집까지 or 계획까지 in the presenter header before sharing; a Server run always goes on to the house (after S5 the next cue is 집 보기, once the Hub has the plan).
The `ep_9031` sample defaults to 집까지. Share from the phone and open the
preparation card with the presenter cue. A house run opens 우리 집 after the
Hub receives its plan. A plan run ends at 계획.

The stage strip marks each stage done when its data arrives. A Hub plan receipt
for the active episode at or after its share time marks 집 done. Items, home
comparison, calendar and similar cases take turns
as evidence. The intent beat keeps the situation, verdict and their source
labels in view.

## Run

```bash
scripts/demo-up --tagger # from the repository root, needs uv and mosquitto
```

Open the printed **Demo** URL. In fixture mode, choose 생일 주문 or 평소 장보기, then tap
다음 (Space/→) to share the sample or upload a screenshot from the phone.
Keep pressing 다음 when its label changes to open the preparation card, visit the
house and play its moments, then open 기록. The cue shows what it is waiting for.
Use ← to go back and open 진행자 조작 to recover with the manual controls.
The share uses the contract's `POST /v1/orders`. In fixture mode, sharing a
sample queues its matching recording before uploading. To rehearse with your
own screenshot, choose a recording on the printed `/_fixture/control` page.

To use an existing Server, register the household with `POST /v1/households`
using its App bearer token, then export the token as `SPIRA_APP_TOKEN` and
the returned `hub_api_key` as `SPIRA_HUB_KEY`.

```bash
scripts/demo-up --server "$SERVER_URL" --household "$SPIRA_HOUSEHOLD_ID"
```

Use the returned household ID. The launcher serves a local App preview with
Server mode enabled and keeps its credentials in the proxy. In the shell,
share your own screenshot. A missing Server read shows
서버가 아직 이 단계를 내보내지 않아요 on its stage. The shell uses the Server's
clock and moments when available. Without a rehearsal clock, the cue skips
clock advances and shows a notice. Text tags and illustrated device displays are
disabled for these runs. The run logs include the selected Server URL.

The judgment scene advances as its data arrives, one screen per stage: each
stage shows all of its results at once (맥락 = items with the usual-order
comparison, calendar and similar orders; 의도 = situation slots and the intent).
Each stage stays at least 4 seconds before the next finished stage is shown, so
stages that the Server finishes close together still play in order. The strip
keeps the real pace: with a Server it reads `GET /v1/demo/episodes/{id}/trace`
(contracts/openapi/demo.yaml, `DEMO_MODE=1`) and shows each stage's Server time
(`14.8초`) or how long the running stage has taken (`진행 중 12초`). Timeouts and
temporary errors are retried and shown briefly in the strip. A complete
rationale received in one response plays in the same order. Saved recordings
hold each stage for 3 seconds.

With a Server (no fixture, not a recording) the right panel is a presenter log
built only from the trace (`ui/serverlog.js`): finished stages fold to one
summary line, the stage being presented is expanded with what it stored (S2:
unusual items, calendar, KB search with similarity bars and the 0.70 line,
intent shares now vs usual; S4: tasks, fridge notices, dropped tasks), and the
next stage shows its real Server state (`의도 추론 중 … 12s`). A stage is ready
when the trace says the Server finished it, so S4 shows before S5.

Stage names (11-27): 1 주문 추출, 2 맥락 검색, 3 의도 추론, 4 할 일 생성, 5 계획 확정, 6 집 실행, 7 기억 저장, the same in the
step bar, the log (S1–S5) and the next cue. The log fills the right area on a console tint: finished stages are bands,
the current or reopened stage is a white card with the left bar, and the head is a dark title bar whose dot pulses green
live and stays blue in a replay. In log mode a finished stage in the step bar opens that stage, and "다음" walks the
stages again after "이전".

App in the phone (`ui/app-phone.js`). With a Server and no fixture, when
`app/build/web/index.html` exists (or `DEMO_APP_WEB` points at a build), the
phone shows the App itself in an iframe (`/demo/app/`) instead of the upload
panel; build it with `app/scripts/demo-shell-web`. The App calls
`/demo/app-api/…`: loopback only, the App routes of
`contracts/openapi/app.yaml` for the active household (no household creation,
no hub routes), forwarded with `DEMO_APP_TOKEN`. The right panel follows any
**new** order of the household (`GET …/episodes?limit=5` every 1.5 s; orders
already there when the page opened are not followed), so an order sent from a
real phone to the same household shows here too. **새로 시작** also clears the
App's saved state (`flutter.spira.*` in this origin's local storage). A replay
hides the phone.

Server replay (`ui/replays.js`, server/spec.md 12.5). When a live run has
finished S5, **재현용 보관** in the log head keeps it (`POST /demo/api/keep/{id}`,
forwarded to `POST /v1/demo/episodes/{id}/keep`); a kept run survives
**새로 시작** in the Server's replay archive and no longer touches the live demo
home. **재현** at the top right lists kept runs (`…/replays`) with a speed
(1×, 2×, 4×) and opens `/demo?replay_episode=ep_…&speed=2`: the log reads the
trace with `?at=` growing by the speed each second, so stages arrive at the
original pace, the head says `재현 · 날짜 · 2×`, the phone stays empty, and the
run ends at the plan (no house, no 새로 시작). This is not `?recording=`, which
plays a fixture recording.

The launcher starts with an empty fixture and fresh Hub and World databases.
To start a fresh take, choose **새로 시작** in **진행자 조작** or in the notice
about earlier house state. Confirm once and wait for stage 1 to open. The
launcher restarts the local fixture, Hub, World, and MQTT broker on the same
ports. The shell ends the active recording and keeps it with earlier takes.
In `--server` mode, the launcher resets the local Hub and World and the
Server keeps its order and judgment history.
For a terminal restart, press Ctrl-C and run `scripts/demo-up` without `--keep`.
Use `--keep` to resume the last run for this checkout, episode, and Simulator
port. **새로 시작** starts fresh even with `--keep`. `--port` sets the Simulator port (default 8730), `--shell-port` sets the
shell's port, and `--peer-ports FIXTURE MQTT HUB` selects the other ports.
Use `--no-shell` to start the live stack by itself. `--realistic [SEED]` starts the
fixture with the 현실 지연 preset (default seed 7). Press Ctrl-C to stop the stack.
`--tagger` defaults `DEMO_TAGGER` to `codex`. It uses the local, authenticated
Codex CLI. Set `DEMO_TAGGER=off` or omit the flag to run without model tags.
The shell draws TV and fridge artwork from templates, including when the
tagger is off. It applies the artwork when the Simulator reading matches the
Hub's verified device read-back. The TV's observed scene code chooses its template. The matching
Server line's validated tags can supply a palette or a motif for the center,
mirrored sides, and sky. Each missing or invalid field uses the template default.
On the fridge, the Server's exact notice and item-task relation choose the item
icon from `ui/item-types.json`. Unknown icons use the generic motif. The
Simulator paints the observed notice over the text-free illustration.

On the presenter machine, open `/demo/artwork` at the shell's loopback address
to compare the four default TV compositions, browse every TV palette and
children's party motif variations, and see sample fridge notices. The fridge
samples use the Simulator's notice painter.

To open the shell beside already running services, set the origins and operator
credential listed below and start its server from the repository root.

```bash
uv run --no-project --python 3.12 \
  --with-requirements demo-shell/requirements.txt \
  --with-editable contracts/generated/python \
  uvicorn demo:app --app-dir demo-shell --host 127.0.0.1 --port 8733
```

Fixture runs save to `demo-shell/recordings/` by default. When launched with
`--server`, the shell saves recordings inside that launcher's run directory.
Each JSON file
includes the chosen path, validated tags, artwork values, each scene sent
with its moment, and the observed values and presenter actions with wall-clock
and story times. Screenshots and request credentials are outside the recording.
Story time follows the available Server clock or wall time on the ordinary live stack.

Open `/demo?recordings` or press **R** to name, star or play a run. Starred runs
come first, newest first within each group. The index is also available at
`GET /demo/api/recordings`. A recording link (`/demo?recording=<id>`) plays from
the shell with saved data and tags. Judgment stages hold for about
three seconds each, with the evidence beats within their stage. House scenes
play in order from saved observations and use locally cached renderer assets
when the Simulator is offline. Older recordings need the Simulator to supply
renderer assets that have yet to be cached. Playback redraws TV and fridge
artwork from recorded template, palette, and motif codes. Earlier recordings
with embedded artwork still play. Add
`&dwell=2` to set the hold in seconds or `&auto=0` to step by hand.

The old `/demo?episode=ep_9031&replay=1` link redirects to a completed local recording
when available. Otherwise it keeps its read-only rehearsal behavior against the
running stack.

The house timeline lists timed plan lines and World events. A timed line opens
on verified device read-back. Trigger-only lines match the World event recorded
by the Hub. A guest-arrival line gets its own device moment when its first
verified read-back arrives. The timeline labels pending moments 대기.
이전 and 다음 move between observed moments. 현관, 거실 and 주방 change the
camera until the next moment.

The 진행자 조작 drawer includes the household actions and the optional clock
advance. The Simulator supplies the people.
After delivery, the stage places berries and cream on the kitchen counter,
ordered hats and the cupcake topper on the dining table, and balloon sets
in the living room. A set adds seven balloons to the bunch and three to the
floor, up to each slot's count limit. The shell scene rules omit garland and confetti. A line
palette can recolour the balloons after that line is observed.

After the last house moment, 다음 opens 기록. The right area waits for the
per-card verdicts and a fresh household memory read. The phone also shows
its own record.

Deep links include `/demo?episode=ep_9031&step=3` and
`/demo?episode=ep_9031&page=house`. They require a readable Server episode.
House links also wait for that run's Hub receipt.

Add `owners=1` to the query string to show the owner tags. They are hidden by default.

| Panel or region | Owner tag |
| --- | --- |
| Phone order screen and share stage | 앱 · 공유 |
| Phone preparation screen and plan stage | 앱 · 카드 |
| 주문 추출, 맥락 검색, 의도 추론, 할 일 생성 stages | 앱 · 판단 근거 |
| Phone 우리 집 map | 앱 · 우리 집 |
| 3D house, device labels and house timeline | 시뮬레이터 · 집 |
| Similar cases in the judgment scene | 서버 창 |

## Where to change what

| To change | Edit | Do not need to touch |
| --- | --- | --- |
| Shared colours, spacing, type and motion | [`design/tokens.json`](design/tokens.json), then run `python3 demo-shell/design/build.py` | Generated stylesheets |
| The stage readiness strip | `ui/flow.js` | |
| Stage wording and fallback cameras for cached renderers | `ui/scenes.json` | |
| Shared room cameras | [`house.js`](../simulator/spira_simulator/ui/house/house.js) | |
| House moments, props and display gating | `ui/scene-rules.js` | |
| Display templates, palettes and motifs | `ui/artwork/` | |
| Layout and component styles | `ui/index.html`, `ui/demo.css` | |
| World inventory, room placement and initial values for `h_042` | [`simulator/spira_simulator/profiles/ep_9031.json`](../simulator/spira_simulator/profiles/ep_9031.json) | Recorded plans |
| Hub device registration and command bindings | [`scripts/demo-devices.json`](../scripts/demo-devices.json), added to `hub/installation.example.json` by `scripts/demo_up.py` | Shared contract fixtures |
| 3D models, device faces and lamp anchor | [`simulator/spira_simulator/ui/house/house.js`](../simulator/spira_simulator/ui/house/house.js) | |
| Web evidence chain shape, joins and fixed map devices | `ui/chain.js` | Panel renderers |
| The next phone action and line switch rules | `ui/wire.js` | |
| Judgment beat order and evidence display | `ui/judgment.js` and `ui/judgment-view.js` | Server rationale |
| Text tagger lists, validation and cache | `tag-lists.json` and `tagger.py` | |
| Prepared item icons, storage words and props per unit | `ui/item-types.json` | Item names |
| App contract polling and tag reads | `ui/episode.js` | |
| Reasoning stages and pacing | `ui/reasoning.js` | |
| Phone, sharing, reactions and final review | `ui/phone.js` | |
| House timeline and cameras | `ui/house-timeline.js` | |
| Presenter cues, navigation and rehearsal clock | `ui/presenter-cues.js`, `ui/presenter.js` | |
| Recording timestamps and playback | `ui/recording.js`, `ui/run.js` | |
| Shell setup and Simulator renderer loading | `ui/demo.js` | |
| Story clock and time formatting | `ui/story-time.js` | |
| Allowed assets and upstream routes | `demo.py` | |

`buildChain({ episode, rationale, card, hubPlan, hubLedger, snapshot, storyTime })`
is the one place that defines the evidence-chain shape on the web. It takes one
card or the episode's card list, the Hub's received actions by task ID, Hub
receipts and house events, the World snapshot, and `{ timing, guestWindows }`
for the story clock.

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
- `ready` records arrival by stage. The house uses the active Hub `receipt`
  to open and builds its timeline from card times, Hub task relations and World facts.

The fixed 1920×1080 stage has two columns. The 448×856 phone stays centered
in the left column. The right column has a fixed strip above the judgment or
house. At 1440×900, `fit()` scales the frame to 75% and centers it. The phone
content can scroll when a card is long or several cards arrive.

Run the shell tests from the repository root. The evidence-chain tests use
Node.js 22.15 or newer and also run directly via
`node --test demo-shell/tests/*.test.mjs`.

```bash
PYTHONPATH=demo-shell uv run --no-project --python 3.12 \
  --with-requirements demo-shell/requirements.txt --with-editable contracts/generated/python \
  --with pytest --with httpx2 \
  python -m pytest -q demo-shell/tests
```

Rules the demo keeps:

- Device looks come from World values. The Simulator supplies delivery, guest
  arrival, person actions and event end through its viewer and operator reads.
  The Hub relates plan lines to timings, trigger matches and verified
  device read-backs. Camera navigation only changes the view.
- Close-up labels use the Simulator's observed device values and the current
  moment name. Guest arrival opens on the entrance. When a matching device
  read-back arrives, the active guest moment advances to the preparation line's
  devices. The 3D fridge can show its observed notice.
- `GET /demo/api/hub` reads only the Hub's `/state`. Waiting actions and recorded
  run commands from received plans supply the device settings.
- The plan and card project the linked rationale calendar for display. The
  house timeline uses supplied schedule and observation times independently of
  the judgment.
- The shell fetches the renderer from the Simulator's HTTP asset route. The
  judgment stage can open independently while a live house waits for the
  Simulator.
- The tagger sends one batch of eligible rationale texts when they are ready.
  It validates source substrings, listed tags and each line's Server devices.
  `GET /demo/tags?episode=…` serves cached or ready results while the stage
  continues to show the Server text. Replays load their recorded tags.

## Settings (set by `demo-up`)

| Variable | Meaning |
| --- | --- |
| `DEMO_SIMULATOR_URL` | Simulator origin for house assets, snapshot and viewer fragment |
| `DEMO_OPERATOR_TOKEN` | Simulator operator credential for presenter controls |
| `DEMO_SERVER_URL`, `DEMO_APP_TOKEN` | Server for the contract reads and the order share |
| `DEMO_HOUSEHOLD` | Household for contract reads and shares (default `h_042`) |
| `DEMO_FIXTURE_EPISODE` | Enables fixture scene selection, request logging, and quiet-window fast-forward |
| `DEMO_HUB_URL` | Hub for plan receipts, received actions, triggers and verified read-backs (`/state`) |
| `DEMO_NUMBERS_PATH` | Path to the Server's `config/numbers.yaml` when using `DEMO_MODE=1` |
| `DEMO_RECORDINGS_DIR` | Local recordings and cache directory (default: ignored `demo-shell/recordings/`) |
| `DEMO_TAGGER` | `codex` enables background text tags. Defaults to `off` for the standalone shell and tests. |
