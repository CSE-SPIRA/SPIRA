import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../contracts.dart' as wire;

class HttpHomeHubOnboarding {
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

  Future<wire.Devices?> fetchDevices(String household) async {
    final uri = _uri;
    final key = _apiKey;
    if (uri == null || key == null) return null;

    final request = http.Request('GET', uri)
      ..followRedirects = false
      ..headers['Accept'] = 'application/json'
      ..headers['X-API-Key'] = key;
    try {
      final response = await _client
          .send(request)
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 12));
      if (response.statusCode != 200) return null;
      final devices = wire.devicesFromJson(utf8.decode(response.bodyBytes));
      return devices.householdId == household ? devices : null;
    } on http.ClientException {
      return null;
    } on TimeoutException {
      return null;
    } on FormatException {
      return null;
    } on TypeError {
      return null;
    }
  }

  void close() => _client.close();
}
