import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../app.dart';
import '../data/database.dart';
import '../l10n/app_localizations.dart';
import 'report_detail_screen.dart';
import 'report_screen.dart';
import 'settings_screen.dart';
import 'widgets.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(t.homeTitle),
        actions: [
          IconButton(
            tooltip: t.settings,
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.campaign_outlined),
        label: Text(t.newReport),
        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ReportScreen())),
      ),
      body: RefreshIndicator(
        onRefresh: state.refresh,
        child: StreamBuilder<List<LocalReport>>(
          stream: state.reports,
          builder: (context, snap) {
            final reports = snap.data ?? const [];
            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.only(bottom: 96),
              children: [
                if (state.offline || state.pending > 0)
                  MaterialBanner(
                    content: Text(state.offline ? t.offline : '${t.waitingToSend}: ${state.pending}'),
                    leading: Icon(state.offline ? Icons.cloud_off : Icons.schedule),
                    actions: [TextButton(onPressed: state.refresh, child: Text(t.sendNow))],
                  ),
                if (reports.isEmpty && snap.hasData)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(32, 32, 32, 0),
                    child: Column(
                      children: [
                        const SizedBox(
                          width: 220,
                          child: Illustration(Assets.reportPrompt, height: 220, fit: BoxFit.contain),
                        ),
                        const SizedBox(height: 20),
                        Text(t.emptyReports, textAlign: TextAlign.center),
                      ],
                    ),
                  ),
                for (final r in reports) _ReportTile(report: r),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ReportTile extends StatelessWidget {
  const _ReportTile({required this.report});
  final LocalReport report;

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    final title = report.themeCode != null ? state.themeLabel(report.themeCode) : t.voiceNote;
    final date = DateFormat.yMMMd(state.language).format(report.createdAt.toLocal());
    // The status sits under the text, so titles keep the full width on small phones.
    return ListTile(
      leading: Icon(report.hasAudio || report.audioPath != null ? Icons.mic_none : Icons.notes),
      title: Text(title),
      isThreeLine: true,
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text([date, if (report.body != null) report.body!].join(' · '), maxLines: 2, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 6),
          StatusChip(status: report.status, syncState: report.syncState),
        ],
      ),
      onTap: () =>
          Navigator.push(context, MaterialPageRoute(builder: (_) => ReportDetailScreen(clientId: report.clientId))),
    );
  }
}
