# App product specification

Status: ACTIVE. This document owns App behavior and acceptance. Shared HTTP
bodies, enum values, identifiers, and time rules remain under
[contracts](../contracts/README.md). The App MUST use generated contract models.

## 1. Purpose and boundaries

**P-R1.** The App MUST center on one preparation's lifecycle, from an order
capture through execution, intervention, and memory. Main, Calendar, and Our
Home MUST be the three tabs after first-run onboarding. No plan approval is
required. (PC-1, PC-3, PC-5, PC-6)

**P-R2.** The App MUST use the Server for household, order, preparation, and
memory data. It MUST make zero requests to the Hub or Simulator. Google
Calendar is read on the phone. A command receipt MUST NOT be shown as a
confirmed effect. (PC-4, PC-5)

**P-R3.** Until the real Server implements the App contract, the local App peer
MUST be the contract fixture Server at `hub/tests/fixture_server`. A run against
that peer MUST remain visibly qualified as fixture evidence and MUST NOT be
presented as real-Server interoperability. (PC-4)

## 2. Requirements

### A1. Main lifecycle

Main MUST keep the order above the preparation area. Both areas remain in
place as Server state changes. Up to two cards for the same order can appear
together. Only Server-issued cards can appear. The presentation shell MUST
embed the App's actual web build when it shows the App.

| ID | Required presentation | Contract source |
| --- | --- | --- |
| M1 | The App MUST accept one to three ordered images from Android share or the gallery. Each selection MUST have one stable `source_id` for retry. After acceptance, show the submitted thumbnails and receipt. | `POST /v1/orders`, `received` |
| M2 | The order area MUST show a list skeleton during reading. | Episode `reading` |
| M3 | The order area MUST show names and quantities, plus only a count for masked items. Read failure MUST prompt the user to send again. | Episode `items`, `item_count`, `masked_count`, `read_failed` |
| M4a | The order MUST remain visible with an empty preparation area when no card was produced. Item guidance state appears beside the item when supplied and the list is expanded. | Episode `judged`, empty `card_ids`, `item_tasks[].state` |
| M4b | A held card MUST show the Server's text verbatim. | Episode `held`, card held template |
| M5 | With a card present, the order MUST default to one tappable row with a thumbnail, item count, first visible item and remaining count, and a chevron. Tapping MUST reveal or hide the full order. A preparation card MUST show the Server's text verbatim, schedule, timed or triggered lines, progress, and applicable controls. The App MUST deduplicate local notifications by `card_id` and `updated_at`, and honor `notify` for new and newly timed cards. | Card poll `text`, `starts_at`, `lines`, `summary`, `notify` |
| M6 | The App MUST show each supplied line state distinctly, including the Server's note and any awaited event. | Card poll `lines[].state`, `note`, `summary.waiting_for` |
| M7a | Line off MUST remain available while a line runs. Line on MUST be available only before start. A 409 indicating start MUST remove that control. Stop applies only to its card. Requests MUST remain pending until refreshed card state confirms the change. | Card `line_off`, `line_on`, `stop` reactions |
| M7b | A human change MUST show the changed state and Server note. A person-started standby task uses the Server's resulting state. | Card `user_changed`, `note`, `done` |
| M8 | The App MUST show the supplied restoration outcome and note per line. | Card `lines[].end_state`, `note` |
| M9 | When the observation window closes, the card MUST become a memory sheet with the intent, lines and states, verdict, and task feedback. | Episode rationale `intents[].intent_text`, `tasks`, `observations` |
| M10 | At episode close, live cards MUST leave Main and the latest memory sheet MUST stay until the next accepted order or acknowledgment. Calendar MUST keep the closed episode marker regardless of acknowledgment. | Episode `closed`, last card update, episode history |

The App MUST use the card poll's `server_time` cursor, reconcile cached cards
with the Server after startup or reconnect, and avoid inventing a planned
end condition. Poll every 30 seconds, with a three-second foreground cadence
during active preparation or intake. Show the last known state and a connection
notice while reads fail.

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

The App MUST read the next 14 days of Google events on the phone. In fixture or
preview builds, it MUST show a bundled calendar marked `예시 일정` while Google
is disconnected, and sync those same events with `PUT …/calendar`. A connected
Google calendar MUST replace the samples, including when it has no events.
A disconnected production build MUST omit sample events.

Calendar MUST use the household episode listing for history. It MUST date a
closed episode in the household time zone using the last observed card
`starts_at`, with `shared_at` as the fallback for a card the App never saw.
A card seen only in the held state has no marker. The App MUST reconstruct the
sheet from episode detail and rationale without cached card bodies.

### A3. Our Home and onboarding

Our Home MUST show editable household types via `PUT …/profile`, Google
connect/disconnect, and the device list on one page. Until the App device
routes exist, Our Home and onboarding MUST show the fixed demo inventory
from the example Hub installation, labeled `예시 집`. It MUST group devices by
room and show a name and type icon. Each delegation control MUST remain
disabled and labeled `집 연결 후`. The App needs a Server device list including
rooms and a Server write route for per-device delegation. The Hub needs that
delegation before execution.

Our Home MUST match open card lines to devices through
`GET /v1/episodes/{id}/rationale`, using the task's card and task identifiers
and its `devices` identifiers, types, and rooms. The row MUST display the card
line's text and state and use the card's `line_off` reaction when available.
Onboarding MUST show the device list read-only. A fixture or preview first-run
switch MUST start at Google setup with no household, even when a fixture
household is configured or setup was previously completed.

| ID | Requirement |
| --- | --- |
| ON-1 | First-run setup MUST start with optional Google sign-in. Connected events MUST sync to `PUT …/calendar` after the household exists. |
| ON-2 | The user MUST be able to select multiple household types. A 422 `household_types_invalid` response MUST show the Server's reason inline. |
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
Fixture builds MUST use a small qualifier. User-facing copy MUST use concise,
natural Korean and omit internal diagnostics.

### A6. Removed surfaces

The App MUST omit WHY, order stories and evidence, order name or quantity
editing, household pause, settings memory and memory deletion, execution plans
on Calendar, automatic key handoff, and presenter controls.

## 3. Acceptance catalogue

All exits are observed through rendered UI and Server requests. A request to
the Hub or Simulator fails acceptance.

| ID | Scenario and observable exit |
| --- | --- |
| AP-AT-1 | Start a fixture preview with the first-run switch. Skip Google, select two types, create the household, see and copy the connection code, review the read-only sample devices, and save to Main. The Server stores the household and types. |
| AP-AT-2 | Share two images from Android and pick one from the gallery. Both go through M1, M2, and M3. |
| AP-AT-3 | Send an order requiring no preparation. The order remains at M4a with an empty preparation area. |
| AP-AT-4 | Send an order requiring preparation. An M5 card appears with no evidence, comparisons, or examples. |
| AP-AT-5 | Turn off a running line, turn another line off and on before it starts, then stop the card. Each request remains pending until confirmed. Started lines offer no on control. |
| AP-AT-6 | A person changes a light at home. The next poll shows the human-change state and Server note. |
| AP-AT-7 | Close the observation window, then the episode. The card becomes M9, stays on Main after close, and leaves a dot on its start day. Acknowledge it or accept another order. The sheet leaves Main and the dot remains. |
| AP-AT-8 | Select the day with a memory dot and tap its memory. The M9 sheet opens without explanatory prose. |
| AP-AT-9 | Open Our Home. The fixed installation appears under room headings. Delegation switches are disabled. Turn off a matched device line. It shows pending immediately and sends that card and task's `line_off` to the Server. |
| AP-AT-10 | Open Calendar. Navigate months and return to today. Find the birthday label and memory dot on their dates, and select a date to see its agenda. |
| AP-AT-11 | Start a fixture or preview without Google. Calendar shows `예시 일정` and the Server receives the same events. Connect Google and verify that its read replaces the samples. |
| AP-AT-12 | With no card, see the full order. When the card arrives, see one summary row above its title. Expand and collapse the order and verify guidance appears only in the full list. |
| AP-AT-13 | Inspect Main and setup at phone width. The shared typeface and tokens are applied, line timing and state are legible, and the fixture qualifier is secondary. |
