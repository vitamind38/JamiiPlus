import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/app_localizations.dart';
import 'notice_screen.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    final me = state.me;
    return Scaffold(
      appBar: AppBar(title: Text(t.settings)),
      body: ListView(
        children: [
          if (me != null) ...[
            ListTile(leading: const Icon(Icons.badge_outlined), title: Text(t.yourCodeName(me.pseudonym))),
            ListTile(leading: const Icon(Icons.home_work_outlined), title: Text(t.unit(me.unit, me.ward))),
            const Divider(),
          ],
          ListTile(
            leading: const Icon(Icons.translate),
            title: Text(t.language),
            trailing: SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'sw', label: Text('Kiswahili')),
                ButtonSegment(value: 'en', label: Text('English')),
              ],
              selected: {state.language},
              onSelectionChanged: (s) => state.setLanguage(s.first),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: Text(t.privacyNotice),
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NoticeScreen(readOnly: true))),
          ),
          ListTile(
            leading: const Icon(Icons.logout),
            title: Text(t.logOut),
            onTap: () {
              Navigator.popUntil(context, (r) => r.isFirst);
              state.logout();
            },
          ),
        ],
      ),
    );
  }
}
