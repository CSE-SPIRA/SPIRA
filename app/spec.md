# SPIRA App Specification

Implementation specification for `app/`. It defines the App's product responsibility and use of repository contracts; it does not certify an existing implementation.

- **Sources.** The owner App design formerly maintained in Notion, the current integration contract, and the Server specification.
- **Authority.** [`contracts/`](../contracts/README.md) is authoritative for shared HTTP bodies, identifiers, enums, and state meanings. If this document conflicts with a shared contract, the contract wins. Notion may propose a change but does not override the repository.
- **Implementation.** Flutter/Dart. Use generated contract models from [`contracts/generated/`](../contracts/generated/) rather than handwritten wire-model copies.
- **This change.** Requirements only: no App runtime, contract revision, deployment claim, or mobile-platform qualification.

## 1. Role and boundary

The App is SPIRA's household-facing surface. It collects minimum household context, sends order screenshots to the Server, presents Server-produced cards and explanations, and lets the user change or stop future preparation.

The App:

1. creates and identifies one household;
2. configures household profile and calendar context;
3. submits order screenshots and permits correction of extracted items;
4. displays cards, line/result state, rationale, and this-home memory;
5. submits pause, stop, line-off, and line-on decisions; and
6. notifies only when the Server marks a card update as notifiable.

The App does **not** infer purchase intent, generate plans, command devices, calculate card-line state, infer success from a device acknowledgement, or call the KB directly.

## 2. Shared contract surface

The App uses [`contracts/openapi/app.yaml`](../contracts/openapi/app.yaml). Its linked schemas and rules are part of this specification.

| Concern | Contract source | App responsibility |
| --- | --- | --- |
| Authentication | `appToken` | Send the bearer token; never log or commit it. |
| Household creation | `household_create.json`, `household_created.json` | Store `household_id`; hand off the one-time Hub key only through an approved local setup flow. |
| Order intake | `POST /v1/orders` | Send 1–3 valid images and a stable `source_id`. |
| Episode/edit | `episode.json`, `order_edit.json` | Display Server state and replace items only through the specified endpoint. |
| Cards | `cards_response.json`, `card.json` | Poll, render, and cache by contract identifiers/timestamps. |
| Reactions | `reaction.json` | Send only supported stop/line controls; render the returned card. |
| Rationale/memory | `rationale.json`, `memory.json` | Display stored evidence/results without inventing explanations. |
| State meaning | [`state-mapping.md`](../contracts/state-mapping.md) | Render Server-computed state; do not recompute it from local guesses. |

The Server is the only shared network service called by the App in the current contract. Local App-to-Hub provisioning is not specified in `contracts/`; this document does not invent a team-wide route or persistence format.

## 3. Required behaviour

### A1. First setup and household identity

- Create a household through `POST /v1/households`; persist the returned `household_id` with the App credential.
- Treat the returned Hub API key as a one-time secret. Exclude it from analytics, screenshots, logs, source control, and normal App exports.
- If local Hub handoff is unavailable, retain a recoverable incomplete setup state. Do not claim the Hub is connected.
- Re-entry uses the existing household rather than silently creating another one.

### A2. Household context

- Let the user choose supported household types and submit the complete selection.
- Send calendar events from now through 14 days ahead as a full replacement list. The Server owns tagging and title disposal.
- Surface validation errors without replacing the user's last confirmed local selection.

### A3. Order sharing and episode tracking

- Accept JPG/PNG screenshots through the platform share action and enforce contract count/size limits before upload.
- Generate a stable `source_id` for one source share so retries do not duplicate an episode.
- Treat `200` and `202` according to contract: both identify the episode, but neither means a card is ready.
- Show every episode status in `episode.json`, including read failure, no-card judgement, held, and paused outcomes.

### A4. Order correction

- Display extracted items and masked count without reconstructing hidden names.
- Replace items only through `PUT /v1/episodes/{episode_id}/order`.
- Explain that only work not already started can change. Never present an edit as reversal of completed physical action.

### A5. Preparation cards

- Poll open cards every 30 seconds. Use the previous `server_time` as the next `since`; omit `since` when loading all open cards.
- Preserve `card_id`, `episode_id`, line identity, `updated_at`, and Server order during updates.
- Render text, start time, up to four lines, summary, waiting trigger, line/end state, buttons, and stopped state.
- Use [`state-mapping.md`](../contracts/state-mapping.md): `running`, `done`, `partial`, `blocked`, `unknown`, `user_changed`, and restore outcomes remain distinct.

### A6. User controls

- `line_off` excludes one line from future work; `line_on` requests re-inclusion if the Server still permits it.
- `stop` stops remaining preparation for one card. It is distinct from household pause.
- Household pause prevents new automatic preparation until resumed; it does not assert that started physical work was reversed.
- The card returned by the reaction endpoint becomes the new source of truth. Post-stop reactions follow contract no-effect semantics.

### A7. Explanation, results, and memory

- WHY reads `GET /v1/episodes/{episode_id}/rationale` and labels evidence, choices, executions, and observations as stored facts.
- Do not issue a new LLM request or add an App-authored causal explanation.
- Show per-item notices even when no preparation card exists.
- Show execution through refreshed cards/rationale; there is no App execution-results endpoint.
- Show this-home memory grouped by intent and allow one case to be forgotten through the contract endpoint.

### A8. Notification and refresh

- Produce at most one local notification per `(card_id, updated_at)` where `notify` is true.
- A repeated poll or App restart does not create another notification.
- A notification opens the matching card if available; otherwise it opens episode history without fabricating stale content.
- On network failure, a cached view remains visibly stale and retryable rather than appearing fresh.

### A9. Privacy, accessibility, and diagnostics

- Keep credentials, raw screenshots, and sensitive product names out of diagnostic logs.
- Delete temporary upload files after the platform share/upload lifecycle no longer needs them.
- Provide text labels for controls/progress; colour alone must not communicate line status.
- Diagnostics may contain request class, status code, contract identifier, and timestamp, but no tokens or screenshot content.

## 4. Lifecycle and truth levels

```text
setup -> profile/calendar -> screenshots accepted -> Server reads/judges
      -> card or no-card outcome -> user controls -> Hub results
      -> refreshed cards/rationale -> memory/closed episode
```

Every screen preserves the distinction between accepted input, planned work, Hub-admitted work, independently observed work, and restored/end state.

## 5. Failure and recovery

- Retry reads normally. Retry writes only with stable identifiers or contract duplicate protection.
- A timeout is unknown delivery, not a business failure; refresh the resource before offering another write.
- Preserve setup/profile/calendar/order-edit drafts until the Server confirms them.
- Authentication failure returns to recoverable setup without automatically erasing the household.
- Contract-invalid responses are diagnostic failures, never plausible cards or successful actions.

## 6. Acceptance cases

Component tests must cover at least:

1. household creation and one-time Hub-key handling without secret logging;
2. duplicate screenshot submission with stable `source_id`;
3. episode progression including read failure, no card, held, and notified;
4. polling with `server_time`, deduplication, and one notification per update;
5. distinct line off/on, card stop, and household pause/resume;
6. every line/end state in `state-mapping.md`;
7. rationale/memory display without local inference;
8. offline restart with stale data visibly marked; and
9. contract fixtures deserialised through generated Dart models.

End-to-end acceptance additionally requires real Server and Hub contract runs. Mocked UI tests do not establish external conformance or release readiness.

## 7. Open joint decisions and non-claims

The following require separate decisions: authenticated local App-to-Hub setup/discovery/key storage; production sign-in and recovery; push transport beyond local notification; and iOS/Android release, permission, and accessibility qualification.

This specification does not claim those decisions are complete, that physical devices were qualified, or that an App implementation currently passes the acceptance cases.
