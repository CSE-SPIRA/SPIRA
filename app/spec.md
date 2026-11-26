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
together. Only Server-issued cards can appear.

| ID | Required presentation | Contract source |
| --- | --- | --- |
| M1 | The App MUST accept one to three ordered images from Android share or the gallery. Each selection MUST have one stable `source_id` for retry. After acceptance, show the submitted thumbnails and receipt. | `POST /v1/orders`, `received` |
| M2 | The order area MUST show a list skeleton during reading. | Episode `reading` |
| M3 | The order area MUST show names and quantities, plus only a count for masked items. Read failure MUST prompt the user to send again. | Episode `items`, `item_count`, `masked_count`, `read_failed` |
| M4a | The order MUST remain visible with an empty preparation area when no card was produced. Item guidance state appears beside the item when supplied. | Episode `judged`, empty `card_ids`, `item_tasks[].state` |
| M4b | A held card MUST show the Server's text verbatim. | Episode `held`, card held template |
| M5 | A preparation card MUST show the Server's text verbatim, schedule, timed or triggered lines, progress, and applicable controls. The App MUST deduplicate local notifications by `card_id` and `updated_at`, and honor `notify` for new and newly timed cards. | Card poll `text`, `starts_at`, `lines`, `summary`, `notify` |
| M6 | The App MUST show each supplied line state distinctly, including the Server's note and any awaited event. | Card poll `lines[].state`, `note`, `summary.waiting_for` |
| M7a | Line off MUST remain available while a line runs. Line on MUST be available only before start. A 409 indicating start MUST remove that control. Stop applies only to its card. Requests MUST remain pending until refreshed card state confirms the change. | Card `line_off`, `line_on`, `stop` reactions |
| M7b | A human change MUST show the changed state and Server note. A person-started standby task uses the Server's resulting state. | Card `user_changed`, `note`, `done` |
| M8 | The App MUST show the supplied restoration outcome and note per line. | Card `lines[].end_state`, `note` |
| M9 | When the observation window closes, the card MUST become a memory sheet with the intent, lines and states, verdict, and task feedback. | Episode rationale `intents[].intent_text`, `tasks`, `observations` |
| M10 | The preparation MUST leave Main when its episode closes. Calendar MUST index the eligible closed episode by the card start day. | Episode `closed`, last card update, episode history |

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

Calendar MUST show upcoming Google events from the existing 14-day phone read
as bars. It MUST show past memories as dots, one per closed episode with a
dated card, on the card's `starts_at` day in the household time zone. A held
card with no start has no marker. Preparation plans remain on Main.

A memory dot MUST open the same sheet as M9 using episode detail and rationale,
including purchased items, masked count, and start/end times when supplied.
Calendar MUST use the household episode listing for history. The current App
contract omits card start/end metadata from both episode history and rationale.
A previously observed Server start can be saved as a date index. A closed
episode with no available start cannot be dated until the Server supplies it.
The sheet itself MUST be reconstructible without cached card bodies.

### A3. Our Home and onboarding

Our Home MUST show editable household types via `PUT …/profile`, Google
connect/disconnect, and the device section on one page. Until an App device
route exists, the section MUST display that devices appear after connecting a
home. The App needs a Server device list including rooms, and a Server write
route for per-device delegation. The Hub needs that delegation before execution.

| ID | Requirement |
| --- | --- |
| ON-1 | First-run setup MUST start with optional Google sign-in. Connected events MUST sync to `PUT …/calendar` after the household exists. |
| ON-2 | The user MUST be able to select multiple household types. A 422 `household_types_invalid` response MUST show the Server's reason inline. |
| ON-3 | Household creation MUST display the returned `hub_api_key` as a copyable connection code, with instructions for entering it on the Hub. |
| ON-4, ON-5 | The device step MUST show the same connection state as Our Home while the App device and delegation routes are unavailable. |
| ON-6 | Saving MUST complete onboarding and open Main. |

### A4. The three ways to turn something off

Future non-delegation is a per-device setting and requires the Server routes
described above. App intervention lives on Main and sends card-scoped line
off/on or stop. A change made at home is reported through the Server and shown
with the resulting state and note. Switching off all lines does not count as
Stop. The App MUST provide no Stop All control.

### A5. Removed surfaces

The App MUST omit WHY, order stories and evidence, order name or quantity
editing, household pause, settings memory and memory deletion, execution plans
on Calendar, automatic key handoff, and presenter controls.

## 3. Acceptance catalogue

All exits are observed through rendered UI and Server requests. A request to
the Hub or Simulator fails acceptance.

| ID | Scenario and observable exit |
| --- | --- |
| AP-AT-1 | On first install, connect Google or skip, select two types, see and copy the Hub code, and save to Main. Once the Server provides device routes, place three devices and leave one non-delegated. The Server stores the household, types and, when supported, placement and delegation. App-to-Hub requests total zero. |
| AP-AT-2 | Share two images from Android and pick one from the gallery. Both go through M1, M2, and M3. |
| AP-AT-3 | Send an order requiring no preparation. The order remains at M4a with an empty preparation area. |
| AP-AT-4 | Send an order requiring preparation. An M5 card appears with no evidence, comparisons, or examples. |
| AP-AT-5 | Turn off a running line, turn another line off and on before it starts, then stop the card. Each request remains pending until confirmed. Started lines offer no on control. |
| AP-AT-6 | A person changes a light at home. The next poll shows the human-change state and Server note. |
| AP-AT-7 | Close the observation window, then the episode. The card becomes M9, leaves Main at M10, and leaves a dot on its start day. |
| AP-AT-8 | Tap a dot. The M9 memory opens without explanatory prose. |
| AP-AT-9 | Once App device routes are available, add, remove, and mark devices as non-delegated in Our Home. Server inventory and delegation change and apply to the next plan. Until then, verify the connection state and zero Hub requests. |
