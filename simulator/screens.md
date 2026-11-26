# Simulator screens

**ACTIVE.** This is the screen reference for the independent Simulator on this branch. [Specification](spec.md) owns requirements and acceptance, and [device protocol](protocol.md) owns the Hub boundary. The viewer and its optional shell fragment show the house. The App and its cards have their own surface.

## Screen map

| Screen | Address | Purpose |
| --- | --- | --- |
| 3D test home | `/sim/viewer` (`/` redirects) | Follow the whole house and act as a person at a device. |
| House observation fragment | `/sim/viewer?fragment=true` | Refresh live viewer observations or render the house overlay in the demo shell. It uses the same screen data and omits the page wrapper and its 3D canvas. |
| `집에서 일어나는 일` | `/operator` | Stage household events, act at device panels, and inspect private evidence. |
| `가전 앱 · {home}` | `/app` | Act as a person from a phone-sized appliance remote. |
| `생일 장면 소품실` | `/sim/library` | Preview the birthday look and isolated 3D props. |

[api.py](spira_simulator/api.py) serves these pages. `/health`, `/sim/snapshot`, `/sim/overlay`, and the operator JSON endpoints supply data. `/sim/stage.js`, `/sim/style.css`, `/operator/ui.js`, and `/sim/assets/house/*` supply assets.

## 3D test home

Presenters use the whole-house view to see work start, observe device changes together, and inspect a result. A household participant can select a device and act as one of the configured people when operator actions are enabled.

Open the Simulator URL at `/sim/viewer` or `/`. The launcher prints `Viewer:` and links to `집 화면` (`집과 기기의 변화를 3D로 봐요.`) on the start page. The operator's `Open household stage` link opens the same viewer. The fragment is also used by the shell, which owns its advance controls. Launcher wording comes from [demo_up.py](../scripts/demo_up.py) and [demo_start.py](../scripts/demo_start.py).

```text
+------------------------------------------------------+
| Home name                             Other homes    |
| Seoul weekday and time           Device connection  |
| +--------------------------------------------------+ |
| | Room links                    Observation legend | |
| |                 Whole-house 3D canvas            | |
| | Entrance / living room / kitchen                 | |
| | Change markers    Selected device + action pane  | |
| +--------------------------------------------------+ |
| Room observations / entrance history                |
| Unplaced waiting work / restore reports             |
+------------------------------------------------------+
```

### Layout and data

| Region, in reading order | What appears and where its data comes from |
| --- | --- |
| Home heading and peer links | The name comes from profile `display_name` or `우리 집`. Optional `집 바꾸기` links are configured by `WORLD_PEER_VIEWERS` as comma-separated `label=URL` pairs. |
| Status and clock | World `now` formats as the Seoul weekday (`월화수목금토일`, one character) and `HH:MM`. `기기 연결됨` or `기기 연결 끊김` comes from the MQTT connection. The previous gap adds ` · 마지막 끊김 {time}` from `mqtt.last_gap_at`. A failed browser refresh has a separate status above this area. |
| Canvas and room links | An oblique overview of `현관`, `거실`, `주방` labelled `현관, 거실, 주방의 입체 모형`. World display snapshot fields `devices[].values`, `observation`, and `observed_at` drive the room and device presentation through `viewer_world`. Named person figures are derived from recent World observations. The 3D TV follows `play_mood`, the oven shows `{temp_c}° · {minutes}분`, and the fridge surface displays `냉장고 안내` with the World notice. Room controls sit at the upper left. At narrow widths they reveal only the selected room's list. The room list also provides the fallback when 3D cannot open. |
| Legend, device labels, and selected explanation | `SPIRA가 설정했어요` marks a World-observed SPIRA change and `아직 실행 전이에요` keys the faint planned rows. The legend is upper right on wide views and lower right on narrow views. Resting devices use compact or suppressed value labels. Labels include observed state, any freshness warning, and the latest World change caption. Close-up overlays the selected label and the person panel on the canvas. The panel uses profile `demo_people` and eligible `device_controls`. |
| Entrance | Latest observation and time, with reverse chronological history labelled `현관 관찰 기록`. The World journal projects camera, bell, lock, and presence signals as `택배 들임`, `초인종 울림`, `문 열림 감지`, `손님 있음`, and `손님 나감`. Guest figures reflect matching arrival/departure signals, defaulting to three on arrival unless a count is observed. |
| Waiting overlays | Optional C-1 plan input supplies `tasks[].actions`, `trigger`, and guest `window`. See the [Simulator dependency note](spec.md#1-purpose-and-boundaries) for plan input wiring. Hub `GET /state` supplies `task_stories[].steps` with run outcomes and trigger evidence. A matching run outcome clears the waiting action regardless of delivery. An item notice's words appear after World observes them. The overlay carries the action label and trigger. An action for a device outside the local inventory appears below the house with `기기 · `. |
| Restore reports | `되돌림 기록` shows latest five rows and `더 보기` opens `이전 되돌림 기록` for older rows. Hub `GET /state` supplies `restoration[].packet.items[]`, packet `at`, `delivered`, and run substrate from `task_stories[].steps`. ` · 전송 대기` means Hub delivery remains outstanding. Standalone replay can use a C-4 evidence file. A restore result and the device's current World observation are independent. |

The source files are [viewer.html](spira_simulator/ui/viewer.html) and [home.html](spira_simulator/ui/home.html) for page wording, [surfaces.py](spira_simulator/surfaces.py) for device, entrance, time and overlay formatting, and [sources.py](spira_simulator/sources.py) for plan and evidence projections. [house.js](spira_simulator/ui/house/house.js) owns canvas and close-up text. MQTT commands reach World on `P/command`. The Hub discovers, reads, and observes effects on the [device protocol](protocol.md), including `P/events`. World state comes from the Simulator's own store.

### States

| Condition | What shows | Exact text | Controls available |
| --- | --- | --- | --- |
| First load | Server-rendered observations appear and the 3D view initializes on the whole house, or on a room named by a valid fragment. Already-running jobs receive markers. | Profile home name, or `우리 집` | Peer and room links, available markers |
| No entrance observations or preparation | Entrance has its room name and a title hint. The report area shows that no household preparation is scheduled. An item-only plan can still show notice rows. | `현관`, `관찰된 현관 사건 없음`, `예정된 집 준비 없음` | Room links, device actions when enabled |
| Normal or waiting | Filled values follow observations. Waiting rows show action and time or trigger. Multiple newly changed devices get markers together without camera movement. | `아직 실행 전이에요`, `택배를 들이면`, `손님 오면`, `행사가 끝나면` | Room links, marker/device selection, detail popovers |
| Selected | Room or device close-up, an observed-value callout, and applicable person actions | Marker labels `{device} · 변경 보기`, `{device} · 조작 보기`, or `{device} · 집 전체 보기`. Callout fallback `{device} · 상태가 바뀌었어요` or `{device} · 상태 보기`. Panel `누가`, `기기 조작`, `{device} · 사람 조작`, `사용할 수 있는 조작이 없어요.` | Select person or action, toggle or Escape |
| Person action in progress | Optimistic canvas reading and selected action label appear immediately. Action buttons are marked disabled for the pending device. | `집 상태 확인 중…` | Person selector, Escape, existing navigation |
| World confirms action | Matching fresh reading replaces the provisional value. The panel status updates. A named person can appear by the device for the observed six-second window. | `집 상태를 확인했어요.`, `{name} · 기기 패널` or `{name} · 가전 앱` | Action buttons re-enable |
| Fresh reading disagrees or read-back fails | On a mismatch the viewer shows the confirmed actual value. On a failed read it falls back to the last observed value. | `선택한 동작을 확인하지 못했어요.` or `집 상태를 확인하지 못했어요.` | Action buttons re-enable |
| Stale, missing, or unavailable device reading | Stale has the cached value and timestamp. Missing or unavailable has no current value. An unknown latest actor can be labelled separately on a current observation. | `오래된 관찰값 · {time}`, `관찰값 누락`, `관찰 불가`, `누가 바꿨는지 모름` | Links and available controls remain |
| Disconnection or optional source unavailable | Failed browser refresh retains the last displayed data. MQTT status and overlay-source errors are independent. | `연결 끊김 · 마지막 관찰값`, `기기 연결 끊김`, `예정 또는 되돌림 정보를 읽을 수 없음` | Existing controls remain, requests need a reachable Simulator |
| 3D initialization fails | Room observations remain as HTML and the canvas is hidden | `이 화면에서 입체 집을 열 수 없어요.` | Peer links and available HTML popovers |
| Guest window expires without a matching trigger | The waiting entry becomes an observed-outcome row when the window passes and evidence supports it | `손님이 오지 않아 실행 안 됨` | Other navigation and applicable actions |
| Run or event ends | The cleaner returns to dock after the run ends. Guest presence clears at departure. Current device values and available restore report rows show the result. | `청소 끝` or `청소 중지`, `손님 나감`, `되돌림 기록` with outcome wording below | Restoration details, markers, room and peer links |

### Device and overlay wording

[design_vocabulary.py](spira_simulator/design_vocabulary.py) supplies the shared vocabulary used by [surfaces.py](spira_simulator/surfaces.py). The [birthday profile](spira_simulator/profiles/ep_9031.json) names the house `지아네` and people `엄마`, `아빠`, `지아`, `손님`. The [family profile](spira_simulator/profiles/ep_9120.json) names the house `부모님 댁` and people `할머니`, `할아버지`, `손님`.

The birthday profile places `청소기`, `조명`, `TV`, `공기청정기`, and `에어컨` in `거실`, `인덕션`, `오븐`, `냉장고`, and `포트 플러그` in `주방`, and `스타일러` in `현관`. The family profile places `청소기` and `스피커` in `거실`, `오븐` and `냉장고` in `주방`, and uses `현관` for event observations.

| Region | Exact words or format |
| --- | --- |
| Device and room names | The profile label is preferred. `Kettle plug` is translated as `포트 플러그` and `Virtual light panel` as `조명`. Device fallbacks are `청소기`, `조명`, `TV`, `인덕션`, `오븐`, `냉장고`, `플러그`, `스피커`, `공기청정기`, `스타일러`, `에어컨`, or `기기`. Rooms use `현관`, `거실`, `주방`, `침실`. A physical tile adds `실물 기기 · 미검증`. The 3D fixed-model fallback in [devices.js](spira_simulator/ui/house/devices.js) and [vocabulary.js](spira_simulator/ui/house/vocabulary.js) uses `로봇청소기`, `거실 조명`, `전기포트 플러그` for those three devices. |
| Light and TV | Light `꺼짐`, `분홍 빛`, `주황 빛`, `노랑 빛`, `초록 빛`, `파랑 빛`, `보라 빛`, `흰 빛`, `따뜻한 빛`. Kelvin below 4000 reads warm in the house and `{kelvin}K` on the appliance page. A saturation of zero reads white. TV `공주 화면`, `파티 화면`, `잔잔한 화면`, `영화 화면`, `화면 켜짐`, or `꺼짐`. |
| Other observed values | Oven `{degrees}° · {minutes}분 · 대기`, `굽는 중` with available temperature and `{minutes}분 남음`, `다 구움`, `굽기 중지`, or `꺼짐`. Fridge `평소 화면` or observed notice text verbatim. Cleaner `대기 중`, `청소 중`, `청소 끝`, `청소 중지`. Cooktop `사용 중`, `잠금`, `잠금 해제`. Speaker `잔잔한 음악`, `파티 음악`, `가족 모임 음악`, or `음악 재생`, with ` · 볼륨 {volume}`, or `재생 안 함`. Purifier `자동`, `터보`, `취침`. Air conditioner `꺼짐`, `냉방`, `난방`, `자동`, with ` · {temperature}℃` when available and on. Styler `표준 코스 대기`, `울케어 코스 대기`, `코스 대기`, or `대기 설정 없음`. Other boolean power values use `켜짐` and `꺼짐`. |
| Planned values and details | `{room} 청소`, named scene or color from above, `색조 {hue}° · 채도 {saturation}% · 밝기 {brightness}%`, `{kelvin}K`, `{degrees}° {minutes}분 굽기 대기` (minutes optional), named playlist with optional volume, `{mode} 모드`, or `{course} 코스 대기`. Command fallbacks are `청소`, `조명 색상 변경`, `색온도 변경`, `분위기 화면`, `끄기`, `잠금`, `굽기 설정 대기`, `안내 표시`, `음악 재생`, `정지`, `운전 모드 변경`, `코스 설정 대기`, or `기기 동작`. An invalid clock string formats as `시각 확인 불가`. Guest windows add `{HH:MM}–{HH:MM}` with detail `이 시간 안에 손님이 오면 켜져요. 지나면 실행하지 않아요.`. |
| Restore | `되돌림`, `되돌릴 값 없음`, `바뀐 값 유지`, `되돌리기 실패`, `되돌림 확인 불가`, `종료 미관찰로 잠금·차단 유지`. Rows add `실물 기기 · 미검증` or `전송 대기` when applicable. |

### Controls, accessibility, and motion

| Control | Request or local input | Immediate response and confirmation |
| --- | --- | --- |
| Peer-home link | Browser GET to configured URL | Navigates to that viewer. |
| Room link | Sets `#viewer-room-{room}` in the same page | Frames the room, marks link `aria-current="location"`, and scrolls to the room observations. |
| Change marker or eligible canvas device | Local selection, no request | The view moves in and opens the callout. Where person actions are enabled the adjacent panel opens and focuses the selector. Selecting again returns to overview. Escape returns and focuses the marker. Shell advance closes the focused view through the shared house module. |
| Entrance summary and history | Hover or keyboard focus within entrance card | Shows the stored history, with no request. |
| Notice or waiting detail | Native popover, no request | Opens the full notice or detail text. Native outside click or Escape dismisses it. |
| `더 보기` / `닫기` | Native restore popover, no request | Opens or hides older rows. |
| `누가` | Writes `spira.house.person` to browser local storage when available | Selects the actor for the next action. The birthday house defaults to `엄마` unless a valid saved name is available, and other profiles fall back to their first person. |
| Person action button | `POST /operator/person?target={target}` with URL-encoded form fields `person`, `control`, and `Accept: application/json`. On `{"applied":true}`, standalone follows with `GET /sim/snapshot`. | Paints immediately, then compares a same-epoch, available `current` reading against the requested values or running job. The panel distinguishes confirmation, mismatch, and failed read. Hub observes the resulting World change over MQTT. The fragment advertises the action endpoint for a configured shell origin. |

The viewer uses native buttons and links, so Tab reaches the available markers and popovers and Enter or Space activates a button. Marker and action buttons keep Space from triggering a surrounding shell shortcut. Refresh preserves the canvas and attempts to restore focus by ID and reopen matching notice and waiting popovers. Camera and cleaner motion snap to a static position under reduced motion, entrance/person and decorative motion use their reduced-motion poses, and the viewer reveal animation is removed. The renderer still paints observed state and lighting. [stage.js](spira_simulator/ui/stage.js), [person-actions.js](spira_simulator/ui/house/person-actions.js), [house.js](spira_simulator/ui/house/house.js), [viewer.css](spira_simulator/ui/house/viewer.css), and [house.css](spira_simulator/ui/house/house.css) implement this.

The panel has no fixed delay for action feedback or confirmation. The POST has a five-second timeout and the standalone snapshot read an eight-second timeout. The viewer refreshes its HTML observations after one second and schedules one second after each attempt ends. The refresh timeout is eight seconds.

### Acceptance

[SIM-AT-01, SIM-AT-09, SIM-AT-10, SIM-AT-16, SIM-AT-18–20, SIM-AT-22–23, and SM-AT-1–5](spec.md#3-acceptance-catalogue) apply to independent World, observed values, waiting and restore overlays, privacy, and the change/person controls. [test_stage_and_judge.py](tests/test_stage_and_judge.py) checks both configured households, observation projection, guest windows, notices, and restore outcomes. [test_world.py](tests/test_world.py) checks isolation, persistence and read faults. [test_mqtt.py](tests/test_mqtt.py) checks MQTT gap evidence. [house.test.mjs](tests/house.test.mjs), [scene.test.mjs](tests/scene.test.mjs), and [room-views.test.mjs](tests/room-views.test.mjs) check camera, markers, readings and people. [test_person_integration.py](tests/test_person_integration.py) tests the light, music, and cleaner actions and the Hub attribution path to the fixture. The running cleaner stops and reports an interrupted run as `unknown`. The old expected card assertion remains an expected failure.

**Not covered by a test.** Browser refresh loss and recovery, rendered MQTT gap text, WebGL failure fallback, the full native popover/focus path, and live Server end-to-end acceptance. The shell owns the advance-to-overview integration.

### Shared named device actions

The viewer and backup operator use the panel controls. The appliance page uses the same control keys except the panel-only fridge action. [surfaces.py](spira_simulator/surfaces.py) builds the list from virtual device commands, writable property schemas, and job configuration. [design_vocabulary.py](spira_simulator/design_vocabulary.py) supplies the interpolated state and scene words. A button appears only where the target accepts its values. The browser sends the control key and person. The server expands that key to the following World values.

| Device or capability | Control key and button text | World action |
| --- | --- | --- |
| Light color | `color_pink` `조명 색 바꾸기 · 분홍 빛`, `color_yellow` `조명 색 바꾸기 · 노랑 빛` | `color: {hue: 330 or 55, saturation: 60, brightness: 70}` |
| Light temperature | `kelvin_2700` `2700K로 변경`, `kelvin_4000` `4000K로 변경`, `kelvin_6500` `6500K로 변경` | `color: {kelvin}` |
| Display scene | `kids_party` `공주 화면 켜기`, `party` `파티 화면 켜기`, `calm` `음악 바꾸기 · 잔잔한 음악`, `cinema` `영화 화면 켜기`, `display_off` `끄기` | `play_mood: {scene}` or `null` |
| Power | `power_on` `켜기`, `power_off` `끄기` | `power: true` or `false` |
| Cooktop lock | `lock` `잠그기`, `unlock` `잠금 해제` | `child_lock: true` or `false` |
| Cleaner | `clean` `청소 시작`, `stop_clean` `청소 중지` | `clean: {room}` using the configured room's label, or `clean: null` |
| Speaker | `play` `가족 모임 음악 재생`, `music_calm` `음악 바꾸기 · 잔잔한 음악`, `stop` `음악 정지` | `play: {playlist: "family" or "calm", volume: 30}` or `play: null` |
| Purifier | `auto` `자동`, `turbo` `터보`, `sleep` `취침` | `mode` equals the control key |
| Air conditioner | `off` `에어컨 꺼짐`, `cool` `에어컨 냉방`, `heat` `에어컨 난방`, `auto` `에어컨 자동` | `mode` equals the control key |
| Styler | `standard` `표준 코스 대기`, `wool_care` `울케어 코스 대기`, `clear_course` `대기 설정 해제` | `course_standby: {course}` or `null` |
| Oven | `start` `굽기 시작` | `start: true` with no property values |
| Fridge | `open_door` `문 열기` | `door_open: true` on the panel path |

### House observation fragment

`GET /sim/viewer?fragment=true` serves the same World, plan and Hub observations through [home.html](spira_simulator/ui/home.html). It starts at the clock and MQTT status, followed by room observations, entrance history, and reports. The standalone viewer takes only its live regions from this response. The demo shell uses it as input to its own house renderer. The state text, data provenance and local popovers are the same as above. The embedded keyboard path, camera, failure banner, and advance controls belong to the host. For configured embedding, `WORLD_HOUSE_SHELL_ORIGIN` supplies the exact allowed origin and the marker block includes the Simulator's person endpoint. [test_stage_and_judge.py](tests/test_stage_and_judge.py) checks the fragment for SIM-AT-19–20. [test_person_integration.py](tests/test_person_integration.py) checks the action endpoint metadata for SIM-AT-22.

**Not covered by a test.** Browser fragment-refresh failure and recovery in the host.

## Household operator

A presenter uses the top controls to stage deliveries, guests, and event end. A participant can use the named device-panel actions as a backup. Developers use the remaining controls to inject observations and compare evidence.

Open `/operator` or use the launcher line or start-page link `집에서 일어나는 일` (`택배를 들이고 손님을 맞이해요.`). Operator access, including its APIs and the appliance app, requires `WORLD_OPERATOR=1`. The launcher's Simulator factory accepts a bind address. Exactly `127.0.0.1` allows access without credentials. Otherwise the browser prompts for HTTP Basic user `operator` and the configured token. Disabled access returns `Operator disabled`. A failed credential check returns `Operator credentials required` and challenges with realm `SPIRA operator`. [api.py](spira_simulator/api.py), [demo_simulator.py](../scripts/demo_simulator.py), [demo_up.py](../scripts/demo_up.py), and [demo_start.py](../scripts/demo_start.py) define access and launcher wording.

```text
+--------------------------------------------------------+
| Household events                                       |
| Package + time | Guests + window and time | End + time |
| Household operator / household ID / viewer / remote    |
| > Device substrate and panel reporting                 |
| Person actions / v first person / > other people       |
| Home events | Device action form | Faults              |
| Status                                                 |
| Private evidence / JSON output                         |
| Hub command counts / marker / time range / JSON output |
+--------------------------------------------------------+
```

### Layout and data

| Region, in reading order | What appears and where its data comes from |
| --- | --- |
| Household events | `집에서 일어나는 일` and enabled actions for profile `home_signals` and `home_action_labels`. [profile.py](spira_simulator/profile.py) defaults to `택배 들이기`, `손님 도착`, and `파티 끝`. Under each, World supplies the last matching journal occurrence, its Seoul time and a label from the viewer's entrance vocabulary. An unrecognized observation uses `집에서 변화를 감지했어요`. |
| Guest window below guest control | `손님 맞이 {HH:MM}–{HH:MM}` from the latest-starting configured plan window, through `GET /operator/guest-window → label, detail`. World clock and matching arrival truth determine its detail. |
| Operator header and inventory | `Household operator`, profile household ID, `Open household stage`, `Open appliance app`. Disclosure `Device substrate and panel reporting` lists logical device ID, `Physical (unqualified)` or `Virtual`, and `Class A (panel reporting assumed)` or `Class B` from installed profile fields. |
| Named panel actions | `Person actions` within `Named person controls`. One disclosure per profile `demo_people` name, first open. Form buttons say `{person} · 기기 패널 · {device} {action}` using the [named action table](#shared-named-device-actions). |
| Generic controls | `Home events`, `Device action`, and `Faults` fill from `GET /operator/options` fields `home_actions`, `actors`, and `devices[]`. Selectors list virtual devices only. Device controls use the selected target, editable property names, and whether it supports a local job start. |
| Evidence | `Private evidence` shows raw JSON from the World journal, operator snapshot, or C-3 judge. The judge compares World truth with Hub `GET /state` `events[].packet`, `delivered`, and `delivery_error`. Hub mode compares delivered records and lists pending records separately. A standalone evidence run can supply fixture receipts. `Hub command counts` uses the World command-arrival journal and marker or explicit time range. |

[operator.html](spira_simulator/ui/operator.html) and [operator.js](spira_simulator/ui/operator.js) own labels and interactions. [surfaces.py](spira_simulator/surfaces.py) and [design_vocabulary.py](spira_simulator/design_vocabulary.py) supply device, event, and window words. [sources.py](spira_simulator/sources.py) projects judge evidence, and [world.py](spira_simulator/world.py) owns actual effects and private truth.

### States

| Condition | What shows | Exact text | Controls available |
| --- | --- | --- | --- |
| First load | The server renders event status, inventory, and named controls. Generic selectors populate after the options read. First person's disclosure is open. | `집에서 일어나는 일`, `Household operator`, `Person actions` | Named and top events are available where configured. Generic choices arrive with options. |
| Empty | No timestamp before a matching event. No named section if there are no people. No top section if no labelled action is configured. Guest window and evidence outputs start blank when no data applies. | `아직 관찰된 일이 없어요` below any unused top control | Other configured controls |
| Normal | Latest event time and observation. Before or during the guest window, its explanation appears. A missed window replaces the explanation. | `{time} · {observation}`, `이 시간 안에 손님이 오면 켜져요. 지나면 실행하지 않아요.`, `손님 맞이 시간이 지났어요` | All applicable controls |
| In progress | Top buttons disable together and prior error clears. Evidence fetch clears its own JSON output. Named actions use normal form navigation. | No new waiting text | Other controls stay enabled during a top event |
| Confirmed | Top row uses the response observation and time. Generic request success is acknowledged in the status line. Named actions redirect to the refreshed operator. | `{time} · {observation}`, `Operator action recorded` | Top buttons re-enable and focus returns to the initiating button |
| Failed | Top controls retain the last recorded occurrence. Generic controls show HTTP detail or client error. Named form errors render FastAPI's response. | `집에서 일어난 일을 기록하지 못했어요. 다시 눌러 주세요.`, `Request failed ({status})`, `이 화면에서 기기를 조작해 주세요`, or `사용할 수 없는 기기 조작입니다` as applicable | Top buttons re-enable. Use browser Back after a failed form navigation. |
| Disconnected or stale | A guest-window polling error preserves the previous label and detail. Other failed requests surface on use. The page has no general connection banner. | Prior guest-window words, or request error text | Controls remain, requests need a reachable Simulator |
| End of run | The `파티 끝` action records its configured end signals. Its latest observation time and the private evidence remain visible or refreshable. | `파티 끝`, typically `{time} · 손님 나감` with the bundled profiles | Same event, device and evidence controls |

### Controls, accessibility, and motion

| Control | Request or local input | Immediate response and confirmation |
| --- | --- | --- |
| `택배 들이기`, `손님 도착`, `파티 끝` | `POST /operator/home` JSON with `action` set to `delivery`, `guests_arrive`, or `event_end`. A profile may configure other labelled actions. | Disables the top row during the request. Response `applied`, `occurred_at`, `at`, and `observation` updates the clicked row only. The lower `Bring package inside`, `Guests arrive`, and `Event ends` buttons send the same request and report status in the lower panel. |
| Header links and disclosures | GET `/sim/viewer` or `/app`. Native inventory and person disclosures toggle locally. | Browser navigates or shows/hides the selected group immediately. |
| Named panel control | Form POST `/operator/person?target={target}` with `person` and `control` | Normal form submission. A successful World write records the named person and `device_panel`, then a 303 reloads `/operator`. |
| `Device`, `Actor`, `Display name (optional)`, `Action path`, and `Property values (JSON)` | Local field edits. Device selection changes available quick buttons and lists editable keys with underscores shown as spaces. Actor defaults to `resident`. Name and path are shown for `resident`, `child`, or `guest`. Path choices are `Device panel` (`device_panel`) and `Other app` (`other_app`). | Visible options update on change. JSON starts at `{}`. No World action until submitted. |
| `Apply property values`, `Set warm white`, `Start oven` / `Start job`, and `Open fridge door` | JSON `POST /operator/device` with `target`, `actor`, `values`, and `start`. For people also `actor_name` (trimmed or null) and `action_path`. Quick values are `{color: {kelvin: 2700}}`, `{}` with `start: true`, or `{door_open: true}`, respectively. | Locally parses JSON for manual writes. World response confirms recording or shows the error. Device state is visible in the viewer or snapshot. |
| Fault selectors and `Apply fault mode` | `POST /operator/fault` JSON `{target, fault, mode}`. `link:offline` / `link:online` are `Device offline` / `Device online`. `command:reject` / `command:unchanged` / `command:clear` are `Reject next command` / `Accept next command without changing state` / `Clear command fault`. `readback:stale` / `readback:missing` / `readback:unavailable` / `readback:current` are `Stale readback` / `Missing readback` / `Unavailable readback` / `Resume current readback`. | Fault selection alone is local. `applied: true` records the requested arm or availability change. A subsequent command or observation shows the fault's effect. |
| `Refresh truth journal`, `Refresh operator snapshot`, `Read received C-3 and compare` | GET `/operator/truth`, `/operator/snapshot`, or `/operator/judge` | Clears evidence output and prints the response JSON. Judge can return `Received C-3 source is unconfigured` or `Received C-3 source unavailable or invalid`. |
| `Set command marker`, `Count Hub commands` | POST `/operator/judge/marker` with `{}`, or GET `/operator/judge/commands` with optional `start` and `end` from `Start (ISO 8601 with offset)` and `End (ISO 8601 with offset)`. Hint is `Leave both times blank to count since the marker.` | Clears then populates command evidence with a marker or counts. Range includes start and excludes end. Errors include `Provide both start and end, or use the marker`, `End must be later than start`, and `Set a command marker or enter a time range`. |

Tab reaches links, native disclosures, buttons and labelled inputs, and Enter or Space activates a button or disclosure. Focus rings, a polite per-event observation, the live guest detail, and live evidence regions are provided. Top controls explicitly restore focus after submission. There is no custom key binding, page motion, or fixed confirmation delay. The guest window polls after two seconds and schedules its next read two seconds after the previous attempt. The lower controls and evidence update on user action. [style.css](spira_simulator/ui/style.css) defines layout and focus.

### Acceptance

[SIM-AT-02, SIM-AT-05, SIM-AT-09, SIM-AT-16, SIM-AT-18, SIM-AT-21, and SM-AT-3](spec.md#3-acceptance-catalogue) cover private attribution, faults, home and device actions, and substrate. [test_stage_and_judge.py](tests/test_stage_and_judge.py) checks authentication, Korean home controls, guest windows, named panel forms, judge input and outputs, and counts. [test_world.py](tests/test_world.py) checks the fault and device effects, and [test_person_integration.py](tests/test_person_integration.py) checks the observed action and resulting C-3 receipt through the fixture.

**Not covered by a test.** Top-row disabled state, focus restoration, generic JavaScript form and evidence interactions, and guest-window preservation after a failed browser poll are untested as screen behavior.

## Appliance app

A participant uses this phone-sized remote to change a household device through the simulated other-app path. Developers can compare its observation with the same action from a device panel.

Open `/app` or the operator's `Open appliance app` link. It uses the same access policy as the operator and has no launcher line or keyboard shortcut. On a second phone use the Simulator's reachable host and port. A valid `?person={name}` selects that person initially.

```text
+------------------------------+
| Appliance app / home         |
| Actor selector               |
| Connection warning if needed |
| Device                    Room|
| Observed state / freshness   |
| Action buttons               |
| Next device                  |
+------------------------------+
```

### Layout and data

| Region, in reading order | What appears and where its data comes from |
| --- | --- |
| Heading and person selector | `가전 앱 · {home}`, with profile `display_name` or `우리 집`. `조작하는 사람` lists profile `demo_people`. Defaults to `아빠` if present, otherwise the first person. |
| Connection warning | `연결 끊김 · 마지막 관찰값` appears if refreshing this page fails. |
| Device cards | Device name and room from profile and vocabulary. Current value and observation quality come from World `snapshot(for_display=True).devices[]`. Device words match the [viewer vocabulary](#device-and-overlay-wording), with Kelvin shown as `{kelvin}K`. A stale reading shows the stale label without a timestamp here. |
| Device buttons | Available [named actions](#shared-named-device-actions) below each value. The profile and writable device fields decide eligibility. The fridge door action is panel-only. |

[appliance.html](spira_simulator/ui/appliance.html) owns page text. [api.py](spira_simulator/api.py) selects the person and assembles the page with [surfaces.py](spira_simulator/surfaces.py). [stage.js](spira_simulator/ui/stage.js) refreshes the value regions only.

### States

| Condition | What shows | Exact text | Controls available |
| --- | --- | --- | --- |
| First load | The response contains the populated device list and defaults the actor | `가전 앱 · {home}`, `조작하는 사람` | Selector and eligible buttons |
| Empty or read-only | No actor selector or buttons without profile people. Empty inventory leaves the heading. Devices with no supported actions have no buttons. | No separate empty-state copy | Remaining controls, if any |
| Normal | Device value and eligible commands | For example `평소 화면`, `대기 중`, `켜짐` or `꺼짐` | Selector and buttons |
| Change in progress | Browser submits a form and keeps its normal navigation behavior | No custom pending text | Native navigation |
| Confirmed | Successful form submission redirects with the submitted person selected. The page shows the latest World reading. | The observed value, with no separate success text | Selector and buttons |
| Failed | Form response is FastAPI error JSON. There is no optimistic value to roll back. | `이 화면에서 기기를 조작해 주세요` or `사용할 수 없는 기기 조작입니다` for the specific validation errors | Browser Back to controls |
| Disconnected, stale, missing, or unavailable | Browser failure retains the visible values. Device faults appear per card on a successful fetch. | `연결 끊김 · 마지막 관찰값`, `오래된 관찰값`, `관찰값 누락`, `관찰 불가` | Selector and buttons, with submission requiring connection |
| End of run | The device card replaces the running text when World reports completion or stop. The app stays on the device list. | `청소 끝`, `청소 중지`, `다 구움`, or `굽기 중지` as applicable | Selector and buttons |

### Controls, accessibility, and motion

- Change `조작하는 사람` locally. The selection is submitted with the next device action. Value refreshes keep the selector and buttons mounted.
- Click an action button or reach it with Tab and activate with Enter or Space. It sends form fields `person` and `control` to `POST /app/device?target={target}`. World records the named person via `other_app` with `local_operation: false`. The 303 returns to `/app?person={name}`. It confirms the write and renders a World observation, with any reading fault surfaced separately.
- Inputs are native, labels are associated, focus is visible, and the connection warning is a status region. There is no custom keyboard shortcut, focus transfer, page animation, or fixed action delay. The shared stage script refreshes values about one second after each completed poll and times out a fetch at eight seconds. [style.css](spira_simulator/ui/style.css)

### Acceptance

[SIM-AT-21](spec.md#3-acceptance-catalogue) covers named panel and other-app signals and truth. [test_stage_and_judge.py](tests/test_stage_and_judge.py) checks the Korean page, selected person and action path. [test_world.py](tests/test_world.py) checks shared World job and freshness states.

**Not covered by a test.** No-people and empty-inventory rendering, browser refresh loss and recovery, keyboard submission, and focus after the redirect are untested as screen behavior.

## Birthday prop library

Presenters and developers use the library to preview the birthday scene, compare isolated props, and replay house motion with sample readings.

Open `/sim/library` directly. Public access uses no operator login. There is no launcher link or global keyboard shortcut.

```text
+--------------------------------------------------------+
| Prop library                 House / shelf links        |
| Load failure, when applicable                          |
| Birthday house              Camera / replay controls   |
| Sample light status         Light off                  |
|                         3D preview                     |
| Prop shelf                                             |
| Sample A / options | Sample B | Sample C / options      |
+--------------------------------------------------------+
```

### Layout and data

| Region, in reading order | What appears and where its data comes from |
| --- | --- |
| Header | Page title `생일 장면 소품실 · SPIRA`, heading `생일 장면 소품실`. Navigation named `미리보기` has `집 안에서` and `소품 선반`. |
| House and controls | `지아네 생일 준비`, groups `카메라 시점` and `움직임 재생`, with camera buttons `집 전체`, `거실 가까이`, and `식탁 가까이`. Replay buttons come from motion entries in `slots.json`. |
| Sample reading | `거실 조명 예시 상태 {status} · 천장 간접조명은 이 상태를 따릅니다.` and `조명 끄기`. Browser-local sample light and display readings, separate from the decorative scene. |
| Stage | Birthday balloons, garland, hats, cupcake toppers, strawberry and cream packs, castle artwork on the TV, and sample guests. Accessible label is `풍선과 생일 가랜드, 분홍 성이 나오는 TV, 컵케이크와 고깔모자가 놓인 식탁이 보이는 지아네`. `library-scene.js` supplies props, readings, camera settings, and artwork. `library.js` supplies a three-guest sample. |
| Shelf | `소품 선반`. Each card renders a local slot sample, Korean label, ID, and options where configured. [slots.json](spira_simulator/ui/house/slots.json) provides names and parameters. |

[library.html](spira_simulator/ui/library.html) supplies headings, accessible labels, the initial light status and load error. [library.js](spira_simulator/ui/house/library.js) supplies option labels and interactive text. [library-scene.js](spira_simulator/ui/house/library-scene.js) and [slots.js](spira_simulator/ui/house/slots.js) supply local content. The library has no World, MQTT, or Hub input.

### States

| Condition | What shows | Exact text | Controls available |
| --- | --- | --- | --- |
| First load | Static headings and camera buttons appear while slot data initializes. Stage and shelf are initially empty. | `지아네 생일 준비`, `꺼짐`, `소품 선반` | Page anchors work immediately. Preview handlers attach on initialization. |
| Empty shelf or no motion entries | No cards or replay buttons for an empty collection | No extra empty text | Other controls that initialized |
| Normal | Whole-house birthday sample, light off, rotating visible shelf samples | `집 전체`, `거실 조명 예시 상태 꺼짐 · 천장 간접조명은 이 상태를 따릅니다.` | Camera, replay, light, shelf selectors and navigation |
| Change in progress | Scene motion paints in the stage. Light state changes locally and a marker appears immediately. | `켜짐 · 분홍색` for the light replay | Same controls |
| Confirmed | Camera selection exposes a pressed state or the sample takes the new local reading. The light marker can open a close-up. | `켜짐 · 분홍색` or `꺼짐` | Same controls, light marker |
| Failed or disconnected at setup | An HTTP, scene, or 3D setup exception reveals the alert. A partial setup can remain visible. | `3D 미리보기를 불러오지 못했습니다.` | Anchors and any initialized controls |
| Disconnected after setup | The loaded sample stays local. There is no network-staleness status for the running preview. | Current sample text | Initialized controls |
| Motion ends | The sample settles. Light state remains until another control changes it. `조명 끄기` restores the off reading and base scene. | `꺼짐` after explicitly switching off | Replay, camera, light and shelf controls |

### Controls, accessibility, and motion

| Control | Request or local input | Immediate response and confirmation |
| --- | --- | --- |
| `집 안에서`, `소품 선반` | Native `#house`, `#shelf` links | Jump to the corresponding section. |
| `집 전체`, `거실 가까이`, `식탁 가까이` | Local camera selection | Instantly sets the view and updates the selected button's `aria-pressed`. |
| `거실 청소 동선`, `손님 입장`, `무드등 빛 퍼짐` | Replays a local motion slot or sets sample arrival. Light replay sets `light_01` to the pink reading first. | Scene animates, sample guests enter, or light switches on with its floor effect. Light replay resets the camera and shows a light marker. |
| `조명 끄기` | Sets sample `light_01.power` false and reapplies base scene | The stage switches off the light, resets the camera and shows the light marker. |
| Light marker or selected light | Local close-up shared with the viewer | Displays sample reading. Reselect or Escape returns to the overview. |
| Shelf selects | Local slot parameters | Replaces only that card's sample. `색과 배치` offers `분홍·흰색·금색 다발`, `바닥 풍선`, `분홍 다발`, `파랑 다발`, `노랑 다발`. `배치` offers `냉장고 선반` and `조리대` on both pack cards. `머리 모양` offers `단발`, `곱슬머리`, `짧은 머리` on the child guest card. `벽 장식` offers `가랜드` and `그림`. |

Shelf labels from [slots.json](spira_simulator/ui/house/slots.json) are `풍선 다발`, `고깔모자`, `왕관 장식 컵케이크`, `딸기 팩`, `휘핑크림 팩`, `생일 주인공`, `어린이 손님`, `보호자`, `꽃종이 팡`, `천장 간접조명`, `벽걸이 가랜드`, `거실 청소 동선`, `손님 입장`, and `무드등 빛 퍼짐`.

The initial slot fetch is `GET /sim/assets/house/slots.json`; the preview also loads static art. Control input is local and has no fixed wait before feedback. Tab reaches native links, buttons, and selects, with visible focus and labels. The sample light is a polite live status, the setup error is an alert, and the prop canvases are hidden from assistive technology in favor of their labelled cards. Reduced motion stops shelf rotation and samples a static pose, and house camera and motion follow the shared reduced-motion behavior. [library.js](spira_simulator/ui/house/library.js), [library.css](spira_simulator/ui/house/library.css), [house.js](spira_simulator/ui/house/house.js)

### Acceptance

[SM-AT-2 and SM-AT-4](spec.md#3-acceptance-catalogue) apply to the shared camera/marker behavior and content boundary. The library has no dedicated acceptance ID in the team specification. [test_library.py](tests/test_library.py) checks route access, markup, assets and slot schema. [scene.test.mjs](tests/scene.test.mjs) and [slots.test.mjs](tests/slots.test.mjs) check sample values, look, motions, artwork, and camera framing.

**Not covered by a test.** Browser setup-failure alert, shelf selector interactions and focus, and the end of an actual rendered replay are untested as screen behavior.
