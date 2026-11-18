import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'adapters/fixture/fixture_product_source.dart';
import 'adapters/local/preferences_product_cache.dart';
import 'core/domain/product.dart';
import 'core/persistence/product_repository.dart';

const ProductScope localFixtureScope = ProductScope(
  environment: 'local-fixture',
  householdId: 'fixture-household',
);

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final preferences = await SharedPreferences.getInstance();
  runApp(
    SpiraApp(
      repository: ProductRepository(
        source: const FixtureProductSource(),
        cache: PreferencesProductCache(preferences),
      ),
    ),
  );
}

class SpiraApp extends StatelessWidget {
  const SpiraApp({required this.repository, super.key});

  final ProductRepository repository;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SPIRA',
      theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
      home: PreparationScreen(repository: repository),
    );
  }
}

class PreparationScreen extends StatefulWidget {
  const PreparationScreen({required this.repository, super.key});

  final ProductRepository repository;

  @override
  State<PreparationScreen> createState() => _PreparationScreenState();
}

class _PreparationScreenState extends State<PreparationScreen> {
  late Future<ProductSnapshot> _snapshot;

  @override
  void initState() {
    super.initState();
    _snapshot = widget.repository.load(localFixtureScope);
  }

  void _retry() {
    setState(() => _snapshot = widget.repository.load(localFixtureScope));
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Preparations')),
      body: FutureBuilder<ProductSnapshot>(
        future: _snapshot,
        builder: (context, state) {
          if (state.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          if (state.hasError) {
            return Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('Preparations are unavailable.'),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _retry, child: const Text('Retry')),
                ],
              ),
            );
          }

          final snapshot = state.requireData;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Wrap(
                spacing: 8,
                children: [
                  if (snapshot.fixture)
                    const Chip(label: Text('LOCAL FIXTURE')),
                  if (snapshot.stale)
                    const Chip(label: Text('STALE / OFFLINE')),
                ],
              ),
              for (final card in snapshot.cards)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(card.title,
                            style: Theme.of(context).textTheme.titleLarge),
                        const SizedBox(height: 8),
                        Text(card.summary),
                        const Divider(),
                        for (final line in card.lines)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(line.text),
                            subtitle: Text(line.state),
                          ),
                      ],
                    ),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}
