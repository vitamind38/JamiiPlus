import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:uuid/uuid.dart';

import '../config.dart';
import '../l10n/app_localizations.dart';

/// The microphone, behind an interface so widget tests can run without one.
abstract class VoiceRecorderController {
  Future<bool> hasPermission();
  Future<void> start(String path);
  Future<String?> stop();
  Future<void> dispose();
}

class DeviceRecorder implements VoiceRecorderController {
  final _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  // Mono AAC at 32 kbps: about 240 KB a minute, small enough for weak networks,
  // and 16 kHz is what speech-to-text models expect.
  @override
  Future<void> start(String path) => _recorder.start(
    const RecordConfig(encoder: AudioEncoder.aacLc, bitRate: 32000, sampleRate: 16000, numChannels: 1),
    path: path,
  );

  @override
  Future<String?> stop() => _recorder.stop();

  @override
  Future<void> dispose() => _recorder.dispose();
}

class VoiceRecorder extends StatefulWidget {
  const VoiceRecorder({super.key, required this.onChanged, this.controller});
  final ValueChanged<String?> onChanged;
  final VoiceRecorderController? controller;

  @override
  State<VoiceRecorder> createState() => _VoiceRecorderState();
}

class _VoiceRecorderState extends State<VoiceRecorder> {
  VoiceRecorderController? _instance; // created on first use, so opening the screen never touches the mic
  VoiceRecorderController get _rec => _instance ??= widget.controller ?? DeviceRecorder();
  Timer? _ticker;
  int _seconds = 0;
  bool _recording = false;
  String? _path;

  @override
  void dispose() {
    _ticker?.cancel();
    _instance?.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    final t = AppLocalizations.of(context);
    if (!await _rec.hasPermission()) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t.micPermission)));
      return;
    }
    await _discard();
    final dir = Directory(p.join((await getApplicationDocumentsDirectory()).path, 'voice'));
    await dir.create(recursive: true);
    final path = p.join(dir.path, '${const Uuid().v4()}.m4a');
    await _rec.start(path);
    setState(() {
      _recording = true;
      _seconds = 0;
    });
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      setState(() => _seconds++);
      if (_seconds >= maxVoiceNote.inSeconds) _stop();
    });
  }

  Future<void> _stop() async {
    _ticker?.cancel();
    final path = await _rec.stop();
    setState(() {
      _recording = false;
      _path = path;
    });
    widget.onChanged(path);
  }

  Future<void> _discard() async {
    if (_path != null) {
      final f = File(_path!);
      if (await f.exists()) await f.delete();
    }
    setState(() => _path = null);
    widget.onChanged(null);
  }

  @override
  Widget build(BuildContext context) {
    final t = AppLocalizations.of(context);
    if (kIsWeb) {
      return ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.mic_off_outlined),
        title: Text(t.voiceNotOnWeb),
      );
    }
    if (_recording) {
      return Row(
        children: [
          const Icon(Icons.fiber_manual_record, color: Colors.red),
          const SizedBox(width: 8),
          Expanded(child: Text(t.recordingSeconds(_seconds))),
          FilledButton.tonalIcon(onPressed: _stop, icon: const Icon(Icons.stop), label: Text(t.stopRecording)),
        ],
      );
    }
    if (_path != null) {
      return Row(
        children: [
          const Icon(Icons.mic),
          const SizedBox(width: 8),
          Expanded(child: Text(t.recordedSeconds(_seconds))),
          TextButton(onPressed: _start, child: Text(t.recordAgain)),
          TextButton(onPressed: _discard, child: Text(t.deleteRecording)),
        ],
      );
    }
    return OutlinedButton.icon(
      style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(52)),
      onPressed: _start,
      icon: const Icon(Icons.mic_none),
      label: Text(t.recordVoice),
    );
  }
}
