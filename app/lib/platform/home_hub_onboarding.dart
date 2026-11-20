import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../contracts.dart' as wire;
import 'app_store.dart';

abstract interface class HomeHubOnboardingPort {
  Future<HomeDiscovery> discover(String scope);

  Future<HomeSaveResult> saveRoomsNamesDelegation(
    String scope,
    HomeDiscovery discovery,
    Map<String, HomeDeviceSettings> settings,
  );
}

enum HomeSaveResult { local, sent, uploadPending }

class HomeHubException implements Exception {
  const HomeHubException(this.status, {this.message});

  final int status;
  final String? message;
}

/// Device details needed by the App. The Hub's discovery has no substrate.
class HomeDevice {
  const HomeDevice({
    required this.id,
    required this.type,
    required this.label,
    required this.room,
    required this.commands,
    required this.never,
    this.substrate,
  });

  HomeDevice.fromManifest(wire.DeviceElement device)
    : id = device.id,
      type = device.type,
      label = device.label,
      room = device.room,
      commands = device.commands,
      never = device.never,
      substrate = device.substrate;

  final String id;
  final String type;
  final String? label;
  final String? room;
  final List<wire.CommandElement> commands;
  final List<String> never;
  final wire.Substrate? substrate;

  Set<String> get selectableCommands => {
    for (final command in commands)
      if (!never.contains(command.cmd)) command.cmd,
  };
}

class HomeDeviceSettings {
  HomeDeviceSettings({
    required this.room,
    required this.name,
    required Set<String>? delegated,
    this.roomConfirmed = true,
  }) : delegated = delegated == null ? null : Set.unmodifiable(delegated);

  final String? room;
  final String? name;
  final Set<String>? delegated;
  final bool roomConfirmed;
}

class HomeDiscovery {
  const HomeDiscovery({
    this.manifest,
    this.devices = const [],
    this.settings = const {},
  });

  final wire.Devices? manifest;
  final List<HomeDevice> devices;
  final Map<String, HomeDeviceSettings> settings;

  HomeDiscovery withSettings(Map<String, HomeDeviceSettings> updates) =>
      HomeDiscovery(
        manifest: manifest,
        devices: devices,
        settings: Map.unmodifiable({...settings, ...updates}),
      );
}

class HttpHomeHubOnboarding implements HomeHubOnboardingPort {
  HttpHomeHubOnboarding(String origin, {http.Client? client})
    : _uri = _devicesUri(origin),
      _client = client ?? http.Client();

  final Uri? _uri;
  final http.Client _client;
  String? _apiKey;

  void useApiKey(String key) => _apiKey = key;

  static Uri? _devicesUri(String origin) {
    final uri = Uri.tryParse(origin);
    if (uri == null ||
        uri.host.isEmpty ||
        (!uri.isScheme('http') && !uri.isScheme('https')) ||
        uri.userInfo.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        uri.hasQuery ||
        uri.hasFragment) {
      return null;
    }
    return uri.replace(path: '/home/onboarding/devices');
  }

  Future<http.Response> _send(String method, {Object? body}) async {
    final uri = _uri;
    if (uri == null) throw const HomeHubException(503);
    final key = _apiKey;
    if (key == null) throw const HomeHubException(401);

    final request = http.Request(method, uri)
      ..followRedirects = false
      ..headers['Accept'] = 'application/json'
      ..headers['X-API-Key'] = key;
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    try {
      return await _client
          .send(request)
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 12));
    } on http.ClientException {
      throw const HomeHubException(503);
    } on TimeoutException {
      throw const HomeHubException(503);
    }
  }

  Map<String, dynamic> _json(http.Response response) =>
      jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;

  HomeHubException _failure(http.Response response) {
    String? message;
    if (response.statusCode == 422) {
      try {
        message = _json(response)['message'] as String?;
      } on FormatException {
        // A proxy may return an error outside the Hub's format.
      } on TypeError {
        // The HTTP status still identifies the rejection.
      }
    }
    return HomeHubException(response.statusCode, message: message);
  }

  @override
  Future<HomeDiscovery> discover(String scope) async {
    final response = await _send('GET');
    if (response.statusCode != 200) throw _failure(response);

    final devices = <HomeDevice>[];
    final settings = <String, HomeDeviceSettings>{};
    for (final entry
        in (_json(response)['devices'] as List<dynamic>)
            .cast<Map<String, dynamic>>()) {
      final device = HomeDevice(
        id: entry['id'] as String,
        type: entry['type'] as String,
        label: entry['label'] as String?,
        room: entry['room'] as String?,
        commands: (entry['commands'] as List<dynamic>)
            .cast<Map<String, dynamic>>()
            .map(wire.CommandElement.fromJson)
            .toList(),
        never: (entry['never'] as List<dynamic>).cast<String>(),
      );
      devices.add(device);
      if (entry['stored'] case final Map<String, dynamic> stored) {
        final delegated = (stored['delegated_commands'] as List<dynamic>?)
            ?.cast<String>()
            .toSet();
        final storedRoom = stored['room'] as String?;
        final storedName = stored['label'] as String?;
        // A save always includes a delegation list, even when it is empty.
        final roomConfirmed =
            storedRoom != null ||
            (delegated != null && stored.containsKey('room'));
        final nameSaved =
            storedName != null ||
            (delegated != null && stored.containsKey('label'));
        settings[device.id] = HomeDeviceSettings(
          room: roomConfirmed ? storedRoom : device.room,
          name: nameSaved ? storedName : device.label,
          delegated: delegated,
          roomConfirmed: roomConfirmed,
        );
      }
    }
    return HomeDiscovery(
      devices: List.unmodifiable(devices),
      settings: Map.unmodifiable(settings),
    );
  }

  @override
  Future<HomeSaveResult> saveRoomsNamesDelegation(
    String scope,
    HomeDiscovery discovery,
    Map<String, HomeDeviceSettings> settings,
  ) async {
    final response = await _send(
      'PUT',
      body: {
        'devices': [
          for (final entry in settings.entries)
            {
              'id': entry.key,
              'room': entry.value.room,
              'label': entry.value.name,
              'delegated_commands': entry.value.delegated!.toList(),
            },
        ],
      },
    );
    if (response.statusCode == 502) return HomeSaveResult.uploadPending;
    if (response.statusCode != 200) throw _failure(response);
    if (_json(response)['revision'] is! int) {
      throw const FormatException('Missing Hub revision');
    }
    return HomeSaveResult.sent;
  }

  void close() => _client.close();
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
    final data = saved == null
        ? <String, dynamic>{}
        : jsonDecode(saved) as Map<String, dynamic>;
    final entries = data['settings'] as Map<String, dynamic>? ?? {};
    if (data['manifest'] case final Map<String, dynamic> cached
        when manifest == null) {
      manifest = wire.Devices.fromJson(cached);
    }
    return HomeDiscovery(
      manifest: manifest,
      devices:
          manifest?.devices.map(HomeDevice.fromManifest).toList() ?? const [],
      settings: Map.unmodifiable(
        entries.map((id, value) {
          final entry = value as Map<String, dynamic>;
          return MapEntry(
            id,
            HomeDeviceSettings(
              room: entry['room'] as String?,
              name: entry['name'] as String?,
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
  Future<HomeSaveResult> saveRoomsNamesDelegation(
    String scope,
    HomeDiscovery discovery,
    Map<String, HomeDeviceSettings> settings,
  ) async {
    await store.write(
      _key(scope),
      jsonEncode({
        'manifest': discovery.manifest?.toJson(),
        'settings': {
          for (final entry in {...discovery.settings, ...settings}.entries)
            entry.key: {
              'room': entry.value.room,
              'name': entry.value.name,
              'delegated': entry.value.delegated!.toList(),
            },
        },
      }),
    );
    return HomeSaveResult.local;
  }
}
