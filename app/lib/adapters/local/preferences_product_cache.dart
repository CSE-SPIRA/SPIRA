import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/domain/product.dart';

class PreferencesProductCache implements ProductCache {
  PreferencesProductCache(this._preferences);

  static const int schemaVersion = 1;
  static const String _prefix = 'spira.product.v1.';

  final SharedPreferences _preferences;

  @override
  Future<ProductSnapshot?> read(ProductScope scope) async {
    final encoded = _preferences.getString('$_prefix${scope.cacheKey}');
    if (encoded == null) return null;

    try {
      final value = jsonDecode(encoded) as Map<String, Object?>;
      if (value['schema'] != schemaVersion ||
          value['environment'] != scope.environment ||
          value['household_id'] != scope.householdId) {
        return null;
      }
      final cards = (value['cards'] as List<Object?>)
          .map((item) => _decodeCard(item! as Map<String, Object?>))
          .toList(growable: false);
      return ProductSnapshot(
        scope: scope,
        sourceRevision: value['source_revision']! as String,
        fetchedAt: DateTime.parse(value['fetched_at']! as String),
        cards: cards,
        fixture: value['fixture']! as bool,
      );
    } on Object {
      return null;
    }
  }

  @override
  Future<void> write(ProductSnapshot snapshot) async {
    final value = <String, Object?>{
      'schema': schemaVersion,
      'environment': snapshot.scope.environment,
      'household_id': snapshot.scope.householdId,
      'source_revision': snapshot.sourceRevision,
      'fetched_at': snapshot.fetchedAt.toIso8601String(),
      'fixture': snapshot.fixture,
      'cards': snapshot.cards.map(_encodeCard).toList(growable: false),
    };
    final stored = await _preferences.setString(
      '$_prefix${snapshot.scope.cacheKey}',
      jsonEncode(value),
    );
    if (!stored) throw StateError('product cache write failed');
  }

  static Map<String, Object?> _encodeCard(PreparationCard card) => {
        'id': card.id,
        'title': card.title,
        'summary': card.summary,
        'lines': card.lines
            .map((line) => {
                  'id': line.id,
                  'text': line.text,
                  'state': line.state,
                })
            .toList(growable: false),
      };

  static PreparationCard _decodeCard(Map<String, Object?> value) {
    return PreparationCard(
      id: value['id']! as String,
      title: value['title']! as String,
      summary: value['summary']! as String,
      lines: (value['lines']! as List<Object?>)
          .map((item) => item! as Map<String, Object?>)
          .map(
            (line) => PreparationLine(
              id: line['id']! as String,
              text: line['text']! as String,
              state: line['state']! as String,
            ),
          )
          .toList(growable: false),
    );
  }
}
