import 'package:flutter/material.dart';

import 'app.dart';
import 'config.dart';
import 'data/api_client.dart';
import 'data/database.dart';
import 'data/session_store.dart';
import 'state/app_state.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState(
    db: AppDatabase(),
    api: ApiClient(baseUrl: apiBaseUrl),
    store: const SecureSessionStore(),
  );
  state.start();
  runApp(JamiiPulseApp(state: state));
}
