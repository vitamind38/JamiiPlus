import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Swahili and English have the same strings', () {
    Map<String, dynamic> load(String lang) =>
        jsonDecode(File('lib/l10n/app_$lang.arb').readAsStringSync()) as Map<String, dynamic>;
    Set<String> keys(Map<String, dynamic> m) => m.keys.where((k) => !k.startsWith('@')).toSet();
    final en = load('en');
    final sw = load('sw');
    expect(keys(sw).difference(keys(en)), isEmpty, reason: 'only in Swahili');
    expect(keys(en).difference(keys(sw)), isEmpty, reason: 'missing in Swahili');
    for (final k in keys(en)) {
      final placeholders = RegExp(r'\{(\w+)\}').allMatches(en[k] as String).map((m) => m[1]).toSet();
      final swPlaceholders = RegExp(r'\{(\w+)\}').allMatches(sw[k] as String).map((m) => m[1]).toSet();
      expect(swPlaceholders, placeholders, reason: k);
    }
  });
}
