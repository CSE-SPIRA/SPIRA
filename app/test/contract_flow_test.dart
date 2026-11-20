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
import 'package:spira_app/platform/google_calendar.dart';

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
    if (value.startsWith('{')) saved.add(jsonDecode(value));
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
  final calendars = <wire.Calendar>[];
  List<Map<String, dynamic>> cards = [];
  Map<String, dynamic> memory = fixture('memory.json');
  final rationales = {
    'ep_9031': fixture('rationale.json'),
    'ep_9150': fixture('rationale.json', episode: 'ep_9150'),
  };
  Map<String, dynamic> get birthday => episodes['ep_9031']!;
  bool failDelete = false;
  bool keepDeletedUntilRead = false;
  bool unavailable = false;
  bool failCalendar = false;
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
      final calendar = wire.calendarFromJson(request.body);
      calendars.add(calendar);
      if (failCalendar) {
        return response({'code': 'internal', 'message': 'offline'}, 503);
      }
      return response({'accepted': calendar.events.length}, 202);
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
      final rationale = rationales[request.url.pathSegments[2]];
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
  CalendarReader? calendar,
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

Future<void> openApp(
  WidgetTester tester,
  AppController app, {
  Size size = const Size(850, 1700),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(SpiraApp(app: app));
  await tester.pumpAndSettle();
}

Future<void> tapText(WidgetTester tester, String text, {int index = 0}) async {
  final target = find.text(text).at(index);
  await tester.ensureVisible(target);
  await tester.pump();
  await tester.tap(target);
  await tester.pumpAndSettle();
}

Future<void> settings(WidgetTester tester) async {
  await tester.tap(find.byTooltip('설정'));
  await tester.pumpAndSettle();
}

Future<void> connectCalendar(WidgetTester tester, AppController app) async {
  await openApp(tester, app);
  await tapText(tester, '2인');
  await tapText(tester, '우리 집 만들기');
  await tapText(tester, 'Google 캘린더 연결');
  await tapText(tester, '설정 완료');
}

Future<void> resumeApp(WidgetTester tester) async {
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
  await tester.pump();
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
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
          calendar: ({required interactive}) async =>
              wire.Calendar.fromJson(calendar),
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

  testWidgets('APP-03 startup sends the full list after an event is added', (
    tester,
  ) async {
    final peer = Peer();
    final store = TestStore();
    var calendar = wire.Calendar.fromJson(fixture('calendar.json'));
    final modes = <bool>[];
    Future<wire.Calendar> read({required bool interactive}) async {
      modes.add(interactive);
      return calendar;
    }

    await connectCalendar(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );
    await tester.pumpWidget(const SizedBox.shrink());
    final added = wire.Calendar.fromJson(
      fixture('calendar.json', episode: 'ep_9120'),
    ).events.single;
    calendar = wire.Calendar(events: [...calendar.events, added]);
    await openApp(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );

    expect(modes, [true, false]);
    expect(peer.calendars, hasLength(2));
    expect(peer.calendars.last.toJson(), calendar.toJson());
    final saved = store.values.values.join('\n');
    for (final event in calendar.events) {
      expect(saved, isNot(contains(event.title)));
    }
    expect(store.values.values, contains(matches(RegExp(r'^[0-9a-f]{64}$'))));
  });

  testWidgets('APP-03 rereads an unchanged list without resending it', (
    tester,
  ) async {
    final peer = Peer();
    final store = TestStore();
    var calendar = wire.Calendar.fromJson(fixture('calendar.json'));
    var reads = 0;
    Future<wire.Calendar> read({required bool interactive}) async {
      reads++;
      return calendar;
    }

    await connectCalendar(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );
    await tester.pumpWidget(const SizedBox.shrink());
    calendar = wire.Calendar(events: calendar.events.reversed.toList());
    await openApp(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );
    await resumeApp(tester);
    await settings(tester);
    await tapText(tester, '캘린더 다시 보내기');

    expect(reads, 4);
    expect(peer.calendars, hasLength(1));
  });

  testWidgets('APP-03 foreground sends a title edit while paused', (
    tester,
  ) async {
    final peer = Peer();
    var calendar = wire.Calendar.fromJson(fixture('calendar.json'));
    await connectCalendar(
      tester,
      controller(
        peer,
        setup: true,
        calendar: ({required interactive}) async => calendar,
      ),
    );
    await settings(tester);
    await tapText(tester, '자동 준비 일시정지');
    final first = calendar.events.first;
    calendar = wire.Calendar(
      events: [
        wire.EventElement(
          id: first.id,
          title: '생일 모임',
          start: first.start,
          end: first.end,
        ),
        ...calendar.events.skip(1),
      ],
    );
    expect(peer.calendars, hasLength(1));

    await resumeApp(tester);

    expect(peer.pauses, [
      {'paused': true},
    ]);
    expect(peer.calendars, hasLength(2));
    expect(peer.calendars.last.toJson(), calendar.toJson());
  });

  testWidgets(
    'APP-03 settings sends an empty replacement and retries quietly',
    (tester) async {
      final peer = Peer();
      final platform = TestPlatform();
      var failRead = false;
      var calendar = wire.Calendar.fromJson(fixture('calendar.json'));
      await connectCalendar(
        tester,
        controller(
          peer,
          setup: true,
          platform: platform,
          calendar: ({required interactive}) async {
            if (failRead) throw StateError('Calendar read failed');
            return calendar;
          },
        ),
      );
      await settings(tester);
      calendar = wire.Calendar(events: []);
      failRead = true;
      await tapText(tester, '캘린더 다시 보내기');
      expect(peer.calendars, hasLength(1));

      failRead = false;
      peer.failCalendar = true;
      await tapText(tester, '캘린더 다시 보내기');
      expect(peer.calendars, hasLength(2));

      peer.failCalendar = false;
      await tapText(tester, '캘린더 다시 보내기');
      expect(peer.calendars, hasLength(3));
      expect(peer.calendars.last.events, isEmpty);
      await tapText(tester, '캘린더 다시 보내기');
      expect(peer.calendars, hasLength(3));
      expect(platform.deliveries, isEmpty);
      expect(find.byType(SnackBar), findsNothing);
    },
  );

  testWidgets('APP-03 skipped calendar stays disconnected after restart', (
    tester,
  ) async {
    final peer = Peer();
    final store = TestStore();
    var reads = 0;
    Future<wire.Calendar> read({required bool interactive}) async {
      reads++;
      return wire.Calendar(events: []);
    }

    await openApp(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );
    await tapText(tester, '2인');
    await tapText(tester, '우리 집 만들기');
    await tapText(tester, '건너뛰기');
    await tapText(tester, '설정 완료');
    await tester.pumpWidget(const SizedBox.shrink());
    await openApp(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );
    await resumeApp(tester);
    await settings(tester);

    expect(reads, 0);
    expect(peer.calendars, isEmpty);
    expect(find.text('캘린더 다시 보내기'), findsNothing);
  });

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
      expect(find.text('10월 17일 토요일 오후 2시 일정'), findsOneWidget);
      expect(find.text('토 12:30'), findsOneWidget);
      expect(find.text('토 13:30'), findsOneWidget);
      expect(find.text('토 14:00'), findsOneWidget);
      expect(find.text('손님이 오면'), findsNWidgets(2));
      expect(find.text('예정됨'), findsNothing);
      expect(find.textContaining('실행 예정'), findsNothing);
      expect(
        find.descendant(of: find.byType(Card), matching: find.text('완료')),
        findsNothing,
      );
      const states = [
        ('held', '시간을 기다리는 중'),
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
      peer.cards = [finalCard];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('3/3 준비'), findsOneWidget);
      expect(find.text('꺼짐'), findsOneWidget);
      expect(find.text('사용자가 바꾼 상태를 유지함'), findsOneWidget);
      expect(find.text('사용자가 조명을 바꿔 현재 상태를 유지했어요'), findsOneWidget);
      expect(find.text('이전 상태로 복원됨'), findsOneWidget);
      expect(find.text('복원 대상 없음'), findsOneWidget);
      expect(find.textContaining('종료 조건'), findsNothing);

      final failedRestore = fixture('card.final.json')
        ..['updated_at'] = '2026-10-17T17:50:17+09:00';
      lines(failedRestore)[1]['end_state'] = 'restore_failed';
      peer.cards = [failedRestore];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('복원 실패 또는 결과 확인 불가'), findsOneWidget);
      expect(find.text('이전 상태로 복원됨'), findsNothing);

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
    'APP-AT-04/05/10 shows withheld on the affected line until the Server reports restoration',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json');
      final card = fixture('card.final.json');
      final safety = lines(card)[1]..['end_state'] = null;
      final mood = lines(card)[2];
      peer.cards = [card];
      final app = controller(peer);
      await openApp(tester, app);
      const explanation = '행사 끝을 확인하지 못해 안전 설정을 그대로 두었어요.';
      expect(find.text(explanation), findsNothing);

      Finder lineText(Map<String, dynamic> line, String label) {
        final row = find.byWidgetPredicate(
          (widget) =>
              widget is Column &&
              widget.children.whereType<Text>().any(
                (text) => text.data == line['text'],
              ),
        );
        return find.descendant(of: row, matching: find.text(label));
      }

      card['updated_at'] = '2026-10-17T20:00:01+09:00';
      safety['end_state'] = 'withheld';
      await app.sync();
      await tester.pumpAndSettle();
      expect(lineText(safety, explanation), findsOneWidget);
      expect(lineText(safety, '완료'), findsOneWidget);
      expect(lineText(safety, '이전 상태로 복원됨'), findsNothing);
      expect(lineText(mood, '사용자가 바꾼 상태를 유지함'), findsOneWidget);
      expect(find.textContaining('종료 조건'), findsNothing);

      card['updated_at'] = '2026-10-17T20:00:02+09:00';
      safety['note'] = explanation;
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text(explanation), findsOneWidget);

      card['updated_at'] = '2026-10-17T20:01:00+09:00';
      safety['end_state'] = 'restored';
      safety['note'] = null;
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text(explanation), findsNothing);
      expect(lineText(safety, '이전 상태로 복원됨'), findsOneWidget);
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

  testWidgets('card lines use the Server trigger in Seoul time', (
    tester,
  ) async {
    final peer = Peer();
    peer.episodes['ep_9031'] = fixture('episode.json');
    final card = fixture('card.v1.json');
    lines(card).first['when'] = {'time': '2026-10-16T15:05:00+00:00'};
    lines(card)[1]['when'] = null;
    peer.cards = [card];
    await openApp(tester, controller(peer));

    expect(find.text('토 00:05'), findsOneWidget);
    expect(find.text('손님이 오면'), findsOneWidget);
    expect(find.text('토 14:00'), findsOneWidget);
    expect(find.text('토 13:30'), findsNothing);
    expect(find.text('일정이 시작될 때'), findsNothing);
  });

  testWidgets(
    'APP-AT-11 shows the ep_9031 evidence chain and live card state',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json');
      peer.cards = [fixture('card.v1.json')];
      final app = controller(peer);
      await openApp(tester, app, size: const Size(390, 760));
      await tapText(tester, 'WHY · 이유 보기');

      final headings = [
        '주문에서 읽은 것',
        '이 집과 함께 본 것',
        '알아낸 상황',
        '그래서 집이 할 일',
        '냉장고 안내',
      ];
      var previous = 0.0;
      for (final heading in headings) {
        final target = find.text(heading);
        expect(target, findsOneWidget);
        final top = tester.getTopLeft(target).dy;
        expect(top, greaterThan(previous));
        previous = top;
      }
      expect(find.text('수량 미확인'), findsOneWidget);
      expect(find.text('2개'), findsOneWidget);
      expect(find.text('6개'), findsOneWidget);
      expect(find.text('이번 준비와 따로 본 물건'), findsNWidgets(2));

      for (final sentence in [
        '14:00–17:00',
        '평소 1개 → 이번 2개',
        '아이 생일 파티 9건',
        '홈베이킹 2건',
        '의도 없음 1건',
        '아이 친구들을 집에 초대해 생일 파티를 여는 준비',
        '4/6개 겹침 · 고깔모자 · 딸기 · 케이크 토퍼 · 풍선',
        '행사',
        '손님',
        '활동',
        '테마',
        '손님 여러 명',
        '컵케이크 굽고 꾸미기',
        '디즈니 공주 케이크 토퍼',
        '디즈니 공주',
        '손님 오기 전 거실 정리',
        '손님 오기 전 거실 청소',
        '거실 로봇청소기',
        '주방 인덕션 · 주방 스마트 플러그',
        '설정 대기',
        '토 12:30',
        '토 13:30',
        '손님이 오면',
        '토 14:00',
        '씻지 말고 키친타월을 깔아 냉장 보관하고, 토요일 꾸미기 직전에 씻어 주세요',
        '꾸미기 직전까지 냉장고 안쪽에 두고, 휘핑할 때 볼도 차갑게 해 두면 잘 올라와요',
      ]) {
        expect(find.text(sentence), findsOneWidget, reason: sentence);
      }
      expect(find.text('토요일 생일 일정'), findsNWidgets(2));
      expect(find.text('가구 유형'), findsNWidgets(2));
      expect(find.text('실행'), findsNWidgets(3));
      expect(find.text('꺼짐'), findsNothing);
      expect(find.text('완료'), findsNothing);
      for (final excluded in ['가족 모임', 'syn_A1-3_0018', 'cooktop_01', 'c1']) {
        expect(find.textContaining(excluded), findsNothing, reason: excluded);
      }

      const intent = '디즈니 공주 테마로 손님 여럿이 오는 아이 생일 파티를 열고, 컵케이크를 굽고 꾸미려는 준비';
      final intentText = find.text(intent);
      final span = tester.widget<Text>(intentText).textSpan! as TextSpan;
      final theme = Theme.of(tester.element(intentText));
      expect(
        span.children,
        contains(
          TextSpan(
            text: '디즈니 공주',
            style: TextStyle(color: theme.colorScheme.secondaryContainer),
          ),
        ),
      );

      final card = fixture('card.final.json');
      lines(card)[1]['end_state'] = 'withheld';
      peer.cards = [card];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('꺼짐'), findsOneWidget);
      expect(find.text('완료'), findsNWidgets(2));
      expect(find.text('행사 끝을 확인하지 못해 안전 설정을 그대로 두었어요.'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tapText(tester, 'WHY · 이유 보기');
      expect(peer.rationaleReads, 1);
    },
  );

  testWidgets('line WHY opens at its task and scrolls to its situation', (
    tester,
  ) async {
    final peer = Peer();
    peer.episodes['ep_9031'] = fixture('episode.json');
    peer.cards = [fixture('card.v1.json')];
    await openApp(tester, controller(peer), size: const Size(390, 760));
    await tapText(tester, '왜?', index: 2);

    expect(find.text('선택한 할 일').hitTestable(), findsOneWidget);
    final mood = find.text('손님 오시면 공주 분위기 화면·조명');
    expect(mood.hitTestable(), findsOneWidget);
    expect(find.text('손님이 오면').hitTestable(), findsOneWidget);
    expect(find.text('주문에서 읽은 것').hitTestable(), findsNothing);

    await tapText(tester, '이 일을 정한 근거 보기');
    expect(find.text('선택한 할 일의 근거').hitTestable(), findsOneWidget);
    expect(find.text('토요일 생일 일정').hitTestable(), findsOneWidget);
    expect(find.text('가구 유형').hitTestable(), findsWidgets);
    expect(mood.hitTestable(), findsNothing);

    await tapText(tester, '선택한 할 일 보기');
    expect(mood.hitTestable(), findsOneWidget);
    expect(peer.rationaleReads, 1);
  });

  testWidgets(
    'line WHY uses the replacement card line when the rationale has the old task',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json');
      final card = fixture('card.v1.json');
      lines(card).first
        ..['task_id'] = 't_clean#7'
        ..['text'] = '거실 청소 다시 켜기'
        ..['when'] = {'time': '2026-10-17T12:45:00+09:00'};
      peer.cards = [card];
      await openApp(tester, controller(peer), size: const Size(390, 760));
      await tapText(tester, '왜?');

      expect(find.text('선택한 할 일').hitTestable(), findsOneWidget);
      expect(find.text('거실 청소 다시 켜기').hitTestable(), findsOneWidget);
      expect(find.text('토 12:45').hitTestable(), findsOneWidget);
      expect(find.text('토 12:30'), findsNothing);
      expect(
        find.text('이 할 일의 자세한 근거를 볼 수 없어요.').hitTestable(),
        findsOneWidget,
      );
      await tapText(tester, '이 일을 정한 근거 보기');
      expect(find.text('선택한 할 일의 근거').hitTestable(), findsOneWidget);
    },
  );

  testWidgets(
    'WHY shows a missing slot without exposing an unresolved calendar ID',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json');
      peer.cards = [fixture('card.v1.json')];
      final rationale = peer.rationales['ep_9031']!;
      final evidence = rationale['evidence'] as Map<String, dynamic>;
      evidence['calendar'] = [];
      final intent = (rationale['intents'] as List).single as Map;
      (intent['situation'] as Map)['guests'] = null;

      await openApp(tester, controller(peer));
      await tapText(tester, 'WHY · 이유 보기');
      expect(find.text('연결된 일정'), findsNothing);
      expect(find.text('c1'), findsNothing);
      expect(find.text('손님'), findsOneWidget);
      expect(find.text('알 수 없어요'), findsOneWidget);
      expect(find.textContaining('끝난 걸 확인하면 풀어요'), findsNothing);
    },
  );

  testWidgets(
    'APP-AT-11/12 plain groceries shows stored no-intent WHY and remains card-free',
    (tester) async {
      final peer = Peer();
      final episode = fixture('episode.json', episode: 'ep_9150');
      peer.episodes['ep_9150'] = episode;
      final rationale = peer.rationales.remove('ep_9150')!;
      final app = controller(peer);
      final tasks = (episode['item_tasks'] as List<dynamic>)
          .cast<Map<String, dynamic>>();
      final guidance = [for (final task in tasks) task['text'] as String];
      const releaseNote = '택배를 집 안으로 들이면 안내를 볼 수 있어요.';
      await openApp(tester, app);
      expect(find.byType(Card), findsNothing);
      expect(find.text('집에서 준비할 일이 없어요.'), findsOneWidget);
      expect(find.text('읽은 품목 6개'), findsOneWidget);
      expect(find.text(releaseNote), findsOneWidget);
      expect(find.text('예정됨'), findsNothing);
      for (final text in guidance) {
        expect(find.text(text), findsNothing);
      }
      await tapText(tester, 'WHY · 이유 보기');
      expect(find.text('저장된 이유를 볼 수 없어요.'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      peer.rationales['ep_9150'] = rationale;
      await tapText(tester, 'WHY · 이유 보기');
      expect(find.text(rationale['none_reason'] as String), findsOneWidget);
      expect(find.text('주문에서 읽은 것'), findsOneWidget);
      expect(find.text('알아낸 상황'), findsNothing);
      expect(find.text('그래서 집이 할 일'), findsNothing);
      expect(find.text('연결된 일정'), findsNothing);
      expect(find.text('평소와 달랐던 물건'), findsNothing);
      expect(find.text('의도 없음 11건'), findsOneWidget);
      expect(find.text('4/4개 겹침 · 계란 · 딸기 · 우유 · 휴지'), findsOneWidget);
      expect(find.textContaining('syn_A1-1_0107'), findsNothing);
      expect(find.text('냉장고 안내'), findsOneWidget);
      for (final text in guidance) {
        expect(find.text(text), findsOneWidget);
      }
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      for (final task in tasks) {
        task['state'] = 'done';
      }
      await app.sync();
      await tester.pumpAndSettle();
      for (final text in guidance) {
        expect(find.text(text), findsOneWidget);
      }
      expect(find.text(releaseNote), findsNothing);
      expect(find.text('완료'), findsNWidgets(2));
      expect(find.byType(Card), findsNothing);

      episode['status'] = 'closed';
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('품목 안내가 종료됐어요.'), findsOneWidget);
      for (final text in guidance) {
        expect(find.text(text), findsNothing);
      }
      expect(find.byType(Card), findsNothing);
    },
  );

  testWidgets(
    'APP-AT-12 shows each episode’s own strawberry guidance after release',
    (tester) async {
      final peer = Peer();
      final groceries = fixture('episode.json', episode: 'ep_9150');
      final birthday = fixture('episode.json')..['status'] = 'notified';
      peer.episodes.addAll({'ep_9150': groceries, 'ep_9031': birthday});
      peer.cards = [fixture('card.v1.json')];

      Map<String, dynamic> strawberry(Map<String, dynamic> episode) =>
          (episode['item_tasks'] as List<dynamic>)
              .cast<Map<String, dynamic>>()
              .singleWhere((task) => task['item'] == '딸기');

      final groceryTask = strawberry(groceries);
      final groceryText = groceryTask['text'] as String;
      final birthdayText = strawberry(birthday)['text'] as String;
      expect(groceryText, isNot(birthdayText));
      final app = controller(peer);
      await openApp(tester, app);
      expect(find.byType(Card), findsOneWidget);
      expect(find.text(groceryText), findsNothing);
      expect(find.text(birthdayText), findsOneWidget);

      groceryTask['state'] = 'done';
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.byType(Card), findsOneWidget);
      for (final text in [groceryText, birthdayText]) {
        final notice = find.text(text);
        expect(notice, findsOneWidget);
        expect(
          find.ancestor(of: notice, matching: find.byType(Card)),
          findsNothing,
        );
      }
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
