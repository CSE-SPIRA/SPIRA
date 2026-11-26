# App

Status: ACTIVE. This is the entry point for running and testing SPIRA's Android
App. [App behavior and acceptance](spec.md) and
[shared payloads](../contracts/README.md) have their own specifications.

[Screen reference](screens.md)

Main shows the Server's progress and the full order until its preparation card
arrives. Cards and known episode history stay available when the Server has no
episode list. Tap the order
summary to see items and guidance. The final memory stays on Main until
**확인** or a new accepted order. Its Calendar marker remains available.
Calendar shows a month of events and memory markers. Select a day to see its
agenda and open a memory. Our Home shows rooms with devices, controls for
matching preparation lines, household types, and Google connection.

## Run locally

Use Flutter 3.50 and the Android SDK. Start the
[contract fixture Server](../hub/README.md#contract-fixture-server) from the same
checkout. In a local `.env` under `app/`, set `SPIRA_BASE_URL` to its
Android-accessible origin and `SPIRA_PEER=fixture`. Use `SPIRA_PEER=server`
for a qualified team Server. An Android emulator can reach a local peer
through `10.0.2.2`. Debug builds allow HTTP.

```sh
flutter run -d <android-device-id> --dart-define-from-file=.env
```

If the peer requires authentication, enter the App bearer token via the
toolbar key. Set `SPIRA_HOUSEHOLD_ID` to open the household created by
`server/scripts/demo_home.py` directly. The App needs the Server URL and App
credentials to open that household. Set `SPIRA_FIRST_RUN=1` to run onboarding
even with a configured household.
Share one to three JPG or PNG screenshots from Android or
choose them from **주문 분석하기** on Main. During onboarding, copy the
connection code and enter it on the home Hub.

To enable Google Calendar, register `org.cse_spira.spira_app` and the signing
SHA-1 as an Android OAuth client, enable Calendar API, and set the Web client
ID in `SPIRA_GOOGLE_CLIENT_ID`. Connected events are read from the primary
calendar for 14 days and synced to the Server. Disconnect Google from **우리 집**
to replace the synchronized list with **예시 일정**. Fixture and preview use
the replay dates. With `SPIRA_PEER=server`, the sample birthday starts 20
minutes after the first cards response's `server_time` and lasts one hour.
The App sends the events and keeps the anchor for that household across
restarts. When the birthday has ended or starts in less than 10 minutes, a
cards refresh renews the sample if no card is open. The Server tags the
events after accepting the calendar.
[Flutter Android sign-in setup](https://pub.dev/packages/google_sign_in_android)

## Local preview

From the repository root, use `app/scripts/browser-demo` for the fixture
preview. It requires Flutter, Python, `uv`, and `mosquitto`. The launcher
starts or reuses the demo stack and connects the App preview to the fixture
Server. Use **예시 주문으로 공유** or **주문 분석하기** to send an order.
Use `--build-serve` to serve a built preview. Add `--first-run` to start
onboarding from an empty App, including when the fixture already has a
household. The first-run build skips Google, collects household types, shows
the connection code, and lets the user review the sample devices before
saving.

```sh
app/scripts/browser-demo --build-serve --first-run
```

With sample schedules, Calendar opens to the fixture's birthday month.
**오늘** jumps to the current month. Android share and Google sign-in require
Android.

## Tests

From `app/`:

```sh
flutter test
flutter analyze --no-pub
```

Widget and unit tests use typed fake Server responses. Android delivery and
TalkBack require an Android runtime.

## Contract boundaries

- Android share redelivery is identified by its ordered content URIs and
  bytes. Gallery selection uses a distinct source identity per selection.
- Our Home and onboarding show the fixed installation as **예시 집** with
  delegation disabled. The inventory test compares the bundled device IDs,
  types, rooms, and names with the Hub example installation.
- **끄기** on a device sends the matching card's line reaction to the Server.
  The App keeps accepted reactions pending until a card refresh confirms them.
  A reaction 404 restores the control and shows a message.
- A missing episode list falls back to direct reads of shared and known
  episodes. The App waits 60 seconds before trying the list again.
- Episode history omits card start and end timestamps. Calendar can locate
  a closed preparation by a start supplied by the card poll, or by the share
  day when the App never saw the card.
  Memory content comes from fresh episode and rationale reads.
