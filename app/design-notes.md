# App design notes

> **Non-normative.** This file preserves useful implementation choices from the
> pre-G0 App specification. Agents may use it as guidance, but nothing here is a
> Gate G0 product requirement or acceptance exit. [`spec.md`](spec.md) and
> [`contracts/`](../contracts/README.md) remain authoritative.

The product is intentionally thin, so implementation machinery should remain
behind the App's small user surface. These notes do not authorize extra product
flows.

## 1. Architecture and model guidance

A useful dependency direction is:

```text
widgets -> application/controller -> product/intake/control ports
                              -> local persistence port
ports <- server / fixture / Android / preferences adapters
server adapter -> generated Dart contract models
```

- Keep contract DTO conversion in the Server adapter. Immutable typed Dart
  values in the application layer make unknown and nullable contract states
  explicit; raw maps and `dynamic` values should stop at adapters.
- Keep HTTP, JSON, platform channels, preferences, Google SDKs, and generated
  enums out of feature widgets.
- Use separate ports for product reads, order intake, controls, local state,
  Android share inbox, notifications, calendar, secure storage, and Hub
  provisioning. Internal ports do not create a new App↔Hub wire.
- Treat identifiers as opaque. Do not parse device IDs or hardcode episode,
  intent, device-type, or fixture-specific behavior.
- Keep receipt, observed effect, long-running job completion, and restore result
  as separate facts. Unknown device types can use a generic presentation;
  unknown result values should never fall through to completed.

## 2. Runtime profiles and qualification

Explicit composition profiles can keep evidence honest:

| Profile | Intended use |
| --- | --- |
| local contract fixture | deterministic G1/G2 work against `hub/tests/fixture_server`; always show a fixture qualifier |
| team Server | generated App-contract adapter and protected credential; qualify independently when SP-14 is implemented |

Fence cached state, inbox work, pending controls, and notification keys by both
environment and household. A profile change should not consume another
profile's cached cards or acknowledgements. Production transport should use
HTTPS; developer loopback HTTP can be an explicit profile choice. Secrets do not
belong in URLs, ordinary preferences, logs, or `dart-define` values.

Pin and record the Flutter/Dart and native Android toolchains used for a release,
including `pubspec.lock`. The current product scope is Android; the old iOS share
extension requirement was removed rather than retained as guidance.
Prefer dependencies that let the local owner workflow run without paid software
or service requirements.

## 3. Local state and migrations

Useful durable state includes the active environment/household, onboarding
checkpoint, accepted intake-to-episode links, pending intake, cache cursor and
fetch time, successful notification keys, and unresolved control requests.
Credentials and OAuth tokens belong behind protected OS storage rather than in
ordinary preferences.

A versioned cache can migrate atomically or be discarded, but unacknowledged
share-inbox work should not be discarded as cache. Open storage and complete any
migration before rendering actionable cached controls. Household removal should
isolate its cached data and explicitly resolve pending intake.

Cache or history retention may be bounded by a documented configuration. It
should not silently delete pending work, and Server data remains authoritative.

## 4. Android share intake

One possible durable lifecycle is:

```text
OS share -> copied to private inbox -> validating -> queued -> uploading
         -> accepted(episode_id) -> native acknowledgement -> cleaned
```

- Support the Android intents needed for one or multiple shared screenshots and
  route them through one durable path. There is no picker path.
- Copy content URIs to private storage before acknowledging the OS share. Keep
  image order and a stable source identity across activity/process recreation.
- The current contract limits intake to one through three JPEG/PNG images of at
  most 5 MiB each. Validate at the adapter boundary and surface decode/type
  errors distinctly.
- Serialize pending uploads after household readiness. A second share can wait
  in arrival order while an upload is active.
- A lost HTTP response is uncertain, not proof of failure. Retry the same source
  identity and reconcile the returned episode rather than minting a new one.
- Record the accepted episode durably before acknowledging and cleaning the
  native inbox. Failed work can remain retryable or be explicitly removed.

The state machine and storage technology are implementation choices. Android
activity recreation and share redelivery deserve native tests in addition to
widget tests.

## 5. Setup, re-entry, and navigation

A compact setup sequence can be:

```text
open storage -> create/connect household -> household types/calendar
             -> discover/review devices -> select commands/never -> ready
```

Persisting a checkpoint before advancing helps avoid duplicate household
creation after interruption. Real Hub credential handoff belongs behind a
provisioning port; an unresolved handoff should be shown as unsupported rather
than replaced with fixture success.

On re-entry, load the scoped cache, reconcile pending intake and controls, then
refresh. An unavailable Server can leave a clearly stale view and retry action.
Expired credentials can enter reconnect without deleting the share inbox.

The thin surface needs preparations and settings. This-home memory sits inside
settings rather than as primary navigation. Deep links, if retained, should
resolve household/card identity through normal setup and authorization rather
than bypassing them.

If an episode-history view is retained, project the Server's dated results as
historical facts. Do not relabel an old result from today's device state, and do
not promote history or memory into a primary destination.

Loading, empty, stale/offline, recoverable error, access denied, and unsupported
states are useful explicit projections. Large text, screen-reader labels,
logical focus, adequate touch targets, and status cues beyond color support the
intervention acceptance tests.

## 6. Delegation and calendar adapters

Discovery and delegation are distinct states. Registration adapters can show
room, label, type, substrate, supported commands, and `never`, and can reconcile
revision conflicts by refreshing for review instead of overwriting unseen
changes. Editing labels should not replace stable logical device identity.

Calendar access should request read-only consent through explicit user action,
send only the contract fields in the contract window, and keep access tokens in
the native SDK/secure boundary. Denial, revocation, pagination failure, and
network failure mean time context is unavailable; they do not mean there is no
event. The Server owns tagging and title disposal.

## 7. Card refresh, controls, and notifications

One ordered refresh coordinator per active household avoids timer, resume, and
control races. Each request can capture environment, household, and a generation
token; discard a response after its generation becomes inactive. Persist a
cursor only with the fully parsed snapshot that produced it, and do not move the
cursor on malformed data.

Follow the contract's 30-second foreground card polling and `server_time`
cursor. Refreshing immediately after resume or a control can reduce ambiguity.
Repeated read failure can preserve the last known projection with a stale label.
Never let an older response roll back a newer card.

A local control lifecycle such as

```text
idle -> persisted pending -> sending -> acknowledged -> refreshed/confirmed
                               \-> uncertain or failed
```

can prevent duplicate taps and avoid optimistic physical success. A timeout is
uncertain; refresh before resending a mutation unless the contract identity
makes repetition safe. Do not invent an idempotency header or body field.

General reads may use bounded backoff. The former implementation used 1, 2, 4,
and 8 seconds capped at 30 seconds, 12-second reads, and 20-second uploads; these
are tunable starting points, not product requirements. Disposal should stop
timers and reject late widget updates.

Persist a successful notification delivery key for (`environment`, `household`,
`card_id`, `updated_at`). A failed local delivery should not consume the key.
Notification taps should re-enter through normal household/setup resolution.
Polling does not imply guaranteed background delivery.

## 8. Presentation details

- Localize contract codes at the presentation edge; contract values remain
  English codes.
- Keep item guidance outside the card widget and outside card-control state.
- Keep the planned end condition absent until SP-09 supplies an explicit field.
  `end_state` describes what happened after the end; it is not the condition.
- Treat a Stop response as acknowledgement until the refreshed card/result
  projection confirms cancellation and restore outcomes.
- Render missing WHY as unavailable. Do not regenerate or reconstruct it from
  order, card, execution, or fixture data.
- Keep the WHY chain in order from read items through household context, situation,
  intent, tasks, and fridge notices. Join item quantities from the episode and
  line timing from the card. Trace a selected task to its situation by card ID.
- Keep the rationale's purchase-history comparisons, similar-order counts, and
  examples out of logs and diagnostics.

The owner also decided that shared household displays such as a refrigerator or
TV show only item guidance or ambience, never intent text. This cross-surface
privacy rule currently has no PC mapping, so Gate G0 keeps it here rather than
creating an App product requirement. App-owned display/provisioning code should
still avoid forwarding `intent_text` to a shared-display channel.

## 9. Security and observability

Use platform-private storage for the share inbox and caches. Exclude raw order
images, calendar titles, tokens, and keys from ordinary logs and evidence.
Reject malformed links and foreign-household identifiers. Stop network workers
before logout credential cleanup so late work cannot cross sessions.

Useful redacted diagnostics include environment, application revision, cache
age, pending intake/control counts, last successful refresh, and error category.
Evidence should record the platform and peer qualification and should not turn a
fixture render into native, real-Server, or physical-device proof.

## 10. Suggested modules and test ownership

The former target layout remains a reasonable option:

```text
bootstrap/
core/{domain,persistence,errors,clock}/
features/{onboarding,orders,preparations,rationale,settings}/
adapters/{server,fixture}/
platform/{share,notifications,calendar,secure_storage}/
```

Standard Flutter controllers and explicit composition are sufficient; a new
framework is not required. Keep fixture adapters selected at composition rather
than imported by production features.

- Domain tests can cover validation, ordering, and control guards.
- Widget tests can cover rendering, pending/error states, and accessibility.
- Adapter tests can cover generated-model conversion, malformed input,
  persistence, source identity, and exact contract requests.
- Android tests can cover share intents, activity/process recreation,
  permissions, and notification delivery.
- Integration tests can observe the App and contract peer without claiming real
  Server, Hub, Simulator, or physical-device qualification beyond what ran.

Offline device commands, Server inference, KB memory creation, device control
from the App, Stop All, house-wide immediate stop, a picker, and iOS support are
not implied by these notes.
