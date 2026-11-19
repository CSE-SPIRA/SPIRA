import 'dart:async';
import 'dart:convert';
import 'dart:io';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:spira_app/api/app_api.dart';
import 'package:spira_app/app_controller.dart';
import 'package:spira_app/contracts.dart' as wire;
import 'package:spira_app/main.dart';
import 'package:spira_app/platform/android_bridge.dart';

Map<String, dynamic> fixture(String file, {String episode = 'ep_9031'}) =>
    jsonDecode(File('../contracts/fixtures/$episode/$file').readAsStringSync())
        as Map<String, dynamic>;

class TestImage extends Fake implements File {
  static final _bytes = utf8.encode('screenshot');

  @override
  String get path => '/0.jpg';

  @override
  Uri get uri => Uri.file(path);

  @override
  Future<int> length() async => _bytes.length;

  @override
  Stream<List<int>> openRead([int? start, int? end]) => Stream.value(_bytes);
}

class TestStore implements AppStore {
  final values = <String, String>{};
  final saved = <Object?>[];

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
    saved.add(jsonDecode(value));
  }
}

class TestPlatform implements AppPlatform {
  final changes = StreamController<void>.broadcast();
  final orders = <SharedOrder>[];
  final delivered = <String, String>{};
  final deliveries = <String>[];
  final acknowledged = <String, String>{};
  bool permission = true;
  void Function()? beforeAck;

  @override
  Stream<void> get sharesChanged => changes.stream;

  @override
  Future<ShareInbox> inbox(String scope) async => ShareInbox(
    orders.where((order) => !acknowledged.containsKey(order.sourceId)).toList(),
    null,
  );

  @override
  Future<void> acknowledge(
    String scope,
    String sourceId,
    String episodeId,
  ) async {
    beforeAck?.call();
    acknowledged[sourceId] = episodeId;
  }

  @override
  Future<void> discardInvalid(String scope, String sourceId) async {
    orders.removeWhere((order) => order.sourceId == sourceId);
  }

  @override
  Future<bool> notify(
    String scope,
    String key,
    String title,
    String text,
  ) async {
    if (!permission) return false;
    final scoped = '$scope/$key';
    if (!delivered.containsKey(scoped)) deliveries.add(text);
    delivered[scoped] = text;
    return true;
  }

  @override
  Future<void> requestNotificationPermission() async {}
}

class Peer {
  final episodes = <String, Map<String, dynamic>>{};
  final requests = <http.Request>[];
  final reactions = <(String, Map<String, dynamic>)>[];
  final pauses = <Object?>[];
  final edits = <Object?>[];
  List<Map<String, dynamic>> cards = [];
  Map<String, dynamic> memory = fixture('memory.json');
  Map<String, dynamic>? rationale = fixture('rationale.json');
  Map<String, dynamic> get birthday => episodes['ep_9031']!;
  bool failDelete = false;
  bool keepDeletedUntilRead = false;
  bool unavailable = false;
  int rationaleReads = 0;
  int pollCount = 0;
  Future<http.Response> Function(http.Request)? reaction;
  Future<http.Response> Function(http.Request)? upload;
  void Function(bool)? onPause;

  AppApi client() =>
      AppApi(Uri.parse('https://test.invalid'), client: MockClient(handle));

  static http.Response response(Object? payload, [int status = 200]) =>
      http.Response.bytes(
        utf8.encode(jsonEncode(payload)),
        status,
        headers: {'content-type': 'application/json'},
      );

  Future<http.Response> handle(http.Request request) async {
    requests.add(request);
    if (unavailable) {
      return response({'code': 'internal', 'message': 'offline'}, 503);
    }
    final method = request.method;
    final path = request.url.path;
    const householdPath = '/v1/households/h_042';
    if (method == 'POST' && path == '/v1/households') {
      return response(fixture('household.created.json'), 201);
    }
    if (method == 'PUT' && path == '$householdPath/profile') {
      return response({
        'household_id': 'h_042',
        ...jsonDecode(request.body) as Map<String, dynamic>,
      });
    }
    if (method == 'PUT' && path == '$householdPath/calendar') {
      return response({'accepted': 5}, 202);
    }
    if (method == 'POST' && path == '$householdPath/pause') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      pauses.add(body);
      onPause?.call(body['paused'] as bool);
      return response({'household_id': 'h_042', ...body});
    }
    if (method == 'GET' && path == '$householdPath/cards') {
      pollCount++;
      return response({
        'cards': cards,
        'server_time': '2026-11-05T01:02:03+09:00',
      });
    }
    if (method == 'GET' && path == '$householdPath/episodes') {
      return response({
        'episodes': [
          for (final episode in episodes.values)
            {
              for (final key in [
                'episode_id',
                'shared_at',
                'status',
                'item_count',
                'card_ids',
              ])
                key: episode[key],
            },
        ],
        'next_before': null,
      });
    }
    if (method == 'GET' && path == '$householdPath/memory') {
      return response(memory);
    }
    if (method == 'DELETE' && path.startsWith('$householdPath/memory/')) {
      if (failDelete) {
        return response({'code': 'internal', 'message': 'failed'}, 500);
      }
      if (!keepDeletedUntilRead) {
        memory = {'household_id': 'h_042', 'intents': []};
      }
      return http.Response('', 204);
    }
    if (method == 'GET' &&
        path.startsWith('/v1/episodes/') &&
        path.endsWith('/rationale')) {
      rationaleReads++;
      if (rationale != null) return response(rationale);
      return response({'code': 'not_found', 'message': 'no rationale'}, 404);
    }
    if (method == 'PUT' &&
        path.startsWith('/v1/episodes/') &&
        path.endsWith('/order')) {
      edits.add(jsonDecode(request.body));
      birthday['status'] = 'reading';
      return response({'episode_id': 'ep_9031', 'status': 'received'}, 202);
    }
    if (method == 'GET' && path.startsWith('/v1/episodes/')) {
      final episode = episodes[request.url.pathSegments.last];
      if (episode != null) return response(episode);
      return response({'code': 'not_found', 'message': 'pending'}, 404);
    }
    if (method == 'POST' &&
        path.startsWith('/v1/cards/') &&
        path.endsWith('/reactions')) {
      reactions.add((
        request.url.pathSegments[2],
        jsonDecode(request.body) as Map<String, dynamic>,
      ));
      return reaction!(request);
    }
    if (method == 'POST' && path == '/v1/orders') return upload!(request);
    fail('Unexpected App API request $method $path');
  }
}

List<Map<String, dynamic>> lines(Map<String, dynamic> card) =>
    (card['lines'] as List<dynamic>).cast<Map<String, dynamic>>();

Map<String, dynamic> phase(Map<String, dynamic> card, int minute) => {
  ...card,
  'updated_at': '2026-10-17T14:${minute.toString().padLeft(2, '0')}:00+09:00',
  'notify': false,
};

AppController controller(
  Peer peer, {
  TestPlatform? platform,
  TestStore? store,
  wire.Devices? discovered,
  Future<wire.Calendar> Function()? calendar,
  bool setup = false,
  bool fixture = true,
}) => AppController(
  api: peer.client(),
  platform: platform ?? TestPlatform(),
  store: store ?? TestStore(),
  fixture: fixture,
  configuredHousehold: setup ? null : 'h_042',
  discovered: discovered,
  readCalendar: calendar,
);

Future<void> openApp(WidgetTester tester, AppController app) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(850, 1700);
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(SpiraApp(app: app));
  await tester.pumpAndSettle();
}

Future<void> tapText(WidgetTester tester, String text, {int index = 0}) async {
  final target = find.text(text).at(index);
  await tester.ensureVisible(target);
  await tester.tap(target);
  await tester.pumpAndSettle();
}

Future<void> settings(WidgetTester tester) async {
  await tester.tap(find.byTooltip('설정'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'APP-AT-01 selects household types and records explicit device choices',
    (tester) async {
      final peer = Peer();
      await openApp(
        tester,
        controller(
          peer,
          setup: true,
          discovered: wire.Devices.fromJson(fixture('devices.json')),
        ),
      );
      await tapText(tester, '3~4인');
      await tapText(tester, '초등 자녀');
      await tapText(tester, '우리 집 만들기');
      await tapText(tester, '건너뛰기');
      expect(find.text('거실 · 조명 · 실물 기기'), findsOneWidget);
      expect(find.text('거실 · 로봇청소기 · 가상 기기'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('cleaner_01/clean')));
      await tester.pumpAndSettle();
      await tapText(tester, '맡기기');
      await tester.tap(find.byKey(const ValueKey('light_01/color')));
      await tester.pumpAndSettle();
      await tapText(tester, '맡기지 않기');
      await tapText(tester, '설정 완료');
      final profile = peer.requests.singleWhere(
        (r) => r.url.path.endsWith('/profile'),
      );
      expect(jsonDecode(profile.body), {
        'household_types': ['3~4인', '초등 자녀'],
      });
      expect(
        peer.requests.any((r) => r.url.path.endsWith('/calendar')),
        isFalse,
      );
      await settings(tester);
      expect(find.text('청소 · 맡기기로 선택'), findsOneWidget);
      expect(find.text('조명 색상 설정 · 맡기지 않기로 선택'), findsOneWidget);
      expect(find.textContaining('조명 색온도 설정'), findsNothing);
    },
  );

  testWidgets(
    'APP-AT-01 sends only Calendar contract fields after connection',
    (tester) async {
      final peer = Peer();
      final calendar = fixture('calendar.json');
      await openApp(
        tester,
        controller(
          peer,
          setup: true,
          calendar: () async => wire.Calendar.fromJson(calendar),
        ),
      );
      await tapText(tester, '2인');
      await tapText(tester, '우리 집 만들기');
      await tapText(tester, 'Google 캘린더 연결');
      expect(
        jsonDecode(
          peer.requests
              .singleWhere((r) => r.url.path.endsWith('/calendar'))
              .body,
        ),
        calendar,
      );
      await tapText(tester, '설정 완료');
    },
  );

  test('APP-AT-02 Dart boundary sends one and three in order and retries the same source after lost response', () async {
    final folder = Directory.systemTemp.createTempSync('spira-shares-');
    addTearDown(() => folder.deleteSync(recursive: true));
    final images = [
      for (var i = 0; i < 3; i++)
        File('${folder.path}/$i.png')..writeAsStringSync('image-$i'),
    ];
    final one = SharedOrder('one', '2026-10-15T21:00:08+09:00', [images.first]);
    final three = SharedOrder('three', '2026-10-15T21:01:12+09:00', images);
    final store = TestStore();
    final platform = TestPlatform()..orders.addAll([one, three]);
    platform.beforeAck = () {
      expect(
        store.saved.whereType<Map<String, dynamic>>().last['accepted'],
        contains('ep_9031'),
      );
    };
    final peer = Peer();
    final sources = <String, String>{};
    var attempts = 0;
    peer.upload = (request) async {
      final body = request.body;
      expect(
        request.headers['content-type'],
        startsWith('multipart/form-data; boundary='),
      );
      expect(body, contains('name="household_id"\r\n\r\nh_042'));
      expect(body, contains('name="shared_at"'));
      final source = RegExp('name="source_id"\r\n\r\n([^\r]+)')
          .firstMatch(body)!
          .group(1)!;
      final ordered = RegExp('filename="([^"]+)"')
          .allMatches(body)
          .map((match) => match.group(1))
          .toList();
      expect(
        ordered,
        source == 'one' ? ['0.png'] : ['0.png', '1.png', '2.png'],
      );
      expect(body, contains('content-type: image/png'));
      final duplicate = sources.containsKey(source);
      sources[source] = 'ep_9031';
      if (++attempts == 1) {
        throw const SocketException('response lost after intake');
      }
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'reading';
      return Peer.response({
        'episode_id': sources[source],
        'status': 'received',
      }, duplicate ? 200 : 202);
    };
    final first = controller(peer, platform: platform, store: store);
    await first.start();
    expect(platform.acknowledged, isEmpty);
    first.dispose();
    final restarted = controller(peer, platform: platform, store: store);
    await restarted.start();
    expect(platform.acknowledged, {'one': 'ep_9031', 'three': 'ep_9031'});
    platform.orders.add(one);
    await restarted.sync();
    expect(attempts, 3);
    expect(restarted.episodes.keys, ['ep_9031']);
    restarted.dispose();
  });

  testWidgets(
    'APP-AT-03 reads receipt and status, edits the full named list before start, and handles extraction failure',
    (tester) async {
      final platform = TestPlatform();
      final peer = Peer()
        ..upload = (_) async =>
            Peer.response({'episode_id': 'ep_9031', 'status': 'received'}, 202);
      final app = controller(peer, platform: platform);
      await openApp(tester, app);
      platform.orders.add(
        SharedOrder('capture', '2026-10-15T21:00:08+09:00', [TestImage()]),
      );
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('주문을 받았어요. 읽기 결과를 기다리는 중이에요.'), findsOneWidget);
      expect(find.byType(Card), findsNothing);
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'reading'
        ..['card_ids'] = <String>[];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('주문을 읽고 있어요.'), findsOneWidget);
      peer.birthday['status'] = 'notified';
      peer.birthday['card_ids'] = ['nc_331'];
      peer.cards = [fixture('card.v1.json')];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('읽은 품목 9개'), findsOneWidget);
      await tapText(tester, '읽은 품목 수정');
      await tester.enterText(find.byType(TextFormField).at(0), '딸기 상품');
      await tester.enterText(find.byType(TextFormField).at(1), '3');
      final save = find.text('수정 저장');
      await tester.scrollUntilVisible(
        save,
        360,
        scrollable: find.byType(Scrollable).last,
      );
      await tapText(tester, '수정 저장');
      final body = peer.edits.single as Map<String, dynamic>;
      expect((body['items'] as List<dynamic>).first, {
        'item_id': 'it_1',
        'name': '딸기 상품',
        'qty': 3,
      });
      expect(body['items'], hasLength(9));
      peer.birthday['status'] = 'notified';
      peer.cards = [phase(fixture('card.v1.json'), 1)];
      lines(peer.cards.single).first['state'] = 'running';
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('읽은 품목 수정'), findsNothing);
      peer.birthday['status'] = 'read_failed';
      peer.birthday['card_ids'] = <String>[];
      peer.birthday['items'] = [];
      peer.birthday['item_count'] = 0;
      peer.birthday['item_tasks'] = [];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.textContaining('주문 화면을 캡처해서 다시 공유'), findsOneWidget);
      expect(find.byType(Card), findsNothing);
    },
  );

  testWidgets(
    'APP-AT-04/05/10 renders two cards, supplied timing and all distinct result states',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['card_ids'] = ['nc_331', 'nc_340'];
      final second = fixture('card.found.json', episode: 'ep_9120')
        ..['episode_id'] = 'ep_9031'
        ..['summary'] = {'done': 0, 'total': 2, 'waiting_for': 'guest_arrived'};
      peer.cards = [fixture('card.v1.json'), second];
      final app = controller(peer);
      await openApp(tester, app);
      expect(find.byType(Card), findsNWidgets(2));
      expect(find.text('이 준비 중지'), findsNWidgets(2));
      expect(find.text('승인'), findsNothing);
      expect(find.text('0/4 준비'), findsOneWidget);
      expect(find.text('손님 도착 기다리는 중'), findsOneWidget);
      expect(find.text('일정 · 10월 17일 14:00'), findsOneWidget);
      expect(find.text('실행 예정 · 10월 17일 12:30'), findsOneWidget);
      expect(
        find.descendant(of: find.byType(Card), matching: find.text('완료')),
        findsNothing,
      );
      const states = [
        ('held', '시간을 기다리는 중'),
        ('scheduled', '예정됨'),
        ('running', '진행 중'),
        ('done', '완료'),
        ('partial', '일부 완료'),
        ('failed', '실패'),
        ('unknown', '결과 확인 불가'),
        ('blocked', '실행하지 못함'),
        ('user_changed', '사용자가 변경함'),
        ('off', '꺼짐'),
        ('stopped', '중지됨'),
        ('cancelled', '취소됨'),
        ('dropped', '준비하지 않음'),
      ];
      for (final (index, (code, label)) in states.indexed) {
        final card = phase(fixture('card.v1.json'), index + 1);
        lines(card).first['state'] = code;
        peer.cards = [card];
        await app.sync();
        await tester.pumpAndSettle();
        expect(
          find.descendant(
            of: find.byKey(const ValueKey('nc_331')),
            matching: find.text(label),
          ),
          findsWidgets,
          reason: code,
        );
      }
      final finalCard = fixture('card.final.json');
      lines(finalCard)[1]['end_state'] = 'restore_failed';
      lines(finalCard)[3]['end_state'] = 'restored';
      peer.cards = [finalCard];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('3/3 준비'), findsOneWidget);
      expect(find.text('사용자가 바꾼 상태를 유지함'), findsOneWidget);
      expect(find.text('사용자가 조명을 바꿔 현재 상태를 유지했어요'), findsOneWidget);
      expect(find.text('이전 상태로 복원됨'), findsOneWidget);
      expect(find.text('복원 실패 또는 결과 확인 불가'), findsOneWidget);
      expect(find.text('복원 대상 없음'), findsOneWidget);
      expect(find.textContaining('종료 조건'), findsNothing);

      peer.unavailable = true;
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.textContaining('마지막으로 확인한 정보'), findsOneWidget);
      expect(
        tester
            .widget<OutlinedButton>(
              find.ancestor(
                of: find.text('이 준비 중지').first,
                matching: find.byType(OutlinedButton),
              ),
            )
            .onPressed,
        isNull,
      );
    },
  );

  testWidgets(
    'APP-AT-06 polls every 30 seconds using the cursor and asks Android to notify each flagged pair once',
    (tester) async {
      final peer = Peer();
      final platform = TestPlatform();
      final held = fixture('card.held.json', episode: 'ep_9120');
      final found = fixture('card.found.json', episode: 'ep_9120');
      peer.cards = [held];
      final app = controller(peer, platform: platform);
      await openApp(tester, app);
      expect(platform.deliveries, [held['text']]);
      expect(
        peer.requests
            .where((r) => r.url.path.endsWith('/cards'))
            .first
            .url
            .queryParameters,
        isEmpty,
      );
      await tester.pump(const Duration(seconds: 30));
      await tester.pumpAndSettle();
      expect(peer.pollCount, 2);
      expect(
        peer.requests
            .lastWhere((r) => r.url.path.endsWith('/cards'))
            .url
            .queryParameters['since'],
        '2026-11-05T01:02:03+09:00',
      );
      expect(platform.deliveries, [held['text']]);
      peer.cards = [
        {...found, 'notify': false},
      ];
      await app.sync();
      expect(platform.deliveries, [held['text']]);
      platform.permission = false;
      peer.cards = [found];
      await app.sync();
      expect(platform.deliveries, [held['text']]);
      platform.permission = true;
      await app.sync();
      expect(platform.deliveries, [held['text'], found['text']]);
    },
  );

  testWidgets(
    'APP-AT-07 toggles one line with a new task ID on re-enable and hides controls after start',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final card = fixture('card.v1.json');
      card['lines'] = [lines(card).first];
      card['summary'] = {'done': 0, 'total': 1, 'waiting_for': null};
      peer.cards = [card];
      final app = controller(peer);
      await openApp(tester, app);
      peer.reaction = (_) async {
        final change = peer.reactions.last.$2;
        final updated = phase(card, peer.reactions.length);
        final off = change['reaction'] == 'line_off';
        updated['lines'] = [
          {
            ...lines(card).first,
            'state': off ? 'off' : 'scheduled',
            'checked': !off,
            'task_id': off ? 't_clean#1' : 't_clean#7',
          },
        ];
        updated['summary'] = {
          'done': 0,
          'total': off ? 0 : 1,
          'waiting_for': null,
        };
        peer.cards = [updated];
        return Peer.response(updated);
      };
      await tapText(tester, '항목 끄기');
      expect(peer.reactions.single.$1, 'nc_331');
      expect(peer.reactions.single.$2, {
        'reaction': 'line_off',
        'task_id': 't_clean#1',
      });
      expect(find.text('꺼짐'), findsOneWidget);
      expect(find.text('0/0 준비'), findsOneWidget);
      expect(find.text('이 준비 중지'), findsOneWidget);
      await tapText(tester, '항목 켜기');
      expect(peer.reactions.last.$1, 'nc_331');
      expect(peer.reactions.last.$2, {
        'reaction': 'line_on',
        'task_id': 't_clean#1',
      });
      final running = phase(peer.cards.single, 3);
      lines(running).first['state'] = 'running';
      peer.cards = [running];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('항목 켜기'), findsNothing);
      expect(find.text('항목 끄기'), findsNothing);
      expect(find.text('진행 중'), findsOneWidget);
      expect(find.textContaining('잘못'), findsNothing);
      expect(find.textContaining('모두 중지'), findsNothing);
      await settings(tester);
      expect(find.text('자동 준비 일시정지'), findsOneWidget);
      expect(find.textContaining('모두 중지'), findsNothing);
    },
  );

  testWidgets(
    'APP-AT-08 Stop is pending through the receipt and confirms only refreshed restoration',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final active = phase(fixture('card.v1.json'), 1);
      lines(active)[0]['state'] = 'running';
      lines(active)[1]['state'] = 'scheduled';
      lines(active)[2]['state'] = 'user_changed';
      lines(active)[3]['state'] = 'blocked';
      lines(active)[3]['note'] = '사용자가 시작한 조리를 유지했어요.';
      peer.cards = [active];
      final app = controller(peer);
      await openApp(tester, app);
      final guidance = find.textContaining('씻지 말고 키친타월');
      expect(guidance, findsOneWidget);
      expect(
        find.ancestor(of: guidance, matching: find.byType(Card)),
        findsNothing,
      );

      final receipt = Completer<http.Response>();
      peer.reaction = (_) => receipt.future;
      await tester.tap(find.text('이 준비 중지'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.textContaining('중지 요청 확인 중'), findsOneWidget);
      expect(peer.reactions.single.$1, 'nc_331');
      expect(peer.reactions.single.$2, {'reaction': 'stop'});
      expect(find.byType(AlertDialog), findsNothing);

      final stopped = phase(active, 2)
        ..['stopped'] = true
        ..['buttons'] = [];
      stopped['lines'] = [
        {...lines(active)[0], 'state': 'stopped'},
        {...lines(active)[1], 'state': 'stopped'},
        {...lines(active)[2], 'state': 'stopped'},
        {...lines(active)[3], 'state': 'stopped'},
      ];
      receipt.complete(Peer.response(stopped));
      await tester.pumpAndSettle();
      expect(find.textContaining('중지 요청 확인 중'), findsOneWidget);
      expect(find.text('이 준비가 중지됐어요.'), findsNothing);
      peer.cards = [stopped];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('종료 결과 확인 중…'), findsOneWidget);
      final restored = phase(stopped, 3);
      lines(restored)[0]['end_state'] = 'restored';
      lines(restored)[2]['end_state'] = 'kept_user_change';
      peer.cards = [restored];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('이 준비가 중지됐어요.'), findsOneWidget);
      expect(find.text('이전 상태로 복원됨'), findsOneWidget);
      expect(find.text('사용자가 바꾼 상태를 유지함'), findsOneWidget);
      expect(find.text('사용자가 시작한 조리를 유지했어요.'), findsOneWidget);
      expect(guidance, findsOneWidget);
    },
  );

  testWidgets(
    'APP-AT-09 sends pause and resume, renders cancelled and running work and stored orders',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final active = phase(fixture('card.v1.json'), 1);
      lines(active)[0]['state'] = 'running';
      peer.cards = [active];
      final platform = TestPlatform();
      peer.onPause = (paused) {
        if (!paused) return;
        final cancelled = phase(active, 2);
        lines(cancelled)[1]['state'] = 'cancelled';
        lines(cancelled)[2]['state'] = 'cancelled';
        lines(cancelled)[3]['state'] = 'cancelled';
        peer.cards = [cancelled];
      };
      peer.upload = (_) async {
        expect(peer.pauses.last, {'paused': true});
        peer.episodes['ep_9150'] = fixture('episode.json', episode: 'ep_9150')
          ..['status'] = 'paused_skip'
          ..['items'] = []
          ..['item_count'] = 0
          ..['item_tasks'] = [];
        return Peer.response({
          'episode_id': 'ep_9150',
          'status': 'paused_skip',
        }, 202);
      };
      final app = controller(peer, platform: platform);
      await openApp(tester, app);
      await settings(tester);
      await tapText(tester, '자동 준비 일시정지');
      expect(peer.pauses, [
        {'paused': true},
      ]);
      expect(find.text('자동 준비 일시정지됨'), findsOneWidget);
      platform.orders.add(
        SharedOrder('paused-share', '2026-11-04T19:30:41+09:00', [TestImage()]),
      );
      await app.sync();
      expect(platform.acknowledged['paused-share'], 'ep_9150');
      await tapText(tester, '자동 준비 재개');
      expect(peer.pauses, [
        {'paused': true},
        {'paused': false},
      ]);
      expect(find.text('자동 준비 켜짐'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      expect(find.text('취소됨'), findsNWidgets(3));
      expect(find.text('진행 중'), findsOneWidget);
      expect(find.textContaining('주문을 판단하지 않았어요'), findsOneWidget);
      expect(find.byType(Card), findsOneWidget);
    },
  );

  testWidgets(
    'APP-AT-11 displays only stored rationale whitelist and joins current card state',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json');
      peer.cards = [fixture('card.v1.json')];
      await openApp(tester, controller(peer));
      await tapText(tester, 'WHY · 이유 보기');
      expect(find.textContaining('손님 여럿이 오는 아이 생일 파티'), findsOneWidget);
      expect(find.textContaining('캘린더 생일 (토 14:00–17:00)'), findsOneWidget);
      expect(find.text('세탁 세제 · 로션'), findsOneWidget);
      expect(find.text('손님 오기 전 거실 정리'), findsOneWidget);
      expect(find.text('거실 · 로봇청소기'), findsOneWidget);
      expect(find.text('예정됨'), findsNWidgets(4));
      for (final excluded in ['이 집이 산 적 없는 종류', '홈베이킹', '답례품 봉투', '가족 모임']) {
        expect(find.textContaining(excluded), findsNothing);
      }
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tapText(tester, 'WHY · 이유 보기');
      expect(peer.rationaleReads, 1);
    },
  );

  testWidgets(
    'APP-AT-12 plain groceries remains card-free through the guidance lifecycle',
    (tester) async {
      final peer = Peer();
      final episode = fixture('episode.json', episode: 'ep_9150');
      peer.episodes['ep_9150'] = episode;
      peer.rationale = null;
      final app = controller(peer);
      final text =
          ((episode['item_tasks'] as List<dynamic>).first
                  as Map<String, dynamic>)['text']
              as String;
      await openApp(tester, app);
      expect(find.byType(Card), findsNothing);
      expect(find.text('집에서 준비할 일이 없어요.'), findsOneWidget);
      expect(find.text('읽은 품목 5개'), findsOneWidget);
      expect(find.text('택배를 집 안으로 들이면 품목 안내가 표시돼요.'), findsOneWidget);
      expect(find.text(text), findsNothing);
      await tapText(tester, 'WHY · 이유 보기');
      expect(find.text('저장된 이유를 볼 수 없어요.'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      peer.rationale = {
        ...fixture('rationale.json'),
        'episode_id': 'ep_9150',
        'intents': [],
        'none_reason': '일상 장보기로 판단했어요.',
        'unbundled': [],
        'tasks': [],
        'observations': [],
        'executions': [],
        'item_tasks': [],
      };
      await tapText(tester, 'WHY · 이유 보기');
      expect(find.text('일상 장보기로 판단했어요.'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      (episode['item_tasks'] as List<dynamic>)
              .cast<Map<String, dynamic>>()
              .first['state'] =
          'done';
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text(text), findsOneWidget);
      expect(find.text('완료'), findsOneWidget);
      expect(find.byType(Card), findsNothing);

      episode['status'] = 'closed';
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('품목 안내가 종료됐어요.'), findsOneWidget);
      expect(find.text(text), findsNothing);
      expect(find.byType(Card), findsNothing);
    },
  );

  testWidgets(
    'APP-AT-13 memory keeps the case on failure or pending and removes it only on readback',
    (tester) async {
      final peer = Peer()..failDelete = true;
      await openApp(tester, controller(peer));
      await settings(tester);
      await tapText(tester, '우리 집 기억');
      expect(find.text('아이 생일 파티'), findsOneWidget);
      expect(find.textContaining('손님 도착 뒤 색온도 2700K로 바꿈'), findsOneWidget);
      expect(find.text('편집'), findsNothing);
      await tapText(tester, '이 기억 삭제');
      await tapText(tester, '삭제');
      expect(find.text('선택한 기억을 삭제하지 못했어요.'), findsOneWidget);
      expect(find.text('아이 생일 파티'), findsOneWidget);

      peer.failDelete = false;
      peer.keepDeletedUntilRead = true;
      await tapText(tester, '이 기억 삭제');
      await tapText(tester, '삭제');
      expect(find.text('선택한 기억의 삭제를 확인하는 중이에요.'), findsOneWidget);
      expect(find.text('아이 생일 파티'), findsOneWidget);
      peer.memory = {'household_id': 'h_042', 'intents': []};
      await tapText(tester, '새로고침');
      expect(find.text('선택한 기억을 삭제했어요.'), findsOneWidget);
      expect(find.text('아이 생일 파티'), findsNothing);
      expect(
        peer.requests
            .where((r) => r.method == 'DELETE')
            .map((r) => r.url.pathSegments.last),
        ['home_h_042_ep_9031_1', 'home_h_042_ep_9031_1'],
      );
    },
  );

  testWidgets(
    'APP-AT-14 labels both configured peers and keeps their cached observations separate',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json');
      peer.cards = [fixture('card.final.json')];
      final store = TestStore();
      await openApp(tester, controller(peer, store: store));
      expect(find.text('계약 테스트 서버'), findsOneWidget);
      expect(find.byType(Card), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      peer.unavailable = true;
      await openApp(tester, controller(peer, store: store, fixture: false));
      expect(find.text('실제 서버 프로필'), findsOneWidget);
      expect(find.text('계약 테스트 서버'), findsNothing);
      expect(find.byType(Card), findsNothing);
      expect(
        peer.requests.every(
          (request) =>
              !request.url.path.contains('/hub/') &&
              !request.url.path.contains('/sim/'),
        ),
        isTrue,
      );
    },
  );

  testWidgets(
    'APP-AT-15 exposes scoped actions and status to accessibility at 200% text',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final active = fixture('card.v1.json');
      active['lines'] = [lines(active).first];
      peer.cards = [active];
      final app = controller(peer);
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final semantics = tester.ensureSemantics();
      try {
        await openApp(tester, app);
        tester.view.physicalSize = const Size(360, 1150);
        await tester.pumpAndSettle();
        final stop = find.bySemanticsLabel(RegExp(r'이 준비 중지 · 토요일 생일'));
        final off = find.bySemanticsLabel(RegExp(r'손님 오기 전 거실 청소 끄기'));
        expect(stop, findsOneWidget);
        expect(off, findsOneWidget);
        peer.reaction = (_) async {
          final disabling = peer.reactions.last.$2['reaction'] == 'line_off';
          final next = phase(active, disabling ? 1 : 2);
          next['lines'] = [
            {
              ...lines(active).first,
              'state': disabling ? 'off' : 'scheduled',
              'checked': !disabling,
              'task_id': disabling ? 't_clean#1' : 't_clean#7',
            },
          ];
          peer.cards = [next];
          return Peer.response(next);
        };
        await tester.ensureVisible(find.text('항목 끄기'));
        await tester.pumpAndSettle();
        await tester.tap(off);
        await tester.pumpAndSettle();
        final on = find.bySemanticsLabel(RegExp('손님 오기 전 거실 청소 켜기'));
        expect(on, findsOneWidget);
        await tester.tap(on);
        await tester.pumpAndSettle();
        expect(off, findsOneWidget);
        final receipt = Completer<http.Response>();
        peer.reaction = (_) => receipt.future;
        await tester.ensureVisible(find.text('이 준비 중지'));
        await tester.pumpAndSettle();
        await tester.tap(stop);
        await tester.pump();
        await tester.ensureVisible(find.text('이 준비의 중지 요청 확인 중…'));
        await tester.pumpAndSettle();
        expect(find.bySemanticsLabel('이 준비의 중지 요청 확인 중…'), findsOneWidget);
        final stopped = phase(peer.cards.single, 3)
          ..['stopped'] = true
          ..['buttons'] = [];
        lines(stopped).first['state'] = 'stopped';
        peer.cards = [stopped];
        receipt.complete(Peer.response(stopped));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('이 준비가 중지됐어요.'));
        await tester.pumpAndSettle();
        expect(find.bySemanticsLabel('이 준비가 중지됐어요.'), findsOneWidget);
        await settings(tester);
        expect(find.bySemanticsLabel('자동 준비 일시정지'), findsOneWidget);
        await tapText(tester, '자동 준비 일시정지');
        expect(find.bySemanticsLabel('자동 준비 일시정지됨'), findsOneWidget);
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );
}
