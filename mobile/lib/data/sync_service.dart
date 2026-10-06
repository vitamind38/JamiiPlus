import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:drift/drift.dart';

import 'api_client.dart';
import 'database.dart';

/// What one sync pass did, for the UI and for tests.
class SyncResult {
  int uploaded = 0;
  int failed = 0;
  int waiting = 0;
  bool offline = false;
  bool unauthorized = false;
  bool consentRequired = false;
  bool pulled = false;
}

/// The offline queue. Reports are saved on the phone first; this pushes them up, oldest
/// first, with backoff, and then pulls back what officers have done.
///
/// Uploads are idempotent: each report carries its client id, so a retry after a dropped
/// connection never creates a second report on the server.
class SyncService {
  SyncService(this.db, this.api, {DateTime Function()? clock, this.deleteAudioAfterUpload = true})
    : _clock = clock ?? DateTime.now;

  final AppDatabase db;
  final ApiClient api;
  final DateTime Function() _clock;
  final bool deleteAudioAfterUpload;
  Future<SyncResult>? _running;

  /// Waits for 2, 4, 8 ... minutes between attempts, capped at six hours.
  static Duration backoff(int attempts) => Duration(minutes: min(pow(2, attempts).toInt(), 360));

  /// One pass. Concurrent callers share the pass already in flight.
  Future<SyncResult> sync() => _running ??= _sync().whenComplete(() => _running = null);

  Future<SyncResult> _sync() async {
    final result = SyncResult();
    for (final report in await db.dueForUpload(_clock())) {
      try {
        final server = await api.submitReport(
          clientId: report.clientId,
          language: report.language,
          reportedAt: report.createdAt,
          themeCode: report.themeCode,
          text: report.body,
          audioPath: await _existingAudio(report.audioPath),
        );
        await db.updateReport(
          report.clientId,
          LocalReportsCompanion(
            syncState: const Value(SyncState.synced),
            serverId: Value(server.id),
            status: Value(server.status),
            channel: Value(server.channel),
            hasAudio: Value(server.hasAudio),
            body: Value(server.text), // the redacted text the server stored
            lastError: const Value(null),
            audioPath: Value(deleteAudioAfterUpload ? null : report.audioPath),
          ),
        );
        if (deleteAudioAfterUpload) await _deleteAudio(report.audioPath);
        result.uploaded++;
      } on OfflineException catch (e) {
        await _retryLater(report, e.message);
        result.offline = true;
        break; // no network: the rest would fail the same way
      } on RetryLaterException catch (e) {
        await _retryLater(report, 'HTTP ${e.status}');
        result.waiting++;
        break;
      } on UnauthorizedException {
        result.unauthorized = true;
        return result;
      } on ConsentRequiredException {
        result.consentRequired = true;
        return result;
      } on RejectedException catch (e) {
        await db.updateReport(
          report.clientId,
          LocalReportsCompanion(
            syncState: const Value(SyncState.failed),
            lastError: Value('${e.status}: ${e.message}'),
          ),
        );
        result.failed++;
      }
    }
    if (!result.offline) await _pull(result);
    return result;
  }

  Future<void> _pull(SyncResult result) async {
    try {
      for (final r in await api.myReports()) {
        await db.mergeFromServer(
          serverId: r.id,
          clientId: r.clientId,
          channel: r.channel,
          themeCode: r.themeCode,
          body: r.text,
          hasAudio: r.hasAudio,
          status: r.status,
          createdAt: r.createdAt,
          responsesJson: jsonEncode(r.responses),
        );
      }
      result.pulled = true;
    } on UnauthorizedException {
      result.unauthorized = true;
    } on ApiException {
      result.offline = true;
    }
  }

  Future<void> _retryLater(LocalReport report, String error) => db.updateReport(
    report.clientId,
    LocalReportsCompanion(
      attempts: Value(report.attempts + 1),
      nextAttemptAt: Value(_clock().add(backoff(report.attempts + 1))),
      lastError: Value(error),
    ),
  );

  Future<String?> _existingAudio(String? path) async => path != null && await File(path).exists() ? path : null;

  Future<void> _deleteAudio(String? path) async {
    if (path == null) return;
    final f = File(path);
    if (await f.exists()) await f.delete();
  }
}
