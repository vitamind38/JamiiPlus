import 'package:flutter/material.dart';

import '../app.dart';
import '../l10n/app_localizations.dart';
import 'voice_recorder.dart';
import 'widgets.dart';

/// Tap a category, record a short voice note, or both. Saved on the phone first.
class ReportScreen extends StatefulWidget {
  const ReportScreen({super.key, this.recorder});
  final VoiceRecorderController? recorder;

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  String? _theme;
  String? _audioPath;
  final _text = TextEditingController();
  bool _saving = false;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    if (_theme == null && _audioPath == null && _text.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.needSomething)));
      return;
    }
    setState(() => _saving = true);
    await state.submit(themeCode: _theme, text: _text.text, audioPath: _audioPath);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(state.offline ? t.savedWillSend : t.sent)));
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    final state = AppScope.of(context);
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(t.newReport)),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            NoPatientNamesBanner(text: t.noPatientNames),
            const SizedBox(height: 20),
            Text(t.chooseCategory, style: text.titleMedium),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final theme in state.themes)
                  ChoiceChip(
                    label: Text(state.language == 'sw' ? theme.labelSw : theme.labelEn),
                    selected: _theme == theme.code,
                    onSelected: (on) => setState(() => _theme = on ? theme.code : null),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            Text(t.voiceNote, style: text.titleMedium),
            const SizedBox(height: 4),
            Text(t.voiceTip, style: text.bodySmall),
            const SizedBox(height: 8),
            VoiceRecorder(controller: widget.recorder, onChanged: (path) => _audioPath = path),
            const SizedBox(height: 24),
            TextField(
              controller: _text,
              maxLines: 3,
              maxLength: 500,
              decoration: InputDecoration(labelText: t.describeOptional),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(52)),
              onPressed: _saving ? null : _send,
              icon: const Icon(Icons.send),
              label: Text(t.send),
            ),
          ],
        ),
      ),
    );
  }
}
