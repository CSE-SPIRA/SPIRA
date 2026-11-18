# App implementation specification

This document is the normative implementation specification for `app/`.
`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. Shared HTTP bodies,
identifiers, enums, and state meanings remain authoritative in
[`contracts/`](../contracts/README.md); this document defines App-owned state,
algorithms, failure handling, and acceptance. If they conflict, the contract
wins. The requirements consolidate the adopted owner design, current team
contracts, and the responsibilities already published in this repository.

This specification does not certify an implementation. Implementation and
platform qualification are established only by the tests and evidence named in
the change that adds them.

## 1. Purpose, owners and limits

The App MUST accept order images, present Server-provided preparations, preserve
user intent, and explain observed execution and restore outcomes. It MUST offer
Flutter mobile on Android and iOS. App owns navigation, local durable intake,
cache, permission interaction and presentation. Server owns interpretation,
preparation generation, stored rationale and memory. Home owns durable device
execution. Simulator owns virtual world truth. App MUST NOT infer purchase
intent, generate native commands, infer completion from an HTTP acknowledgement,
or turn a user's override into permanent delegation/preference.

App MUST present proactive preparation without a per-preparation Accept gate.
The open-source implementation MUST NOT require a software purchase or paid
software dependency merely to run its local owner development flow.

App MUST remain independently testable against a typed fixture data-source port.
A fixture peer is a test actor, not a product Server. App MUST NOT import
Home or Simulator implementation. Physical and virtual qualifiers MUST remain
visible. A local fixture render does not qualify Server interoperability or either
mobile platform's native lifecycle.

## 2. Glossary and domain objects

All identifiers are opaque strings with nonempty validation at adapter entry.
Domain objects MUST be immutable typed Dart values; maps/dynamic wire payloads
MUST terminate at adapters, including persistence/native channel adapters.

| Object | Required fields and invariants |
| --- | --- |
| Household | id, label, profile, registry revision, paused, environment qualifier; one active household per session |
| Profile | household type set, calendar connection and last successful sync; no inference on missing calendar |
| Device/delegation | logical id, room, label, type, virtual/physical qualifier, discovered/registered state, commands, never, revision; discovery is not admission |
| Episode | id, creation time, intake/source identity, state, ordered preparation ids; an episode may contain multiple preparations |
| Preparation/card | card id, episode id, updated version/time, text, summary, scheduled time, stopped, lines, item guidance, notify; maximum four visible preparation lines |
| Line | task id, text, state, started, enabled, schedule, result and restore evidence; started identity is immutable |
| Rationale | episode id, captured order/calendar basis, reasons, room/device choice and execution evidence; historical rationale is read, never regenerated locally |
| History record | episode identity, date, immutable past result projection |
| Memory record | id, stored Server context and provenance; deletion is a request followed by readback |
| Intake | durable source id, ordered image references, digest, state, accepted episode id, last error |
| Reaction intent | local id, household, scope, action, base revision, pending/confirmed/failed state |
| Cache | schema version, environment + household key, fetch time, source revision and typed product state |

Unknown device types MUST use a generic device presentation. Unknown result values
MUST display unknown, never completed. Command receipt, fresh observed effect,
job completion and restore are separate facts.

## 3. Process and architecture

One Flutter process owns UI/application state. Android private-file inbox or iOS
App Group inbox survives its death. OS/native bridges MUST transfer typed
intake events into the same application path used by the image picker.

```text
widgets -> application/controller -> product/intake/control ports
                              -> local persistence port
ports <- server / fixture / native / preferences adapters
server adapter -> pinned generated Dart team DTOs (when qualified)
```

The App MUST NOT contact a Simulator device endpoint. Server and local provisioning
are separate ports. Domain and feature code MUST NOT depend on http, JSON,
MethodChannel, shared_preferences, Google SDK or generated wire enums.

## 4. Runtime and configuration

Flutter/Dart versions MUST be pinned and recorded for each build together with
`pubspec.lock` and native build tools; availability MUST be checked rather than
assumed. Configuration MUST
select an explicit environment and endpoint; caches/intake MUST be fenced by
that environment and household. Secrets MUST NOT be dart-defines or URLs.

| Profile | Inputs and claim |
| --- | --- |
| local fixture | typed deterministic state, local persistence, no Server required; fixture label always shown |
| reference fixture | typed private peer with an explicit fixture label; no OCR/KB/provisioning claim |
| team Server | generated APP contract adapter and secret-store credential; separately qualified |

Production requires HTTPS; developer loopback HTTP MAY be explicitly enabled.
A profile change MUST NOT consume another profile's cached cards, pending
reactions or inbox acknowledgements. App MUST open/migrate local state before
rendering actionable product data.

## 5. Persistence, identity and migrations

Local storage MUST retain active environment/household, onboarding progress,
accepted intake→episode links, pending intake, cache revisions/fetch times,
notification keys, selected navigation/deep link and pending user-control intent.
It MUST NOT persist OAuth access tokens in preferences. The native secret-store
port MUST provide credential read/write/delete without exposing key bytes to
widgets. Pairing wire remains an external/joint decision.

Intake uniqueness is `(environment, household, source_id)`; changing bytes for an
existing source id MUST be rejected. The local inbox MUST copy content URIs to
private storage before acknowledging the OS share. Image order MUST persist.
Images MUST be 1–3 per intake, each nonempty and at most 5 MiB. The App MUST
validate count/size before upload. Mime/decoding failures MUST be explicit.

A versioned cache MUST either migrate atomically or be discarded as a cache;
unacknowledged inbox entries MUST never be discarded on schema mismatch.
Durable writes MUST be checked for success before transition. Raw images SHOULD
be removed after accepted episode identity is durably recorded and native
acknowledgement succeeds; failed entries remain retryable/removable by the user.
No arbitrary retention limit may delete pending work. Completed cache/history
may be bounded by a documented configurable retention policy; Server history
remains authoritative. Household removal MUST purge its cache/secret references
and explicitly handle its pending intake rather than silently forwarding it.

## 6. First-init and re-entry state machines

<a id="a1"></a>
### A1. First setup (APP-01/03/12, HUB-14)

```text
opening storage -> introduction -> environment/household selection
 -> household creation/connection -> credential provisioning
 -> profile -> room/device/delegation review -> optional permissions -> ready
```

Every step MUST persist its checkpoint before advancing. Back/cancel MUST retain
already saved data and avoid duplicate household creation. Product setup MUST
obtain household id and Hub key through the team Server route, store the key
securely, and pass it through an explicit provisioning port. The App MUST display
unsupported provisioning while that port is unresolved; fixture confirmation MUST
NOT masquerade as product pairing. A fixture entry MAY bypass real provisioning
only after the user explicitly chooses fixture mode.

On re-entry: open local storage; restore environment/household; reconcile pending
intake and control intents; show cached state with stale label; refresh current
household/permissions; navigate to the last safe screen or validated deep link.
Expired/revoked credentials enter reconnect without deleting inbox. Unavailable
Server enters offline with retry. Re-entry MUST NOT request OS permission again
merely because a screen is rebuilt.

<a id="a2"></a>
### A2. Household and delegation (APP-13, HUB-05)

Device states are `discovered -> review -> saving -> registered/excluded`, with
save failure returning to editable review. App MUST distinguish candidates from
registered devices, show room/name/type/substrate and allow explicit command and
never choices. Saving MUST use the revision expected by the boundary; revision
conflict MUST refresh/review rather than overwrite unseen changes. A successful
registration MUST follow binding/capability confirmation, not just a local tap.
Editing a room or display name MUST preserve the stable logical device id.
Changing delegation MUST NOT rewrite past results. General discovery and local
provisioning protocol MUST stay open joint boundaries until adopted.

## 7. Navigation and complete view states

Primary destinations are preparations, household/settings and history/memory.
A preparation opens its WHY or pre-start order correction. Settings opens profile,
delegation, calendar and notifications. A deep link targets a household/card id,
then resolves through the same repository; it MUST NOT bypass auth or setup.

Every asynchronous surface MUST represent loading, empty, current, stale/offline,
recoverable error, access denied and unsupported explicitly. Unknown card id
shows unavailable with navigation back. Initial network failure MUST leave retry
and setup available. During a control request, its affected scope MUST show
pending and prevent duplicate taps; unaffected navigation MUST remain usable.
Large text, screen readers, keyboard focus and ≥48 logical-pixel touch targets
MUST be supported. Status MUST NOT be communicated by color alone. Dates MUST
be stored as explicit instants/timezones and displayed in the user's locale.

## 8. Native intake and upload lifecycle

<a id="a3"></a>
### A3. Orders (APP-02/07/11/16)

```text
OS/picker -> durable queued -> validating -> ready -> uploading
 -> accepted(episode_id) -> native acknowledgement -> cleaned
```

`uploading -> retryable` on timeout/network/5xx; `validating -> rejected` on bad
input; `accepted -> ack_pending` on native failure. Restart MUST treat an
unresolved upload as uncertain and retry with the SAME source id. It MUST never
mint a new id merely because the HTTP response was lost. Duplicate delivery of
one native source id MUST enqueue once per session and across process recreation.
One serialized worker MUST drain pending intake only after household readiness.
A newly shared intake during upload MUST remain queued, in arrival order.

The native adapter MUST support Android ACTION_SEND/ACTION_SEND_MULTIPLE and
picker lost-data recovery; iOS share extension MUST commit into its App Group
before completion. iOS extension and app MUST coordinate file writes atomically.
A picker result MUST use the same durable path as a share. Android activity
recreation and iOS extension/app termination require independent native tests.

202/episode id means intake accepted, not preparation created. APP-11 item_count
MUST be retained with the episode when supplied. Extracted order items MUST remain
viewable independently of whether optional preparation exists. App MUST poll
APP-11 for processing, ready, no-preparation, failed-extract, failed-context and
paused-skip. Paused intake remains recorded without proactive execution. Order
correction MUST be allowed only before any affected preparation starts; save
must refresh the same episode and a stale server rejection MUST retain edits for
review/retry, without claiming re-interpretation succeeded. Correction MUST edit
product name and quantity, submit them to Server for pre-start re-judgment and
refresh the same episode; it MUST NOT mutate already started preparation work.

## 9. Preparation rendering and evidence

<a id="a4"></a>
### A4. Cards (APP-04/06/11/14, C-7)

The App MUST render typed card state without hardcoded episode/device type logic.
It MUST show summary, schedule, up to four lines, WHY, Stop and independent item
guidance. An order MUST show at most two preparation cards. Multiple preparations retain separate Stop scopes even if notification
is grouped. Card results MUST update through card polling, not an invented result
API. Foreground polling cadence is 30 seconds plus immediate refresh after a
control or app resume; background delivery follows platform limits.

<a id="a8"></a>
### A8. Result projection (HUB-08, C-7)

Waiting/scheduled, executing, completed, partial, failed, user changed, unknown
and restored MUST be distinguishable. A result MUST preserve receipt/effect/
job/restore evidence and environment qualifier. Explicit USER evidence is
required for a user-change label; ambiguous external changes remain unknown
actor. App MUST NOT interpret missing evidence as success. Acknowledged Stop
means stop requested; confirmed stopped/result state requires refreshed data.
Completed MUST require every expected action sibling to have confirming evidence;
a known completed sibling plus unknown/failed siblings MUST remain partial or
failed according to the supplied aggregate. Restore restored, skipped, failed and
unknown MUST remain separate from effect status. Summary MUST show confirmed
count/total and any waiting condition rather than implying unfinished work is done.

## 10. User control state machine

<a id="a5"></a>
### A5. Reactions (APP-05/10)

| Intent | Guard | Scope and terminal confirmation |
| --- | --- | --- |
| line off | current line addressable; not another pending intent | this task only; refreshed line disabled/cancelled |
| line on | not started, not stopped/pause-cancelled | same line; fresh revision permits reenabling |
| Stop | preparation addressable | this preparation; guidance has independent lifecycle |
| pause | household selected | new household proactive work; already running lifecycle/restore remain visible |
| resume | paused and current revision known | future eligibility only; cancelled version does not silently revive |

Intent states are `idle -> persisted_pending -> sending -> acknowledged ->
confirmed`; timeout enters `uncertain`, definite rejection enters `failed`.
App MUST show uncertainty and refresh current state before retrying. It MUST NOT
optimistically mark physical completion. All lines off MUST NOT imply Stop.
The App MUST keep separate action/scope and failure messages for line, Stop and
pause. Idempotency keys MAY be transmitted only where the selected external
contract supports them; App MUST NOT invent a team header/field. Without such
support uncertain controls require reconciliation rather than blind retry.

## 11. WHY, guidance, history and memory

<a id="a6"></a>
### A6. Rationale

WHY MUST read the captured episode rationale and show order/calendar basis,
preparation reasons, device/room choice and actual execution outcomes. Historical
WHY MUST NOT trigger new inference. Missing rationale shows unavailable without
fabricated explanation; cached rationale MUST carry its version/freshness.

<a id="a7"></a>
### A7. Item guidance

Guidance states are unreleased, released, closed/expired, unknown. It MUST be
hidden as active instruction before release, appear on brought-in release and
close on its own end condition. For the selected item-guidance contract, App MUST
render the Server/Home-provided first-open +2h or release +12h closure across
re-entry; it MUST NOT invent local device timers or infer expiry from a stale
cache. Preparation Stop MUST NOT delete independent
guidance. Device presentation outcome and guidance text MUST be distinguishable.

<a id="a9"></a>
### A9. History and this-home memory (APP-15)

History MUST group dated episode/preparation results without relabelling old
results from today's device state. Memory MUST display stored context/provenance,
support deletion request and refresh before claiming deletion. Offline deletion
MUST remain pending or fail visibly. Neither manual override nor a local card
can become permanent global preference or execution authority.

## 12. Refresh, concurrency and retry algorithms

There MUST be one ordered refresh coordinator per active household. Concurrent
resume/timer/control refreshes SHOULD coalesce. Each refresh captures environment,
household and generation; a response whose generation is no longer active MUST
be ignored. Source revisions/cursors MUST be persisted only with the corresponding
fully parsed snapshot. A cursor MUST NOT advance on malformed/partial response.
Card `(id, revision)` or documented `(id, updated_at)` ordering MUST reject stale
responses. A wall-clock timestamp MUST NOT override an explicit server version.

```text
refresh():
  capture session + generation
  fetch household + cards through product port
  validate complete typed snapshot and scope
  if generation obsolete: discard
  persist snapshot and cursor atomically
  publish state; process notification dedup keys
```

Read failures MAY retry with bounded backoff (1, 2, 4, 8, up to 30 seconds) and
user retry; malformed/auth errors require explicit handling. Existing private
adapter timeouts are 12 seconds per request/read and 20 seconds for uploads;
platform release settings MUST remain configurable and tested. Repeated polling
failure MUST preserve last known values with stale/offline presentation. Mutating
operations MUST NOT automatically retry unless their contract identity makes
repetition safe. Disposal MUST stop timers and reject late widget updates.

## 13. Notifications and calendar

Notification permission states are unknown/requesting/granted/denied/revoked/
unsupported. Only explicit user action requests permission. On first notify=true
card version, App MUST deduplicate by environment/household/card id/updated_at
or source revision, persist the successful delivery key, and open the correct
card on tap after normal setup/auth reconciliation. A delivery failure MUST not
write a success key. Local notification polling is bounded by app lifecycle;
this specification does not claim guaranteed background push.

Calendar MUST request least required read-only permission and send only event
id/start/end/title through the selected APP-03 adapter. It MUST exclude cancelled
entries, bound its read window/pagination and preserve last successful sync time.
The contract window is now through 14 days ahead. Permission denial/revocation,
OAuth misconfiguration, pagination failure and network failure mean time context
unavailable; they MUST NOT mean no intent/event. Server owns allowed-tag classification and title disposal under APP-03; App
MUST NOT claim that forwarding titles implements that Server duty. Tokens stay with the native
Google SDK/secret-store boundary, never in logs/cache. Disconnect MUST revoke/
clear local references and update Server state when supported. Real consent,
revocation and OS lifecycle need separate native qualification.

## 14. Security, privacy and observability

Private inbox/cache storage MUST use platform-private locations and exclude raw
images, tokens, keys and calendar titles from ordinary logs/evidence. Secret-store
implementation MUST use OS protected storage; unsupported targets expose an
explicit unavailable port. Fixture mode MUST never require production credentials.
Malformed links/URLs and foreign household identifiers MUST be rejected. Logout
MUST stop network workers before clearing credentials and isolate residual work.

Diagnostics SHOULD expose environment, application revision, cache age, queued
intake count, pending control count, last successful refresh and redacted error
category. Bounded evidence MUST record command, revision, platform and observed
claim; screenshots MUST omit secrets/raw customer data. Logs MUST NOT upgrade a
fixture or native source test into physical proof.

## 15. Ports and conversion ownership

| Port | Contract | Adapter owner |
| --- | --- | --- |
| ProductDataSource | typed household/cards/rationale/history/memory snapshots | App adapters/server or adapters/local |
| OrderIntake | ordered images + durable source id -> accepted episode identity | Server/private peer conversion only |
| Control | distinct typed intent -> acknowledgement/rejection/current projection | team Server contract adapter |
| LocalState | load/save versioned typed cache and session | core persistence implementation |
| ShareInbox | typed queued intake, persist, acknowledge, resume | Android/iOS platform bridge |
| Notifications | permission, deliver idempotent notice, card deep link | OS plugin adapter |
| Calendar | consent, bounded typed events, sync status | Google native adapter + Server conversion |
| SecretStore/Provisioning | opaque credential reference and explicit provision result | protected OS storage / unresolved joint protocol |

Generated team DTOs MUST remain inside the Server adapter. A private fixture
adapter is not APP contract conformance. App↔Hub local wire MUST NOT be declared
by introducing these internal ports.

## 16. Recommended modules and migration rules

The target layout separates `bootstrap/`,
`core/{domain,persistence,errors,clock}/`,
`features/{onboarding,orders,preparations,rationale,history,settings}/`,
`adapters/{server,fixture}/`, and
`platform/{share,notifications,calendar,secure_storage}/`. `main.dart` is the
process entry. Structural changes MUST update imports/resources/tests and preserve
the selected Android package, method-channel name, iOS App Group and inbox schemas.
A framework is not required: standard Flutter state/controller injection is
sufficient. No second App implementation tree or fixture import into production
domain may be introduced. The fixture adapter is selected in composition only.

## 17. Acceptance catalogue

Tests below are normative target exits, not a declaration that they all pass.
Each test MUST run independently of a real Server using adapter fakes except
explicit native/selected-contract qualification.

| ID | Initial state | Input | Observation and exit |
| --- | --- | --- | --- |
| APP-AT-01 | empty local store; fixture profile | boot | storage opens, typed state renders one preparation with fixture qualifier; no network needed |
| APP-AT-02 | cached fixture state | destroy/recreate controller/process | same household/card identities and state; no duplicate seed or effect |
| APP-AT-03 | clean product setup | create household, interrupt each checkpoint, re-enter | progress preserved, no repeated creation, unresolved provisioning remains explicit |
| APP-AT-04 | discovered devices | register/exclude with limited commands | only explicit choices saved; stale revision prompts review; virtual distinction remains |
| APP-AT-05 | unconfirmed household, native share queued | confirm then upload | 1–3 images in order, one stable source id, accepted episode stored before native ack |
| APP-AT-06 | server accepted but upload response lost | restart/retry same source | one episode identity, durable inbox retained until accepted ack |
| APP-AT-07 | upload active | second share + duplicate first share | serial two unique intakes, no duplicate upload worker; failure retains retry |
| APP-AT-08 | pending line and independent guidance | line off/on, Stop, pause/resume independently | distinct scope/intent; no line-on after start; guidance independent; cancelled work not revived |
| APP-AT-09 | current card version N | stale response N-1 and malformed newer response | UI/cache/cursor stay N, errors visible; late session response ignored |
| APP-AT-10 | cached card, network absent | resume/refresh | stale offline presentation, same last known evidence, retry available |
| APP-AT-11 | receipt accepted, no fresh effect | render results | unknown/partial rather than completed; USER label only with USER evidence |
| APP-AT-12 | no notification consent, notify card | deny then grant and refresh/restart | no notice before grant, once per card version after success; tap resolves safe card route |
| APP-AT-13 | calendar disconnected | deny, token fail, cancelled event, paginated read | minimum fields/window, no secret log, unavailable distinct from empty schedule |
| APP-AT-14 | past episode, stored rationale/memory | WHY, delete memory with failed then successful readback | no inference call, failure visible, deletion only confirmed after refresh |
| APP-AT-15 | Android/iOS private inbox populated | kill activity/app/extension during copy/upload/ack | committed image survives, partial write ignored, ack only after accepted identity |
| APP-AT-16 | card active with large text/screen reader | navigate/control/deep link | labels, logical focus, visible status, operable targets and correct household scope |
| APP-AT-17 | pinned generated contract models and isolated credential | execute APP contract cases on each qualified platform | exact conversion/auth matches the repository contract; native release/export evaluated separately |

Domain tests own validation/identity/ordering/control guards. Widget tests own
view/navigation/error/pending/accessibility states. Adapter tests own wire,
malformed input, persistence and source identity. Native tests own Android/iOS
process recreation, permission, share/picker and notification delivery. Integration
tests own independent peer/App/Home/world observation with bounded claims.

## 18. Extension points and unsupported behavior

Additional episodes/devices MUST extend typed adapters rather than hardcoded
fixture-specific UI branches. New persistent fields require additive migration. Offline
commands, new provisioning protocols, actual push delivery, Server inference,
KB memory creation, device control from App and broad physical equivalence are
not implied by the skeleton. Unsupported behavior MUST produce explicit errors,
not success-shaped fixtures.
