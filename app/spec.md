# App product specification

This is the normative Gate G0 specification for `app/`. `MUST` and `MUST NOT`
are requirements. Every requirement is tied to one or more product claims
(`PC-1`–`PC-6`). Implementation guidance is deliberately outside this document
in [`design-notes.md`](design-notes.md).

Shared HTTP bodies, identifiers, enum values, limits, and state meanings are
owned by [`contracts/`](../contracts/README.md). The App uses the generated
contract models and does not redefine those shapes. If this document and a
contract differ, the contract wins and the difference remains an Open item.

## 1. Purpose and boundaries

The App is intentionally thin. A person delegates once, shares an order, and
intervenes only when needed; their main judgment happens by living in the home.
The App shows Server decisions and observed home results. It does not infer an
intent, create preparation work or device commands, contact the Simulator, or
treat command acceptance as completion. The current product platform is Android.

**P-R1.** The App MUST limit its product role to initial delegation, Android
order sharing, presentation of Server-provided preparations and rationale, and
the three interventions in A5. It MUST NOT add a per-plan approval step or turn
the App into the primary place where the user judges the preparation. (PC-1,
PC-3, PC-5, PC-6)

**P-R2.** The App MUST derive product state only from contract values received
from the Server and MUST distinguish observed results from acknowledgements,
unknown facts from success, and virtual, physical, fixture, and real-Server
qualification. The Hub's home-key authenticated `GET /home/onboarding/devices`
supplies the read-only inventory for 우리 집. The App MUST mark the devices
from the card's rationale tasks and the order's item tasks. Item-task
executions identify their devices. For a fridge notice without an execution,
the App uses the home's fridge by type when there is exactly one match. If the
Hub list is unavailable, the App shows the identified devices with a note.
The App MUST NOT use the Hub or Simulator to control devices directly.
(PC-4, PC-5)

**P-R3.** Until the real Server implements the App contract, the local App peer
MUST be the contract fixture Server at `hub/tests/fixture_server`. A run against
that peer MUST remain visibly qualified as fixture evidence and MUST NOT be
presented as real-Server interoperability. (PC-4)

## 2. Requirements

### A1. Initial delegation

**A1-R1.** Initial setup MUST let the user create the home, choose one or more
household types, and connect Google Calendar or skip it. These values are inputs
to Server judgment, not App inference. This setup is the App's single delegation
flow. (PC-1, PC-3)

### A2. Devices and delegated actions

**A2-R1.** For each discovered device, setup MUST distinguish discovery from
delegation, identify its room, type, and virtual or physical substrate, and let
the user choose delegated `commands` and non-delegated `never` actions. The App
MUST NOT represent an undisclosed or unselected action as delegated. (PC-3,
PC-5)

### A3. Shared orders

**A3-R1.** The only production order input MUST be an Android OS share
containing one to three ordered screenshots. The App MUST NOT provide an image
picker, form, or follow-up question. It MUST preserve one share identity so
redelivery or retry does not create a second episode. The browser fixture
preview uses the demo shell's sample order and disables the Android share and
calendar integrations. (PC-1, PC-3, PC-4)

**A3-R2.** An HTTP 202 MUST be shown only as intake acceptance, never as a
finished judgment or preparation. The App MUST use the episode contract to show
reading, the number of read items, failure with instructions to share again, and
the absence of preparation. Before any line has started, the user MUST be able to
correct read product names and quantities; after a line starts, that correction
affordance MUST be absent. (PC-1, PC-2, PC-4)

### A4. Preparation cards

**A4-R1.** One preparation MUST be shown as one card, with no approval button.
For each order the App MUST show no more than the contract maximum of two cards.
Each card MUST show the understood situation in one line (`text`), its schedule,
up to four lines, `done / total`, the awaited event, and for every line its
contract state and `when`. Show absolute line times as a Seoul weekday and
24-hour clock, and show the guest-arrival trigger as “손님이 오면”. After a line
ends, it MUST show the supplied `end_state` and Server display `note`.
(PC-1, PC-3, PC-4, PC-5)

**A4-R2.** A line's planned end condition MUST be shown only when a future
contract field explicitly supplies it. The App MUST NOT infer one from `when`,
`end_state`, `note`, a timer, or fixture knowledge. The missing field remains
Open item O-04/SP-09. (PC-4, PC-5)

**A4-R3.** The App MUST follow the contract's card polling and `notify` rules and
show at most one local notification for each (`card_id`, `updated_at`) for which
`notify` is true. Other card updates MUST be silent. (PC-3, PC-4)

### A5. Interventions

**A5-R1.** The App MUST expose exactly these three intervention scopes:

1. one **Stop** on each card;
2. line off/on on that card before the line starts; and
3. household pause/resume in settings.

It MUST NOT expose Stop All, a house-wide immediate stop, a Server-bypassing
App-to-Hub stop, or a wrong-judgment label. Switching off every line MUST NOT be
presented as Stop. (PC-5, PC-6)

**A5-R2.** Card Stop MUST send the existing contract `stop` reaction and mean
“end this preparation now”: cancel unstarted lines, undo changes still owned by
SPIRA, and preserve changes or jobs made or started by a person. It applies only
to that card, does not affect item guidance, and MUST NOT ask the user for a
reason. The App MUST show the request as pending until refreshed contract state
confirms the result. It MUST NOT decide how one Stop affects future Server
judgment; that remains O-02/SP-01. (PC-5, PC-6)

**A5-R3.** Household pause MUST cancel not-started work across orders, leave
running effects to their existing lifecycle, and keep newly shared orders
without judging them, as defined by the contract. Resume MUST affect future
eligibility only and MUST NOT silently revive cancelled work. (PC-5, PC-6)

### A6. WHY

**A6-R1.** WHY MUST show the stored evidence chain without starting a new
inference. In one scroll, show item types and quantities with unbundled items
marked, linked calendar evidence, unusual items and their reasons, similar
order counts by intent and examples with overlapping items, situation slots
with their evidence, and intent text with the theme highlighted. Then show each
task's need, line, devices, way, and available card time and state, followed by
fridge notice text. Use contract fields only. For no-intent orders, show the
stored reason and notices and skip empty sections. A line's WHY opens at its
task and highlights the situation behind its card. Missing rationale remains
unavailable. (PC-1, PC-2)

### A7. Item guidance

**A7-R1.** Item guidance MUST be a separate episode area, outside every card and
outside Stop scope. Before release it MUST say that guidance appears when the
package is brought in; after release it MUST show the supplied text and state;
after closure it MUST show that guidance ended. A plain-groceries order MUST
have no preparation card and show only its item guidance. (PC-1, PC-2)

### A8. Observed result projection

**A8-R1.** Card and line status MUST come from refreshed contract state. The App
MUST keep the supplied `held`, `scheduled`, `running`, `done`, `partial`,
`failed`, `unknown`, `blocked`, `user_changed`, `off`, `stopped`, `cancelled`,
and `dropped` line states distinct, together with the supplied restore outcome.
It MUST NOT turn an HTTP receipt, missing evidence, or a stale value into `done`.
A `user_changed` presentation requires that Server-provided state, and
`kept_user_change` MUST be shown as a preserved human change rather than a
failure. (PC-4, PC-5)

### A9. This-home memory

**A9-R1.** This-home memory MUST be a secondary screen inside settings. It MUST
support only viewing the Server-provided memory and deleting a selected contract
case. The App MUST refresh or otherwise observe Server confirmation before
showing a deletion as complete; it MUST NOT offer memory editing or preference
authoring. (PC-6)

## 3. Acceptance catalogue

All tests observe the App through its rendered UI, Android OS boundary, or the
contract peer. Unit tests of private classes do not by themselves satisfy these
exits.

| ID | External scenario and observable exit | Claims | Requirements |
| --- | --- | --- | --- |
| APP-AT-01 | Complete setup with multiple household types, skip or connect Google Calendar, and review discovered devices. The saved boundary contains only selected `commands`/`never`; discovered and delegated and virtual and physical remain visibly distinct. | PC-1, PC-3, PC-5 | P-R1, A1-R1, A2-R1 |
| APP-AT-02 | Send Android share intents with one and three ordered screenshots, then redeliver the same share. One episode is accepted with image order preserved; no picker, form, or question is available; redelivery creates no second episode. | PC-1, PC-3, PC-4 | P-R1, A3-R1 |
| APP-AT-03 | Return 202, then exercise processing, ready, failed extraction, no-preparation, and a nonzero `item_count`. The UI never claims a card at 202, shows the contract result, permits name/quantity correction only before a line starts, and tells the user to share again after read failure. | PC-1, PC-2, PC-4 | A3-R2 |
| APP-AT-04 | Supply an order with two cards and four lines, including schedule, awaited event, `when`, mixed line states, final `end_state`, and `note`. Both cards render all supplied fields, no third card or approval button appears, and Stop scope remains per card. | PC-1, PC-3, PC-4, PC-5 | P-R1, A4-R1 |
| APP-AT-05 | Supply different `when`, `end_state`, and `note` values using the current contract, which has no planned end-condition field. No planned end condition is inferred or displayed. | PC-4, PC-5 | A4-R2 |
| APP-AT-06 | Poll repeated card responses with `notify` false and duplicate/new (`card_id`, `updated_at`) pairs with `notify` true. Only the first delivery of each notified pair produces a local notification. | PC-3, PC-4 | A4-R3 |
| APP-AT-07 | Inspect an active card and settings, then start one line. The only interventions are card Stop, pre-start line off/on, and settings pause/resume; line on is unavailable after start; all-lines-off is not Stop; no Stop All, house stop, or wrong-judgment action exists. | PC-5, PC-6 | P-R1, A5-R1 |
| APP-AT-08 | Stop a card containing unstarted work, a SPIRA-owned effect, a person-changed effect, and a person-started job. The peer receives contract `stop`; refreshed UI shows cancellation/restoration while preserving both human effects, asks no reason, and leaves item guidance unchanged. | PC-5, PC-6 | A5-R2, A7-R1, A8-R1 |
| APP-AT-09 | Pause a household with unstarted work, a running effect, and then a newly shared order. The refreshed projection cancels the unstarted work, keeps the running lifecycle, stores the order as paused without judgment, and does not revive cancelled work after resume. | PC-5, PC-6 | A5-R3, A8-R1 |
| APP-AT-10 | After the peer has only a command acknowledgement, return a card that is not `done`; then return refreshed `done`, `partial`, `failed`, `unknown`, and restore outcomes. The UI does not complete on acknowledgement and renders every supplied state without upgrading unknown evidence. | PC-4, PC-5 | P-R2, A8-R1 |
| APP-AT-11 | Render the `ep_9031` and `ep_9150` evidence chains from contract fields. A line's WHY focuses its task and supporting situation. A second open uses the stored rationale. | PC-1, PC-2 | A6-R1 |
| APP-AT-12 | Render the plain-groceries episode with `card_ids: []` and item guidance through unreleased, released, and closed states. No preparation card is fabricated, and the guidance lifecycle remains visible. | PC-1, PC-2 | A3-R2, A7-R1 |
| APP-AT-13 | From settings, open memory, view Server rows, delete one case with a failed response and then a successful response/readback. No edit controls exist; failure remains visible; deletion is claimed only after Server confirmation. | PC-6 | A9-R1 |
| APP-AT-14 | Run the same scene against the local fixture peer and against a qualified Server profile. Fixture qualification is visible and never presented as real-Server, physical-device, or native-lifecycle evidence. Verify 우리 집 reads the Hub inventory and that browser sample sharing uses the demo shell route. | PC-4 | P-R2, P-R3 |
| APP-AT-15 | With Android large text and a screen reader enabled, locate and operate card Stop, pre-start line off/on, and settings pause. Each scope and pending/confirmed result is identifiable without color alone. | PC-5 | A5-R1, A5-R2, A5-R3 |

## 4. Open items

- **O-02 / SP-01 — Server:** determine whether one `stopped` observation can
  suppress the same intent permanently. The App sends and displays the current
  contract value and does not encode a future-learning rule.
- **O-04 / SP-09 — Server/contract:** add a card-line field for the planned end
  condition. Until then, the App shows none and never derives one.
- **O-05 / SP-06, SP-07, SP-12 — Server/shared fixtures:** complete the
  no-intent rationale and same-item contrast fixtures, and move the line-off demo
  away from the child-safety line.
- **SP-14 — Server:** provide the real App/Hub contract routes and recorded
  `ep_9031` flow. Until that exists, G1/G2 use `hub/tests/fixture_server` and make
  no real-Server interoperability claim.
