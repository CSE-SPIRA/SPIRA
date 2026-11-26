# App screens

**ACTIVE.** This is the screen reference for the Android App and its browser preview on this branch. [Specification](spec.md) owns requirements and acceptance; this file says what each screen shows, when, with which words, from which data, and what each control does. Shared bodies and enum values are in [contracts](../contracts/README.md). Korean strings are copied from the code; the source file is named with each group.

## Screen map

| Screen | How it opens | Purpose |
| --- | --- | --- |
| Start and connection | App launch | Configuration check, token entry, Server reachability. |
| Setup (first run) | No household stored, or `SPIRA_FIRST_RUN=1` | Google calendar, household types, household creation, Hub connection code, device check. |
| 메인 | Tab 1 (default) | One preparation's lifecycle: share → staged wait → card → interventions → memory. |
| 캘린더 | Tab 2 | Month of events and memories; a day's agenda; a memory sheet. |
| 우리 집 | Tab 3 | Devices by room with what each is doing now; household types; Google connection. |
| Stop confirmation | 멈추기 on a card | Confirms stopping one card's preparation. |
| Memory sheet | Main after close, or a memory on Calendar | What happened and the Server's verdict. |

Every screen shows the header `SPIRA` and, in a fixture or preview build, the qualifier `미리보기 · 계약 테스트 서버` in small type ([labels.dart](lib/features/labels.dart)). The App never calls the Hub or the Simulator.

Polling: every 3 seconds while an order is being read or a card is open, every 30 seconds otherwise ([app_controller.dart](lib/app_controller.dart) `_activePollInterval`, `_idlePollInterval`). Nothing on screen advances on a timer of its own; every change follows stored Server data or a confirmed request.

## Start and connection

Source: [main.dart](lib/main.dart), [app_controller.dart](lib/app_controller.dart).

| Condition | What shows | Controls |
| --- | --- | --- |
| `SPIRA_BASE_URL` missing or invalid | Centered `서버 주소를 설정해 주세요.` | None. |
| Restoring stored state | `앱 시작 중` | None. |
| Server answers 401 | Toolbar key; dialog `서버 접속 토큰 입력` with field `서버 접속 토큰` / `접속 토큰`; message `서버 접속 토큰을 입력해 주세요.` | `취소`, `연결`. Saving failure: `접속 정보를 저장하지 못했어요.` |
| Server unreachable | Banner `서버에 연결할 수 없어요`, after a first success `서버에 연결할 수 없어요 · 마지막 확인 {HH:MM}`. The last view stays readable. | Pull to refresh. |
| Stored state unreadable | `저장된 정보를 불러오지 못했어요.` | Retry by restarting. |
| Refresh failed for another reason | `새로 불러오지 못했어요. 다시 시도해 주세요.` | Pull to refresh. |

A household configured at build time (`SPIRA_HOUSEHOLD_ID`, for example the household made by the Server's demo home script) opens directly on Main; setup is skipped. `SPIRA_FIRST_RUN=1` forces setup.

The order on Main is the one this phone shared, else the newest order that is not `closed` (in progress or with open cards, also when shared from another phone or the presenter). Closed orders (for example the demo home's past orders) are not shown as the current order; they appear under 최근 이 집의 기억.

The bottom navigation has three tabs: `메인`, `캘린더`, `우리 집`.

## Setup (first run)

Source: [setup.dart](lib/features/setup.dart). One step per screen, one primary button per step.

```text
+----------------------------------+
| SPIRA                            |
| 미리보기 · 계약 테스트 서버          |
| Step title                       |
| One sentence                     |
| [ primary button ]               |
| secondary link                   |
+----------------------------------+
```

| Step | Title and text | Controls | Request |
| --- | --- | --- | --- |
| 1. Google | `Google 캘린더`; connected build: `앞으로 14일의 일정을 참고해 준비할게요.`; without a Google client: `Google 연결 없이 시작할 수 있어요.` | `Google 캘린더 연결` (Android with a client id), `건너뛰기` | Google sign-in on the phone only. |
| 2. Household types | `가구 유형`; groups `인원` (`1인`, `2인`, `3~4인`, `5인 이상`), `구성` (`부부·커플`, `영유아 자녀`, `초등 자녀`, `중학생 자녀`, `고등학생 자녀`, `부모 + 성인 자녀`, `3대 함께`, `룸메이트·셰어하우스`), `생활 단계` (`대학생`, `직장인`, `은퇴·노년`), `근무 형태` (`맞벌이`, `재택근무`), `반려동물` (`반려견`, `반려묘`, `그 밖의 반려동물`). `인원` and `생활 단계` are pick-one. | `우리 집 만들기` | `POST /v1/households {household_types}`. A blocked combination: `함께 선택할 수 없는 가구 유형이에요.` Other failure: `설정을 저장하지 못했어요. 다시 시도해 주세요.` |
| 3. Connection code | `집 허브 연결 코드`; `이 코드를 집 허브에 입력하세요`; the `hub_api_key` from the creation response, shown once | `연결 코드 복사` → `연결 코드를 복사했어요`; `다음` | None. The code is entered on the Hub by a person. |
| 4. Devices | `집 기기 확인`; the sample device list (see 우리 집), read-only, delegation disabled | `저장` | Calendar sync after the household exists (see Calendar). |

After step 4 the App opens Main.

## 메인

Source: [preparations.dart](lib/features/preparations.dart), [order_extraction.dart](lib/features/order_extraction.dart), [memory_sheet.dart](lib/features/memory_sheet.dart).

```text
+----------------------------------+
| SPIRA                            |
| 주문                              |
| No order: large upload box (+)   |
|   주문 분석하기                     |
|   + 최근 이 집의 기억 (cards)        |
| After a share: [ 주문 분석하기 ]     |
| Order area (wait / items /       |
|   collapsed row)                 |
| Card (title, date, lines)        |
| or memory sheet                  |
+----------------------------------+
| 메인 | 캘린더 | 우리 집              |
+----------------------------------+
```

### Order area states (M1–M5)

| State | Data | What shows | Controls |
| --- | --- | --- | --- |
| No order yet (Android) | — | `쇼핑 앱에서 주문 화면을 공유하면, 그 주문에 맞춰 집을 준비해요.` / `주문 화면을 캡처하고 공유 메뉴에서 SPIRA를 선택해 주세요.` | `주문 분석하기` (gallery, 1–3 images). Preview: `예시 주문으로 공유` (`주문을 보내는 중…` while sending). |
| No order yet (other) | — | `주문 화면을 보내면 필요한 준비를 찾아드려요.` | `주문 분석하기`. |
| No order yet, images can be picked (Android gallery, web file picker) | — | A large bordered box with a `+` circle, `주문 분석하기` and `온라인 주문 화면 캡처를 올려 주세요 (1~3장)` instead of the button and the lines above; below it **최근 이 집의 기억**: up to five cards, preparation memories first (closed orders with cards, as on Calendar; tap opens the memory sheet), then recent orders without cards (`M월 D일 · 주문`, item types when the order was read, else `품목 N개`); `아직 쌓인 기억이 없어요.` when none. | Tap the box. |
| Sending | Upload in flight | `공유한 주문을 보내는 중이에요…` | None. |
| Offline share | Upload queued | `연결되면 공유한 주문을 보낼게요.` | Sent automatically on reconnect. |
| Share rejected | 4xx from `POST /v1/orders` or image checks | One of `주문 화면을 한 번에 1~3장 공유해 주세요.`, `이미지 한 장은 5MB 이하여야 해요.`, `JPG 또는 PNG 주문 화면을 공유해 주세요.`, `서버가 이미지를 읽을 수 없어요. 새 캡처를 공유해 주세요.`, `공유한 이미지를 열 수 없어요. 주문 화면을 다시 공유해 주세요.`; gallery: `사진을 1~3장 골라 주세요.`, `선택한 사진을 열 수 없어요. 다시 골라 주세요.`; generic `주문을 보내지 못했어요. 다시 시도해 주세요.` | `다시 시도`, `다시 보내기`, `선택 취소`. |
| **Staged wait** (M2) | Episode `received`/`reading`, from this phone or shared elsewhere | Loading panel: activity indicator, the stage in progress, a progress bar. Below it, one line per stored stage (see next table). Sent thumbnails (`보낸 사진 N`) between the panel and the lines. | None. |
| Read failed | Episode `read_failed` | `읽지 못했어요. 다시 보내 주세요` | Share again. |
| Items, no card (M3, M4a) | Episode judged, no card | `받았어요`; `품목 N개를 읽었어요`; item name and `N개` per row; `가린 품목 N개` when masked; item guidance (below). | None. |
| Card present (M5) | `card_ids` non-empty | Collapsed row: thumbnail (`주문 사진`), `주문 N개 · {first item} 외 N-1개`, chevron; `가린 품목 N개` when masked. | Tap toggles the full order (items and guidance). |

**Staged wait lines** ([order_extraction.dart](lib/features/order_extraction.dart) `OrderExtraction.build`). The panel line names the stage in progress; a finished stage adds a checked line that fades in. Upcoming stages are never listed. The bar moves only when a stage is stored.

| Stored on the Server | Panel line (in progress) | Line added below |
| --- | --- | --- |
| Episode accepted | `주문을 읽고 있어요` | `받았어요` |
| S1: `GET /v1/episodes/{id}` has `items` | `일정과 지난 주문을 살펴보고 있어요` | `품목 N개를 읽었어요` and item names as small chips |
| S2: `GET …/rationale` answers 200 | `어떤 준비인지 보고 있어요` | `일정과 지난 주문을 살펴봤어요` |
| S3: `intents[0].intent_text` present | `집에서 할 일을 정리하고 있어요` | The Server's intent text, verbatim |
| S5: card arrives | — | The wait block is replaced by the collapsed row and the card. |

With reduced motion the indicator is a static icon and nothing fades or pulses.

**Item guidance** (M4a; [order_extraction.dart](lib/features/order_extraction.dart) `_ItemGuidance`). From `item_tasks[]`, shown once under the first item of that type (`item` is the item type): kind `냉장고에 보관 안내` (`storage`), `냉장고에 손질 안내` (`prep`), `품목 안내` (none); the Server's `text`; state `택배가 들어오면 보여 드려요` (`scheduled`), `냉장고에 띄웠어요` (`done`), otherwise the line state word.

### Card (M4b, M6–M8)

Data: `GET /v1/households/{id}/cards`. Text is the Server's template text, verbatim.

| Region | What shows |
| --- | --- |
| Title | `card.text`, large. |
| Meta | Start `M월 D일 (요일) HH:MM`; `N개 중 M개 끝남`; awaited event `일정이 끝나길 기다리는 중` / `손님 도착을 기다리는 중` / `택배가 들어오길 기다리는 중`. |
| Card status | `요청함` while a stop is pending; `이 준비가 중지됐어요.` when stopped; control errors (below). |
| Each line | Left: time `HH:MM` or trigger (`손님이 오면`, `일정이 끝나면`, `택배가 들어오면`) with relation (`{파티/일정} 전`, `… 시작에 맞춰`, `… 시작 후`); the line text; the restore outcome; the Server's note. Right: state chip; `요청함` while pending; the on/off switch where allowed. |
| Footer | `멈추기` (or `멈추기 다시 요청` after an unconfirmed stop) when the card offers `stop`. |

Line state words ([design_vocabulary.g.dart](lib/design_vocabulary.g.dart) `lineWords`): `held` `시간을 기다리는 중`, `scheduled` `예정됨`, `running` `진행 중`, `done` `완료`, `partial` `일부 완료`, `failed` `실패`, `unknown` `결과 확인 불가`, `blocked` `실행하지 못함`, `user_changed` `직접 바꾸셨어요`, `off` `꺼짐`, `stopped` `중지됨`, `cancelled` `취소됨`, `dropped` `준비하지 않음`. Restore outcomes (`endWords`): `restored` `원래대로 돌렸어요`, `kept_user_change` `바꾸신 그대로 두었어요`, `restore_failed` `복원 실패 또는 결과 확인 불가`, `withheld` `행사 끝을 확인하지 못해 안전 설정을 그대로 두었어요.`

**Controls** (M7a):

| Control | Shown when | Sends | Immediate response | Confirmed by |
| --- | --- | --- | --- | --- |
| Line switch off | Line not finished (also while running) | `POST /v1/cards/{id}/reactions {line_off, task_id}` | `요청함` | Next card read shows `off`. |
| Line switch on | Line off and not started | `… {line_on, task_id}` | `요청함` | Next card read. A 409 (already started) removes the switch: `이미 시작된 항목은 바꿀 수 없어요.` |
| `멈추기` | Card offers stop | Opens the stop confirmation | — | — |

Errors: `준비 항목 변경을 확인하지 못했어요.`, `중지 요청을 확인하지 못했어요.` When the Server does not serve reactions (404): `아직 이 서버에서는 끌 수 없어요`, the control is restored and not retried.

**Stop confirmation**: `이 준비를 멈출까요?` / `이 카드의 준비만 멈춰요.`; `취소`, `멈추기` → `{stop}` reaction.

**Notifications**: a new or newly timed card raises one local notification titled `준비 카드` when the card's `notify` is set, deduplicated by card and update time.

### Memory on Main (M9, M10)

When the episode closes, live cards leave Main and the memory sheet takes their place until a new order is accepted or the user taps `확인` (`확인 상태를 저장하지 못했어요.` on failure). The Calendar keeps the marker either way.

Memory sheet ([memory_sheet.dart](lib/features/memory_sheet.dart)): title `이렇게 기억할게요`; the order items; per line, the state and the task feedback `끔` (off) / `바꿈` (changed) / `그대로` (kept); the verdict `예상대로 쓰였어요` (match), `멈추셨어요` (stopped), `확인하지 못했어요` (unconfirmed), `아직 판정 전` before the Server's observation. Data: `GET …/rationale` `observations[]`, `GET /v1/episodes/{id}`.

## 캘린더

Source: [calendar.dart](lib/features/calendar.dart), [sample_calendar.dart](lib/sample_calendar.dart).

```text
+----------------------------------+
| ‹  2026년 10월  ›        [오늘]   |
| 예시 일정                          |
| 일 월 화 수 목 금 토                 |
| month grid: event bars, dots     |
| Day agenda: events, memories     |
+----------------------------------+
```

| Region | What shows | Data |
| --- | --- | --- |
| Header | `{YYYY}년 {M}월`; `이전 달`, `다음 달`, `오늘` | Local. |
| Sample label | `예시 일정` while samples are shown | Sample calendar. |
| Grid | Weekdays `일 … 토`; today marked; event bars with title and time; a memory dot on each date with a memory | Events from Google or the samples; memories from closed episodes (date = the card's `starts_at` the App saw, else `shared_at`). |
| Day agenda | `M월 D일` (`오늘, ` prefix today) · `일정 N개 · 기억 N개`; heading `일정` with `{title} · 종일` or times; heading `준비 기억`; empty: `이날의 일정과 기억이 없어요.` | Same. |
| Memory open | Memory sheet; `기억 불러오는 중`; failure `기억을 불러오지 못했어요` with `다시 시도` | `GET /v1/episodes/{id}`, `…/rationale`. |

**Which events**: Google events when connected (they replace the samples, even when empty). Without Google: in a fixture or preview build, the replay's sample (생일 파티 on the replay's Saturday 14:00–18:00, plus ordinary events); against the real Server, the same sample anchored to Server time (the birthday starts 20 minutes after the `server_time` of a cards read and lasts one hour; ordinary events on later days). The anchor is stored and survives restarts; a new one is made only when the birthday has ended or is under 10 minutes away and no card is open.

**Sync**: `PUT /v1/households/{id}/calendar` after the household exists and when the events change. Failures: `캘린더를 동기화하지 못했어요.`, `예시 일정을 보내지 못했어요.`

## 우리 집

Source: [our_home.dart](lib/features/our_home.dart), [sample_devices.dart](lib/features/sample_devices.dart).

| Region | What shows | Controls and data |
| --- | --- | --- |
| Devices `기기` | `예시 집` label; rooms that have devices (entrance hidden when empty), each device with its type icon and name; failure `예시 집을 불러오지 못했어요.` | Bundled copy of `hub/installation.example.json` (kept equal by a test). |
| Delegation `맡기기` | Toggle per device, disabled, `집 연결 후`; label `{name} 맡기기 · 집 연결 후` | No Server route yet. |
| Now running | `지금: {line text} · {state}` for a device in an open card's line | Device → task from `GET …/rationale` `tasks[].devices` (`id`, `type`, `room` only). `끄기` sends that line's `line_off`; `요청함` while pending. |
| Household types `가구 유형` | The chosen types | `가구 유형 저장` → `PUT …/profile`. |
| Google `Google 캘린더` | `연결됨` / `연결 안 됨` | `Google 연결` / `Google 연결 해제` (Android). |

## Server routes the screens use

| Route | Screen | Served by the real Server on this branch | Without it |
| --- | --- | --- | --- |
| `POST /v1/households`, `PUT …/profile`, `PUT …/calendar` | Setup, 우리 집, 캘린더 | Yes | — |
| `POST /v1/orders` | 메인 | Yes | — |
| `GET …/cards` | 메인, 우리 집 | Yes | — |
| `GET /v1/episodes/{id}`, `…/rationale` | 메인, 캘린더, 우리 집 | Yes (readable from the start, stage by stage) | — |
| `GET …/episodes` | 메인, 캘린더 | No | Main runs from cards and the shared order; retried every 60 s; Calendar keeps memories the App saw close. |
| `POST /v1/cards/{id}/reactions` | 메인, 우리 집 | No | `아직 이 서버에서는 끌 수 없어요`; control restored. |
| `GET …/memory` | — | No | Not used by these screens. |

## Acceptance

The acceptance ids are in [spec.md](spec.md) §3 and the widget and controller tests are in [test/contract_flow_test.dart](test/contract_flow_test.dart). Not covered by an automated test: Android share-sheet delivery, Google sign-in, local notification display and TalkBack; these need an Android device.
