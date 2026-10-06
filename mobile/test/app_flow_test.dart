import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jamii_pulse/app.dart';
import 'package:jamii_pulse/config.dart';
import 'package:jamii_pulse/data/api_client.dart';
import 'package:jamii_pulse/data/database.dart';
import 'package:jamii_pulse/data/session_store.dart';
import 'package:jamii_pulse/state/app_state.dart';

import 'fakes.dart';

// The in-memory database is synchronous, so everything here runs in the test's fake-async
// zone; no runAsync, which would split Drift's stream queries across two zones.
void main() {
  late AppDatabase db;
  late FakeApi api;
  late MemorySessionStore store;
  late AppState state;

  setUp(() {
    db = AppDatabase(NativeDatabase.memory());
    api = FakeApi();
    store = MemorySessionStore();
    state = AppState(db: db, api: api, store: store);
  });

  Future<void> boot(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1080, 3200); // tall, so whole screens are built
    tester.view.devicePixelRatio = 2;
    addTearDown(tester.view.reset);
    await state.start();
    await tester.pumpWidget(JamiiPulseApp(state: state, watchConnectivity: false));
    await tester.pumpAndSettle();
  }

  Future<void> settle(WidgetTester tester, Future<void> Function() action) async {
    await action();
    await tester.pumpAndSettle();
  }

  Future<void> finish(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox());
    final closing = db.close();
    await tester.pump(const Duration(seconds: 1)); // Drift's stream cleanup runs on (fake) timers
    await closing;
  }

  testWidgets('first use: notice and promises in Swahili, then login, consent and home', (tester) async {
    await boot(tester);
    expect(find.text('Kabla hujaanza'), findsOneWidget);
    expect(find.textContaining('kamwe kumwadhibu'), findsOneWidget); // never used to discipline
    expect(find.textContaining('Usitaje majina ya wagonjwa'), findsOneWidget);

    await tester.tap(find.text('Nimeelewa na ninakubali'));
    await tester.pumpAndSettle();
    expect(await store.read(Keys.noticeVersion), noticeVersion);

    await tester.enterText(find.byType(TextField), '0712345678');
    await tester.tap(find.text('Tuma nambari'));
    await tester.pumpAndSettle();
    final logIn = find.widgetWithText(FilledButton, 'Ingia'); // the app bar says Ingia too
    await tester.enterText(find.byType(TextField), '000000');
    await tester.tap(logIn);
    await tester.pumpAndSettle();
    expect(find.text('That code is not right.'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '123456');
    await tester.tap(logIn);
    await tester.pumpAndSettle();
    expect(api.calls, contains('consent $noticeVersion')); // recorded on the server after login
    expect(state.phase, Phase.home);
    expect(find.text('Ripoti zangu'), findsOneWidget);
    expect(await store.read(Keys.token), 'token-1');
    await finish(tester);
  });

  testWidgets('switching language changes the notice', (tester) async {
    await boot(tester);
    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();
    expect(find.text('Before you start'), findsOneWidget);
    expect(find.textContaining('never used to discipline'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('a report made offline is kept, then sent and answered', (tester) async {
    await store.write(Keys.noticeVersion, noticeVersion);
    await store.write(Keys.token, 'token-1');
    await store.write(Keys.language, 'en');
    api.consentRequired = false;
    api.failAllSubmits = const OfflineException('no network');
    await boot(tester);
    await settle(tester, state.refresh); // loads the themes
    expect(find.textContaining('No reports yet'), findsOneWidget);

    await tester.tap(find.text('Report a problem'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Do not name patients'), findsOneWidget);
    await tester.tap(find.text('Medicines & supplies'));
    await tester.enterText(find.byType(TextField), 'No ORS since Monday');
    await tester.tap(find.text('Send'));
    await tester.pumpAndSettle();
    await tester.pump(const Duration(seconds: 5)); // let the snackbar go
    await tester.pumpAndSettle();

    expect(find.text('Waiting to send'), findsOneWidget);
    expect(state.pending, 1);
    expect(state.offline, isTrue);

    // Network is back and the retry is due.
    api.failAllSubmits = null;
    await db.customStatement('UPDATE local_reports SET next_attempt_at = NULL');
    await settle(tester, state.refresh);
    expect(state.pending, 0);
    expect(find.text('Received'), findsOneWidget);

    api.officerResponds(api.byClientId.keys.single, '200 ORS packs delivered');
    await settle(tester, state.refresh);
    expect(find.text('Action taken'), findsOneWidget);

    await tester.tap(find.text('Medicines & supplies'));
    await tester.pumpAndSettle();
    expect(find.text('200 ORS packs delivered'), findsOneWidget);
    expect(find.textContaining('Peter Mwangi'), findsOneWidget);
    await finish(tester);
  });

  testWidgets('a CHP can remove a report', (tester) async {
    await store.write(Keys.noticeVersion, noticeVersion);
    await store.write(Keys.token, 'token-1');
    await store.write(Keys.language, 'en');
    api.consentRequired = false;
    await boot(tester);
    await settle(tester, () => state.submit(themeCode: 'stockout', text: 'hakuna dawa'));
    await settle(tester, state.refresh);
    await tester.tap(find.text('Medicines & supplies'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Remove this report'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Remove'));
    await tester.pumpAndSettle();
    final row = (await db.select(db.localReports).get()).single;
    expect(row.status, 'withdrawn');
    expect(row.body, isNull);
    await finish(tester);
  });

  testWidgets('log out wipes the phone and shows the notice to the next person', (tester) async {
    await store.write(Keys.noticeVersion, noticeVersion);
    await store.write(Keys.token, 'token-1');
    api.consentRequired = false;
    await boot(tester);
    await db.addReport(
      LocalReportsCompanion.insert(
        clientId: 'x',
        themeCode: const Value('stockout'),
        language: 'sw',
        createdAt: DateTime.now(),
        syncState: SyncState.pending,
      ),
    );
    await settle(tester, () => state.logout());
    expect(state.phase, Phase.notice);
    expect(find.text('Kabla hujaanza'), findsOneWidget);
    expect(await store.read(Keys.token), isNull);
    expect(await db.select(db.localReports).get(), isEmpty);
    expect(api.calls, contains('logout'));
    await finish(tester);
  });
}
