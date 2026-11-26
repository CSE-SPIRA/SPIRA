# Demo shell

**ACTIVE** · This guide covers running and presenting the demo shell.
The [shell specification](spec.md) defines its behaviour, and the
[integration contracts](../contracts/) define Server payloads.

At `/demo`, the real Flutter App runs at phone size on the left. The shell
owns the Server stages, house, record and presenter controls on the right.
The App and the shell show what they independently read from the same
Server. The App source and build entry points live in `app/`.

## Run

```bash
scripts/demo-up --tagger # from the repository root
```

The launcher uses `uv`, `mosquitto` and Flutter. It runs `flutter build web`,
serves the build and its preview proxy, and supplies the preview URL to the
shell. Builds are cached under `/private/tmp` on macOS by the App tree,
working build inputs and build settings. The launcher prints the URLs for
you to open.

Use `--no-app` for the placeholder or `--app-web DIR` to serve an existing
build. A supplied build must target the chosen App proxy port, household
and peer mode. `--proxy-port` defaults to 8731 and `--web-port` to 8732.
Set `DEMO_STATE_ROOT` to choose a directory for launcher state and the build
cache.

Open the printed **Demo** URL. In fixture mode, choose 생일 주문 or 평소 장보기
and press **공유** (Space/→) to submit the sample, or use **주문 분석하기** in
the App to upload a screenshot. Advance through the Server stages with **다음**.
**집으로** opens the house once a card and its Hub plan receipt are available.
**기록** ends on the house record. In the App, open the calendar to see the
memory. The cue shows what it is waiting for.
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

Use the returned household ID. The shell and App preview use that Server.
The preview proxy keeps the credentials on the launcher machine. Submit your
own screenshot using **주문 분석하기** in the App. A missing Server read shows
서버가 아직 이 단계를 내보내지 않아요 on its stage. The shell uses the Server's
clock and moments when available. Without a rehearsal clock, the cue skips
clock advances and shows a notice. Text tags and illustrated device displays are
disabled for these runs. The run logs include the selected Server URL.

In a live run, press 다음 to move to the next stage. A waiting stage shows its
skeleton, then fills in place. The intent stage has separate situation and
intent views. Add `?auto=1` for the optional timed judgment rehearsal.
If you have a Server dashboard URL, pass it URL-encoded as the
`dashboard` query parameter to display a link in the presenter header.

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
`GET /demo/api/recordings`. Open `/demo?recording=<id>` and press 다음
(Space/→) to advance immediately through the saved stages and house moments.
Saved playback uses the phone placeholder. It can run from the recorded
Server and house data while the peers are offline.
The house uses locally cached renderer assets when the Simulator is offline.
Older recordings may need the Simulator to supply assets that have yet to be
cached. Playback redraws TV and fridge artwork from recorded template,
palette, and motif codes. Earlier recordings with embedded artwork still play.

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

After the last house moment, **기록** shows the house record. When memory
is available, the App calendar's dot for the execution day opens the App's
memory sheet independently.

Deep links include `/demo?episode=ep_9031&step=3` and
`/demo?episode=ep_9031&page=house`. They require a readable Server episode.
House links also wait for that run's card and Hub receipt.

Add `owners=1` to the query string to show the owner tags. They are hidden by default.

| Panel or region | Owner tag |
| --- | --- |
| Embedded phone | 앱 |
| Server stages and house record | 서버 창 |
| 3D house, device labels and house timeline | 시뮬레이터 · 집 |

## Where to change what

| To change | Edit | Do not need to touch |
| --- | --- | --- |
| Shared colours, spacing, type and motion | [`design/tokens.json`](../design/tokens.json), then run `python3 design/build.py` | Generated stylesheets |
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
| Judgment stage order and evidence display | `ui/judgment.js` and `ui/judgment-view.js` | Server rationale |
| Text tagger lists, validation and cache | `tag-lists.json` and `tagger.py` | |
| Prepared item icons, storage words and props per unit | `ui/item-types.json` | Item names |
| Server episode discovery, polling and tag reads | `ui/episode.js` | |
| Presenter sample order upload | `ui/order-share.js` | App order UI |
| House record | `ui/house-record.js` | App calendar |
| Reasoning stages and pacing | `ui/reasoning.js` | |
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
viewport fills the phone frame.

Run the shell tests from the repository root. The evidence-chain tests use
Node.js 22.15 or newer and also run directly via
`node --test demo-shell/tests/*.test.mjs`.

```bash
PYTHONPATH=demo-shell uv run --no-project --python 3.12 \
  --with-requirements demo-shell/requirements.txt --with-editable contracts/generated/python \
  --with pytest --with httpx2 \
  python -m pytest -q demo-shell/tests scripts/tests
```

Rules the demo keeps:

- Device looks come from World values. The Simulator supplies delivery, guest
  arrival, person actions and event end through its viewer and operator reads.
  The Hub relates plan lines to timings, trigger matches and verified
  device read-backs. Camera navigation only changes the view.
- The whole-house view marks each observed change. A marker opens an optional
  close-up with the observed device values. The 3D fridge can show its observed
  notice.
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
| `DEMO_APP_URL` | App web URL shown in the phone frame |
| `DEMO_SERVER_URL`, `DEMO_APP_TOKEN` | Server for the contract reads and the order share |
| `DEMO_HOUSEHOLD` | Household for contract reads and shares (default `h_042`) |
| `DEMO_FIXTURE_EPISODE` | Enables fixture scene selection, request logging, and quiet-window fast-forward |
| `DEMO_HUB_URL` | Hub for plan receipts, received actions, triggers and verified read-backs (`/state`) |
| `DEMO_NUMBERS_PATH` | Path to the Server's `config/numbers.yaml` when using `DEMO_MODE=1` |
| `DEMO_RECORDINGS_DIR` | Local recordings and cache directory (default: ignored `demo-shell/recordings/`) |
| `DEMO_TAGGER` | `codex` enables background text tags. Defaults to `off` for the standalone shell and tests. |
