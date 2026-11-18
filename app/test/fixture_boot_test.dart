import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:spira_app/adapters/fixture/fixture_product_source.dart';
import 'package:spira_app/adapters/local/preferences_product_cache.dart';
import 'package:spira_app/core/domain/product.dart';
import 'package:spira_app/core/persistence/product_repository.dart';
import 'package:spira_app/main.dart';

void main() {
  testWidgets('boots the typed fixture and visibly qualifies it', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final repository = ProductRepository(
      source: const FixtureProductSource(),
      cache: PreferencesProductCache(preferences),
    );

    await tester.pumpWidget(SpiraApp(repository: repository));
    await tester.pumpAndSettle();

    expect(find.text('LOCAL FIXTURE'), findsOneWidget);
    expect(find.text('Prepare for delivery'), findsOneWidget);
    expect(find.text('Turn on the entrance light'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    final reentered = ProductRepository(
      source: const _OfflineSource(),
      cache: PreferencesProductCache(preferences),
    );
    await tester.pumpWidget(SpiraApp(repository: reentered));
    await tester.pumpAndSettle();

    expect(find.text('STALE / OFFLINE'), findsOneWidget);
    expect(find.text('Prepare for delivery'), findsOneWidget);
  });
}

class _OfflineSource implements ProductDataSource {
  const _OfflineSource();

  @override
  Future<ProductSnapshot> fetch(ProductScope scope) {
    return Future.error(StateError('offline'));
  }
}
