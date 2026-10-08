import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';

part 'database.g.dart';

/// Sync states for reports made on this phone.
abstract final class SyncState {
  static const pending = 'pending'; // saved here, not yet on the server
  static const synced = 'synced'; // the server has it
  static const failed = 'failed'; // the server refused it; retrying will not help
}

/// Reports, whether made on this phone or by SMS/USSD and pulled from the server.
/// The client id is the idempotency key: a retried upload never creates a second report.
class LocalReports extends Table {
  TextColumn get clientId => text()();
  TextColumn get themeCode => text().nullable()();
  TextColumn get body => text().nullable()();
  TextColumn get audioPath => text().nullable()();
  TextColumn get language => text()();
  DateTimeColumn get createdAt => dateTime()();
  TextColumn get syncState => text()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  DateTimeColumn get nextAttemptAt => dateTime().nullable()();
  TextColumn get lastError => text().nullable()();
  IntColumn get serverId => integer().nullable()();
  TextColumn get channel => text().withDefault(const Constant('app'))();
  BoolColumn get hasAudio => boolean().withDefault(const Constant(false))();

  /// What the CHP sees: received, escalated, action_taken, resolved, withdrawn.
  TextColumn get status => text().withDefault(const Constant('received'))();

  /// Officer responses as JSON: [{kind, text, officer, at}].
  TextColumn get responsesJson => text().withDefault(const Constant('[]'))();

  @override
  Set<Column> get primaryKey => {clientId};
}

class CachedThemes extends Table {
  TextColumn get code => text()();
  TextColumn get labelEn => text()();
  TextColumn get labelSw => text()();
  IntColumn get position => integer()();

  @override
  Set<Column> get primaryKey => {code};
}

@DriftDatabase(tables: [LocalReports, CachedThemes])
class AppDatabase extends _$AppDatabase {
  AppDatabase([QueryExecutor? executor])
    : super(
        executor ??
            driftDatabase(
              name: 'jamii_pulse',
              // In a browser, SQLite runs as WebAssembly in a worker; both files live in web/.
              web: DriftWebOptions(sqlite3Wasm: Uri.parse('sqlite3.wasm'), driftWorker: Uri.parse('drift_worker.js')),
            ),
      );

  @override
  int get schemaVersion => 1;

  Stream<List<LocalReport>> watchReports() =>
      (select(localReports)..orderBy([(r) => OrderingTerm.desc(r.createdAt)])).watch();

  Future<LocalReport?> report(String clientId) =>
      (select(localReports)..where((r) => r.clientId.equals(clientId))).getSingleOrNull();

  Future<void> addReport(LocalReportsCompanion row) => into(localReports).insert(row);

  /// Pending reports whose retry time has come, oldest first.
  Future<List<LocalReport>> dueForUpload(DateTime now) =>
      (select(localReports)
            ..where(
              (r) =>
                  r.syncState.equals(SyncState.pending) &
                  (r.nextAttemptAt.isNull() | r.nextAttemptAt.isSmallerOrEqualValue(now)),
            )
            ..orderBy([(r) => OrderingTerm.asc(r.createdAt)]))
          .get();

  Future<int> pendingCount() async {
    final count = localReports.clientId.count();
    final q = selectOnly(localReports)
      ..addColumns([count])
      ..where(localReports.syncState.equals(SyncState.pending));
    return (await q.getSingle()).read(count) ?? 0;
  }

  Future<void> updateReport(String clientId, LocalReportsCompanion changes) =>
      (update(localReports)..where((r) => r.clientId.equals(clientId))).write(changes);

  /// Merge the server's view of a report: by client id if it was made here, else by server id.
  Future<void> mergeFromServer({
    required int serverId,
    required String? clientId,
    required String channel,
    required String? themeCode,
    required String? body,
    required bool hasAudio,
    required String status,
    required DateTime createdAt,
    required String responsesJson,
  }) async {
    final byClient = clientId == null ? null : await report(clientId);
    final byServer =
        byClient ?? await (select(localReports)..where((r) => r.serverId.equals(serverId))).getSingleOrNull();
    if (byServer != null) {
      await updateReport(
        byServer.clientId,
        LocalReportsCompanion(
          serverId: Value(serverId),
          status: Value(status),
          responsesJson: Value(responsesJson),
          themeCode: Value(themeCode ?? byServer.themeCode),
          body: Value(body),
          syncState: const Value(SyncState.synced),
        ),
      );
      return;
    }
    await into(localReports).insert(
      LocalReportsCompanion.insert(
        clientId: clientId ?? 'server-$serverId',
        themeCode: Value(themeCode),
        body: Value(body),
        language: 'sw',
        createdAt: createdAt,
        syncState: SyncState.synced,
        serverId: Value(serverId),
        channel: Value(channel),
        hasAudio: Value(hasAudio),
        status: Value(status),
        responsesJson: Value(responsesJson),
      ),
    );
  }

  Future<List<CachedTheme>> themes() => (select(cachedThemes)..orderBy([(t) => OrderingTerm.asc(t.position)])).get();

  Future<void> replaceThemes(List<CachedThemesCompanion> rows) => transaction(() async {
    await delete(cachedThemes).go();
    await batch((b) => b.insertAll(cachedThemes, rows));
  });

  /// On log out: nothing about this CHP's reports stays on the phone.
  Future<void> wipe() => transaction(() async {
    await delete(localReports).go();
    await delete(cachedThemes).go();
  });
}
