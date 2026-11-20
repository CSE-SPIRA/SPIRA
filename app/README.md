# App

Owner: Yejoon Kim

SPIRA's Android app receives shared order screenshots, shows the Server's
preparation cards and rationale, and sends card Stop, line off/on, and household
pause/resume. Settings contains this-home memory and case deletion.

## Run locally

Use Flutter 3.50 and the Android SDK. Start the contract fixture Server from its
own checkout using the Hub owner's launcher and expose its App API to Android.
For G0, that process belongs to `hub/tests/fixture_server`. The App has no
bundled fixture Server. The fixture launch command is provided with H10-R1.

From `app/`, set `SPIRA_BASE_URL` in a local `.env` to the peer's Android-accessible
origin. Set `SPIRA_PEER=fixture` for H10-R1 or `SPIRA_PEER=server` for a team Server
profile. Emulator hosts use `10.0.2.2` for a peer bound to the development
machine. A connected physical device needs a reachable address. HTTP is enabled
in debug builds.

```sh
flutter run -d <android-device-id> --dart-define-from-file=.env
```

If the peer returns 401, open the key button and enter the App's bearer token
for that session. The token stays in memory. Keep tokens out of the Dart defines.
Use Android's share menu to send one to three JPG or PNG screenshots to SPIRA.

Optional Dart defines:

- `SPIRA_HOUSEHOLD_ID` opens an already created household, useful for a scripted
  fixture demo. Omit it to exercise initial setup.
- `SPIRA_DISCOVERY_JSON` supplies a C-2 device manifest for reviewing available
  actions. The demo can use `contracts/fixtures/ep_9031/devices.json`.
  In **우리 집**, opened from a preparation card, the manifest for the current
  household also supplies devices outside that card's rationale. Without it,
  the view shows the card's selected devices by room. Setup selections stay on
  this device. The App contract has no discovery or delegation-publishing route.
- `SPIRA_GOOGLE_CLIENT_ID` enables Google Calendar setup. Register
  `org.cse_spira.spira_app` and the build's signing SHA-1 as an Android OAuth
  client, enable Calendar API, and set the Web client ID used by the Android
  sign-in plugin. After connection, the App rereads primary-calendar events
  for now through the next 14 days at startup, on return to the foreground,
  and from **캘린더 다시 보내기** in settings. It sends the full list when it
  changes, including while automatic preparation is paused. The App saves only
  the connection flag and the last accepted list's hash for calendar sync.
  [Flutter Android sign-in setup](https://pub.dev/packages/google_sign_in_android)
  [Google Calendar events API](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)

## Checks

```sh
flutter test
flutter analyze
flutter build apk --debug
```

The Flutter tests drive the UI and typed HTTP client with small in-test peers.
They read the shared fixture payloads directly. Build verification covers the
Android manifest, Kotlin share inbox and notification bridge. Android share
delivery, process recreation, and TalkBack still require an Android runtime.

## Contract boundaries

- Android share intents have no delivery ID. The inbox uses the ordered content
  URIs and image bytes to identify redelivery. Sharing the exact same URIs with
  the exact same bytes is indistinguishable from redelivery. A newly captured
  screenshot can be shared again after a read failure. Pending uploads bind to
  the first ready profile and household that takes them.
- C-6 carries no explicit line-start history or planned end condition.
  Interventions use the supplied line state and previously observed starts.
  Missing guidance release and closure fields are projected from item task
  states and the episode's `closed` status. The App consumes only App API data.
- The App displays the Server's per-line `end_state` and `note`.
  Device-level restore items, including `withheld_end_not_observed`, travel
  from the Hub to the Server in C-4. A card line reports `withheld` when the
  Server projects that outcome.
- App API has no pause status read route. Settings uses the last successful
  pause/resume response and shows an unknown state before one is available.
- Creating a household returns a one-time Hub key. Hub provisioning and
  publishing delegation require an agreed handoff. The App does not contact the
  Hub or the Simulator.
