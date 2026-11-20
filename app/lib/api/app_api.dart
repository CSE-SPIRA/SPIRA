import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../contracts.dart' as wire;

class AppApiException implements Exception {
  const AppApiException(this.status, this.code);

  final int status;
  final wire.ErrorCode? code;
}

/// The files have already been copied to the Android app's private inbox.
class SharedOrder {
  const SharedOrder(this.sourceId, this.sharedAt, this.images);

  final String sourceId;
  final String sharedAt;
  final List<File> images;
}

class AppApi {
  AppApi(this.baseUrl, {http.Client? client})
    : _client = client ?? http.Client();

  final Uri baseUrl;
  final http.Client _client;

  /// Entered at runtime when the peer requires a bearer token.
  String? token;

  String _household(String id) => '/v1/households/${Uri.encodeComponent(id)}';
  String _episode(String id) => '/v1/episodes/${Uri.encodeComponent(id)}';

  Uri _uri(String path, [Map<String, String>? query]) {
    return baseUrl.replace(
      path: baseUrl.path.replaceFirst(RegExp(r'/$'), '') + path,
      queryParameters: query,
    );
  }

  Future<T> _json<T>(
    String method,
    String path,
    Set<int> statuses,
    T Function(String) decode, {
    Map<String, Object?>? body,
    Map<String, String>? query,
  }) async {
    final request = http.Request(method, _uri(path, query));
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    return decode(await _send(request, statuses));
  }

  Future<String> _send(http.BaseRequest request, Set<int> statuses) async {
    request.followRedirects = false;
    request.headers['Accept'] = 'application/json';
    final bearer = token;
    if (bearer != null && request.url.path.startsWith(_uri('/v1/').path)) {
      request.headers['Authorization'] = 'Bearer $bearer';
    }
    final response = await _client
        .send(request)
        .then(http.Response.fromStream)
        .timeout(const Duration(seconds: 25));
    final body = utf8.decode(response.bodyBytes);
    if (!statuses.contains(response.statusCode)) {
      wire.ErrorCode? code;
      try {
        code = wire.errorFromJson(body).code;
      } catch (_) {
        // A proxy may send a non-contract error response.
      }
      throw AppApiException(response.statusCode, code);
    }
    return body;
  }

  Future<wire.Health> health() =>
      _json('GET', '/health', {200, 503}, wire.healthFromJson);

  Future<wire.HouseholdCreated> createHousehold(wire.HouseholdCreate body) =>
      _json(
        'POST',
        '/v1/households',
        {201},
        wire.householdCreatedFromJson,
        body: body.toJson(),
      );

  Future<wire.Profile> profile(String household, wire.Profile body) => _json(
    'PUT',
    '${_household(household)}/profile',
    {200},
    wire.profileFromJson,
    body: body.toJson()..remove('household_id'),
  );

  Future<wire.CalendarResponse> calendar(
    String household,
    wire.Calendar body,
  ) => _json(
    'PUT',
    '${_household(household)}/calendar',
    {202},
    wire.calendarResponseFromJson,
    body: body.toJson(),
  );

  Future<wire.Pause> pause(String household, wire.Pause body) => _json(
    'POST',
    '${_household(household)}/pause',
    {200},
    wire.pauseFromJson,
    body: body.toJson()..remove('household_id'),
  );

  Future<wire.EpisodeList> episodes(
    String household, {
    String? before,
    int? limit,
  }) => _json(
    'GET',
    '${_household(household)}/episodes',
    {200},
    wire.episodeListFromJson,
    query: {'before': ?before, if (limit != null) 'limit': '$limit'},
  );

  Future<wire.CardsResponse> cards(String household, {String? since}) => _json(
    'GET',
    '${_household(household)}/cards',
    {200},
    wire.cardsResponseFromJson,
    query: since == null ? null : {'since': since},
  );

  Future<wire.Memory> memory(String household) => _json(
    'GET',
    '${_household(household)}/memory',
    {200},
    wire.memoryFromJson,
  );

  Future<void> deleteCase(String household, String id) => _json(
    'DELETE',
    '${_household(household)}/memory/${Uri.encodeComponent(id)}',
    {204},
    (_) {},
  );

  Future<wire.Episode> episode(String id) =>
      _json('GET', _episode(id), {200}, wire.episodeFromJson);

  Future<wire.OrderAccepted> editOrder(String id, wire.OrderEdit body) => _json(
    'PUT',
    '${_episode(id)}/order',
    {202},
    wire.orderAcceptedFromJson,
    body: body.toJson(),
  );

  Future<wire.Rationale> rationale(String id) =>
      _json('GET', '${_episode(id)}/rationale', {200}, wire.rationaleFromJson);

  Future<wire.Card> react(String cardId, wire.Reaction body) => _json(
    'POST',
    '/v1/cards/${Uri.encodeComponent(cardId)}/reactions',
    {200},
    wire.cardFromJson,
    body: body.toJson()..removeWhere((key, value) => value == null),
  );

  Future<wire.OrderAccepted> share(String household, SharedOrder order) async {
    final request = http.MultipartRequest('POST', _uri('/v1/orders'));
    request.fields.addAll({
      'household_id': household,
      'source_id': order.sourceId,
      'shared_at': order.sharedAt,
    });
    for (final image in order.images) {
      final png = image.path.endsWith('.png');
      request.files.add(
        http.MultipartFile(
          'images',
          image.openRead(),
          await image.length(),
          filename: image.uri.pathSegments.last,
          contentType: MediaType('image', png ? 'png' : 'jpeg'),
        ),
      );
    }
    return wire.orderAcceptedFromJson(await _send(request, {200, 202}));
  }

  Future<wire.OrderAccepted> shareExample() async {
    // The demo shell route replays a recorded order and only needs a PNG part.
    final image = base64Decode(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=',
    );
    final request = http.MultipartRequest('POST', _uri('/demo/api/order'))
      ..fields['sample'] = 'birthday'
      ..files.add(
        http.MultipartFile.fromBytes(
          'images',
          image,
          filename: 'example-order.png',
          contentType: MediaType('image', 'png'),
        ),
      );
    return wire.orderAcceptedFromJson(await _send(request, {200, 202}));
  }
}
