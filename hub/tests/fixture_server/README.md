# Live scene controls

The contract fixture is non-inference test support. Run it from the repository
root with Python 3.12 and `uv`.

```bash
TMPDIR=/private/tmp PYTHONPATH=contracts/generated/python \
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
   applies the committed calendar through the same path as the App's
   `PUT /v1/households/h_051/calendar`.

Each upload sets the story clock to the recorded episode's `shared_at`.
The plan's triggers, lifecycle times, linked calendar and wording come from
the episode fixtures. The quiet window uses the Server's normal `quiet_s`
from the share. The fixture releases items and then evidence, intents, tasks,
and the card and plan on the story clock. The other offsets are assumptions
in [`JUDGMENT_SECONDS`](scene_support.py). An evidence-only rationale has
`intents: []` and `none_reason: null`. A completed no-intent result carries
the recorded reason. Fixed-date replays serve the committed snapshots.

The demo launcher starts the clock one minute before the selected episode's
share time. A standalone live fixture starts on wall time until a share or a
clock change. The loopback clock endpoints are:

| Request | Result |
| --- | --- |
| `GET /v1/demo/clock` | Clock state with the current story time in `now`. |
| `POST /v1/demo/clock` | Send `{"set_to":"<offset ISO time>"}` to jump, or `{"advance_to":"<offset ISO time>","over_seconds":6}` to ramp forward. The ramp duration accepts 1–60 real seconds and defaults to 6. |
| `GET /v1/demo/moments` | The quiet-window end (`judgment.quiet_end`), task and guest-window times, and recorded world events for the current episode. Simultaneous time triggers share one entry with multiple task IDs. |
| `POST /v1/demo/clock/next` | Send an optional `{"over_seconds":6}`. Ramps to the quiet-window end or event time, or to 20 seconds before a task or guest-window time. A moment within its 20-second lead-in returns 409 until the clock passes it. Returns 404 when the episode has no future moments. |

Event moments carry the recorded event type. Use `delivery`, `guests_arrive`,
and `event_end` at the Simulator's `POST /operator/home`. Use
`POST /operator/device` for the person's light change.

A live `package.brought_in` selects the latest uploaded episode with a
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

## Control page

Open `http://127.0.0.1:8000/_fixture/control` for a standalone live fixture.
`scripts/demo-up` prints the actual URL and writes it to `urls.txt`.
The page and its JSON routes require a loopback connection and a local host.
They are available when live scenes are enabled and use no App or Hub key.

- **지금** shows story time, the active episode, judgment stages and their
  countdown, recent peers, plan pull and acknowledgement history, and cards.
- **시계** sets story time, pauses, resumes, changes the rate, or ramps to a
  recorded moment. Moment controls use the same lead-in as the demo clock.
  Sharing a new recording anchors the clock at its recorded share time at 1×.
- **판단 속도** adjusts the current episode's unfinished stages or the next
  new share. The server preset uses the normal `quiet_s` and the existing
  assumed offsets. Fast and slow are rehearsal assumptions. A hold keeps
  the selected stage pending. Holding at receipt leaves the episode in
  `received`. Release makes the remaining judgment available immediately.
  Task trigger and end times stay on the recorded schedule.
- **회차** queues the next recording and sends sample multipart requests
  through the App route. The image part has no order content. The recording
  supplies all items, intents, tasks and card text. Repeat reuses the sample's
  `source_id`. The second-capture case uses a new source ID on the same
  recorded order and restarts the quiet window.
- **경우** arms a scenario or shows the next action to perform on a real
  client. For instance, the package case waits for the house event and
  the line-off case waits for the App's reaction. To follow an episode
  shared outside the shell, open its Demo URL with `?episode=<episode_id>`.
- **고장** shows one armed fault per route group, named as synthetic.
  Counts apply to matching requests. A new fault replaces the group's
  previous arm. Apply-then-fail replaces a successful write response with
  503 after the normal handler takes effect. A connection drop closes an
  incomplete HTTP response. Clear the preflight fault after observing the
  block. It stays armed across periodic pulls and affects plan pulls only.
- **요청 기록** shows the most recent 300 requests, newest first. The fixture
  records wall time, credential kind, method, path, status, latency, and the
  applied fault. The shell marks its fixture requests separately. Hub-key
  reads, including reads from peers sharing the Hub key, share one category.
  Query values, credentials and request bodies are excluded.

Reset returns the fixture to one minute before the selected recording.
It clears the fixture's episode history but does not clear the Hub ledger
or the house. Stop the stack and run [`scripts/demo-up`](../../../scripts/demo-up)
without `--keep` to start a fresh stack. Faults stay armed until consumed
or explicitly cleared. The request log and fault arms live in process memory.

All routes below are relative to `/_fixture/control`.

| Method | Path | Input or result |
| --- | --- | --- |
| GET | (none) | The HTML control page |
| GET | `/state` | One current state snapshot |
| GET | `/log?after=0` | Requests after the given ID and the latest ID |
| POST | `/clock` | `action` set, advance, next, pause, resume, or rate. Set uses `at`. Advance uses `at` or a moment ID in `moment`, with optional `over_seconds`. Rate uses `rate`. |
| POST | `/judgment` | `preset` server, fast, slow, custom, stuck, or release. `scope` is next or current. Custom accepts `quiet_seconds` and `offsets` by stage ID. Stuck takes `hold`. Release uses current. |
| POST | `/episode` | `action` select, share, repeat, capture, reset, calendar, or resume. Select and reset accept `episode_id`. |
| POST | `/case` | Case `id`, or `null` to clear its current selection. Clear armed transport faults separately. |
| POST | `/fault` | `group`, `kind`, and `count` (integer or `null`). Latency takes `delay_ms`. Status takes `status`. Optional `route` narrows a group to order, edit, plans, events, executions, or clock-read. |
| POST | `/fault/{group}/clear` | Clears the arm for app, hub, clock, or health. |

Each successful POST returns the updated snapshot. A sample share or
recorded calendar reports the App route's own status in `sample_response`.

### Case catalogue

Paused shares and read failures use the public episode status and carry no
judgment content. The order-edit 202 is an acknowledgement only. Stale edit
is synthetic because the public order-edit operation has no revision field
or documented 409. Sources refer to [common rules](../../../contracts/rules.md),
[schemas](../../../contracts/schemas), [recordings](../../../contracts/fixtures)
and the [Server spec](../../../server/spec.md).

| ID | Case | Source | Reproducible |
| --- | --- | --- | --- |
| `invalid-image` | 읽을 수 없는 이미지 | synthetic · contracts/rules.md:89 · App OpenAPI POST /v1/orders | Yes |
| `read-failed` | 상품 읽기 실패 | synthetic outcome · common.json#EpisodeStatus · server/spec.md:513 | Yes |
| `duplicate-share` | 같은 공유 재전송 | contracts/rules.md:64 | Yes |
| `paused-share` | 일시정지 중 공유 후 재개 | contracts/rules.md:73 · common.json#EpisodeStatus | Yes |
| `second-capture` | 조용한 시간 중 두 번째 캡처 | ep_9031/timeline.md:7 · contracts/rules.md:10,81 · server/spec.md:505 | Yes (h_042) |
| `order-edit` | 주문 수정 접수 | contracts/openapi/app.yaml §APP-07 | Yes |
| `stale-edit` | 주문 수정 충돌 | synthetic · contracts/schemas/error.json · common.json#ErrorCode · contracts/openapi/app.yaml §APP-07 | Yes |
| `edit-rejudge` | 주문 수정 뒤 재판단 | contracts/schemas/order_edit.json | No. Needs recorded corrected items, rationale, card and plan after the edit. |
| `birthday` | 생일 주문 전체 | ep_9031 | Yes (h_042) |
| `groceries` | 장보기 · 의도 없음 | ep_9150/rationale.json | Yes (h_042) |
| `held` | 일정 대기 카드 | ep_9120/card.held.json | Yes (h_051) |
| `calendar` | 기록된 일정 적용 | ep_9120/calendar.json · card.found.json · plan.v2.json | Yes (h_051) |
| `unclassified` | 분류되지 않은 의도 | common.json#ReservedIntent · server/spec.md:729 | No. Needs recorded unclassified rationale, card and plan. |
| `two-cards` | 한 주문에 카드 두 장 | contracts/rules.md:11 | No. Needs recorded rationale, two cards and their matching plan. |
| `judgment-failed` | 읽기 이후 판단 실패 | server/spec.md:421 · contracts/schemas/episode.json | No. Needs public S2–S4 failure response and an agreed client-visible signal. |
| `server-pace` | 서버 기본 숫자 | server/config/numbers.yaml · fixture JUDGMENT_SECONDS (assumed) | Yes |
| `fast` | 빠른 리허설 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `slow` | 느린 LLM | fixture JUDGMENT_SECONDS × 4 (assumed) | Yes |
| `stuck-received` | 공유 접수 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-reading` | 읽기 시작 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-items` | 상품 읽기 완료 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-quiet_window` | 조용한 시간 종료 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-evidence` | 근거 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-intents` | 의도 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-tasks` | 작업 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `stuck-published` | 카드·계획 공개 단계에서 멈춤 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `release-now` | 판단 지금 끝내기 | fixture JUDGMENT_SECONDS (assumed) | Yes |
| `partial-rationale` | 중간 근거만 보기 | ep_9031/rationale.json · live projection | Yes (h_042) |
| `package` | 택배 들이기 · 계획 새 버전 | ep_9031/events.json · contracts/rules.md:35,39 | Yes (h_042) |
| `equal-plan` | 같은 계획 버전 재전송 | contracts/rules.md:36 · recorded plan | Yes |
| `lower-plan` | 이전 계획 버전 재전송 | contracts/rules.md:36 · recorded plan history | Yes |
| `ack-device` | 수신 거절 · 알 수 없는 기기 | derived from ep_9031, changed t_oven#4.actions[0].device · contracts/rules.md:40 | Yes (h_042) |
| `ack-command` | 수신 거절 · 지원하지 않는 명령 | derived from ep_9031, changed t_oven#4.actions[0].cmd · contracts/rules.md:40 | Yes (h_042) |
| `ack-value` | 수신 거절 · 범위 밖 값 | derived from ep_9031, changed t_oven#4.actions[0].value.temp_c · contracts/rules.md:40 | Yes (h_042) |
| `preflight` | 실행 직전 계획 확인 실패 | synthetic · contracts/rules.md:41,89 | Yes |
| `event-resend` | 집 이벤트 적용 후 응답 실패 | synthetic · contracts/rules.md:62,89 | Yes |
| `result-resend` | 실행 결과 적용 후 응답 실패 | synthetic · contracts/rules.md:63,89 | Yes |
| `line-off-before` | 실행 전 줄 끄기 | ep_9031/reactions.json · contracts/rules.md:37–38,71 | Yes |
| `line-off-after` | 실행 후 줄 끄기 | contracts/rules.md:37–38,71 | Yes |
| `line-on-after` | 시작한 줄 다시 켜기 | contracts/rules.md:71 | Yes |
| `stop` | 준비 중지 후 반응 무시 | contracts/rules.md:37–38,72 | Yes |
| `pause-resume` | 가구 일시정지와 재개 | contracts/rules.md:38,73 | Yes |
| `memory-delete` | 우리 집 기억 삭제 | ep_9031/memory.json · App OpenAPI DELETE memory | Yes |
| `latency` | 응답 지연 | synthetic · contracts/rules.md:89 | Yes |
| `internal` | 서버 내부 오류 | synthetic · contracts/rules.md:89 | Yes |
| `app-unavailable` | 앱 연결 불가 | synthetic · contracts/rules.md:89 | Yes |
| `hub-unavailable` | 허브 연결 불가 | synthetic · contracts/rules.md:89 | Yes |
| `app-drop` | 앱 연결 끊김 | synthetic · contracts/rules.md:89 | Yes |
| `hub-drop` | 허브 연결 끊김 | synthetic · contracts/rules.md:89 | Yes |
| `app-unauthorized` | 앱 인증 거절 | synthetic · contracts/rules.md:89 | Yes |
| `forbidden` | 접근 거절 | synthetic · contracts/rules.md:89 | Yes |
| `not-found` | 앱 대상 없음 | synthetic · contracts/rules.md:89 | Yes |
| `health` | 상태 확인 저하 | synthetic · contracts/rules.md:89 · contracts/schemas/health.json | Yes |
| `no-clock` | 시계 경로 없음 | synthetic · contracts/rules.md:89 | Yes |

The control page’s **현실 지연** preset takes an integer seed. It adds App response
latency jitter and an isolated rationale 503. From the next share, it also
varies judgment timings and can release two stages at the same moment. It
starts off unless `scripts/demo-up --realistic [SEED]` is used.

## Open questions

- What public signal distinguishes a judgment failure after reading from a
  completed card-less result? The Server spec uses `judged` and stores an
  internal error, while the episode schema exposes only `status`. Confirm
  the App's card-less notification signal for `read_failed`.
- Does the production Server restart quiet time on each distinct capture
  exactly as in the Server spec, including captures from separate shares?
  The birthday recording contains two captures. The common rules define
  the eight-hour grouping and quiet duration.
- Is there a public stage-progress or next-stage timing endpoint? The
  fixture's stage times are rehearsal estimates.
- Confirm the order-edit conflict semantics and record a corrected order
  with its resultant rationale, card and plan.
- Record one `unclassified` order and one two-card order, including their
  Hub plans and the card content.
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
