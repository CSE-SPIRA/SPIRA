import 'dart:convert';

import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

import '../contracts.dart' as wire;

typedef CalendarReader = Future<wire.Calendar> Function({
  required bool interactive,
});

const _calendarScopes = [
  'https://www.googleapis.com/auth/calendar.events.readonly',
];

class GoogleCalendarReader {
  GoogleCalendarReader(this.serverClientId);

  final String serverClientId;
  Future<void>? _initialization;

  Future<void> _initialize() => _initialization ??= GoogleSignIn.instance
      .initialize(serverClientId: serverClientId);

  Future<void> disconnect() async {
    await _initialize();
    await GoogleSignIn.instance.disconnect();
  }

  Future<wire.Calendar> call({required bool interactive}) async {
    await _initialize();
    final signIn = GoogleSignIn.instance;
    // Android remembers the default account selected during setup.
    final authClient = interactive
        ? (await signIn.authenticate()).authorizationClient
        : signIn.authorizationClient;
    final authorization = interactive
        ? await authClient.authorizeScopes(_calendarScopes)
        : await authClient.authorizationForScopes(_calendarScopes);
    if (authorization == null) throw StateError('Calendar unavailable');
    final now = DateTime.now().toUtc();
    final end = now.add(const Duration(days: 14));
    final events = <wire.EventElement>[];
    String? page;
    final client = http.Client();
    try {
      do {
        final request =
            http.Request(
                'GET',
                Uri.https(
                  'www.googleapis.com',
                  '/calendar/v3/calendars/primary/events',
                  {
                    'timeMin': now.toIso8601String(),
                    'timeMax': end.toIso8601String(),
                    'singleEvents': 'true',
                    'fields': 'nextPageToken,items(id,summary,start,end)',
                    'pageToken': ?page,
                  },
                ),
              )
              ..followRedirects = false
              ..headers['Authorization'] =
                  'Bearer ${authorization.accessToken}';
        final response = await client
            .send(request)
            .then(http.Response.fromStream)
            .timeout(const Duration(seconds: 25));
        if (response.statusCode != 200) {
          if (response.statusCode == 401) {
            await authClient.clearAuthorizationToken(
              accessToken: authorization.accessToken,
            );
          }
          throw StateError('Calendar unavailable');
        }
        final result =
            jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
        for (final item
            in (result['items'] as List? ?? const [])
                .cast<Map<String, dynamic>>()) {
          events.add(
            wire.EventElement(
              id: item['id'] as String,
              title: item['summary'] as String? ?? '',
              start: _timestamp(item['start'] as Map<String, dynamic>),
              end: _timestamp(item['end'] as Map<String, dynamic>),
            ),
          );
        }
        page = result['nextPageToken'] as String?;
      } while (page != null);
      return wire.Calendar(events: events);
    } finally {
      client.close();
    }
  }

  // The household calendar contract uses Asia/Seoul for date-only occurrences.
  String _timestamp(Map<String, dynamic> value) =>
      value['dateTime'] as String? ?? '${value['date']}T00:00:00+09:00';
}
