import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Small values that outlive the app process: the token (encrypted at rest), the notice the
/// CHP accepted, their language, and a cached profile for offline starts.
abstract class SessionStore {
  Future<String?> read(String key);
  Future<void> write(String key, String? value);
  Future<void> clear();
}

abstract final class Keys {
  static const token = 'token';
  static const noticeVersion = 'notice_version';
  static const language = 'language';
  static const me = 'me';
}

class SecureSessionStore implements SessionStore {
  const SecureSessionStore([this._storage = const FlutterSecureStorage()]);
  final FlutterSecureStorage _storage;

  @override
  Future<String?> read(String key) => _storage.read(key: key);

  @override
  Future<void> write(String key, String? value) =>
      value == null ? _storage.delete(key: key) : _storage.write(key: key, value: value);

  @override
  Future<void> clear() async {
    final language = await read(Keys.language);
    await _storage.deleteAll();
    await write(Keys.language, language); // keep the language for the next person to log in
  }
}

class MemorySessionStore implements SessionStore {
  final Map<String, String> values = {};

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String? value) async => value == null ? values.remove(key) : values[key] = value;

  @override
  Future<void> clear() async => values.removeWhere((k, _) => k != Keys.language);
}
