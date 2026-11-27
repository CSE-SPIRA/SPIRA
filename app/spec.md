# App product specification

Status: ACTIVE. This document owns App behavior and acceptance. Shared HTTP
bodies, enum values, identifiers, and time rules remain under
[contracts](../contracts/README.md). The App MUST use generated contract models.

The [screen reference](screens.md) describes each screen, its states, words,
data and controls.

## 1. Purpose and boundaries

**P-R1.** The App MUST center on one preparation's lifecycle, from an order
capture through execution, intervention, and memory. Main, Calendar, and Our
Home MUST be the three tabs after first-run onboarding. No plan approval is
required. (PC-1, PC-3, PC-5, PC-6)

**P-R2.** The App MUST use the Server for household, order, preparation, and
memory data. It MUST make zero requests to the Hub or Simulator. Google
Calendar is read on the phone. A command receipt MUST NOT be shown as a
confirmed effect. (PC-4, PC-5)

**P-R3.** The App MUST support both the real Server and the contract fixture Server at
`hub/tests/fixture_server`. Developer builds (`SPIRA_DEV_TOOLS=1`) running
against that fixture MUST be visibly labeled. (PC-4)

## 2. Requirements

### A1. Main lifecycle

Main MUST keep the order above the preparation area. Both areas remain in
place as Server state changes. Up to two cards for the same order can appear
together. Only Server-issued cards can appear. The presentation shell MUST
embed the App's actual web build when it shows the App.

| ID | Required presentation | Contract source |
| --- | --- | --- |
| M1 | The App MUST accept one to three ordered images from Android share or the gallery. Each selection MUST have one stable `source_id` for retry. After acceptance, show the submitted thumbnails and `받았어요`. | `POST /v1/orders`, `received` |
| M2 | While the shared order is being processed, the order area MUST show a loading panel (an activity indicator, one line naming the stage in progress, and a progress bar that moves only when a stage is stored) and, below it, one short line per stored stage that fades in when that stage is stored. Upcoming stages MUST NOT be listed. Reduced motion MUST render the panel and lines without animation. | Episode and rationale detail |
| M3 | The order area MUST show names and quantities, plus only a count for masked items. Read failure MUST prompt the user to send again. | Episode `items`, `item_count`, `masked_count`, `read_failed` |
| M4a | The order MUST remain visible with an empty preparation area when no card was produced. In the full order, the App MUST show each item task under the first item of its type, with a label for its kind, the Server text, and its state. Scheduled guidance MUST say when it will appear and completed guidance MUST say where it was shown. | Episode `judged`, empty `card_ids`, `item_tasks[].item`, `kind`, `text`, `state` |
| M4b | A held card MUST show the Server's text verbatim. | Episode `held`, card held template |
| M5 | With a card present, the order MUST default to one tappable row with a thumbnail, item count, first visible item and remaining count, and a chevron. Tapping MUST reveal or hide the full order. A preparation card MUST show the Server's text verbatim, schedule, timed or triggered lines, progress, and applicable controls. The App MUST deduplicate local notifications by `card_id` and `updated_at`, and honor `notify` for new and newly timed cards. | Card poll `text`, `starts_at`, `lines`, `summary`, `notify` |
| M6 | The App MUST show each supplied line state distinctly, including the Server's note and any awaited event. | Card poll `lines[].state`, `note`, `summary.waiting_for` |
| M7a | Line off MUST remain available while a line runs. Line on MUST be available only before start. A 409 indicating start MUST remove that control. Stop applies only to its card. Accepted requests MUST remain pending until refreshed card state confirms the change. A reaction 404 MUST show one message, `아직 이 서버에서는 끌 수 없어요`, and restore the control without retrying. | Card `line_off`, `line_on`, `stop` reactions |
| M7b | A human change MUST show the changed state and Server note. A person-started standby task uses the Server's resulting state. | Card `user_changed`, `note`, `done` |
| M8 | The App MUST show the supplied restoration outcome and note per line. | Card `lines[].end_state`, `note` |
| M9 | When the observation window closes, the card MUST become a memory sheet with the intent, lines and states, verdict, and task feedback. | Episode rationale `intents[].intent_text`, `tasks`, `observations` |
| M10 | At episode close, live cards MUST leave Main and the latest memory sheet MUST stay until the next accepted order or acknowledgment. Calendar MUST keep the closed episode marker regardless of acknowledgment. | Episode `closed`, last card update, episode history |

The App MUST use the card poll's `server_time` cursor, reconcile cached cards
with the Server after startup or reconnect, and avoid inventing a planned
end condition. Poll every 30 seconds, with a three-second foreground cadence
during active preparation or intake. Show the last known state and a connection
notice while reads fail.

The App MUST poll the shared episode and its rationale during intake. It MUST
show the item count and list when S1 items are present, the calendar and past
order check when S2 rationale is available, and the Server's short intent text
when S3 intents are present. A rationale 404 before S2 is expected. Changes
MUST follow stored data, with no timed advancement. The preparation card
replaces the progress block when it arrives.

If the household episode list returns 404, 405, or 501, card refresh MUST
continue using episode detail for the open cards, the newly shared order, and
previously seen episodes. The App MUST defer retrying the list until a later
poll interval. Calendar MUST retain markers for episodes observed closing.

Memory MUST render `match`, `stopped`, and `unconfirmed` distinctly, and
`off`, `changed`, and `kept` as per-line results. If no observation is
available, show that the verdict is pending. The App MUST exclude evidence,
KB comparisons, unusual items, unbundled items, and explanatory prose.

### A2. Calendar

Calendar MUST show a month grid with month navigation and a today marker.
Event bars MUST carry labels. Memory dots MUST appear on their dates. Selecting
a day MUST list its events and memories. Selecting a memory MUST open the
same sheet as M9, including purchased items, masked count, and start/end times
when supplied. Preparation plans remain on Main.

The App MUST read the next 14 days of Google events on the phone. A connected
Google calendar MUST replace the samples, including when it has no events.
While Google is disconnected, Calendar MUST show `예시 일정` and the App MUST
send those same events with `PUT …/calendar`. Fixture and preview use the
bundled replay dates. With `SPIRA_PEER=server`, the App MUST anchor a one-hour
birthday 20 minutes after the cards response's `server_time` and put ordinary
events on later days. It MUST persist the sample anchor for the household.
It MUST send the sample once on opening the household and only replace it when
the birthday has ended or starts in less than 10 minutes and there is no open
card. It MUST send no sample while Google is connected.

Calendar MUST use the household episode listing when available and known
closed episodes otherwise. It MUST date a
closed episode in the household time zone using the last observed card
`starts_at`, with `shared_at` as the fallback for a card the App never saw.
A card seen only in the held state has no marker. The App MUST reconstruct the
sheet from episode detail and rationale without cached card bodies.

### A3. Our Home and onboarding

Our Home MUST show editable household types via `PUT …/profile`, Google
connect/disconnect, and the device list on one page. Until the App device
routes exist, Our Home and onboarding MUST show the fixed demo inventory
from the example Hub installation, labeled `예시 집`. It MUST show only rooms with devices, grouped by
room, with a name and type icon per device. Each delegation control MUST remain
disabled and labeled `집 연결 후`. The App needs a Server device list including
rooms and a Server write route for per-device delegation. The Hub needs that
delegation before execution.

Our Home MUST match open card lines to devices through
`GET /v1/episodes/{id}/rationale`, using the task's card and task identifiers
and its `devices` identifiers, types, and rooms. The row MUST display the card
line's text and state and use the card's `line_off` reaction when available.
Onboarding MUST show the device list read-only. `SPIRA_HOUSEHOLD_ID` MUST
open an existing household directly, including one created by the Server's demo
home script. `SPIRA_FIRST_RUN=1` MUST start at Welcome with no household,
even when a household is configured or setup was previously completed. Opening
a household MUST require only the Server connection.

| ID | Requirement |
| --- | --- |
| ON-1 | First-run Setup MUST open with the larger SPIRA mark, `온라인 주문을 보고, 그날에 맞춰 집을 미리 준비해요.` and `시작하기`. The next four steps MUST show progress from `1 / 4` (Google) through `가구 유형`, the connection code and `집 기기 확인` (`4 / 4`). |
| ON-1a | With a Google client, step 1 MUST show `Google 계정으로 시작`, `앞으로 14일의 일정을 참고해 준비할게요.`, `Google로 계속` and `건너뛰기`. Without a client, step 1 MUST offer only `건너뛰기`. Canceling MUST leave the Google step visible with no error. Other sign-in or authorization failures MUST show `Google에 연결하지 못했어요. 건너뛰고 나중에 우리 집에서 연결할 수 있어요.` Calendar read and sync failures MUST use calendar messages. Setup save failures MUST use the setup save message. Connected events MUST sync to `PUT …/calendar` after the household exists. |
| ON-2 | The user MUST be able to select multiple household types. Chips MUST keep their size and use green selection styling in Setup and Our Home. During Setup, a blocked combination from the household type contract MUST disable `우리 집 만들기` and show a reason above it. Rare combinations MUST remain selectable with no message. A 422 `household_types_invalid` response MUST show the Server's Korean reason inline when available, with a generic Korean fallback. (APP-12) |
| ON-3 | Household creation MUST display the returned `hub_api_key` as a copyable connection code, with instructions for entering it on the Hub. |
| ON-4, ON-5 | The device step MUST show the same grouped sample inventory as Our Home, with delegation disabled. |
| ON-6 | Saving MUST complete onboarding and open Main. |

### A4. The three ways to turn something off

Future non-delegation is a per-device setting and requires the Server routes
described above. App intervention sends card-scoped line off/on or stop from Main, or line off
from the matched device in Our Home. A press MUST show its pending state
immediately and let the Server confirm the effect. A change made at home is reported through the Server and shown
with the resulting state and note. Switching off all lines does not count as
Stop. The App MUST provide no Stop All control.

### A5. Presentation

The App MUST use shared design tokens and IBM Plex Sans KR. The preparation
card MUST lead with its title and place line timing on the left and state on
the right. Each screen MUST distinguish one primary action when available.
Developer builds connected to the fixture MUST use a small qualifier on
the numbered Setup steps and after Setup.
User-facing copy MUST use concise, natural Korean and omit internal diagnostics.

### A6. Removed surfaces

The App MUST omit WHY, order stories and evidence, order name or quantity
editing, household pause, settings memory and memory deletion, execution plans
on Calendar, automatic key handoff, and presenter controls.

## 3. Acceptance catalogue

All exits are observed through rendered UI and Server requests. A request to
the Hub or Simulator fails acceptance.

| ID | Scenario and observable exit |
| --- | --- |
| AP-AT-1 | Start a fixture preview with the first-run switch. See the Welcome mark and sentence, tap `시작하기`, and verify progress from `1 / 4` to `4 / 4` as you skip Google, select two types, create the household, copy the connection code, and review the read-only sample devices. Save to Main. The Server stores the household and types. |
| AP-AT-2 | Share two images from Android and pick one from the gallery. Both go through M1, M2, and M3. |
| AP-AT-3 | Send an order requiring no preparation. The order remains at M4a with an empty preparation area. |
| AP-AT-4 | Send an order requiring preparation. An M5 card appears with no evidence, comparisons, or examples. |
| AP-AT-5 | Turn off a running line, turn another line off and on before it starts, then stop the card. Each request remains pending until confirmed. Started lines offer no on control. |
| AP-AT-6 | A person changes a light at home. The next poll shows the human-change state and Server note. |
| AP-AT-7 | Close the observation window, then the episode. The card becomes M9, stays on Main after close, and leaves a dot on its start day. Acknowledge it or accept another order. The sheet leaves Main and the dot remains. |
| AP-AT-8 | Select the day with a memory dot and tap its memory. The M9 sheet opens without explanatory prose. |
| AP-AT-9 | Open Our Home. The fixed installation appears under room headings for rooms with devices. Delegation switches are disabled. Turn off a matched device line. It shows pending immediately and sends that card and task's `line_off` to the Server. |
| AP-AT-10 | Open Calendar. Navigate months and return to today. Find the birthday label and memory dot on their dates, and select a date to see its agenda. |
| AP-AT-11 | Start a fixture or preview without Google. Calendar shows `예시 일정` and the Server receives the same events. Connect Google and verify that its read replaces the samples. |
| AP-AT-12 | With no card, see the full order. When the card arrives, see one summary row above its title. Expand and collapse the order and verify guidance appears only in the full list. |
| AP-AT-13 | Inspect Main and setup at phone width. The shared typeface and tokens are applied, line timing and state are legible, and the fixture qualifier is secondary in a developer build. |
| AP-AT-14 | Return 404, 405, or 501 for the episode list. The shared order advances to its card, existing cards remain usable, and observed closures leave Calendar dots. The list is retried after a backoff. |
| AP-AT-15 | Return 404 to line off, line on, or stop. The card shows one calm message and its control is restored without resending the request. |
| AP-AT-16 | Hold each processing stage until its data is stored. Main advances through receipt, items, context, and Server intent in order, then collapses the order when the card appears. With reduced motion nothing animates. |
| AP-AT-17 | Supply multiple items of one type and one guidance task. In the expanded order the first item of that type shows its kind, Server text, and state wording exactly once. |
| AP-AT-18 | Open a real Server household without Google. The birthday appears 20 minutes after the Server time and lasts one hour. Reopen and verify its anchor stays put. When the birthday has ended or is under 10 minutes away, the next sample is sent only if there is no open card. With Google connected no sample is sent. |
| AP-AT-19 | Open the household configured by `SPIRA_HOUSEHOLD_ID` using only the Server URL and App credentials. Main opens directly. With `SPIRA_FIRST_RUN=1`, Setup opens at Welcome. |
| AP-AT-20 | At phone width with 170% text, select `3~4인` and verify the other chips stay in place. Select `맞벌이` without `부부·커플` and verify the reason appears above the disabled `우리 집 만들기`. Add `부부·커플` and verify the reason clears and creation becomes available. |
| AP-AT-21 | On the Google step, cancel sign-in and verify the step stays open without an error. Trigger an authorization failure, a calendar read failure, and a local save failure and verify their distinct messages. |
