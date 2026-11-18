import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:spira_app/core/domain/product.dart';
import 'package:spira_app/core/persistence/product_repository.dart';

void main() {
  const scope = ProductScope(environment: 'test', householdId: 'home-1');

  test('coalesces concurrent refresh and writes the fresh snapshot', () async {
    final completer = Completer<ProductSnapshot>();
    final source = _Source(() => completer.future);
    final cache = _MemoryCache();
    final repository = ProductRepository(source: source, cache: cache);

    final first = repository.load(scope);
    final second = repository.load(scope);
    expect(source.calls, 0);
    await Future<void>.delayed(Duration.zero);
    expect(source.calls, 1);

    completer.complete(_snapshot(scope));
    expect(await first, same(await second));
    expect(cache.value?.sourceRevision, 'revision-1');
  });

  test('returns a scoped stale snapshot when refresh fails', () async {
    final cache = _MemoryCache()..value = _snapshot(scope);
    final repository = ProductRepository(
      source: _Source(() => Future.error(StateError('offline'))),
      cache: cache,
    );

    final result = await repository.load(scope);
    expect(result.stale, isTrue);
    expect(result.scope, scope);
    expect(result.cards.single.id, 'card-1');
  });
}

ProductSnapshot _snapshot(ProductScope scope) => ProductSnapshot(
      scope: scope,
      sourceRevision: 'revision-1',
      fetchedAt: DateTime.utc(2026, 11, 18),
      fixture: true,
      cards: [
        PreparationCard(
          id: 'card-1',
          title: 'Title',
          summary: 'Summary',
          lines: const [],
        ),
      ],
    );

class _Source implements ProductDataSource {
  _Source(this._fetch);

  final Future<ProductSnapshot> Function() _fetch;
  int calls = 0;

  @override
  Future<ProductSnapshot> fetch(ProductScope scope) {
    calls += 1;
    return _fetch();
  }
}

class _MemoryCache implements ProductCache {
  ProductSnapshot? value;

  @override
  Future<ProductSnapshot?> read(ProductScope scope) async => value;

  @override
  Future<void> write(ProductSnapshot snapshot) async {
    value = snapshot;
  }
}
