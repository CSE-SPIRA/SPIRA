import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../contracts.dart' as wire;
import '../platform/gallery.dart';

class AppApiException implements Exception {
  const AppApiException(this.status, this.code, {this.reason});

  final int status;
  final wire.ErrorCode? code;
  final String? reason;
}

bool isServerUnavailable(Object error) => switch (error) {
  AppApiException(:final status) => status == 408 || status >= 500,
  http.ClientException() || SocketException() || TimeoutException() => true,
  _ => false,
};

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

  /// In-memory bearer token for the active peer.
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
    final response = await _send(request, statuses);
    return decode(utf8.decode(response.bodyBytes));
  }

  Future<http.Response> _send(
    http.BaseRequest request,
    Set<int> statuses,
  ) async {
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
    if (!statuses.contains(response.statusCode)) {
      wire.Error? error;
      try {
        final body =
            jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
        // The generated decoder expects a map for optional details.
        body['details'] ??= <String, dynamic>{};
        error = wire.Error.fromJson(body);
      } catch (_) {
        // A proxy may send a non-contract error response.
      }
      final detail = error?.details?['reason'];
      throw AppApiException(
        response.statusCode,
        error?.code,
        reason: detail is String ? detail : error?.message,
      );
    }
    return response;
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

  Future<wire.Episode> episode(String id) =>
      _json('GET', _episode(id), {200}, wire.episodeFromJson);

  Future<wire.Rationale> rationale(String id) =>
      _json('GET', '${_episode(id)}/rationale', {200}, wire.rationaleFromJson);

  Future<wire.Card> react(String cardId, wire.Reaction body) => _json(
    'POST',
    '/v1/cards/${Uri.encodeComponent(cardId)}/reactions',
    {200},
    wire.cardFromJson,
    body: body.toJson()..removeWhere((key, value) => value == null),
  );

  Future<ShareReceipt> share(String household, SharedOrder order) async {
    final images = <http.MultipartFile>[];
    for (final image in order.images) {
      final png = image.path.endsWith('.png');
      images.add(
        http.MultipartFile(
          'images',
          image.openRead(),
          await image.length(),
          filename: image.uri.pathSegments.last,
          contentType: MediaType('image', png ? 'png' : 'jpeg'),
        ),
      );
    }
    return _share(household, order.sourceId, order.sharedAt, images);
  }

  Future<ShareReceipt> shareExample(
    String household,
    String sourceId,
    String sharedAt,
    Uint8List image,
  ) => _share(household, sourceId, sharedAt, [
    http.MultipartFile.fromBytes(
      'images',
      image,
      filename: 'example-order.png',
      contentType: MediaType('image', 'png'),
    ),
  ]);

  Future<ShareReceipt> shareGallery(
    String household,
    String sourceId,
    String sharedAt,
    List<GalleryImage> images,
  ) => _share(household, sourceId, sharedAt, [
    for (final (index, image) in images.indexed)
      http.MultipartFile.fromBytes(
        'images',
        image.bytes,
        filename: 'order-${index + 1}.${image.png ? 'png' : 'jpg'}',
        contentType: MediaType('image', image.png ? 'png' : 'jpeg'),
      ),
  ]);

  Future<ShareReceipt> _share(
    String household,
    String sourceId,
    String sharedAt,
    List<http.MultipartFile> images,
  ) async {
    final request = http.MultipartRequest('POST', _uri('/v1/orders'))
      ..fields.addAll({
        'household_id': household,
        'source_id': sourceId,
        'shared_at': sharedAt,
      })
      ..files.addAll(images);
    final response = await _send(request, {200, 202});
    final accepted = wire.orderAcceptedFromJson(
      utf8.decode(response.bodyBytes),
    );
    return (accepted: accepted, isNew: response.statusCode == 202);
  }
}

typedef ShareReceipt = ({wire.OrderAccepted accepted, bool isNew});
