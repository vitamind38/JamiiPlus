import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../app.dart';
import '../data/api_client.dart';
import '../data/database.dart';
import '../l10n/app_localizations.dart';
import 'widgets.dart';

/// One report and what was done about it: the "you said, we did" view.
class ReportDetailScreen extends StatelessWidget {
  const ReportDetailScreen({super.key, required this.clientId});
  final String clientId;

  Future<void> _remove(BuildContext context, LocalReport report) async {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        content: Text(t.removeConfirm),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: Text(t.cancel)),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(t.remove)),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    try {
      await state.withdraw(report);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.removed)));
        Navigator.pop(context);
      }
    } on ApiException catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e is OfflineException ? t.errorNoNetwork : t.errorGeneric)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    final text = Theme.of(context).textTheme;
    return StreamBuilder<List<LocalReport>>(
      stream: state.reports,
      builder: (context, snap) {
        final report = snap.data?.where((r) => r.clientId == clientId).firstOrNull;
        if (report == null) return const Scaffold();
        final responses = (jsonDecode(report.responsesJson) as List).cast<Map<String, dynamic>>();
        final fmt = DateFormat.yMMMd(state.language).add_Hm();
        return Scaffold(
          appBar: AppBar(title: Text(report.themeCode != null ? state.themeLabel(report.themeCode) : t.voiceNote)),
          body: SafeArea(
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Row(
                  children: [
                    StatusChip(status: report.status, syncState: report.syncState),
                    const SizedBox(width: 12),
                    Expanded(child: Text(t.reportedOn(fmt.format(report.createdAt.toLocal())))),
                  ],
                ),
                const SizedBox(height: 16),
                if (report.body != null) Text(report.body!, style: text.bodyLarge),
                if (report.hasAudio || report.audioPath != null)
                  ListTile(contentPadding: EdgeInsets.zero, leading: const Icon(Icons.mic), title: Text(t.voiceNote)),
                if (report.body == null && !report.hasAudio && report.audioPath == null) Text(t.categoryOnly),
                const Divider(height: 32),
                Text(t.whatHappened, style: text.titleMedium),
                const SizedBox(height: 8),
                if (responses.isEmpty) Text(t.nothingYet),
                for (final r in responses)
                  Card(
                    child: ListTile(
                      title: Text(r['text'] as String),
                      subtitle: Text('${r['officer']} · ${fmt.format(DateTime.parse(r['at'] as String).toLocal())}'),
                    ),
                  ),
                const SizedBox(height: 24),
                if (report.status != 'withdrawn')
                  OutlinedButton.icon(
                    onPressed: () => _remove(context, report),
                    icon: const Icon(Icons.delete_outline),
                    label: Text(t.removeReport),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
