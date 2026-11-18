import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:spira_app/adapters/local/preferences_product_cache.dart';
import 'package:spira_app/core/domain/product.dart';

void main() {
  test('round-trips product state only inside its scope', () async {
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final cache = PreferencesProductCache(preferences);
    const scope = ProductScope(environment: 'fixture', householdId: 'home-1');
    const other = ProductScope(environment: 'fixture', householdId: 'home-2');

    await cache.write(
      ProductSnapshot(
        scope: scope,
        sourceRevision: 'revision-1',
        fetchedAt: DateTime.utc(2026, 11, 18),
        fixture: true,
        cards: [
          PreparationCard(
            id: 'card-1',
            title: 'Delivery',
            summary: 'Prepare the entrance.',
            lines: const [
              PreparationLine(
                id: 'line-1',
                text: 'Turn on the entrance light',
                state: 'planned',
              ),
            ],
          ),
        ],
      ),
    );

    final restored = await cache.read(scope);
    expect(restored?.scope, scope);
    expect(restored?.sourceRevision, 'revision-1');
    expect(restored?.cards.single.lines.single.id, 'line-1');
    expect(await cache.read(other), isNull);
  });
}
