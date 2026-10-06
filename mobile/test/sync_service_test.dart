import 'dart:io';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jamii_pulse/data/api_client.dart';
import 'package:jamii_pulse/data/database.dart';
import 'package:jamii_pulse/data/sync_service.dart';

import 'fakes.dart';

void main() {
  late AppDatabase db;
  late FakeApi api;
  late DateTime now;
  late SyncService sync;

  setUp(() {
    db = AppDatabase(NativeDatabase.memory());
    api = FakeApi()..token = 't';
    now = DateTime.utc(2026, 10, 6, 8);
    sync = SyncService(db, api, clock: () => now);
  });

  tearDown(() => db.close());

  Future<void> save(String id, {String? text = 'hakuna dawa', String? audio, DateTime? at}) => db.addReport(
    LocalReportsCompanion.insert(
      clientId: id,
      themeCode: const Value('stockout'),
      body: Value(text),
      audioPath: Value(audio),
      language: 'sw',
      createdAt: at ?? now,
      syncState: SyncState.pending,
    ),
  );

  test('uploads pending reports oldest first and marks them synced', () async {
    await save('b', at: now.add(const Duration(minutes: 1)));
    await save('a');
    final result = await sync.sync();
    expect(result.uploaded, 2);
    expect(api.calls.where((c) => c.startsWith('submit')), ['submit a', 'submit b']);
    final a = (await db.report('a'))!;
    expect(a.syncState, SyncState.synced);
    expect(a.serverId, isNotNull);
    expect(await db.pendingCount(), 0);
  });

  test('keeps the server\'s redacted text, not what was typed', () async {
    await save('a', text: 'Mama Wanjiku hakupata dawa');
    await sync.sync();
    expect((await db.report('a'))!.body, 'Mama [NAME] hakupata dawa');
  });

  test('offline: nothing is lost, retry waits, then succeeds without duplicating', () async {
    await save('a');
    await save('b', at: now.add(const Duration(seconds: 1)));
    api.failNextSubmit = const OfflineException('no route');
    final first = await sync.sync();
    expect(first.offline, isTrue);
    expect(api.calls.where((c) => c.startsWith('submit')).length, 1); // stops at the first network error
    final a = (await db.report('a'))!;
    expect(a.syncState, SyncState.pending);
    expect(a.attempts, 1);
    expect(a.nextAttemptAt!.toUtc(), now.add(const Duration(minutes: 2)));

    await sync.sync(); // too soon: 'a' waits; 'b' is due and goes
    expect((await db.report('a'))!.syncState, SyncState.pending);
    expect((await db.report('b'))!.syncState, SyncState.synced);

    now = now.add(const Duration(minutes: 3));
    await sync.sync();
    expect((await db.report('a'))!.syncState, SyncState.synced);
    expect(api.byClientId.length, 2);
  });

  test('a retry after the server already saved it does not create a second report', () async {
    await save('a');
    await api.submitReport(clientId: 'a', language: 'sw', reportedAt: now, themeCode: 'stockout');
    await sync.sync();
    expect(api.byClientId.length, 1);
    expect((await db.report('a'))!.syncState, SyncState.synced);
  });

  test('rejected reports are marked failed and not retried', () async {
    await save('a');
    api.failNextSubmit = const RejectedException(422, 'A report needs a voice note, a description or a category.');
    final result = await sync.sync();
    expect(result.failed, 1);
    final a = (await db.report('a'))!;
    expect(a.syncState, SyncState.failed);
    expect(a.lastError, contains('422'));
    await sync.sync();
    expect(api.calls.where((c) => c == 'submit a').length, 1);
  });

  test('server trouble backs off', () async {
    await save('a');
    api.failNextSubmit = const RetryLaterException(503, '');
    final result = await sync.sync();
    expect(result.waiting, 1);
    expect((await db.report('a'))!.syncState, SyncState.pending);
  });

  test('expired login stops the pass and reports it', () async {
    await save('a');
    api.failAllSubmits = const UnauthorizedException('');
    final result = await sync.sync();
    expect(result.unauthorized, isTrue);
    expect((await db.report('a'))!.syncState, SyncState.pending);
  });

  test('voice note file is deleted from the phone once the server has it', () async {
    final dir = await Directory.systemTemp.createTemp('jp');
    final file = File('${dir.path}/note.m4a')..writeAsBytesSync(List.filled(100, 1));
    await save('a', text: null, audio: file.path);
    await sync.sync();
    expect(file.existsSync(), isFalse);
    final a = (await db.report('a'))!;
    expect(a.audioPath, isNull);
    expect(a.hasAudio, isTrue);
  });

  test('pulls officer responses and reports sent by SMS or USSD', () async {
    await save('a');
    await sync.sync();
    api.officerResponds('a', '200 ORS packs delivered');
    api.byClientId['ussd:xyz'] = ServerReport.fromJson({
      'id': 999,
      'client_id': null,
      'channel': 'ussd',
      'theme_code': 'transport',
      'status': 'received',
      'text': null,
      'has_audio': false,
      'created_at': '2026-10-05T10:00:00Z',
      'responses': <Map<String, dynamic>>[],
    });
    await sync.sync();
    final a = (await db.report('a'))!;
    expect(a.status, 'action_taken');
    expect(a.responsesJson, contains('200 ORS packs delivered'));
    final ussd = (await db.report('server-999'))!;
    expect(ussd.channel, 'ussd');
    expect(ussd.syncState, SyncState.synced);
  });

  test('backoff doubles and caps at six hours', () {
    expect(SyncService.backoff(1), const Duration(minutes: 2));
    expect(SyncService.backoff(3), const Duration(minutes: 8));
    expect(SyncService.backoff(20), const Duration(hours: 6));
  });

  test('concurrent syncs share one pass', () async {
    await save('a');
    await Future.wait([sync.sync(), sync.sync(), sync.sync()]);
    expect(api.calls.where((c) => c == 'submit a').length, 1);
  });
}
