# App

Owner: Yejoon Kim

Flutter app: share order screenshots, show the preparation card, stop or switch
off lines, and show results. See [`spec.md`](spec.md) for the complete target.

The current walking skeleton implements only the server-free product-state
floor: immutable preparation values, an environment/household-scoped cache, a
typed fixture source, cache-first refresh, stale fallback, and a read-only
preparation surface. The fixture qualifier is always visible. It does not
implement image intake, controls, native lifecycle, Server interoperability, or
Android/iOS qualification.

This repository currently contains a Flutter package rather than generated
platform directories. With a compatible Flutter SDK available:

```bash
flutter pub get
flutter test
```

`pubspec.lock` and platform scaffolding must be added and reviewed with the
first platform-qualified build before `flutter run`; this source-only slice
does not make that claim.
