import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/app_localizations.dart';
import 'widgets.dart';

/// The privacy notice and the three promises, shown before first use, in the CHP's language.
class NoticeScreen extends StatelessWidget {
  const NoticeScreen({super.key, this.readOnly = false});
  final bool readOnly;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(t.noticeTitle), actions: const [LanguageToggle()]),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text(t.noticeIntro, style: text.bodyLarge),
            const SizedBox(height: 16),
            Text(t.noticeWhatWeKeep, style: text.bodyLarge),
            const SizedBox(height: 16),
            Text(t.noticeWhoSees, style: text.bodyLarge),
            const SizedBox(height: 16),
            Text(t.noticeRights, style: text.bodyLarge),
            const SizedBox(height: 24),
            Text(t.promisesTitle, style: text.titleMedium),
            const SizedBox(height: 8),
            for (final p in [t.promiseNoDiscipline, t.promiseFeedback, t.promiseRemoval])
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.verified_user_outlined),
                title: Text(p),
              ),
            const SizedBox(height: 8),
            NoPatientNamesBanner(text: t.noPatientNames),
            const SizedBox(height: 24),
            if (!readOnly)
              FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
                onPressed: state.acceptNotice,
                child: Text(t.agree),
              ),
          ],
        ),
      ),
    );
  }
}
