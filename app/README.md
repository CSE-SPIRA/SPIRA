# App

Owner: Yejoon Kim

SPIRA's Android app receives shared order screenshots, shows the Server's
preparation cards and rationale, and sends card Stop, line off/on, and household
pause/resume. Settings contains this-home memory and case deletion.

## Run locally

Use Flutter 3.50 and the Android SDK. Start the contract fixture Server from
the same checkout and expose its App API to Android. See the
[fixture Server command in the Hub README](../hub/README.md#contract-fixture-server).

From `app/`, set `SPIRA_BASE_URL` in a local `.env` to the peer's Android-accessible
origin. Set `SPIRA_PEER=fixture` for H10-R1 or `SPIRA_PEER=server` for a team Server
profile. Emulator hosts use `10.0.2.2` for a peer bound to the development
machine. A connected physical device needs a reachable address. HTTP is enabled
in debug builds.

```sh
flutter run -d <android-device-id> --dart-define-from-file=.env
```

If the peer returns 401, choose **서버 접속 토큰 입력** in **설정** and enter the
App's bearer token. During initial setup, use the key button in the toolbar.
Android saves the server token and home key in the app's local settings.
Clearing the app's storage removes both saved values.
Use Android's share menu to send one to three JPG or PNG screenshots to SPIRA.

Optional Dart defines:

- `SPIRA_HOUSEHOLD_ID` opens an already created household, useful for a scripted
  fixture demo. Omit it to exercise initial setup.
- `SPIRA_DISCOVERY_JSON` supplies a C-2 device manifest for reviewing available
  actions in setup. Setup selections stay on this device.
- `SPIRA_HUB_URL` supplies the Hub's HTTP(S) origin. Enter the home key from
  **우리 집 접속 키 입력** in **설정**. The App also uses the key returned
  when it creates a new home.
  **우리 집** reads the Hub's devices by room and marks those used by the card
  and the order's item tasks. If the Hub list is unavailable, it shows the
  identified devices with a note.
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

### Run the live demo on Android

From the repository root, start the fixture and Hub on fixed ports.

```sh
scripts/demo-up --no-shell --no-app --peer-ports 58137 58138 58139
```

Connect the Android phone over USB. From `app/`, forward both ports and build
the debug APK with the fixture credentials.

```sh
adb reverse tcp:58137 tcp:58137
adb reverse tcp:58139 tcp:58139
fixture_app_token="$(python3 -B -c 'from scripts.browser_demo_web import APP_TOKEN; print(APP_TOKEN)')"
fixture_home_key="$(python3 -c 'import json; print(json.load(open("../contracts/fixtures/ep_9031/household.created.json"))["hub_api_key"])')"
flutter build apk --debug \
  --dart-define=SPIRA_BASE_URL=http://127.0.0.1:58137 \
  --dart-define=SPIRA_HUB_URL=http://127.0.0.1:58139 \
  --dart-define=SPIRA_PEER=fixture \
  --dart-define=SPIRA_HOUSEHOLD_ID=h_042 \
  --dart-define=SPIRA_FIXTURE_APP_TOKEN="$fixture_app_token" \
  --dart-define=SPIRA_HOME_KEY="$fixture_home_key"
adb install -r build/app/outputs/flutter-apk/app-debug.apk
```

Use the printed **Fixture** and **Hub** ports if reusing a stack on different
ports. Sharing an order starts the birthday replay. **우리 집** reads the Hub
inventory using the home key. Saved Android credentials take precedence over
build-time defaults. A `SPIRA_PEER=server` build includes credentials only
when explicitly supplied through the defines.

### Run in the browser

Run the App, Hub, Simulator, and fixture Server from one checkout. The launcher
needs Python 3.9+, `uv`, `mosquitto`, Flutter, and Chrome for hot reload.
Run the following command from the repository root.

```sh
app/scripts/browser-demo
```

Add `--build-serve` for a headless build served at `http://127.0.0.1:8732/`.
The launcher defaults `--checkout` to the repository root containing the script.
It starts the local fixture stack and proxy and supplies the committed fixture
placeholders, so you can skip both token dialogs.
Press Ctrl-C to stop the processes the launcher started.

For a running stack, use the **App preview** command printed by `demo-up`.
It passes the stack's URL file to `--stack-log`. Use `--demo-port`, `--proxy-port`, and `--web-port` to change
the defaults of 8730, 8731, and 8732.

Click **예시 주문으로 공유** in the **미리보기** strip above the tab bar to see
the screenshot scan, extracted items, and preparation card. Tap **자세히** for the
order story or a preparation line for its timing and results. Open **우리 집**
to browse the room grids. The preview uploads the bundled PNG
to `POST /v1/orders` and skips Android sharing and Google Calendar. The web build
serves it at `/assets/assets/example-order.png`.

#### Manual fallback

Start the fixture stack from the repository root.

```sh
scripts/demo-up --no-shell
```

From `app/` in the same checkout, start the local proxy so Chrome can reach
the fixture and Hub. Replace the example URLs with the **Fixture** and **Hub**
lines printed by `demo-up`. The `/health` suffix is OK.

```sh
python3 scripts/browser_demo_proxy.py \
  --fixture http://127.0.0.1:49151/health \
  --hub http://127.0.0.1:49152/
```

From `app/` in another terminal, run Flutter and keep it open for hot reload.

```sh
flutter run -d chrome --web-hostname 127.0.0.1 --web-port 8732 \
  --dart-define=SPIRA_BASE_URL=http://127.0.0.1:8731 \
  --dart-define=SPIRA_HUB_URL=http://127.0.0.1:8731 \
  --dart-define=SPIRA_HOUSEHOLD_ID=h_042 \
  --dart-define=SPIRA_PEER=fixture
```

Enter the fixture placeholder `demo` under **서버 접속 토큰 입력**. Under
**우리 집 접속 키 입력**, enter the fixture home's `hub_api_key` from
`contracts/fixtures/ep_9031/household.created.json`. Keep both tokens out of Dart
defines for manual and real-server runs.

## Tests

```sh
flutter test
flutter analyze
flutter build web
flutter build apk --debug
```

The Flutter tests drive the UI and typed HTTP client with small in-test peers.
They read the shared fixture payloads directly. Build verification covers the
Android manifest, Kotlin share inbox and notification bridge. Android share
delivery, process recreation, and TalkBack still require an Android runtime.

## Where to change what

| Change | File |
| --- | --- |
| Shared design and vocabulary | [`design/`](../design/README.md) |
| App theme | [`theme.dart`](lib/theme.dart) |
| Tabs and app shell | [`main.dart`](lib/main.dart) |
| Current and past preparations | [`preparations.dart`](lib/features/preparations.dart) |
| Order scan and extracted items | [`order_extraction.dart`](lib/features/order_extraction.dart) |
| Order story and line details | [`order_story.dart`](lib/features/order_story.dart), [`order_story_details.dart`](lib/features/order_story_details.dart) |
| Full evidence and order judgment preview | [`rationale.dart`](lib/features/rationale.dart) |
| 우리 집 | [`our_home.dart`](lib/features/our_home.dart) |
| Settings and connection keys | [`settings.dart`](lib/features/settings.dart) |
| Labels | [`labels.dart`](lib/features/labels.dart) |

## Contract boundaries

- Android share intents have no delivery ID. The inbox uses the ordered content
  URIs and image bytes to identify redelivery. Sharing the exact same URIs with
  the exact same bytes is indistinguishable from redelivery. A newly captured
  screenshot can be shared again after a read failure. Pending uploads bind to
  the first ready profile and household that takes them.
- C-6 carries no explicit line-start history or planned end condition.
  Interventions use the supplied line state and previously observed starts.
  Missing guidance release and closure fields are projected from item task
  states and the episode's `closed` status. The App consumes App API data
  for preparation and execution state.
- The App displays the Server's per-line `end_state` and `note`.
  Device-level restore items, including `withheld_end_not_observed`, travel
  from the Hub to the Server in C-4. A card line reports `withheld` when the
  Server projects that outcome.
- App API has no pause status read route. Settings uses the last successful
  pause/resume response and shows an unknown state before one is available.
- The App reads `/home/onboarding/devices` with the home key. Hub provisioning
  and publishing delegation require a separate handoff.
