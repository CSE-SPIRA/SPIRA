# Home Hub screens

**ACTIVE.** This is the screen reference for the Hub dashboard on this branch. [Specification](spec.md) owns requirements and acceptance. The dashboard reads the Hub's local evidence. It has no controls for running devices, changing delegation, or managing Server work.

## Screen map

| Screen | Address | Purpose |
| --- | --- | --- |
| `이 집이 본 것` | `/` | Read what the Hub received, observed, ran, and restored. |
| `자세한 기록` | `/#detail` | Inspect triggers, commands, observations, and the corresponding delivery evidence. |

`GET /state` and `GET /api/state` return the same JSON projection. `GET /health` returns `status`, `server_confirmed`, and `device_online`. These and `/assets/*` are data and asset routes. The fixture's [control page](tests/fixture_server/README.md) belongs to the test Server.

## Household ledger

Presenters use the ledger to follow preparation and household events during a run. Developers use it to find a happening before opening its evidence.

Open the local Hub URL, `http://127.0.0.1:8088/` by default. The demo launcher prints it under `Hub:` and links to it from the start page as `Hub` (`집이 받은 계획과 기기가 움직인 기록을 봐요.`). The launcher owns those labels in [demo_up.py](../scripts/demo_up.py) and [demo_start.py](../scripts/demo_start.py).

```text
+---------------------------------------------------------+
| Ledger                           | Installed devices   |
| Title              Detail link   | Device         Room |
| Home / plan / Server status      | Device         Room |
| Source legend                    |                     |
| v Newest preparation            |                     |
|   mark   time   happening       |                     |
|                 delivery        |                     |
| > Older preparation             |                     |
| > Household activity            |                     |
+---------------------------------------------------------+
```

### Layout and data

| Region, in reading order | What appears and where its data comes from |
| --- | --- |
| Header and detail link | `이 집이 본 것`, `자세한 기록`, then `{home} · {plans} · {connection}`. Home is the CLI's `--home-name` (`우리 집` by default). Plan status uses `plan_history`. Connection uses `server_confirmed` and `server_error` from the Hub's plan reconciliation. |
| Source legend | `기록 표시 안내` names the legend for assistive technology. A filled green circle means `SPIRA가 시킴`, an outlined circle means `기기가 알림`, and a diamond means `집이 되돌림`. Rows can refine these accessible labels with `준비를 받음`, `준비 변경을 받음`, or `집이 감지함`. |
| Preparation groups | `받은 준비 · 받은 시각 {HH:MM}` with the first receipt's Seoul time and the latest available `할 일 {count}` and `품목 안내 {count}`. The group is keyed by plan ID, covers all its versions, and uses the Hub's persisted `plan_history` and task counts. The newest received preparation opens first. Later versions appear within its group as `준비가 바뀌었어요` rows. |
| Happening rows | Marker, Seoul weekday/time (`월화수목금토일`, one character, then `HH:MM`), optional device/room, action or observation, optional `· 사람이 조작함`, then outstanding delivery. Hub `ledger_view` joins durable command attempts, observations from MQTT `P/events`, Server acknowledgement records, and queued C-3/C-4 packets. It groups related reports by operation. Explicit task ties take priority. Other activity goes to the preparation in effect at that row's time or under `집에서 일어난 일`. Rows are newest first within each group. |
| Installed devices | `이 집의 기기` lists label or type and room from the local installation. At 1100 px and above it sits to the right and below that width it follows the ledger. `devices` in the JSON view instead describes bindings and discovered capabilities. |

[dashboard.py](spira_hub/dashboard.py) owns the Korean headers, markers, delivery labels and time format. [dashboard_state.py](spira_hub/dashboard_state.py) owns the projection. [dashboard.css](spira_hub/dashboard_assets/dashboard.css) owns placement. The [device protocol](../simulator/protocol.md) defines the MQTT inputs.

### States

In this table, **navigation** means the detail link and older group summaries, when present. The latest group stays open.

| Condition | What shows | Exact text | Controls available |
| --- | --- | --- | --- |
| First load, awaiting reconciliation | Stored ledger and installation, with pending connection status | `서버 연결 확인 중` | Navigation |
| No received preparation or ledger rows | Empty ledger. A household-only group opens if household rows exist without a preparation. | `받은 준비 없음`, `기록을 기다리고 있어요.`, `집에서 일어난 일` | Navigation |
| Installation empty or invalid | The device panel shows the appropriate empty or error message | `등록된 기기가 없어요.` or `기기 목록을 불러오지 못했어요.` | Navigation |
| Connected with recorded work | Latest group open, past groups collapsed on first load. A first receipt with nothing outstanding may appear only in its group heading. | `받은 준비`, `서버 연결됨`, `받은 준비 · 받은 시각 {HH:MM}` | Navigation |
| New version, run, restore, or report pending | Subdued version change or local outcome row with outstanding delivery below it | `준비가 바뀌었어요`, `응답 확인 중`, `되돌리는 중`, `서버에 보내는 중` | Navigation |
| Device result confirmed, Server delivery confirmed | The local result uses its device or action wording. The delivery mark clears after all linked receipts are delivered. | For example `청소 끝`. The detail uses `Received by Server` for a delivered row. | Navigation |
| Blocked, failed, or unconfirmed | Local outcome stays visible. An unsuccessful post leaves its separate retry mark. | `실행 보류`, `실행 실패`, `실행 여부 모름`, `실행 확인 안 됨`, `보고 없음`, `전송 실패 · 다시 보내는 중` | Navigation |
| Server pull fails | Stored rows remain while the summary changes | `서버 연결 실패` | Navigation |
| Browser refresh fails or MQTT observations have a gap | The browser retains its current HTML on a failed refresh. The ledger adds no browser-offline banner. On a successful refresh, engineering detail exposes the recorded gap. | Last rendered words. Detail uses `Observation gap last marked at {timestamp}`. | Navigation |
| Run ends, restoration succeeds, is skipped, withheld, or fails | Durable end and restore rows remain after work ceases. The ledger persists across runs and restarts. | `일정이 끝난 것을 확인`, `끝난 뒤 되돌림 확인`, `사람이 바꾼 설정 유지`, `바뀐 기기 상태 유지`, `그대로 둠 · 끝남 확인 없음`, `되돌리기 실패`, `되돌림 확인 안 됨` | Navigation |

### Row wording

[dashboard_words.py](spira_hub/dashboard_words.py) supplies the following templates. Braced values are data substitutions. Its [design_vocabulary.py](spira_hub/design_vocabulary.py) provides shared device, room, and state words.

| Row or value | Exact words or format |
| --- | --- |
| Device and room | Installation label first, for example `전기포트` from [installation.example.json](installation.example.json). Type fallback is `청소기`, `조명`, `TV`, `인덕션`, `오븐`, `냉장고`, `플러그`, `스피커`, `공기청정기`, `스타일러`, `에어컨`, or `기기`. Rooms use `현관`, `거실`, `주방`, `침실` or the supplied room code. |
| Plan versions | `받지 못한 일 {count}`, `{device labels} 취소` with `할 일` as the missing-name fallback, and `택배 기다림 끝`. The noncompact JSON ledger also uses `계획 v{version} 받음`. |
| Home and device events | Package `택배 들임` and guest `손님 도착` are at `현관`. End is `일정이 끝난 것을 확인`. Device suffixes map to `시작`, `멈춤`, `끝남`, `문 열림`, or `기기 상태 보고`. A change uses `{before} → {after}`, `{after}로 바뀜`, or `설정 바뀜`. |
| Command and setting | `청소`, `청소 시작`, `청소 끝`, `잠금`, `잠금 해제`, `켜짐`, `꺼짐`, `멈춤`, `기기 동작 요청`. A notice uses `{item} · 안내 표시` if there is an item prefix before ` · `, otherwise `안내 표시`, or `평소 화면` after clear. An oven preset is `{degrees}° {minutes}분 대기`. |
| Light, display, and music | `분홍 빛`, `주황 빛`, `노랑 빛`, `초록 빛`, `파랑 빛`, `보라 빛`, `흰 빛`, `따뜻한 빛`. Kelvin below 4000 is warm and saturation zero is white. Scenes use `공주 화면`, `파티 화면`, `잔잔한 화면`, `영화 화면`, or `분위기 화면`. Music uses `{playlist} · 볼륨 {volume}` with `잔잔한 음악`, `파티 음악`, `가족 음악`, or the playlist code. |
| Restore | `되돌리는 중`, `되돌리기 실패`, `되돌림 확인 안 됨`, `되돌릴 설정 없음`, `되돌림 확인` plus any formatted restored values. An observed event end prefixes `끝난 뒤` in HTML and `일정이 끝난 뒤` in JSON. A partial restore prefixes `일부 되돌림 · ` to `사람이 바꾼 설정 유지` or `바뀐 기기 상태 유지`. A withheld restore uses `그대로 둠 · 끝남 확인 없음` in HTML and `끝났는지 확인되지 않아 그대로 유지` in JSON. |

### Controls, accessibility, and motion

- `자세한 기록` sets the fragment to `#detail` and reveals the detail below the ledger. The anchor is local and sends no request. Browser Back restores the previous fragment.
- Click a group summary or use Tab then Enter or Space. Older groups open and close immediately using native disclosure. The newest group stays open. No request body or confirmation is needed.
- Tab follows the detail link and group summaries in document order. Links and summaries have visible focus rings. The ledger is a polite live region, and source marks carry labels independently of color. [dashboard.js](spira_hub/dashboard_assets/dashboard.js) preserves the focused summary and older groups' open states when replacing the ledger.
- The dashboard has no animated transitions or fixed presentation delays for navigation. JavaScript refreshes the same path after five seconds and schedules the next refresh five seconds after that attempt ends. The fetch times out after five seconds. That polling determines when new state becomes visible.

### Acceptance

[HUB-AT20](spec.md#3-acceptance-catalogue) covers the birthday ledger, row groupings, legend, outstanding deliveries, and navigation to detail. [test_acceptance.py](tests/runtime/test_acceptance.py) also covers version changes, retained history after restart, notice labels, late restores, and failed or unverified rows (HUB-AT08 and HUB-AT17).

**Not covered by a test.** First-load connection and inventory empty/error copy, the browser's handling of failed refreshes, keyboard focus across refresh, older group interaction, and the responsive breakpoint are untested as screen behavior.

## Engineering detail

Developers use the detail to trace what triggered a task, what the Hub sent, how it verified the effect, and whether its Server peer received each report.

Open `/#detail` directly or follow `자세한 기록` on the ledger. The ledger stays above the detail. The detail is rendered in the same HTML response and revealed when it is the fragment target.

```text
+-------------------------------------------------------+
| Details          Back to ledger  /  JSON              |
| Peer / household / last gap                           |
| Waiting work        | Command ack and read-back       |
| Person actions / C-3| Restoration and skips           |
| Plan summaries      | Plan history                    |
| Task stories        | Device bindings                 |
+-------------------------------------------------------+
```

### Layout and data

| Region, in reading order | What appears and where its data comes from |
| --- | --- |
| Heading and metadata | `자세한 기록`, `장부로 돌아가기`, `JSON`, then `server_peer` from the Server's `X-SPIRA-Fixture` plan-pull header or `Server`. The peer line appends `· pull failed`, `· household paused`, or `· installation configuration invalid` when applicable. Then `Household {household}` and `Observation gap last marked at {observation_gap_at}`. |
| `Waiting work` | `waiting[]` from current saved tasks and trigger matching. Each card shows task ID, plan/version, remaining device/command pairs, `Trigger` JSON, and `Window passed · {window_passed_at}` if applicable. |
| `Command acknowledgement and read-back` | `commands[]`, up to 100 most recent local attempts in reverse order. Device/substrate, phase, status, optional reason, target, and operation ID appear above separate `Acknowledgement`, `Desired properties`, and `Read-back` fields. Missing values show `—`. |
| `Person actions and C-3 events` | `events[]`, up to 100 most recent stored event deliveries. Each card shows event type, Hub-derived `packet[0].payload.by` if present, source, delivery state, and `C-3 payload` from the outbox packet. The C-3 list includes home events. |
| `Restoration and skips` | `restoration[]`, up to 100 most recent restore reports. Shows task ID, delivery state, each device and result item `status`, and packet `at`. |
| `Plan summaries` and `Plan history` | `plan_summaries[]` shows counts of device actions, notices, waiting, missed windows, triggered, completed, failed/unknown/unverifiable, restored, and withheld. `plan_history[]` shows versions, receipt timestamps, ack packets and delivery, `Compared with v{version}` when a previous version exists, and `Changes` JSON or `Version changes unavailable.`. |
| `Task stories` | `task_stories[].steps` from admissions, triggers, attempts, in-window person changes, end evidence, and restore outcomes, ordered by recorded or observed time. Each step displays its capitalized kind with underscores replaced by spaces, then the corresponding JSON fields. |
| `Device bindings` | `devices[]` from installed device bindings and MQTT discovery capabilities. Lists logical device ID, target, substrate (`virtual` or `physical`), a `Class A assumption` badge with the supplied assumption, and `Discovered substrate: {value}` if it differs. |

The Korean navigation strings and English diagnostics come from [dashboard.py](spira_hub/dashboard.py). [dashboard_state.py](spira_hub/dashboard_state.py) builds the fields also exposed through `/state`. The detail uses a responsive grid in [dashboard.css](spira_hub/dashboard_assets/dashboard.css).

### States

| Condition | What shows | Exact text | Controls available |
| --- | --- | --- | --- |
| First load | Direct fragment reveals the server-rendered detail through the browser's anchor behavior | `자세한 기록` | Back to ledger, JSON |
| Empty | Each section has its own empty row in layout order | `No tasks waiting.`, `No commands or execution blocks recorded.`, `No device or home events recorded.`, `No restoration results recorded.`, `No plans admitted.`, `No plan versions recorded.`, `No task stories recorded.`, `No delegated devices.` | Back to ledger, JSON |
| Waiting or normal | Trigger, attempts, received versions and associated events become available | `Trigger`, `Received {timestamp}`, `C-3 payload` | Back to ledger, JSON |
| Change in progress | Result follows read-back. A command acknowledgement can be present before it. Outbox rows remain pending until receipt. | `dispatching`, `ACCEPTED`, `Read-back`, `Pending delivery` | Back to ledger, JSON |
| Evidence and delivery confirmed | Local status and observed values are visible. Delivery is shown independently. | `completed`, `Received by Server` | Back to ledger, JSON |
| Failure, stale read, or missed trigger | Status, reason, or read-back appears as recorded. A missed window remains visible among waiting work. A delivery failure has its own row status. | `failed`, `unknown`, `unverifiable`, `Window passed · {timestamp}`, `Pending · {delivery_error}` such as `Pending · HTTP 404` | Back to ledger, JSON |
| Disconnected | A failed browser read leaves last HTML in place. A Server pull failure or observed device gap appears in metadata on a successful refresh. | `· pull failed`, `Observation gap last marked at {timestamp}` | Back to ledger, JSON |
| End of run | Task stories and C-4 results preserve the ending observation and ownership outcome | `End`, `Restore result`, `restored`, `skipped_user_changed`, `withheld_end_not_observed` | Back to ledger, JSON |

### Controls, accessibility, and motion

- Click or Tab to `장부로 돌아가기` then press Enter. It sets `#seen-title`, hides the detail through CSS, and jumps to the ledger. The two fragment links are immediate and send no network request or body.
- Click or press Enter on `JSON` to make `GET /state` with no body and open the raw response in the current tab. The browser's Back action returns to the detail.
- The detail landmark has `tabindex="-1"` and a labelled heading. It is a fragment target, outside the Tab order itself. Its links have visible focus rings. English evidence has `lang="en"`. There is no custom keyboard shortcut or custom focus trap.
- Presentation uses no transitions or fixed navigation delay. The same five-second page polling updates the evidence region. This region has no custom focus-restoration step on refresh.

### Acceptance

[HUB-AT17 and HUB-AT20](spec.md#3-acceptance-catalogue) check the four primary evidence groups, exposed attribution and packets, binding labels, and the detail link. [test_acceptance.py](tests/runtime/test_acceptance.py) checks separate acknowledgement and read-back (HUB-AT06), restart and retry evidence (HUB-AT09), restoration and withheld/skip outcomes (HUB-AT08, HUB-AT12, HUB-AT16), plus missed windows and version history. [test_simulator_light.py](tests/runtime/test_simulator_light.py) covers the Simulator observation path. [test_home_devices.py](tests/runtime/test_home_devices.py) checks the retired App-facing inventory route is absent.

**Not covered by a test.** Browser fragment navigation and focus behavior, all empty messages, transient browser disconnection and recovery, and whether each in-progress diagnostic is visible before the next refresh are untested as screen behavior.
