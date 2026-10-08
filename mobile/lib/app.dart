import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'l10n/app_localizations.dart';
import 'state/app_state.dart';
import 'ui/home_screen.dart';
import 'ui/login_screen.dart';
import 'ui/notice_screen.dart';

const seed = Color(0xFF2A78D6);

/// Gives every screen the app state without a state-management package.
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({super.key, required AppState state, required super.child}) : super(notifier: state);

  static AppState of(BuildContext context) => context.dependOnInheritedWidgetOfExactType<AppScope>()!.notifier!;
}

class JamiiPulseApp extends StatefulWidget {
  const JamiiPulseApp({super.key, required this.state, this.watchConnectivity = true});
  final AppState state;
  final bool watchConnectivity;

  @override
  State<JamiiPulseApp> createState() => _JamiiPulseAppState();
}

class _JamiiPulseAppState extends State<JamiiPulseApp> with WidgetsBindingObserver {
  StreamSubscription<List<ConnectivityResult>>? _net;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.state.startTimer();
    if (widget.watchConnectivity) {
      // Coming back online is the best moment to send what was saved offline.
      _net = Connectivity().onConnectivityChanged.listen((results) {
        if (!results.contains(ConnectivityResult.none)) widget.state.refresh();
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    if (s == AppLifecycleState.resumed) widget.state.refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.state.stopTimer();
    _net?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScope(
      state: widget.state,
      child: ListenableBuilder(
        listenable: widget.state,
        builder: (context, _) => MaterialApp(
          title: 'Jamii Pulse',
          debugShowCheckedModeBanner: false,
          locale: Locale(widget.state.language),
          supportedLocales: AppLocalizations.supportedLocales,
          localizationsDelegates: const [
            AppLocalizations.delegate,
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          theme: ThemeData(
            colorScheme: ColorScheme.fromSeed(seedColor: seed),
            visualDensity: VisualDensity.standard,
            inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
          ),
          darkTheme: ThemeData(
            colorScheme: ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark),
            inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
          ),
          home: switch (widget.state.phase) {
            Phase.loading => const Scaffold(body: Center(child: CircularProgressIndicator())),
            Phase.notice => const NoticeScreen(),
            Phase.login => const LoginScreen(),
            Phase.updateApp => const _UpdateApp(),
            Phase.home => const HomeScreen(),
          },
        ),
      ),
    );
  }
}

class _UpdateApp extends StatelessWidget {
  const _UpdateApp();

  @override
  Widget build(BuildContext context) => Scaffold(
    body: Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(AppLocalizations.of(context).updateApp, textAlign: TextAlign.center),
      ),
    ),
  );
}
