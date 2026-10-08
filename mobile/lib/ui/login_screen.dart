import 'package:flutter/material.dart';

import '../app.dart';
import '../data/api_client.dart';
import '../l10n/app_localizations.dart';
import 'widgets.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  bool _codeSent = false;
  bool _busy = false;
  String? _devCode; // only from a local or demo server
  String? _error;

  @override
  void dispose() {
    _phone.dispose();
    _code.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    final t = AppLocalizations.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on OfflineException {
      _error = t.errorNoNetwork;
    } on ApiException catch (e) {
      _error = e.message.isNotEmpty ? e.message : t.errorGeneric;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(t.loginTitle), actions: const [LanguageToggle()]),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Center(child: BrandMark()),
            const SizedBox(height: 28),
            if (!_codeSent) ...[
              TextField(
                controller: _phone,
                keyboardType: TextInputType.phone,
                autofillHints: const [AutofillHints.telephoneNumber],
                decoration: InputDecoration(labelText: t.phoneLabel, hintText: t.phoneHint),
              ),
              const SizedBox(height: 16),
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: _busy
                    ? null
                    : () => _run(() async {
                        final devCode = await state.requestCode(_phone.text);
                        setState(() {
                          _codeSent = true;
                          _devCode = devCode;
                        });
                      }),
                child: Text(t.sendCode),
              ),
            ] else ...[
              Text(t.codeSentTo(_phone.text)),
              if (_devCode != null) ...[
                const SizedBox(height: 12),
                NoPatientNamesBanner(text: t.devCode(_devCode!), icon: Icons.science_outlined),
              ],
              const SizedBox(height: 16),
              TextField(
                controller: _code,
                keyboardType: TextInputType.number,
                maxLength: 6,
                autofillHints: const [AutofillHints.oneTimeCode],
                decoration: InputDecoration(labelText: t.codeLabel),
              ),
              const SizedBox(height: 8),
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: _busy ? null : () => _run(() => state.verifyCode(_phone.text, _code.text)),
                child: Text(t.logIn),
              ),
              TextButton(
                onPressed: () => setState(() {
                  _codeSent = false;
                  _code.clear();
                }),
                child: Text(t.useAnotherNumber),
              ),
            ],
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ),
          ],
        ),
      ),
    );
  }
}
