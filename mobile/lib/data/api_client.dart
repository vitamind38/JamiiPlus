import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

/// Where a login code went, and the code itself on test servers.
typedef CodeRequest = ({String channel, String? devCode});

/// Anything the API can say back, as types the app can act on.
sealed class ApiException implements Exception {
  const ApiException(this.message);
  final String message;
  @override
  String toString() => '$runtimeType: $message';
}

/// No network, DNS failure, timeout. Keep the report and try later.
class OfflineException extends ApiException {
  const OfflineException(super.message);
}

/// The token is missing, expired or revoked. Log in again.
class UnauthorizedException extends ApiException {
  const UnauthorizedException(super.message);
}

/// The CHP has not accepted the current privacy notice.
class ConsentRequiredException extends ApiException {
  const ConsentRequiredException(super.message);
}

/// The server refused the content. Retrying the same thing will not help.
class RejectedException extends ApiException {
  const RejectedException(this.status, super.message);
  final int status;
}

/// Too many requests, or the server is having trouble. Try again later.
class RetryLaterException extends ApiException {
  const RetryLaterException(this.status, super.message);
  final int status;
}

class Me {
  Me({
    required this.pseudonym,
    required this.unit,
    required this.ward,
    required this.language,
    required this.consentRequired,
    required this.currentConsentVersion,
  });

  factory Me.fromJson(Map<String, dynamic> j) => Me(
    pseudonym: j['pseudonym'] as String,
    unit: j['unit'] as String,
    ward: j['ward'] as String,
    language: j['language'] as String,
    consentRequired: j['consent_required'] as bool,
    currentConsentVersion: j['current_consent_version'] as String,
  );

  final String pseudonym;
  final String unit;
  final String ward;
  final String language;
  final bool consentRequired;
  final String currentConsentVersion;

  Map<String, dynamic> toJson() => {
    'pseudonym': pseudonym,
    'unit': unit,
    'ward': ward,
    'language': language,
    'consent_required': consentRequired,
    'current_consent_version': currentConsentVersion,
  };
}

class ThemeDto {
  ThemeDto(this.code, this.labelEn, this.labelSw);
  final String code;
  final String labelEn;
  final String labelSw;
}

class ServerReport {
  ServerReport.fromJson(Map<String, dynamic> j)
    : id = j['id'] as int,
      clientId = j['client_id'] as String?,
      channel = j['channel'] as String,
      themeCode = j['theme_code'] as String?,
      status = j['status'] as String,
      text = j['text'] as String?,
      hasAudio = j['has_audio'] as bool,
      createdAt = DateTime.parse(j['created_at'] as String),
      responses = (j['responses'] as List).cast<Map<String, dynamic>>();

  final int id;
  final String? clientId;
  final String channel;
  final String? themeCode;
  final String status;
  final String? text;
  final bool hasAudio;
  final DateTime createdAt;
  final List<Map<String, dynamic>> responses;
}

class ApiClient {
  ApiClient({required this.baseUrl, http.Client? client, this.timeout = const Duration(seconds: 30)})
    : _http = client ?? http.Client();

  final String baseUrl;
  final Duration timeout;
  final http.Client _http;
  String? token;

  Uri _uri(String path) => Uri.parse('$baseUrl/api/v1$path');

  Map<String, String> get _headers => {
    'Accept': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  Future<dynamic> _send(Future<http.Response> Function() call) async {
    final http.Response r;
    try {
      r = await call().timeout(timeout);
    } on SocketException catch (e) {
      throw OfflineException(e.message);
    } on TimeoutException {
      throw const OfflineException('timeout');
    } on http.ClientException catch (e) {
      throw OfflineException(e.message);
    } on HandshakeException catch (e) {
      throw OfflineException(e.message);
    }
    final body = r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
    final detail = body is Map ? (body['detail']?.toString() ?? '') : '';
    switch (r.statusCode) {
      case >= 200 && < 300:
        return body;
      case 401:
        throw UnauthorizedException(detail);
      case 403 when detail == 'consent_required':
        throw ConsentRequiredException(detail);
      case 429 || >= 500:
        throw RetryLaterException(r.statusCode, detail);
      default:
        throw RejectedException(r.statusCode, detail);
    }
  }

  Future<dynamic> _json(String method, String path, [Map<String, dynamic>? data]) => _send(() {
    final headers = {..._headers, 'Content-Type': 'application/json'};
    final encoded = data == null ? null : jsonEncode(data);
    return switch (method) {
      'POST' => _http.post(_uri(path), headers: headers, body: encoded),
      'PATCH' => _http.patch(_uri(path), headers: headers, body: encoded),
      _ => _http.get(_uri(path), headers: headers),
    };
  });

  /// Where the code went ("sms" or "email"), and the code itself only from a local or demo
  /// server, which never sends a real message.
  Future<CodeRequest> requestCode(String phone) async {
    final j = await _json('POST', '/auth/otp/request', {'phone': phone});
    if (j is! Map) return (channel: 'sms', devCode: null);
    return (channel: j['channel'] as String? ?? 'sms', devCode: j['dev_code'] as String?);
  }

  Future<(String, Me)> verifyCode(String phone, String code) async {
    final j = await _json('POST', '/auth/otp/verify', {'phone': phone, 'code': code}) as Map<String, dynamic>;
    return (j['access_token'] as String, Me.fromJson(j['me'] as Map<String, dynamic>));
  }

  Future<Me> me() async => Me.fromJson(await _json('GET', '/me') as Map<String, dynamic>);

  Future<Me> consent(String version) async =>
      Me.fromJson(await _json('POST', '/me/consent', {'version': version}) as Map<String, dynamic>);

  Future<Me> setLanguage(String language) async =>
      Me.fromJson(await _json('PATCH', '/me', {'language': language}) as Map<String, dynamic>);

  Future<List<ThemeDto>> themes() async {
    final list = await _json('GET', '/themes') as List;
    return [
      for (final t in list.cast<Map<String, dynamic>>())
        ThemeDto(t['code'] as String, t['label_en'] as String, t['label_sw'] as String),
    ];
  }

  Future<ServerReport> submitReport({
    required String clientId,
    required String language,
    required DateTime reportedAt,
    String? themeCode,
    String? text,
    String? audioPath,
  }) async {
    final j = await _send(() async {
      final req = http.MultipartRequest('POST', _uri('/reports'))
        ..headers.addAll(_headers)
        ..fields['client_id'] = clientId
        ..fields['language'] = language
        ..fields['reported_at'] = reportedAt.toUtc().toIso8601String();
      if (themeCode != null) req.fields['theme_code'] = themeCode;
      if (text != null && text.trim().isNotEmpty) req.fields['text'] = text.trim();
      if (audioPath != null) {
        req.files.add(await http.MultipartFile.fromPath('audio', audioPath, contentType: _audioType));
      }
      return http.Response.fromStream(await _http.send(req));
    });
    return ServerReport.fromJson(j as Map<String, dynamic>);
  }

  Future<List<ServerReport>> myReports() async {
    final list = await _json('GET', '/reports/mine') as List;
    return [for (final r in list.cast<Map<String, dynamic>>()) ServerReport.fromJson(r)];
  }

  Future<ServerReport> withdraw(int serverId) async =>
      ServerReport.fromJson(await _json('POST', '/reports/$serverId/withdraw') as Map<String, dynamic>);

  Future<void> logout() => _json('POST', '/auth/logout');
}

final _audioType = MediaType('audio', 'mp4');
