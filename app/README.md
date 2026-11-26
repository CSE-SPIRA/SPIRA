# App

Status: ACTIVE. This is the entry point for running and testing SPIRA's Android
App. [App behavior and acceptance](spec.md) and
[shared payloads](../contracts/README.md) have their own specifications.

Main shows a submitted order and its preparation cards. Calendar shows Google
events and closed preparations. Our Home manages household types and Google
connection. First-run setup gives the user a code to enter on the Hub.

## Run locally

Use Flutter and the Android SDK. Start the
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
first-run setup. Share one to three JPG or PNG screenshots from Android or
choose them from Main.

To enable Google Calendar, register `org.cse_spira.spira_app` and the signing
SHA-1 as an Android OAuth client, enable Calendar API, and set the Web client
ID in `SPIRA_GOOGLE_CLIENT_ID`. Connected events are read from the primary
calendar for 14 days and synced to the Server.
[Flutter Android sign-in setup](https://pub.dev/packages/google_sign_in_android)

## Local preview

From the repository root, use `app/scripts/browser-demo` for the fixture
preview. It requires Flutter, Python, `uv`, and `mosquitto`. The preview
includes a bundled sample order. Android share and Google sign-in require
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
- There is no App device route. Our Home and the onboarding device step
  show the connection state.
- Episode history omits card start and end timestamps. Calendar can locate
  a closed preparation by a start previously supplied by the card poll.
  Memory content comes from fresh episode and rationale reads.
