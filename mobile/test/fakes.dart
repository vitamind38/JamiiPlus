import 'package:jamii_pulse/data/api_client.dart';

/// An API that behaves like the server, without a network.
class FakeApi implements ApiClient {
  @override
  String? token;

  final Map<String, ServerReport> byClientId = {};
  final List<String> calls = [];
  ApiException? failNextSubmit;
  ApiException? failAllSubmits;
  bool consentRequired = true;
  int _nextId = 100;

  Me _me({bool? consent}) => Me(
    pseudonym: 'CHP-ABC123',
    unit: 'Kawangware CHU',
    ward: 'Kawangware',
    language: 'sw',
    consentRequired: consent ?? consentRequired,
    currentConsentVersion: '2026-10-v2',
  );

  String? devCode;
  String channel = 'sms';

  @override
  Future<CodeRequest> requestCode(String phone) async {
    calls.add('requestCode $phone');
    return (channel: channel, devCode: devCode);
  }

  @override
  Future<(String, Me)> verifyCode(String phone, String code) async {
    calls.add('verifyCode $code');
    if (code != '123456') throw const RejectedException(401, 'That code is not right.');
    return ('token-1', _me());
  }

  @override
  Future<Me> consent(String version) async {
    calls.add('consent $version');
    consentRequired = false;
    return _me(consent: false);
  }

  @override
  Future<Me> me() async => _me();

  @override
  Future<Me> setLanguage(String language) async => _me();

  @override
  Future<List<ThemeDto>> themes() async => [
    ThemeDto('stockout', 'Medicines & supplies', 'Dawa na vifaa'),
    ThemeDto('transport', 'Distance & transport', 'Umbali na usafiri'),
  ];

  @override
  Future<ServerReport> submitReport({
    required String clientId,
    required String language,
    required DateTime reportedAt,
    String? themeCode,
    String? text,
    String? audioPath,
  }) async {
    calls.add('submit $clientId');
    final once = failNextSubmit;
    failNextSubmit = null;
    if (once != null) throw once;
    if (failAllSubmits != null) throw failAllSubmits!;
    return byClientId[clientId] ??= ServerReport.fromJson({
      'id': _nextId++,
      'client_id': clientId,
      'channel': audioPath != null ? 'voice' : 'app',
      'theme_code': themeCode,
      'status': 'received',
      'text': text?.replaceAll('Wanjiku', '[NAME]'),
      'has_audio': audioPath != null,
      'created_at': reportedAt.toUtc().toIso8601String(),
      'responses': <Map<String, dynamic>>[],
    });
  }

  @override
  Future<List<ServerReport>> myReports() async => byClientId.values.toList();

  @override
  Future<ServerReport> withdraw(int serverId) async {
    final entry = byClientId.entries.firstWhere((e) => e.value.id == serverId);
    return byClientId[entry.key] = ServerReport.fromJson({
      'id': serverId,
      'client_id': entry.key,
      'channel': entry.value.channel,
      'theme_code': entry.value.themeCode,
      'status': 'withdrawn',
      'text': null,
      'has_audio': false,
      'created_at': entry.value.createdAt.toIso8601String(),
      'responses': <Map<String, dynamic>>[],
    });
  }

  @override
  Future<void> logout() async => calls.add('logout');

  /// What an officer's response looks like by the time the phone pulls it.
  void officerResponds(String clientId, String text) {
    final r = byClientId[clientId]!;
    byClientId[clientId] = ServerReport.fromJson({
      'id': r.id,
      'client_id': clientId,
      'channel': r.channel,
      'theme_code': r.themeCode,
      'status': 'action_taken',
      'text': r.text,
      'has_audio': r.hasAudio,
      'created_at': r.createdAt.toIso8601String(),
      'responses': [
        {'kind': 'action_taken', 'text': text, 'officer': 'Peter Mwangi', 'at': '2026-10-07T09:00:00Z'},
      ],
    });
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
