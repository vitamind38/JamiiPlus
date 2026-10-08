import 'dart:async';
import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import '../config.dart';
import '../data/api_client.dart';
import '../data/database.dart';
import '../data/session_store.dart';
import '../data/sync_service.dart';

enum Phase { loading, notice, login, updateApp, home }

/// The one place the app's screens read from and act through.
class AppState extends ChangeNotifier {
  AppState({required this.db, required this.api, required this.store, SyncService? sync})
    : sync = sync ?? SyncService(db, api);

  final AppDatabase db;
  final ApiClient api;
  final SessionStore store;
  final SyncService sync;

  Phase phase = Phase.loading;
  String language = 'sw';
  Me? me;
  List<CachedTheme> themes = const [];
  bool offline = false;
  int pending = 0;
  Timer? _timer;

  Stream<List<LocalReport>> get reports => db.watchReports();

  Future<void> start() async {
    language = await store.read(Keys.language) ?? 'sw';
    final cachedMe = await store.read(Keys.me);
    if (cachedMe != null) me = Me.fromJson(jsonDecode(cachedMe) as Map<String, dynamic>);
    themes = await db.themes();
    api.token = await store.read(Keys.token);
    if (await store.read(Keys.noticeVersion) != noticeVersion) {
      phase = Phase.notice;
    } else if (api.token == null) {
      phase = Phase.login;
    } else {
      phase = Phase.home;
      unawaited(refresh());
    }
    pending = await db.pendingCount();
    notifyListeners();
  }

  /// Sync now and every five minutes while the app is open.
  void startTimer() {
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(minutes: 5), (_) => refresh());
  }

  void stopTimer() => _timer?.cancel();

  @override
  void dispose() {
    stopTimer();
    super.dispose();
  }

  Future<void> setLanguage(String code) async {
    language = code;
    await store.write(Keys.language, code);
    notifyListeners();
    if (api.token != null) {
      try {
        me = await api.setLanguage(code); // SMS from officers come in this language too
        await store.write(Keys.me, jsonEncode(me!.toJson()));
      } on ApiException {
        // Offline: the phone's language changes now; the server learns at the next login.
      }
    }
  }

  Future<void> acceptNotice() async {
    await store.write(Keys.noticeVersion, noticeVersion);
    phase = api.token == null ? Phase.login : Phase.home;
    notifyListeners();
  }

  Future<String?> requestCode(String phone) => api.requestCode(phone);

  Future<void> verifyCode(String phone, String code) async {
    final (token, profile) = await api.verifyCode(phone, code);
    api.token = token;
    await store.write(Keys.token, token);
    await _setMe(profile);
    if (profile.language != language) await setLanguage(language);
    phase = phase == Phase.updateApp ? Phase.updateApp : Phase.home;
    notifyListeners();
    unawaited(refresh());
  }

  /// The CHP read this build's notice before logging in; record that on the server.
  Future<void> _setMe(Me profile) async {
    me = profile;
    if (profile.consentRequired) {
      if (profile.currentConsentVersion != noticeVersion) {
        phase = Phase.updateApp;
        notifyListeners();
        return;
      }
      me = await api.consent(noticeVersion);
    }
    await store.write(Keys.me, jsonEncode(me!.toJson()));
  }

  /// Push pending reports, pull statuses and themes. Safe to call any time.
  Future<void> refresh() async {
    if (api.token == null) return;
    final result = await sync.sync();
    if (result.unauthorized) return logout(remote: false);
    if (result.consentRequired) {
      try {
        await _setMe(await api.me());
      } on ApiException {
        // Try again next time.
      }
    }
    offline = result.offline;
    if (!offline) {
      try {
        final list = await api.themes();
        await db.replaceThemes([
          for (final (i, t) in list.indexed)
            CachedThemesCompanion.insert(code: t.code, labelEn: t.labelEn, labelSw: t.labelSw, position: i),
        ]);
        themes = await db.themes();
      } on ApiException {
        // Keep the cached list.
      }
    }
    pending = await db.pendingCount();
    notifyListeners();
  }

  /// Save on the phone first, then try to send. Works with no network at all.
  Future<void> submit({String? themeCode, String? text, String? audioPath}) async {
    await db.addReport(
      LocalReportsCompanion.insert(
        clientId: const Uuid().v4(),
        themeCode: Value(themeCode),
        body: Value(text?.trim().isEmpty ?? true ? null : text!.trim()),
        audioPath: Value(audioPath),
        hasAudio: Value(audioPath != null),
        language: language,
        createdAt: DateTime.now(),
        syncState: SyncState.pending,
      ),
    );
    pending = await db.pendingCount();
    notifyListeners();
    unawaited(refresh());
  }

  Future<void> withdraw(LocalReport report) async {
    if (report.serverId == null) {
      // Never left the phone: just delete it.
      await (db.delete(db.localReports)..where((r) => r.clientId.equals(report.clientId))).go();
    } else {
      final r = await api.withdraw(report.serverId!);
      await db.updateReport(report.clientId, LocalReportsCompanion(status: Value(r.status), body: const Value(null)));
    }
    pending = await db.pendingCount();
    notifyListeners();
  }

  String themeLabel(String? code) {
    for (final t in themes) {
      if (t.code == code) return language == 'sw' ? t.labelSw : t.labelEn;
    }
    return code ?? '';
  }

  Future<void> logout({bool remote = true}) async {
    if (remote) {
      try {
        await api.logout();
      } on ApiException {
        // The token expires on its own; the phone forgets it now either way.
      }
    }
    api.token = null;
    me = null;
    await store.clear();
    await db.wipe();
    phase = Phase.notice; // a shared phone: whoever logs in next reads the notice first
    pending = 0;
    notifyListeners();
  }
}
