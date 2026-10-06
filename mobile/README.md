# Jamii Pulse CHP app

Flutter app for Community Health Promoters: tap a category and/or record a short voice
note, send it (now or when there is network), and see what officers did about it.

- **Offline first.** Reports are saved in a local SQLite database (Drift) and pushed by a
  sync queue (`lib/data/sync_service.dart`) with backoff. Each report carries a client id,
  so a retry never creates a duplicate on the server.
- **Kiswahili first, English too.** Strings live in `lib/l10n/app_sw.arb` and `app_en.arb`;
  a test fails if the two drift apart.
- **Privacy notice before first use**, with the three promises (never used to discipline,
  you will hear back, you can ask for removal). Accepting it is recorded on the server.
- **Nothing lingers on the phone.** Voice notes are deleted once uploaded; the local copy of
  the text is replaced by the server's redacted version; log out wipes everything.
  `android:allowBackup="false"` keeps data out of cloud backups outside Kenya.

## Run

```bash
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

`10.0.2.2` is the dev machine as seen from the Android emulator; start the API with
`python scripts/dev_server.py` from the repository root. Debug builds allow plain HTTP;
release builds need HTTPS.

## Test

```bash
flutter analyze
flutter test
```

Offline and flaky-network behaviour is covered by `test/sync_service_test.dart`; also test
it by hand on a low-end Android phone (airplane mode mid-upload, weak signal) before each
release. See `docs/runbooks/release.md`.

## Release builds

`flutter build apk --release --dart-define=API_BASE_URL=https://<your domain>`. Before the
pilot, set up a release signing key (`android/key.properties`, never committed) and
distribute the APK through the county's channel or a private Play track.

`pubspec.yaml` pins `analyzer` below 14.5 for code generation only, because build_runner
2.16.1 does not yet work with analyzer 14.5. Remove the override when build_runner is fixed.
