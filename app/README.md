# App

Status: ACTIVE. This is the entry point for running and testing SPIRA's Android
App. [App behavior and acceptance](spec.md) and
[shared payloads](../contracts/README.md) have their own specifications.

Main expands the order until a preparation card arrives, then puts the card
first and keeps the final memory until acknowledgment or a new order. Calendar
shows a month of events and memory markers. Our Home shows the sample device
inventory and the controls for matching preparation lines, along with
household types and Google connection.

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
toolbar key. `SPIRA_HOUSEHOLD_ID` opens an existing household. Omit it for
first-run setup, or set `SPIRA_FIRST_RUN=1` in a fixture or preview build.
Share one to three JPG or PNG screenshots from Android or
choose them from **주문 분석하기** on Main. During onboarding, copy the
connection code and enter it on the home Hub.

To enable Google Calendar, register `org.cse_spira.spira_app` and the signing
SHA-1 as an Android OAuth client, enable Calendar API, and set the Web client
ID in `SPIRA_GOOGLE_CLIENT_ID`. Connected events are read from the primary
calendar for 14 days and synced to the Server. Disconnect Google from **우리 집**
to replace the synchronized list with sample events in fixture and preview
builds, or clear it in production. When Google is disconnected, fixture and
preview builds display the bundled events as **예시 일정** and sync them to the
Server.
[Flutter Android sign-in setup](https://pub.dev/packages/google_sign_in_android)

## Local preview

From the repository root, use `app/scripts/browser-demo` for the fixture
preview. It requires Flutter, Python, `uv`, and `mosquitto`. The launcher
starts or reuses the demo stack and connects the App preview to the fixture
Server. Use **예시 주문으로 공유** or **주문 분석하기** to send an order.
Use `--build-serve` to serve a built preview. Android share and Google sign-in
require Android.

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
- There is no App device route. Our Home and the onboarding device step
  show the fixed installation as **예시 집** with delegation disabled.
- Episode history omits card start and end timestamps. Calendar can locate
  a closed preparation by a start supplied by the card poll, or by the share
  day when the App never saw the card.
  Memory content comes from fresh episode and rationale reads.
