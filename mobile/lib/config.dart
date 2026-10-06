/// Build-time settings. Pass with --dart-define, for example:
///   flutter build apk --dart-define=API_BASE_URL=https://pulse.example.go.ke
const String apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000', // the Android emulator's view of the dev machine
);

/// The privacy notice bundled with this build. It must match the server's
/// JAMII_CONSENT_VERSION; a new notice needs a new app release.
const String noticeVersion = '2026-10-v1';

/// Longest voice note the app records. The guidance is about 30 seconds.
const Duration maxVoiceNote = Duration(seconds: 60);
