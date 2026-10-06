import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/app_localizations.dart';

class LanguageToggle extends StatelessWidget {
  const LanguageToggle({super.key});

  @override
  Widget build(BuildContext context) {
    final state = AppScope.of(context);
    final other = state.language == 'sw' ? 'en' : 'sw';
    return TextButton(onPressed: () => state.setLanguage(other), child: Text(other == 'sw' ? 'Kiswahili' : 'English'));
  }
}

class NoPatientNamesBanner extends StatelessWidget {
  const NoPatientNamesBanner({super.key, required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: scheme.tertiaryContainer, borderRadius: BorderRadius.circular(8)),
      child: Row(
        children: [
          Icon(Icons.privacy_tip_outlined, color: scheme.onTertiaryContainer),
          const SizedBox(width: 12),
          Expanded(
            child: Text(text, style: TextStyle(color: scheme.onTertiaryContainer)),
          ),
        ],
      ),
    );
  }
}

/// Status with an icon and a word, never colour alone.
class StatusChip extends StatelessWidget {
  const StatusChip({super.key, required this.status, required this.syncState});
  final String status;
  final String syncState;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final (IconData icon, String label) = switch ((syncState, status)) {
      ('pending', _) => (Icons.schedule, t.waitingToSend),
      ('failed', _) => (Icons.error_outline, t.couldNotSend),
      (_, 'escalated') => (Icons.trending_up, t.statusEscalated),
      (_, 'action_taken') => (Icons.build_circle_outlined, t.statusActionTaken),
      (_, 'resolved') => (Icons.check_circle_outline, t.statusResolved),
      (_, 'withdrawn') => (Icons.remove_circle_outline, t.statusWithdrawn),
      _ => (Icons.inbox_outlined, t.statusReceived),
    };
    return Chip(
      avatar: Icon(icon, size: 18),
      label: Text(label),
      visualDensity: VisualDensity.compact,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }
}
