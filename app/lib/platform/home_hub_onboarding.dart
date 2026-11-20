import 'dart:convert';

import '../contracts.dart' as wire;
import 'app_store.dart';

abstract interface class HomeHubOnboardingPort {
  Future<HomeDiscovery> discover(String scope);

  Future<void> saveRoomsNamesDelegation(
    String scope,
    HomeDiscovery discovery,
    Map<String, HomeDeviceSettings> settings,
  );
}

/// Phone-side choices alongside the generated discovery manifest.
class HomeDeviceSettings {
  HomeDeviceSettings({
    required this.room,
    required this.name,
    required Set<String> delegated,
  }) : delegated = Set.unmodifiable(delegated);

  final String? room;
  final String name;
  final Set<String> delegated;

  static Set<String> selectable(wire.DeviceElement device) => {
    for (final command in device.commands)
      if (!device.never.contains(command.cmd)) command.cmd,
  };
}

class HomeDiscovery {
  const HomeDiscovery({this.manifest, this.settings = const {}});

  final wire.Devices? manifest;
  final Map<String, HomeDeviceSettings> settings;

  List<wire.DeviceElement> get devices => manifest?.devices ?? const [];
}

class LocalHomeHubOnboarding implements HomeHubOnboardingPort {
  LocalHomeHubOnboarding(
    this.store, {
    this.discoveryJson = const String.fromEnvironment('SPIRA_DISCOVERY_JSON'),
  });

  final AppStore store;
  final String discoveryJson;

  String _key(String scope) => 'spira.home.v1.$scope';

  @override
  Future<HomeDiscovery> discover(String scope) async {
    wire.Devices? manifest;
    if (discoveryJson.isNotEmpty) {
      try {
        manifest = wire.devicesFromJson(discoveryJson);
      } catch (_) {
        // A malformed build-time manifest leaves discovery unavailable.
      }
    }
    final saved = await store.read(_key(scope));
    if (saved == null) return HomeDiscovery(manifest: manifest);
    final data = jsonDecode(saved) as Map<String, dynamic>;
    final entries = data['settings'] as Map<String, dynamic>;
    return HomeDiscovery(
      manifest:
          manifest ??
          (data['manifest'] == null
              ? null
              : wire.Devices.fromJson(
                  data['manifest'] as Map<String, dynamic>,
                )),
      settings: Map.unmodifiable(
        entries.map((id, value) {
          final entry = value as Map<String, dynamic>;
          return MapEntry(
            id,
            HomeDeviceSettings(
              room: entry['room'] as String?,
              name: entry['name'] as String,
              delegated: (entry['delegated'] as List<dynamic>)
                  .cast<String>()
                  .toSet(),
            ),
          );
        }),
      ),
    );
  }

  @override
  Future<void> saveRoomsNamesDelegation(
    String scope,
    HomeDiscovery discovery,
    Map<String, HomeDeviceSettings> settings,
  ) => store.write(
    _key(scope),
    jsonEncode({
      'manifest': discovery.manifest?.toJson(),
      'settings': {
        for (final entry in settings.entries)
          entry.key: {
            'room': entry.value.room,
            'name': entry.value.name,
            'delegated': entry.value.delegated.toList(),
          },
      },
    }),
  );
}
