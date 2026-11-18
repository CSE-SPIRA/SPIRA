import 'dart:collection';

class ProductScope {
  const ProductScope({
    required this.environment,
    required this.householdId,
  });

  final String environment;
  final String householdId;

  String get cacheKey => '$environment::$householdId';

  @override
  bool operator ==(Object other) =>
      other is ProductScope &&
      environment == other.environment &&
      householdId == other.householdId;

  @override
  int get hashCode => Object.hash(environment, householdId);
}

class PreparationLine {
  const PreparationLine({
    required this.id,
    required this.text,
    required this.state,
  });

  final String id;
  final String text;
  final String state;
}

class PreparationCard {
  PreparationCard({
    required this.id,
    required this.title,
    required this.summary,
    required List<PreparationLine> lines,
  }) : lines = UnmodifiableListView(lines);

  final String id;
  final String title;
  final String summary;
  final UnmodifiableListView<PreparationLine> lines;
}

class ProductSnapshot {
  ProductSnapshot({
    required this.scope,
    required this.sourceRevision,
    required this.fetchedAt,
    required List<PreparationCard> cards,
    required this.fixture,
    this.stale = false,
  }) : cards = UnmodifiableListView(cards);

  final ProductScope scope;
  final String sourceRevision;
  final DateTime fetchedAt;
  final UnmodifiableListView<PreparationCard> cards;
  final bool fixture;
  final bool stale;

  ProductSnapshot asStale() => ProductSnapshot(
        scope: scope,
        sourceRevision: sourceRevision,
        fetchedAt: fetchedAt,
        cards: cards,
        fixture: fixture,
        stale: true,
      );
}

abstract interface class ProductDataSource {
  Future<ProductSnapshot> fetch(ProductScope scope);
}

abstract interface class ProductCache {
  Future<ProductSnapshot?> read(ProductScope scope);

  Future<void> write(ProductSnapshot snapshot);
}
