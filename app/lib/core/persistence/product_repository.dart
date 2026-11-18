import '../domain/product.dart';

class ProductRepository {
  ProductRepository({required ProductDataSource source, required ProductCache cache})
      : _source = source,
        _cache = cache;

  final ProductDataSource _source;
  final ProductCache _cache;
  final Map<ProductScope, Future<ProductSnapshot>> _pending = {};

  Future<ProductSnapshot> load(ProductScope scope) {
    return _pending.putIfAbsent(scope, () => _load(scope));
  }

  Future<ProductSnapshot> _load(ProductScope scope) async {
    final cached = await _cache.read(scope);
    try {
      final fresh = await _source.fetch(scope);
      if (fresh.scope != scope) {
        throw StateError('product source returned a snapshot for another scope');
      }
      await _cache.write(fresh);
      return fresh;
    } catch (_) {
      if (cached != null) {
        return cached.asStale();
      }
      rethrow;
    } finally {
      _pending.remove(scope);
    }
  }
}
