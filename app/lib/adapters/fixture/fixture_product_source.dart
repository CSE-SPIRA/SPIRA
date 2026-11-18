import '../../core/domain/product.dart';

class FixtureProductSource implements ProductDataSource {
  const FixtureProductSource();

  @override
  Future<ProductSnapshot> fetch(ProductScope scope) async {
    return ProductSnapshot(
      scope: scope,
      sourceRevision: 'fixture-v1',
      fetchedAt: DateTime.utc(2026, 11, 18, 9),
      fixture: true,
      cards: [
        PreparationCard(
          id: 'fixture-preparation-1',
          title: 'Prepare for delivery',
          summary: 'Keep the entrance clear before the package arrives.',
          lines: const [
            PreparationLine(
              id: 'fixture-line-1',
              text: 'Turn on the entrance light',
              state: 'planned',
            ),
          ],
        ),
      ],
    );
  }
}
