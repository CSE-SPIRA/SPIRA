import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:spira_app/api/app_api.dart';
import 'package:spira_app/app_controller.dart';
import 'package:spira_app/contracts.dart' as wire;
import 'package:spira_app/design_tokens.g.dart';
import 'package:spira_app/main.dart';
import 'package:spira_app/platform/android_bridge.dart';
import 'package:spira_app/platform/google_calendar.dart';
import 'package:spira_app/platform/home_hub_onboarding.dart';
import 'package:spira_app/theme.dart';

Map<String, dynamic> fixture(String file, {String episode = 'ep_9031'}) =>
    jsonDecode(File('../contracts/fixtures/$episode/$file').readAsStringSync())
        as Map<String, dynamic>;

class TestImage extends Fake implements File {
  TestImage({this.preview});

  static final _bytes = utf8.encode('screenshot');
  final Uint8List? preview;

  @override
  String get path => '/0.jpg';

  @override
  Uri get uri => Uri.file(path);

  @override
  Future<int> length() async => (preview ?? _bytes).length;

  @override
  Stream<List<int>> openRead([int? start, int? end]) =>
      Stream.value(preview ?? _bytes);

  @override
  Future<Uint8List> readAsBytes() async =>
      preview ?? (throw const FileSystemException('No local preview'));
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
  List<Map<String, dynamic>> historyCards = [];
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
  Future<http.Response> Function()? readRationale;
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
        'cards': request.url.queryParameters['since'] == '1970-01-01T00:00:00Z'
            ? historyCards
            : cards,
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
      if (readRationale case final read?) return read();
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
    if (method == 'POST' && path == '/v1/orders') {
      return upload!(request);
    }
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
  HttpHomeHubOnboarding? homeHub,
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
  homeHub: homeHub,
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

Finder get orderScan => find.byKey(const ValueKey('order-scan-line'));

Future<void> paintOrderPreview(WidgetTester tester) async {
  final image = find.byType(Image);
  await tester.runAsync(() async {
    await precacheImage(
      tester.widget<Image>(image).image,
      tester.element(image),
    );
  });
  await tester.pump();
  final painted = find.descendant(of: image, matching: find.byType(RawImage));
  expect(tester.widget<RawImage>(painted).image, isNotNull);
  await tester.pump();
}

Future<void> tapTab(WidgetTester tester, String label) async {
  await tester.tap(
    find.descendant(
      of: find.byKey(const ValueKey('home-tabs')),
      matching: find.text(label),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> settings(WidgetTester tester) => tapTab(tester, '설정');

Future<void> openPreparationWhy(WidgetTester tester, Peer peer) =>
    tapText(tester, peer.cards.first['text'] as String);

Finder get preparationMenu => find.byType(PopupMenuButton<bool>);

Future<void> openStopConfirmation(WidgetTester tester) async {
  final menu = preparationMenu.first;
  await tester.ensureVisible(menu);
  await tester.pumpAndSettle();
  await tester.tap(menu);
  await tester.pumpAndSettle();
  await tapText(tester, '이 준비 중지');
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
      expect(find.text('거실 · 로봇청소기 · 모의 기기'), findsOneWidget);
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

  for (final reducedMotion in [false, true]) {
    testWidgets(
      'shared screenshot becomes read items with reduced motion $reducedMotion',
      (tester) async {
        if (reducedMotion) {
          tester.platformDispatcher.accessibilityFeaturesTestValue =
              const FakeAccessibilityFeatures(disableAnimations: true);
          addTearDown(
            tester.platformDispatcher.clearAccessibilityFeaturesTestValue,
          );
        }
        final image = File('assets/example-order.png').readAsBytesSync();
        final platform = TestPlatform();
        final peer = Peer()
          ..upload = (_) async => Peer.response({
            'episode_id': 'ep_9031',
            'status': 'received',
          }, 202);
        final app = controller(peer, platform: platform);
        await openApp(tester, app);

        platform.orders.add(
          SharedOrder('capture', '2026-10-15T21:00:08+09:00', [
            TestImage(preview: image),
          ]),
        );
        await app.sync();
        await tester.pump();
        expect(platform.acknowledged['capture'], 'ep_9031');
        expect(find.text('주문을 받았어요. 읽기 결과를 기다리는 중이에요.'), findsOneWidget);
        if (!reducedMotion) {
          final picture = tester.widget<Image>(find.byType(Image));
          expect(picture.semanticLabel, '공유한 주문 화면');
          expect(
            ((picture.image as ResizeImage).imageProvider as MemoryImage).bytes,
            same(image),
          );
        }
        await paintOrderPreview(tester);
        expect(find.byType(Card), findsNothing);

        final complete = fixture('episode.json')
          ..['status'] = 'notified'
          ..['item_count'] = 3
          ..['masked_count'] = 1
          ..['item_tasks'] = [];
        complete['items'] = (complete['items'] as List<Object?>)
            .take(2)
            .toList();
        peer.episodes['ep_9031'] = {
          ...complete,
          'status': 'reading',
          'item_count': 0,
          'masked_count': 0,
          'items': [],
          'card_ids': [],
        };
        await app.sync();
        await tester.pump();
        expect(find.text('주문을 읽고 있어요.'), findsOneWidget);
        expect(find.text('수량 미확인'), findsNothing);
        if (reducedMotion) {
          expect(orderScan, findsNothing);
        } else {
          final start = tester.getTopLeft(orderScan);
          final picture = find.byType(Image);
          final size = tester.getSize(picture);
          await tester.pump(const Duration(milliseconds: 400));
          expect(tester.getTopLeft(orderScan).dy, greaterThan(start.dy));
          expect(tester.getSize(picture), size);
          expect(
            find.ancestor(of: picture, matching: find.byType(Opacity)),
            findsNothing,
          );
          final scan = tester.widget<DecoratedBox>(orderScan);
          expect((scan.decoration as BoxDecoration).boxShadow, isNull);
        }
        await tester.pump(const Duration(milliseconds: 600));
        expect(find.byType(Image), findsOneWidget);
        expect(orderScan, reducedMotion ? findsNothing : findsOneWidget);
        expect(find.byType(Card), findsNothing);

        peer.episodes['ep_9031'] = complete;
        peer.cards = [fixture('card.v1.json')];
        const maskedName = '가린 상품 이름';
        peer.rationales['ep_9031']!['unbundled'] = ['딸기', maskedName];
        await app.sync();
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 1400));
        expect(find.byType(Image), findsNothing);
        expect(find.byType(Card), findsNothing);
        await tapText(tester, '바로 보기');
        expect(find.byType(Card), findsOneWidget);
        expect(find.text('읽은 품목 3개'), findsOneWidget);
        expect(find.text('수량 미확인'), findsNothing);
        await tapText(tester, '읽은 품목 3개');
        for (final text in [
          '딸기',
          '설향 딸기 500g (냉장)',
          '2개',
          '컵케이크 믹스',
          'OO 컵케이크 믹스',
          '수량 미확인',
          '가린 물건 1개',
          '이번 준비와 따로 본 물건',
        ]) {
          expect(find.text(text), findsOneWidget, reason: text);
        }
        expect(find.text(maskedName), findsNothing);
        await tapText(tester, '공유한 주문 보기');
        expect(find.widgetWithText(AppBar, '공유한 주문 보기'), findsOneWidget);
        final capture = tester.widget<Image>(find.byType(Image));
        expect(capture.semanticLabel, '공유한 주문 화면');
        expect((capture.image as MemoryImage).bytes, same(image));
        await tester.tap(find.byType(BackButton));
        await tester.pumpAndSettle();
        await tapText(tester, '읽은 품목 3개');
        expect(find.text('수량 미확인'), findsNothing);
        await openPreparationWhy(tester, peer);
        await tapText(tester, '전체 근거 보기');
        expect(find.text('주문에서 읽은 것 · 3개'), findsOneWidget);
        expect(find.textContaining('수량 미확인'), findsOneWidget);
        expect(find.text('가린 물건 1개'), findsOneWidget);
        expect(find.text(maskedName), findsNothing);
      },
    );
  }

  for (final mode in ['automatic', 'skip', 'reduced motion']) {
    testWidgets(
      'instant peer takes the new share through $mode and never replays on reload',
      (tester) async {
        if (mode == 'reduced motion') {
          tester.platformDispatcher.accessibilityFeaturesTestValue =
              const FakeAccessibilityFeatures(disableAnimations: true);
          addTearDown(
            tester.platformDispatcher.clearAccessibilityFeaturesTestValue,
          );
        }
        final peer = Peer();
        peer.upload = (_) async {
          peer.episodes['ep_9031'] = fixture('episode.json')
            ..['status'] = 'notified';
          peer.cards = [fixture('card.v1.json')];
          return Peer.response({
            'episode_id': 'ep_9031',
            'status': 'received',
          }, 202);
        };
        final store = TestStore();
        AppController preview() => AppController(
          api: peer.client(),
          platform: null,
          store: store,
          fixture: true,
          browserPreview: true,
          configuredHousehold: 'h_042',
        );
        final app = preview();
        await openApp(tester, app, size: const Size(412, 900));

        await tester.tap(find.text('예시 주문으로 공유'));
        await tester.pump();
        expect(app.episodes['ep_9031']?.status, wire.EpisodeStatus.NOTIFIED);
        final reduced = mode == 'reduced motion';
        const shortDwell = Duration(milliseconds: 800);
        const tick = Duration(milliseconds: 1);
        final image = find.byType(Image);
        final situation = find.text('상황');
        final intent = find.text('의도');
        final tasks = find.text('할 일');
        final items = find.text('설향 딸기 500g (냉장)');
        final card = find.byType(Card).hitTestable();

        Future<void> hold(Finder current, Duration dwell, Finder next) async {
          expect(current.hitTestable(), findsOneWidget);
          expect(next, findsNothing);
          await tester.pump((reduced ? shortDwell : dwell) - tick);
          expect(current.hitTestable(), findsOneWidget);
          expect(next, findsNothing);
          await tester.pump(tick);
          expect(current, findsNothing);
          expect(next, findsOneWidget);
        }

        Future<void> finishFade(Finder step) async {
          if (!reduced) {
            await tester.pump();
            await tester.pump(appSettle);
          }
          final fade = find.ancestor(of: step, matching: find.byType(Opacity));
          expect(tester.widget<Opacity>(fade).opacity, 1);
        }

        await paintOrderPreview(tester);
        expect(orderScan, reduced ? findsNothing : findsOneWidget);
        expect(card, findsNothing);
        await hold(image, const Duration(milliseconds: 2400), items);
        if (!reduced) {
          await tester.pump();
          await tester.pump(appSettle + tick);
        }
        if (mode == 'skip') {
          await tester.tap(find.text('바로 보기'));
          await tester.pump();
        } else {
          await hold(items, const Duration(milliseconds: 1500), situation);
          await finishFade(situation);
          expect(find.text('행사 · 생일'), findsOneWidget);
          expect(find.text('토요일 생일 일정 · 케이크 토퍼'), findsOneWidget);
          expect(find.text('테마 · 디즈니 공주'), findsOneWidget);
          expect(card, findsNothing);
          await hold(situation, const Duration(seconds: 2), intent);
          await finishFade(intent);
          final sentence = wire.Rationale.fromJson(peer.rationales['ep_9031']!)
              .intents
              .single
              .intentText;
          final intentText = tester.widget<Text>(find.text(sentence));
          final rich = intentText.textSpan! as TextSpan;
          expect(
            rich.children,
            contains(
              isA<TextSpan>()
                  .having((span) => span.text, 'theme', '디즈니 공주')
                  .having(
                    (span) => span.style?.color,
                    'highlight',
                    appPinkOnGreen,
                  ),
            ),
          );
          expect(find.text('함께 본 근거'), findsOneWidget);
          expect(find.text('이번 준비와 상관없는 물건 2개'), findsOneWidget);
          expect(card, findsNothing);
          await hold(intent, const Duration(milliseconds: 2500), tasks);
          await finishFade(tasks);
          expect(find.text('손님 오기 전 거실 청소'), findsOneWidget);
          expect(find.text('오븐 컵케이크 설정 대기'), findsOneWidget);
          await hold(tasks, const Duration(milliseconds: 1500), card);
        }

        expect(find.byType(Image), findsNothing);
        expect(find.text('바로 보기'), findsNothing);
        expect(situation, findsNothing);
        expect(intent, findsNothing);
        expect(tasks, findsNothing);
        expect(find.byType(Card), findsOneWidget);
        expect(find.text('읽은 품목 9개'), findsOneWidget);
        expect(find.text('설향 딸기 500g (냉장)'), findsNothing);

        await tester.pumpWidget(const SizedBox.shrink());
        await openApp(tester, preview());
        expect(find.byType(Image), findsNothing);
        expect(orderScan, findsNothing);
        expect(find.text('바로 보기'), findsNothing);
        expect(find.text('읽은 품목 9개'), findsOneWidget);
        expect(find.byType(Card), findsOneWidget);
      },
    );
  }

  for (final blur in [false, true]) {
    testWidgets(
      'staged share shows the card within one second of the sequence end (window blur $blur)',
      (tester) async {
        final peer = Peer();
        final app = AppController(
          api: peer.client(),
          platform: null,
          store: TestStore(),
          fixture: true,
          browserPreview: true,
          configuredHousehold: 'h_042',
        );
        await openApp(tester, app);

        final started = tester.binding.clock.now();
        Duration elapsed() => tester.binding.clock.now().difference(started);
        final earlyRationale = Completer<http.Response>();
        final freshRationale = Completer<http.Response>();
        peer.readRationale = () => peer.rationaleReads == 1
            ? earlyRationale.future
            : freshRationale.future;
        peer.upload = (_) async =>
            Peer.response({'episode_id': 'ep_9031', 'status': 'received'}, 202);
        await tester.tap(find.text('예시 주문으로 공유'));
        await tester.pump();
        await paintOrderPreview(tester);

        Future<void> advanceTo(Duration time, {Finder? until}) async {
          while (elapsed() < time && until?.evaluate().isNotEmpty != true) {
            final left = time - elapsed();
            const frame = Duration(milliseconds: 100);
            await tester.pump(left < frame ? left : frame);
          }
        }

        final episode = fixture('episode.json')
          ..['status'] = 'notified'
          ..['shared_at'] = DateTime.now().toUtc().toIso8601String();
        final itemTasks = (episode['item_tasks'] as List<dynamic>)
            .cast<Map<String, dynamic>>();
        await advanceTo(const Duration(seconds: 5));
        peer.episodes['ep_9031'] = {
          ...episode,
          'card_ids': blur ? [] : episode['card_ids'],
          'item_tasks': [
            for (final task in itemTasks) {...task, 'state': 'scheduled'},
          ],
        };
        await advanceTo(const Duration(seconds: 7));
        expect(find.text('설향 딸기 500g (냉장)'), findsOneWidget);
        expect(peer.rationaleReads, 1);
        expect(find.byType(Card), findsNothing);

        if (blur) {
          tester.binding.handleAppLifecycleStateChanged(
            AppLifecycleState.inactive,
          );
        }
        final card = fixture('card.v1.json');
        peer.episodes['ep_9031'] = {
          ...peer.birthday,
          'card_ids': episode['card_ids'],
        };
        peer.cards = [card];
        await advanceTo(const Duration(seconds: 10));
        expect(peer.rationaleReads, 2);
        expect(find.text('설향 딸기 500g (냉장)').hitTestable(), findsOneWidget);
        expect(find.text('상황'), findsNothing);
        final visibleCard = find.byType(Card).hitTestable();
        expect(visibleCard, findsNothing);
        freshRationale.complete(Peer.response(peer.rationales['ep_9031']));
        await tester.pump();
        await tester.pump();
        expect(find.text('상황').hitTestable(), findsOneWidget);
        final sequenceEnd =
            elapsed() + const Duration(seconds: 6) + appSettle * 3;
        await advanceTo(sequenceEnd - const Duration(milliseconds: 100));
        expect(find.text('할 일').hitTestable(), findsOneWidget);
        expect(visibleCard, findsNothing);
        await advanceTo(
          sequenceEnd + const Duration(seconds: 1),
          until: visibleCard,
        );
        expect(visibleCard, findsOneWidget);
        expect(peer.rationaleReads, 2);
        earlyRationale.complete(
          Peer.response({'code': 'not_found', 'message': 'pending'}, 404),
        );
        await tester.pump();

        final lines = (card['lines'] as List<dynamic>)
            .cast<Map<String, dynamic>>();
        expect(find.text('4개 중 0개 끝남'), findsOneWidget);
        expect(find.text(itemTasks.first['text'] as String), findsNothing);
        peer.cards = [
          {
            ...card,
            'lines': [
              for (final line in lines) {...line, 'state': 'done'},
            ],
            'summary': {'done': 4, 'total': 4, 'waiting_for': null},
          },
        ];
        peer.episodes['ep_9031'] = episode;
        final completedLines = find.text('4개 중 4개 끝남');
        await advanceTo(
          elapsed() + const Duration(seconds: 4),
          until: completedLines,
        );
        expect(completedLines, findsOneWidget);
        expect(find.text(itemTasks.first['text'] as String), findsOneWidget);
      },
    );
  }

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
      await tapText(tester, '읽은 품목 9개');
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
        ..['status'] = 'notified'
        ..['card_ids'] = ['nc_331', 'nc_340'];
      final second = fixture('card.found.json', episode: 'ep_9120')
        ..['episode_id'] = 'ep_9031'
        ..['summary'] = {'done': 0, 'total': 2, 'waiting_for': 'guest_arrived'};
      peer.cards = [fixture('card.v1.json'), second];
      final app = controller(peer);
      await openApp(tester, app);
      expect(find.byType(Card), findsNWidgets(2));
      expect(preparationMenu, findsNWidgets(2));
      expect(find.text('이 준비 중지'), findsNothing);
      expect(find.text('승인'), findsNothing);
      expect(find.text('4개 중 0개 끝남'), findsOneWidget);
      expect(find.text('손님 도착 기다리는 중'), findsOneWidget);
      expect(find.text('토요일 생일'), findsOneWidget);
      expect(find.text('파티 전'), findsNWidgets(2));
      expect(find.text('파티 시작에 맞춰'), findsOneWidget);
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
        ('user_changed', '직접 바꾸셨어요'),
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
      expect(find.text('3개 중 3개 끝남'), findsOneWidget);
      expect(find.text('꺼짐'), findsOneWidget);
      expect(find.text('바꾸신 그대로 두었어요'), findsOneWidget);
      expect(find.text('조명을 직접 바꾸셨어요. 바꾸신 그대로 두었어요'), findsOneWidget);
      expect(find.text('원래대로 돌렸어요'), findsOneWidget);
      expect(find.text('복원 대상 없음'), findsNothing);
      expect(find.textContaining('종료 조건'), findsNothing);

      final failedRestore = fixture('card.final.json')
        ..['updated_at'] = '2026-10-17T17:50:17+09:00';
      lines(failedRestore)[1]['end_state'] = 'restore_failed';
      peer.cards = [failedRestore];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('복원 실패 또는 결과 확인 불가'), findsOneWidget);
      expect(find.text('원래대로 돌렸어요'), findsNothing);

      peer.unavailable = true;
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('서버에 연결할 수 없어요 · 마지막 확인 01:02'), findsOneWidget);
      expect(
        tester.widget<PopupMenuButton<bool>>(preparationMenu.first).enabled,
        isFalse,
      );
    },
  );

  testWidgets(
    'APP-AT-04/05/10 shows withheld on the affected line until the Server reports restoration',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
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
      expect(lineText(safety, '원래대로 돌렸어요'), findsNothing);
      expect(lineText(mood, '바꾸신 그대로 두었어요'), findsOneWidget);
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
      expect(lineText(safety, '원래대로 돌렸어요'), findsOneWidget);
    },
  );

  testWidgets(
    'APP-AT-06 polls a held card every 3 seconds with the cursor and notifies each flagged pair once',
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
      await tester.pump(const Duration(seconds: 3));
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
    'polling backs off when idle or in the background and speeds up for a share and active card',
    (tester) async {
      final peer = Peer();
      final platform = TestPlatform();
      final app = controller(peer, platform: platform);
      await openApp(tester, app);
      expect(peer.pollCount, 1);
      await tester.pump(const Duration(seconds: 29));
      expect(peer.pollCount, 1);
      await tester.pump(const Duration(seconds: 1));
      expect(peer.pollCount, 2);

      platform.orders.add(
        SharedOrder('pending-share', '2026-11-04T19:30:41+09:00', [
          TestImage(),
        ]),
      );
      peer.upload = (_) async =>
          Peer.response({'episode_id': 'ep_9031', 'status': 'received'}, 202);
      await app.sync();
      expect(peer.pollCount, 3);
      expect(app.accepted, contains('ep_9031'));
      await tester.pump(const Duration(milliseconds: 2999));
      expect(peer.pollCount, 3);
      await tester.pump(const Duration(milliseconds: 1));
      expect(peer.pollCount, 4);

      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      await tester.pump(const Duration(seconds: 3));
      expect(peer.pollCount, 5);
      expect(app.accepted, isEmpty);
      await tester.pump(const Duration(seconds: 3));
      expect(peer.pollCount, 6);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump(const Duration(seconds: 29));
      expect(peer.pollCount, 6);
      await tester.pump(const Duration(seconds: 1));
      expect(peer.pollCount, 7);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(peer.pollCount, 8);
      peer.cards = [fixture('card.final.json')];
      await tester.pump(const Duration(seconds: 3));
      expect(peer.pollCount, 9);
      await tester.pump(const Duration(seconds: 29));
      expect(peer.pollCount, 9);
      await tester.pump(const Duration(seconds: 1));
      expect(peer.pollCount, 10);
    },
  );

  testWidgets(
    'APP-AT-07 toggles one line with a new task ID on re-enable and allows one undo-less off after start',
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
            'task_id': off ? change['task_id'] : 't_clean#7',
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
      final toggle = find.byType(Switch);
      final enabled = tester.widget<Switch>(toggle);
      expect(enabled.value, isTrue);
      expect(
        enabled.trackColor?.resolve({WidgetState.selected}),
        DesignTokens.greenSoft,
      );
      expect(
        enabled.thumbColor?.resolve({WidgetState.selected}),
        DesignTokens.greenDeep,
      );
      expect(tester.getSize(toggle).height, greaterThanOrEqualTo(48));
      final chevron = find.descendant(
        of: find.byKey(const ValueKey('nc_331')),
        matching: find.byIcon(Icons.chevron_right),
      );
      final arrow = tester.getRect(chevron);
      final switchBounds = tester.getRect(toggle);
      expect(switchBounds.left - arrow.right, greaterThanOrEqualTo(12));
      await tester.tapAt(
        Offset((switchBounds.left + arrow.right) / 2, arrow.center.dy),
      );
      await tester.pumpAndSettle();
      expect(peer.reactions, isEmpty);
      expect(find.text('이 일'), findsNothing);
      await tester.tap(chevron);
      await tester.pumpAndSettle();
      expect(find.text('이 일'), findsOneWidget);
      expect(peer.reactions, isEmpty);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect(peer.reactions.single.$1, 'nc_331');
      expect(peer.reactions.single.$2, {
        'reaction': 'line_off',
        'task_id': 't_clean#1',
      });
      expect(find.text('꺼짐'), findsNWidgets(2));
      expect(find.text('0개 중 0개 끝남'), findsOneWidget);
      expect(preparationMenu, findsOneWidget);
      expect(tester.widget<Switch>(toggle).value, isFalse);
      final undo = find.text('되돌리기');
      expect(undo, findsOneWidget);
      expect(
        tester.widget<SnackBar>(find.byType(SnackBar)).duration,
        const Duration(seconds: 5),
      );
      await tapText(tester, '되돌리기');
      expect(peer.reactions.last.$1, 'nc_331');
      expect(peer.reactions.last.$2, {
        'reaction': 'line_on',
        'task_id': 't_clean#1',
      });
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 4));
      expect(undo, findsOneWidget);
      await tester.pump(const Duration(seconds: 1));
      await tester.pumpAndSettle();
      expect(undo, findsNothing);
      expect(peer.reactions, hasLength(3));
      expect(tester.widget<Switch>(toggle).value, isFalse);
      final running = phase(peer.cards.single, 4);
      lines(running).first['state'] = 'running';
      peer.cards = [running];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('진행 중'), findsOneWidget);
      expect(tester.widget<Switch>(toggle).value, isTrue);
      await tester.tap(toggle);
      await tester.pumpAndSettle();
      expect(peer.reactions.last.$2, {
        'reaction': 'line_off',
        'task_id': lines(running).first['task_id'],
      });
      expect(find.text('되돌리기'), findsNothing);
      expect(toggle, findsNothing);
      expect(find.textContaining('잘못'), findsNothing);
      expect(find.textContaining('모두 중지'), findsNothing);
      await settings(tester);
      expect(find.text('자동 준비가 켜져 있는지 아직 알 수 없어요.'), findsOneWidget);
      expect(find.text('자동 준비 일시정지'), findsOneWidget);
      expect(find.textContaining('모두 중지'), findsNothing);
    },
  );

  testWidgets('a queued line off still applies if polling observes a start', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'notified');
    final scheduled = phase(fixture('card.v1.json'), 1);
    peer.cards = [scheduled];
    final app = controller(peer);
    await openApp(tester, app);
    final card = app.cards['nc_331']!;
    final line = card.lines.first;
    final running = phase(scheduled, 2)
      ..['lines'] = [
        {...lines(scheduled).first, 'state': 'running'},
        ...lines(scheduled).skip(1),
      ];
    peer.cards = [running];
    peer.reaction = (_) async {
      final off = phase(running, 3)
        ..['lines'] = [
          {...lines(running).first, 'state': 'off', 'checked': false},
          ...lines(running).skip(1),
        ];
      peer.cards = [off];
      return Peer.response(off);
    };
    final poll = app.sync();
    final switched = app.switchLine(card, line);
    await poll;
    expect(await switched, isTrue);
    expect(peer.reactions.single.$2, {
      'reaction': 'line_off',
      'task_id': line.taskId,
    });
    expect(app.lineStarted(card, line), isTrue);
    await app.undoLineOff(card.cardId, line.taskId);
    expect(peer.reactions, hasLength(1));
  });

  testWidgets('line controls respect execution evidence and episode closure', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'notified');
    final initial = phase(fixture('card.v1.json'), 1);
    final rows = lines(initial);
    rows[0]['state'] = 'unknown';
    rows[1]
      ..['state'] = 'off'
      ..['checked'] = false;
    rows[2]['state'] = 'failed';
    rows[3]['state'] = 'blocked';
    peer.cards = [initial];
    final rationale = peer.rationales['ep_9031']!;
    rationale['executions'] = [
      for (final (index, status) in [
        (1, 'completed'),
        (2, 'failed'),
        (3, 'blocked'),
      ])
        {
          'task_id': rows[index]['task_id'],
          'device': 'light_01',
          'status': status,
          'substrate': 'virtual',
          'at': initial['updated_at'],
        },
    ];
    final app = controller(peer);
    await openApp(tester, app);
    final card = app.cards['nc_331']!;
    expect(card.lines.map((line) => app.canSwitch(card, line)), [
      true,
      false,
      true,
      true,
    ]);
    await app.undoLineOff(card.cardId, card.lines[1].taskId);
    expect(peer.reactions, isEmpty);
    expect(app.lineStarted(card, card.lines[2]), isTrue);
    expect(app.lineStarted(card, card.lines[3]), isFalse);

    final rejected = phase(initial, 2);
    rows[3]['state'] = 'failed';
    peer.cards = [rejected];
    await app.sync();
    final updated = app.cards['nc_331']!;
    expect(app.canSwitch(updated, updated.lines[3]), isFalse);

    peer.episodes['ep_9031']!['status'] = 'closed';
    await app.sync();
    expect(updated.lines.any((line) => app.canSwitch(updated, line)), isFalse);
  });

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
      await openStopConfirmation(tester);
      expect(find.text('이 준비를 중지할까요?'), findsOneWidget);
      expect(peer.reactions, isEmpty);
      await tapText(tester, '취소');
      expect(peer.reactions, isEmpty);
      await openStopConfirmation(tester);
      await tester.tap(find.text('중지'));
      await tester.pump();
      await tester.pumpAndSettle();
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
      expect(find.text('원래대로 돌렸어요'), findsOneWidget);
      expect(find.text('바꾸신 그대로 두었어요'), findsOneWidget);
      expect(find.text('직접 시작한 조리를 유지했어요.'), findsOneWidget);
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
      await tapTab(tester, '준비');
      expect(find.text('취소됨'), findsNWidgets(3));
      expect(find.text('진행 중'), findsOneWidget);
      expect(find.textContaining('주문을 판단하지 않았어요'), findsOneWidget);
      expect(find.byType(Card), findsOneWidget);
    },
  );

  testWidgets('earlier orders are collapsed below the current preparation', (
    tester,
  ) async {
    final peer = Peer();
    final previous = fixture('card.v1.json');
    final current = fixture('card.found.json', episode: 'ep_9120');
    peer.episodes['ep_9031'] = fixture('episode.json')..['status'] = 'notified';
    peer.episodes['ep_9120'] = fixture('episode.json')
      ..['episode_id'] = 'ep_9120'
      ..['shared_at'] = '2026-11-05T21:00:08+09:00'
      ..['status'] = 'notified'
      ..['card_ids'] = [current['card_id']]
      ..['item_tasks'] = [];
    peer.cards = [previous, current];
    await openApp(tester, controller(peer), size: const Size(412, 900));

    final currentCard = find.byKey(ValueKey(current['card_id'] as String));
    final previousCard = find.byKey(ValueKey(previous['card_id'] as String));
    final history = find.text('지난 준비');
    expect(currentCard, findsOneWidget);
    expect(previousCard, findsNothing);
    expect(
      tester.getBottomLeft(currentCard).dy,
      lessThan(tester.getTopLeft(history).dy),
    );
    await tapText(tester, '지난 준비');
    expect(previousCard, findsOneWidget);
    await tapText(tester, '지난 준비');
    expect(previousCard, findsNothing);
  });

  testWidgets('preview keeps older orders as summaries below the latest', (
    tester,
  ) async {
    final previous = fixture('card.v1.json');
    lines(previous).first['state'] = 'unknown';
    final current = fixture('card.found.json', episode: 'ep_9120');
    final peer = Peer()..cards = [previous, current];
    peer.episodes['ep_9031'] = fixture('episode.json')..['status'] = 'notified';
    peer.episodes['ep_9120'] = fixture('episode.json')
      ..['episode_id'] = 'ep_9120'
      ..['shared_at'] = '2026-11-20T11:00:00+09:00'
      ..['status'] = 'notified'
      ..['card_ids'] = [current['card_id']]
      ..['item_tasks'] = [];
    final app = AppController(
      api: peer.client(),
      platform: null,
      store: TestStore(),
      fixture: true,
      browserPreview: true,
      configuredHousehold: 'h_042',
    );
    await openApp(tester, app, size: const Size(412, 900));

    final currentCard = find.byKey(ValueKey(current['card_id'] as String));
    final previousTitle = find.text(previous['text'] as String);
    final share = find.text('예시 주문으로 공유');
    final history = find.text('지난 준비 1개');
    expect(currentCard, findsOneWidget);
    expect(previousTitle, findsNothing);
    expect(share.hitTestable(), findsOneWidget);
    expect(find.text('미리보기 · 계약 테스트 서버'), findsOneWidget);
    expect(
      tester.getBottomLeft(history).dy,
      lessThan(tester.getTopLeft(share).dy),
    );
    expect(
      tester.getBottomLeft(share).dy,
      lessThan(tester.getTopLeft(find.byKey(const ValueKey('home-tabs'))).dy),
    );
    await tapText(tester, '지난 준비 1개');
    expect(previousTitle, findsOneWidget);
    expect(find.byType(Card), findsOneWidget);
    expect(find.text('결과 확인 불가'), findsNothing);

    peer.episodes['ep_9150'] = fixture('episode.json', episode: 'ep_9150')
      ..['shared_at'] = '2026-11-21T11:00:00+09:00';
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text('지난 준비 2개'), findsOneWidget);
    expect(find.byType(Card), findsNothing);
    expect(previousTitle, findsNothing);
    expect(find.text('집에서 준비할 일이 없어요.'), findsOneWidget);
    await tapTab(tester, '우리 집');
    expect(share, findsNothing);
    expect(find.textContaining('계약 테스트 서버'), findsNothing);
  });

  testWidgets('preview hides the unknown pause state and shows confirmation', (
    tester,
  ) async {
    final peer = Peer();
    await openApp(
      tester,
      AppController(
        api: peer.client(),
        platform: null,
        store: TestStore(),
        fixture: true,
        browserPreview: true,
        configuredHousehold: 'h_042',
      ),
    );
    await settings(tester);
    expect(find.text('자동 준비가 켜져 있는지 아직 알 수 없어요.'), findsNothing);
    expect(find.text('자동 준비 일시정지'), findsOneWidget);
    await tapText(tester, '자동 준비 일시정지');
    expect(find.text('자동 준비 일시정지됨'), findsOneWidget);
  });

  testWidgets(
    'finished preparation cards keep their WHY in collapsed history',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      AppController preview(TestStore store) => AppController(
        api: peer.client(),
        platform: null,
        store: store,
        fixture: true,
        browserPreview: true,
        configuredHousehold: 'h_042',
      );
      final app = preview(TestStore());
      await openApp(tester, app);
      final card = find.byKey(const ValueKey('nc_331'));
      final history = find.text('지난 준비 1개');
      expect(card, findsOneWidget);
      expect(history, findsNothing);

      final finished = fixture('card.final.json');
      peer.birthday['status'] = 'closed';
      peer.cards = [finished];
      await app.sync();
      await tester.pumpAndSettle();
      expect(history, findsNothing);
      expect(card, findsOneWidget);
      expect(find.text('파티가 끝나 인덕션·\u200B스마트 플러그를 원래대로 돌렸어요.'), findsOneWidget);
      expect(find.textContaining('파티가 끝나 TV'), findsNothing);
      expect(find.text('3개 중 3개 끝남'), findsOneWidget);
      await tapText(tester, '손님 오시면 공주 분위기 화면·조명');
      expect(find.text('손님이 오면 공주 테마 분위기').hitTestable(), findsOneWidget);
      expect(find.text('직접 바꾸셨어요').hitTestable(), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(minutes: 29));
      expect(card, findsOneWidget);
      await tester.pump(const Duration(minutes: 1));
      await tester.pumpAndSettle();
      expect(history, findsOneWidget);
      expect(card, findsNothing);
      await tapText(tester, '지난 준비 1개');
      expect(card, findsOneWidget);

      // On a fresh launch, the cursorless endpoint only supplies open cards.
      await tester.pumpWidget(const SizedBox.shrink());
      peer.cards = [];
      peer.historyCards = [finished];
      final fresh = preview(TestStore());
      await openApp(tester, fresh);
      expect(history, findsOneWidget);
      expect(card, findsNothing);
      await tapText(tester, '지난 준비 1개');
      expect(card, findsOneWidget);
      expect(fresh.lastServerCheck, '2026-11-05T01:02:03+09:00');
      await tapText(tester, '손님 오시면 공주 분위기 화면·조명');
      expect(find.text('손님이 오면 공주 테마 분위기').hitTestable(), findsOneWidget);
    },
  );

  testWidgets(
    'the browser preview does not show an earlier fixture run from its cache',
    (tester) async {
      final peer = Peer()
        ..cards = [fixture('card.v1.json')]
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified');
      final store = TestStore();
      AppController preview() => AppController(
        api: peer.client(),
        platform: null,
        store: store,
        fixture: true,
        browserPreview: true,
        configuredHousehold: 'h_042',
      );
      await openApp(tester, preview());
      final card = find.byKey(const ValueKey('nc_331'));
      expect(card, findsOneWidget);
      expect(
        store.values.keys.any((key) => key.startsWith('spira.snapshot')),
        isTrue,
      );

      // A new fixture run starts empty with the same IDs.
      await tester.pumpWidget(const SizedBox.shrink());
      peer.cards = [];
      peer.episodes.clear();
      await openApp(tester, preview());
      expect(card, findsNothing);
    },
  );

  testWidgets('the next share moves the restored preparation into history', (
    tester,
  ) async {
    final peer = Peer()
      ..cards = [fixture('card.v1.json')]
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'notified');
    final app = AppController(
      api: peer.client(),
      platform: null,
      store: TestStore(),
      fixture: true,
      browserPreview: true,
      configuredHousehold: 'h_042',
      discovered: wire.Devices.fromJson(fixture('devices.json')),
    );
    await openApp(tester, app);
    final finalCard = fixture('card.final.json');
    lines(finalCard)[2]['end_state'] = 'restored';
    peer.cards = [finalCard];
    peer.birthday['status'] = 'closed';
    await app.sync();
    await tester.pumpAndSettle();
    const summary = '파티가 끝나 인덕션·\u200B전기포트·\u200BTV·\u200B조명을 원래대로 돌렸어요.';
    expect(find.text(summary), findsOneWidget);
    expect(find.text('지난 준비 1개'), findsNothing);

    peer.upload = (_) async =>
        Peer.response({'episode_id': 'ep_9150', 'status': 'received'}, 202);
    await tester.tap(find.text('예시 주문으로 공유'));
    await tester.pump();
    expect(find.text(summary), findsNothing);
    expect(find.text('지난 준비 1개'), findsOneWidget);
    expect(find.text('주문을 받았어요. 읽기 결과를 기다리는 중이에요.'), findsOneWidget);
  });

  testWidgets('card lines use their own timing relative to the event', (
    tester,
  ) async {
    final peer = Peer();
    peer.episodes['ep_9031'] = fixture('episode.json')..['status'] = 'notified';
    final card = fixture('card.v1.json')
      ..['starts_at'] = '2026-10-16T15:05:00+00:00';
    lines(card).first['when'] = {'time': '2026-10-17T00:05:00+09:00'};
    lines(card)[1]['when'] = {'event': 'package.brought_in'};
    peer.cards = [card];
    await openApp(tester, controller(peer));

    expect(find.text('토요일 생일'), findsOneWidget);
    expect(find.text('파티 시작에 맞춰'), findsOneWidget);
    expect(find.text('택배가 들어오면'), findsOneWidget);
    expect(find.text('손님이 오면'), findsOneWidget);
    expect(find.text('파티 시작 후'), findsOneWidget);
    expect(find.textContaining(RegExp(r'\d{2}:\d{2}')), findsNothing);
  });

  testWidgets('card title wraps and highlights the theme from its rationale', (
    tester,
  ) async {
    final peer = Peer();
    peer.episodes['ep_9031'] = fixture('episode.json')..['status'] = 'notified';
    final card = fixture('card.v1.json');
    lines(card).first['checked'] = false;
    for (final line in lines(card)) {
      line['state'] = 'done';
    }
    lines(card).first['state'] = 'off';
    peer.cards = [card];
    final rationale = peer.rationales.remove('ep_9031')!;
    final app = controller(peer);
    await openApp(tester, app, size: const Size(320, 1050));

    final title = find.text(card['text'] as String);
    final plain = tester.widget<Text>(title);
    expect(plain.maxLines, isNull);
    expect(plain.overflow, isNot(TextOverflow.ellipsis));
    expect(tester.getSize(title).height, greaterThan(40));
    expect((plain.textSpan! as TextSpan).children, isNull);

    peer.rationales['ep_9031'] = rationale;
    await app.sync();
    await tester.pumpAndSettle();
    final pink = Theme.of(tester.element(title))
        .colorScheme
        .onSecondaryContainer;
    expect(
      (tester.widget<Text>(title).textSpan! as TextSpan).children,
      contains(
        TextSpan(
          text: '디즈니 공주',
          style: TextStyle(color: pink),
        ),
      ),
    );
    expect(
      find.descendant(
        of: find.byType(Card),
        matching: find.byIcon(Icons.check),
      ),
      findsNWidgets(3),
    );
    // A5-R1: the off line can be switched back on; done lines that have not ended
    // can still be switched off.
    expect(
      find.descendant(of: find.byType(Card), matching: find.byType(Switch)),
      findsNWidgets(4),
    );
  });

  testWidgets(
    'WHY derives before, after, and same time from the linked start',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.rationales['ep_9031']!['executions'] = [];
      final card = fixture('card.v1.json');
      lines(card)[1]['when'] = {'time': '2026-10-18T00:15:00+09:00'};
      peer.cards = [card];
      await openApp(tester, controller(peer), size: const Size(390, 760));
      for (final (line, time) in [
        ('손님 오기 전 거실 청소', '파티(14:00) 90분 전, 12:30 예정'),
        ('아이 안전 모드 (인덕션 잠금·전기포트 차단)', '파티(토 14:00) 시작 615분 뒤, 일 00:15 예정'),
        ('오븐 컵케이크 설정 대기', '파티(14:00) 시작에 맞춰, 14:00 예정'),
        ('손님 오시면 공주 분위기 화면·조명', '손님이 오면'),
      ]) {
        await tapText(tester, line);
        expect(find.text(time), findsWidgets, reason: line);
        await tester.tap(find.byType(BackButton));
        await tester.pumpAndSettle();
        await tester.tap(find.byType(BackButton));
        await tester.pumpAndSettle();
      }
    },
  );

  testWidgets('empty Android preparation explains how to share an order', (
    tester,
  ) async {
    await openApp(tester, controller(Peer()), size: const Size(412, 900));

    expect(find.text('쇼핑 앱에서 주문 화면을 공유하면, 그 주문에 맞춰 집을 준비해요.'), findsOneWidget);
    expect(find.text('주문 화면을 캡처하고 공유 메뉴에서 SPIRA를 선택해 주세요.'), findsOneWidget);
    expect(find.textContaining('예시 주문으로 공유'), findsNothing);
  });

  testWidgets('browser sample marks card devices and the order fridge', (
    tester,
  ) async {
    final peer = Peer();
    String? firstIdentity;
    peer.upload = (request) async {
      expect(request.url.path, '/v1/orders');
      expect(request.headers['authorization'], 'Bearer test-app-token');
      final body = latin1.decode(request.bodyBytes);
      expect(body, contains('name="household_id"\r\n\r\nh_042\r\n'));
      final source = RegExp(r'name="source_id"\r\n\r\n(preview_[\w-]{16})\r\n')
          .firstMatch(body);
      final time = RegExp(r'name="shared_at"\r\n\r\n([\dT:.\-]+Z)\r\n')
          .firstMatch(body);
      expect(source, isNotNull);
      expect(time, isNotNull);
      expect(body, contains('filename="example-order.png"'));
      final sample = File('assets/example-order.png').readAsBytesSync();
      expect(body, contains(latin1.decode(sample)));
      final identity = '${source!.group(1)} ${time!.group(1)}';
      if (firstIdentity == null) {
        firstIdentity = identity;
        throw http.ClientException('Order receipt lost');
      }
      expect(identity, firstIdentity);
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified'
        ..['card_ids'] = ['nc_331', 'nc_340'];
      peer.cards = [
        fixture('card.v1.json'),
        fixture('card.found.json', episode: 'ep_9120')
          ..['episode_id'] = 'ep_9031',
      ];
      return Peer.response({
        'episode_id': 'ep_9031',
        'status': 'received',
      }, 202);
    };
    final rationale = peer.rationales['ep_9031']!;
    rationale['executions'] = [];
    (rationale['tasks'] as List).add({
      'task_id': 't_oven#7',
      'card_id': 'nc_340',
      'line': '오븐 준비',
      'need': '별도 준비',
      'way': 'standby',
      'state': 'scheduled',
      'devices': [
        {'id': 'oven_01', 'type': 'oven', 'room': '주방'},
      ],
    });
    final homeHub = HttpHomeHubOnboarding(
      'http://hub.test',
      client: MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.path, '/home/onboarding/devices');
        expect(request.headers['x-api-key'], 'test-home-key');
        expect(request.headers['authorization'], isNull);
        final inventory = fixture('devices.json');
        (inventory['devices'] as List).addAll([
          for (final (id, type, room) in [
            ('purifier_01', 'purifier', '거실'),
            ('styler_01', 'styler', '현관'),
          ])
            {
              'id': id,
              'type': type,
              'room': room,
              'substrate': 'virtual',
              'commands': [],
              'events': [],
              'never': [],
              'noisy': false,
            },
        ]);
        return Peer.response(inventory);
      }),
    );
    final app = AppController(
      api: peer.client()..token = 'test-app-token',
      platform: null,
      store: TestStore(),
      fixture: true,
      browserPreview: true,
      configuredHousehold: 'h_042',
      homeHub: homeHub,
    );
    await openApp(tester, app, size: const Size(412, 820));
    final intro = find.text('쇼핑 앱에서 주문 화면을 공유하면, 그 주문에 맞춰 집을 준비해요.');
    final hint = find.text('아래에서 ‘예시 주문으로 공유’를 눌러 보세요.');
    final share = find.text('예시 주문으로 공유');
    expect(intro, findsOneWidget);
    expect(hint, findsOneWidget);
    expect(share.hitTestable(), findsOneWidget);
    expect(tester.getCenter(intro).dy, inInclusiveRange(200, 360));
    expect(
      tester.getBottomLeft(hint).dy,
      lessThan(tester.getTopLeft(share).dy),
    );
    expect(find.text('우리 집 접속 키 입력'), findsNothing);
    await settings(tester);
    await tapText(tester, '우리 집 접속 키 입력');
    await tester.enterText(find.byType(TextField), 'test-home-key');
    await tapText(tester, '연결');
    await tapTab(tester, '우리 집');
    expect(find.text('확인한 기기 9대'), findsOneWidget);
    expect(find.text('쉬는 중'), findsNWidgets(9));
    await tapTab(tester, '준비');
    await tapText(tester, '예시 주문으로 공유');
    expect(find.text('예시 주문을 보내지 못했어요. 다시 시도해 주세요.'), findsOneWidget);
    await tester.tap(share);
    await tester.pump();
    await paintOrderPreview(tester);
    await tester.pump(const Duration(milliseconds: 900));
    await tester.pumpAndSettle();
    await tapText(tester, '바로 보기');
    expect(intro, findsNothing);
    expect(hint, findsNothing);
    expect(find.text('읽은 품목 9개'), findsOneWidget);
    await tapText(tester, '손님 오기 전 거실 청소');
    expect(find.text('이 일'), findsOneWidget);
    expect(peer.rationaleReads, 2);
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(BackButton));
    await tester.pumpAndSettle();
    await tapTab(tester, '우리 집');

    Finder statusFor(String device, String status) => find.descendant(
      of: find.ancestor(
        of: find.text(device),
        matching: find.byType(MergeSemantics),
      ),
      matching: find.text(status),
    );

    expect(find.text('거실'), findsOneWidget);
    expect(find.text('주방'), findsOneWidget);
    expect(find.text('현관'), findsOneWidget);
    expect(find.text('확인한 기기 9대'), findsOneWidget);
    expect(statusFor('로봇청소기', '이번 준비에 써요 · 파티 전'), findsOneWidget);
    expect(statusFor('TV', '이번 준비에 써요 · 손님이 오면'), findsOneWidget);
    expect(statusFor('냉장고', '이번 준비에 써요 · 안내'), findsOneWidget);
    expect(statusFor('공기청정기', '쉬는 중'), findsOneWidget);
    expect(statusFor('스타일러', '쉬는 중'), findsOneWidget);
    expect(find.textContaining('이번 준비에 써요'), findsNWidgets(7));
    expect(find.byType(Switch), findsNothing);
    expect(
      tester.getTopLeft(find.byKey(const ValueKey('light_01'))).dy,
      tester.getTopLeft(find.byKey(const ValueKey('cleaner_01'))).dy,
    );
    await tapTab(tester, '준비');
    expect(find.byType(Card), findsNWidgets(2));
    await tapTab(tester, '우리 집');
    expect(statusFor('로봇청소기', '이번 준비에 써요 · 파티 전'), findsOneWidget);
    final rescheduled = phase(peer.cards.first, 1);
    lines(rescheduled).first['when'] = {'time': rescheduled['starts_at']};
    peer.cards = [rescheduled, peer.cards.last];
    await app.sync();
    await tester.pumpAndSettle();
    expect(statusFor('로봇청소기', '이번 준비에 써요 · 파티 시작에 맞춰'), findsOneWidget);
    expect(peer.rationaleReads, 3);
  });

  for (final submitFromKeyboard in [false, true]) {
    testWidgets(
      'Android home key from ${submitFromKeyboard ? 'keyboard Done' : 'Connect'} '
      'authenticates Our Home refreshes after restart',
      (tester) async {
        final peer = Peer()
          ..episodes['ep_9031'] = (fixture('episode.json')
            ..['status'] = 'notified')
          ..cards = [fixture('card.v1.json')];
        final store = TestStore();
        final inventory = fixture('devices.json');
        (inventory['devices'] as List).addAll([
          for (final (id, type) in [
            ('purifier_01', 'purifier'),
            ('styler_01', 'styler'),
            ('aircon_01', 'aircon'),
          ])
            {
              'id': id,
              'type': type,
              'room': '현관',
              'substrate': 'virtual',
              'commands': [],
              'events': [],
              'never': [],
              'noisy': false,
            },
        ]);
        final hubRequests = <http.Request>[];
        AppController open() => AppController(
          api: AppApi(
            Uri.parse('http://127.0.0.1:58137'),
            client: MockClient((request) async {
              if (request.headers['authorization'] != 'Bearer test-app-token') {
                return Peer.response({
                  'code': 'unauthorized',
                  'message': 'App token required',
                }, 401);
              }
              return peer.handle(request);
            }),
          ),
          platform: TestPlatform(),
          store: store,
          fixture: true,
          configuredHousehold: 'h_042',
          homeHub: HttpHomeHubOnboarding(
            'http://127.0.0.1:58139',
            client: MockClient((request) async {
              hubRequests.add(request);
              return Peer.response(inventory);
            }),
          ),
        );

        await openApp(tester, open(), size: const Size(412, 820));
        await settings(tester);
        await tapText(tester, '서버 접속 토큰 입력');
        await tester.enterText(find.byType(TextField), 'test-app-token');
        await tapText(tester, '연결');
        await tapTab(tester, '우리 집');
        expect(find.text('확인한 기기 7대'), findsOneWidget);
        expect(find.textContaining('집 기기 목록을 받지 못해'), findsOneWidget);
        expect(hubRequests, isEmpty);
        await settings(tester);
        await tapText(tester, '우리 집 접속 키 입력');
        await tester.enterText(find.byType(TextField), 'test-home-key');
        if (submitFromKeyboard) {
          await tester.testTextInput.receiveAction(TextInputAction.done);
          await tester.pumpAndSettle();
        } else {
          await tapText(tester, '연결');
        }
        expect(find.byType(AlertDialog), findsNothing);

        await tapTab(tester, '우리 집');
        expect(find.text('확인한 기기 10대'), findsOneWidget);
        expect(find.textContaining('집 기기 목록을 받지 못해'), findsNothing);
        expect(hubRequests, hasLength(1));
        await tester.drag(find.byType(RefreshIndicator), const Offset(0, 400));
        await tester.pumpAndSettle();
        expect(hubRequests, hasLength(2));

        final previousPollCount = peer.pollCount;
        await tester.pumpWidget(const SizedBox.shrink());
        await openApp(tester, open(), size: const Size(412, 820));
        expect(peer.pollCount, greaterThan(previousPollCount));
        await tapTab(tester, '우리 집');
        expect(find.text('확인한 기기 10대'), findsOneWidget);
        expect(hubRequests, hasLength(3));
        for (final request in hubRequests) {
          expect(request.method, 'GET');
          expect(
            request.url.toString(),
            'http://127.0.0.1:58139/home/onboarding/devices',
          );
          expect(request.headers['x-api-key'], 'test-home-key');
          expect(request.headers['authorization'], isNull);
          expect(request.followRedirects, isFalse);
        }
      },
      variant: const TargetPlatformVariant({TargetPlatform.android}),
    );
  }

  test('a pending Hub response cannot block or overwrite a new key', () async {
    final firstRequest = Completer<void>();
    final firstResponse = Completer<http.Response>();
    final app = controller(
      Peer(),
      homeHub: HttpHomeHubOnboarding(
        'http://hub.test',
        client: MockClient((request) async {
          if (request.headers['x-api-key'] == 'old-home-key') {
            firstRequest.complete();
            return firstResponse.future;
          }
          expect(request.headers['x-api-key'], 'new-home-key');
          return Peer.response(fixture('devices.json')..['revision'] = 2);
        }),
      ),
    );
    addTearDown(() {
      if (!firstResponse.isCompleted) {
        firstResponse.complete(http.Response('', 401));
      }
      app.dispose();
    });
    await app.start();
    await app.useHomeKey('old-home-key');
    final first = app.refreshHomeInventory();
    await firstRequest.future;

    await app.useHomeKey('new-home-key');
    final second = app.refreshHomeInventory();
    expect(second, isNot(same(first)));
    await second;
    expect(app.homeInventory?.revision, 2);

    firstResponse.complete(
      Peer.response(fixture('devices.json')..['revision'] = 1),
    );
    await first;
    expect(app.homeInventory?.revision, 2);
  });

  testWidgets('our home shows only selected devices when the Hub is offline', (
    tester,
  ) async {
    final peer = Peer();
    peer.episodes['ep_9031'] = fixture('episode.json')..['status'] = 'notified';
    peer.cards = [fixture('card.v1.json')];
    final homeHub = HttpHomeHubOnboarding(
      'http://hub.test',
      client: MockClient(
        (request) async => throw http.ClientException('offline'),
      ),
    )..useApiKey('test-home-key');
    await openApp(
      tester,
      controller(
        peer,
        homeHub: homeHub,
        discovered: wire.Devices.fromJson(fixture('devices.json')),
      ),
      size: const Size(390, 760),
    );
    await tapTab(tester, '우리 집');

    expect(find.text('거실'), findsOneWidget);
    expect(find.text('주방'), findsOneWidget);
    expect(find.text('확인한 기기 7대'), findsOneWidget);
    expect(find.textContaining('집 기기 목록을 받지 못해'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('이번 준비에 써요 · 안내'), 120);
    expect(find.textContaining('이번 준비에 써요'), findsNWidgets(7));
    expect(find.text('쉬는 중'), findsNothing);
    expect(find.text('냉장고'), findsOneWidget);
  });

  testWidgets('cold startup shows one quiet notice when the network is down', (
    tester,
  ) async {
    final app = AppController(
      api: AppApi(
        Uri.parse('https://test.invalid'),
        client: MockClient((_) async => throw http.ClientException('offline')),
      ),
      platform: null,
      store: TestStore(),
      fixture: true,
      configuredHousehold: 'h_042',
    );
    await openApp(tester, app);
    expect(find.text('서버에 연결할 수 없어요'), findsOneWidget);
    expect(find.textContaining('마지막 확인'), findsNothing);
    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('준비를 불러오는 중이에요…'), findsNothing);
  });

  testWidgets(
    'offline reload keeps cards and home and retries a queued share',
    (tester) async {
      final store = TestStore();
      final platform = TestPlatform();
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final card = fixture('card.v1.json');
      lines(card).first['state'] = 'done';
      peer.cards = [card];
      var hubUnavailable = false;
      AppController open() => controller(
        peer,
        store: store,
        platform: platform,
        homeHub: HttpHomeHubOnboarding(
          'http://hub.test',
          client: MockClient((_) async {
            if (hubUnavailable) throw http.ClientException('offline');
            return Peer.response(fixture('devices.json'));
          }),
        )..useApiKey('test-home-key'),
      );
      const offline = '서버에 연결할 수 없어요 · 마지막 확인 01:02';
      const queued = '연결되면 공유한 주문을 보낼게요.';
      const cleaner = '이번 준비에 써요 · 파티 전';
      await openApp(tester, open(), size: const Size(412, 900));
      await tapTab(tester, '우리 집');
      expect(find.text('확인한 기기 7대'), findsOneWidget);
      expect(find.text(cleaner), findsWidgets);

      peer.unavailable = hubUnavailable = true;
      await tester.pumpWidget(const SizedBox.shrink());
      await openApp(tester, open(), size: const Size(412, 900));
      expect(find.text(offline).hitTestable(), findsOneWidget);
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(Card), findsOneWidget);
      expect(find.text('완료'), findsWidgets);
      await tapTab(tester, '우리 집');
      expect(find.text(offline).hitTestable(), findsOneWidget);
      expect(find.text('확인한 기기 7대'), findsOneWidget);
      expect(find.text(cleaner), findsWidgets);
      expect(find.textContaining('집 기기 목록을 받지 못'), findsNothing);
      await tapTab(tester, '준비');

      platform.orders.add(
        SharedOrder('queued', '2026-11-05T01:03:00+09:00', [TestImage()]),
      );
      platform.changes.add(null);
      await tester.pumpAndSettle();
      expect(find.text(queued).hitTestable(), findsOneWidget);
      expect(platform.acknowledged, isEmpty);
      final offlineUpload = peer.requests.lastWhere(
        (request) => request.url.path == '/v1/orders',
      );
      expect(offlineUpload.body, contains('queued'));

      peer.upload = (request) async {
        expect(request.body, contains('queued'));
        return Peer.response({
          'episode_id': 'ep_9031',
          'status': 'received',
        }, 200);
      };
      peer.unavailable = false;
      await tester.pump(const Duration(seconds: 30));
      await tester.pumpAndSettle();
      expect(platform.acknowledged['queued'], 'ep_9031');
      expect(find.text(offline), findsNothing);
      expect(find.text(queued), findsNothing);
      expect(find.byType(Card), findsOneWidget);
      expect(find.text('바로 보기'), findsNothing);
    },
  );

  testWidgets(
    'order story follows live server outputs and uses only their supplied times',
    (tester) async {
      final peer = Peer();
      final episode = peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final itemTasks = (episode['item_tasks'] as List)
          .cast<Map<String, dynamic>>();
      for (final item in itemTasks) {
        item['state'] = 'scheduled';
      }
      final rationale = peer.rationales['ep_9031']!;
      final recordedRuns = (rationale['executions'] as List)
          .cast<Map<String, dynamic>>();
      final recordedObservation = rationale['observations'];
      rationale['executions'] = [];
      rationale['observations'] = [];
      final card = fixture('card.v1.json');
      peer.cards = [card];
      final app = controller(peer);
      await openApp(tester, app, size: const Size(390, 760));
      await tapText(tester, '자세히');

      Finder row(String id, String text) => find.descendant(
        of: find.byKey(ValueKey<Object>(id)),
        matching: find.text(text),
      );
      expect(find.widgetWithText(AppBar, '토요일 생일 준비'), findsOneWidget);
      expect(find.text('미리보기 · 계약 테스트 서버'), findsOneWidget);
      expect(find.text('지금'), findsOneWidget);
      expect(find.text('토 12:30에 ‘손님 오기 전 거실 청소’ 예정이에요'), findsOneWidget);
      expect(find.text('4개 중 0개 끝남'), findsOneWidget);
      expect(find.text('목 21:00'), findsOneWidget);
      expect(find.text('목 21:11'), findsNothing);
      expect(find.text('이번 준비와 관계없다고 본 물건: 세탁 세제 · 로션'), findsOneWidget);
      expect(row('t_clean#1', '토 12:30 예정'), findsOneWidget);
      expect(row('t_mood#3', '손님이 오면'), findsOneWidget);
      const mood = '손님 오시면 공주 분위기 화면·조명';
      expect(
        tester.widget<Text>(find.text(mood)).style?.color,
        DesignTokens.muted,
      );
      expect(find.byIcon(Icons.radio_button_unchecked), findsNWidgets(4));
      expect(find.text('판단을 확인했어요'), findsNothing);

      for (final text in [
        '판단 근거',
        '토요일 14:00에 생일 일정',
        '이 집이 산 적 없는 물건',
        '비슷한 주문 12건 중 9건이 아이 생일 파티',
      ]) {
        expect(find.text(text), findsOneWidget, reason: text);
      }
      expect(find.text('그래서 할 일'), findsNothing);
      for (final task in (rationale['tasks'] as List).cast<Map>()) {
        expect(
          row(task['task_id'] as String, task['need'] as String),
          findsOneWidget,
        );
      }

      await tapText(tester, '이렇게 판단했어요');
      expect(find.text('판단 근거'), findsNothing);
      const similarOrders = '비슷한 주문 12건 중 9건';
      expect(find.widgetWithText(ActionChip, similarOrders), findsOneWidget);
      await tapText(tester, similarOrders);
      expect(find.text('판단 근거'), findsOneWidget);
      await tapText(tester, '아이 안전 모드');
      expect(find.widgetWithText(AppBar, '아이 안전 모드'), findsOneWidget);
      expect(find.text('파티 동안 아이가 주방 기기에 다치지 않게'), findsOneWidget);
      expect(find.text('파티(14:00) 30분 전, 13:30 예정'), findsOneWidget);
      expect(find.text('손님이 오면 공주 테마 분위기'), findsNothing);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tapText(tester, '이렇게 판단했어요');
      expect(find.text('판단 근거'), findsNothing);

      final changed = phase(card, 1)
        ..['updated_at'] = '2026-10-16T08:40:00+09:00';
      lines(changed).first
        ..['checked'] = false
        ..['state'] = 'off';
      (changed['summary'] as Map)
        ..['total'] = 3
        ..['waiting_for'] = 'guest_arrived';
      peer.cards = [changed];
      final polls = peer.pollCount;
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(peer.pollCount, greaterThan(polls));
      expect(find.text('판단 근거'), findsNothing);
      expect(find.text('손님 오시기를 기다리고 있어요'), findsOneWidget);
      expect(find.textContaining('항목을 껐어요.'), findsNWidgets(2));
      expect(find.text('금 08:40'), findsNothing);

      final running = phase(changed, 2)
        ..['updated_at'] = '2026-10-17T13:53:00+09:00';
      lines(running)[1]['state'] = 'done';
      lines(running)[2]['state'] = 'done';
      (running['summary'] as Map)
        ..['done'] = 2
        ..['waiting_for'] = null;
      peer.cards = [running];
      for (final item in itemTasks) {
        item['state'] = 'done';
      }
      rationale['executions'] = recordedRuns.take(6).toList().reversed.toList();
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.text('3개 중 2개 끝남'), findsOneWidget);
      expect(find.text('손님 오시기를 기다리고 있어요'), findsNothing);
      expect(
        tester.widget<Text>(find.text(mood)).style?.color,
        DesignTokens.ink,
      );
      expect(find.byIcon(Icons.radio_button_unchecked), findsOneWidget);

      final ordered = [
        find.text('주문을 읽었어요'),
        find.text('이렇게 판단했어요'),
        find.text('할 일 4개를 정했어요'),
        find.text('준비를 바꿨어요'),
        find.text('금 18:05').first,
        find.text('토 13:30').first,
        find.text('손님이 오면 · 13:52'),
        find.text('토 14:00 예정'),
      ];
      for (final (before, after) in Iterable.generate(
        ordered.length - 1,
        (i) => (ordered[i], ordered[i + 1]),
      )) {
        expect(
          tester.getTopLeft(before).dy,
          lessThan(tester.getTopLeft(after).dy),
        );
      }
      expect(find.text('냉장고에 안내를 띄웠어요'), findsOneWidget);
      expect(find.textContaining('택배가 들어오면'), findsNothing);
      expect(find.text('토 14:00에 ‘오븐 컵케이크 설정 대기’ 예정이에요'), findsOneWidget);
      expect(row('t_mood#3', '완료'), findsOneWidget);
      expect(find.text('적용됨 · 끝나면 원래대로'), findsNothing);
      final safety = find.text('아이 안전 모드').first;
      await tester.ensureVisible(safety);
      await tester.tap(safety);
      await tester.pumpAndSettle();
      expect(find.text('토 13:30 · 완료'), findsNWidgets(2));
      expect(find.text('파티(14:00) 30분 전, 13:30에 실행'), findsOneWidget);
      expect(find.text('적용됨 · 끝나면 원래대로'), findsNothing);
      expect(find.text('인덕션'), findsOneWidget);
      expect(find.text('이 판단에서 나왔어요'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      peer.cards = [fixture('card.final.json')];
      rationale['executions'] = recordedRuns;
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('판단을 확인했어요'), findsNothing);

      episode['status'] = 'closed';
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('끝났어요'), findsOneWidget);
      expect(find.textContaining('파티가 끝나 인덕션'), findsOneWidget);
      expect(find.text('원래대로 돌렸어요'), findsOneWidget);
      expect(find.text('판단을 확인했어요'), findsNothing);

      // S7 can become available after the card and episode have closed.
      rationale['observations'] = recordedObservation;
      final reads = peer.rationaleReads;
      await tester.pump(const Duration(seconds: 30));
      await tester.pumpAndSettle();
      expect(peer.rationaleReads, greaterThan(reads));
      expect(find.text('판단을 확인했어요'), findsOneWidget);
      expect(find.text(mood), findsOneWidget);
      expect(find.text('직접 바꾸셨어요'), findsOneWidget);
      expect(find.text('바꾸신 그대로 두었어요'), findsNothing);
      expect(find.textContaining('조명은 바꾸신 그대로 두었어요'), findsOneWidget);
      expect(find.textContaining('인덕션 · 스마트 플러그'), findsOneWidget);
      const adjustment = '조명 · 2700K로 바꾸셨어요 · 시작 70분 뒤';
      final ending = [
        find.text('끝났어요'),
        find.text('판단을 확인했어요'),
        find.text('판단은 맞았고, 바꾸신 점은 다음에 참고할게요.'),
        find.text('다음 생일 준비 때 참고할게요'),
        find.text(adjustment).first,
        find.textContaining('실행 전에 끄셨어요.'),
        find.text('나머지 2개는 그대로 쓰셨어요'),
        find.text('주문을 읽었어요'),
      ];
      for (final (before, after) in Iterable.generate(
        ending.length - 1,
        (i) => (ending[i], ending[i + 1]),
      )) {
        expect(
          tester.getTopLeft(before).dy,
          lessThan(tester.getTopLeft(after).dy),
        );
      }
      expect(row('t_mood#3', adjustment), findsOneWidget);
      expect(row('t_safe#2', adjustment), findsNothing);
      expect(find.textContaining('실행 토'), findsNothing);
      await tapText(tester, mood);
      expect(find.text(adjustment), findsOneWidget);
      expect(find.text('바꾸신 그대로 두었어요'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      expect(find.text('토 17:50'), findsNothing);
      expect(
        peer.requests.where((request) => request.url.path.endsWith('/memory')),
        isEmpty,
      );
      await tapText(tester, '우리 집 기억 보기');
      expect(find.widgetWithText(AppBar, '우리 집 기억'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      await tapText(tester, '전체 근거 보기');
      expect(find.widgetWithText(AppBar, '전체 근거'), findsOneWidget);
      final headings = [
        '주문에서 읽은 것 · 9개',
        '평소와 달랐던 물건',
        '비슷한 주문 (다른 집들)',
        '상황 칸과 근거',
        '연결된 일정',
      ];
      for (var i = 1; i < headings.length; i++) {
        expect(
          tester.getTopLeft(find.text(headings[i - 1])).dy,
          lessThan(tester.getTopLeft(find.text(headings[i])).dy),
        );
      }
      expect(find.textContaining('평소 1개 → 이번 2개'), findsOneWidget);
      expect(find.text('아이 생일 파티 9건'), findsOneWidget);
      expect(
        find.text('6개 중 4개가 같아요 · 고깔모자 · 딸기 · 케이크 토퍼 · 풍선'),
        findsOneWidget,
      );
      expect(find.text('토 14:00–17:00'), findsOneWidget);
      for (final excluded in ['가족 모임', 'syn_A1-3_0018', 'cooktop_01', 'c1']) {
        expect(find.textContaining(excluded), findsNothing, reason: excluded);
      }
    },
  );

  testWidgets(
    'after guest arrival the live summary waits for the end without guessing restoration',
    (tester) async {
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified');
      final rationale = peer.rationales['ep_9031']!;
      final recordedRuns = rationale['executions'];
      rationale['executions'] = [];
      rationale['observations'] = [];
      final beforeGuest = fixture('card.v1.json');
      (beforeGuest['summary'] as Map)
        ..['done'] = 3
        ..['waiting_for'] = 'guest_arrived';
      for (final line in lines(
        beforeGuest,
      ).where((line) => line['task_id'] != 't_mood#3')) {
        line['state'] = 'done';
      }
      peer.cards = [beforeGuest];
      final app = controller(peer, fixture: false);
      await openApp(tester, app, size: const Size(412, 900));
      await tapText(tester, '자세히');
      expect(find.text('미리보기 · 계약 테스트 서버'), findsNothing);
      expect(find.text('손님 오시기를 기다리고 있어요'), findsOneWidget);

      final afterGuest = phase(beforeGuest, 1);
      (afterGuest['summary'] as Map)
        ..['done'] = 4
        ..['waiting_for'] = null;
      lines(afterGuest)[2]['state'] = 'done';
      rationale['executions'] = recordedRuns;
      peer.cards = [afterGuest];
      await app.sync();
      await tester.pumpAndSettle();

      expect(find.text('일정이 끝나기를 기다리고 있어요').hitTestable(), findsOneWidget);
      expect(find.text('손님 오시기를 기다리고 있어요'), findsNothing);
      expect(find.text('4개 중 4개 끝남'), findsOneWidget);
      expect(find.text('손님이 오면 · 13:52'), findsOneWidget);
      expect(find.textContaining('원래대로 돌릴게요'), findsNothing);
      expect(find.text('적용됨 · 끝나면 원래대로'), findsNothing);
    },
  );

  testWidgets(
    'order story keeps the first record when the peer replaces it with completion',
    (tester) async {
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified');
      final rationale = peer.rationales['ep_9031']!;
      rationale['observations'] = [];
      const cleaner = '손님 오기 전 거실 청소';
      Map<String, dynamic> run(
        String task,
        String device,
        String status,
        String at,
      ) => {
        'task_id': task,
        'device': device,
        'status': status,
        'substrate': 'virtual',
        'at': at,
      };
      final starting = run(
        't_clean#1',
        'cleaner_01',
        'running',
        '2026-10-17T13:17:00+09:00',
      );
      rationale['executions'] = [starting];
      final card = phase(fixture('card.v1.json'), 1);
      lines(card).first
        ..['state'] = 'running'
        ..['when'] = {'time': '2026-10-17T13:17:00+09:00'};
      lines(card)[1]['when'] = {'time': '2026-10-17T13:19:00+09:00'};
      (card['summary'] as Map)['waiting_for'] = 'guest_arrived';
      peer.cards = [card];
      final app = controller(peer);
      await openApp(tester, app);
      await tapText(tester, '자세히');
      expect(find.text(cleaner), findsOneWidget);
      expect(find.text('토 13:17'), findsOneWidget);
      expect(find.text('진행 중'), findsOneWidget);
      expect(find.text('‘$cleaner’ 항목을 실행하고 있어요'), findsOneWidget);
      expect(find.text('손님 오시기를 기다리고 있어요'), findsNothing);

      final next = phase(fixture('card.v1.json'), 2);
      lines(next)[0]['state'] = 'done';
      lines(next)[1]['state'] = 'done';
      peer.cards = [next];
      rationale['executions'] = [
        run('t_safe#2', 'plug_kettle', 'completed', '2026-10-17T04:24:00Z'),
        run(
          't_clean#1',
          'cleaner_01',
          'completed',
          '2026-10-17T13:22:00+09:00',
        ),
        run('t_safe#2', 'cooktop_01', 'completed', '2026-10-17T13:19:00+09:00'),
      ];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text(cleaner), findsOneWidget);
      expect(find.text('아이 안전 모드'), findsOneWidget);
      expect(find.text('진행 중'), findsNothing);
      expect(find.text('토 13:17'), findsOneWidget);
      expect(find.text('토 13:19'), findsOneWidget);
      expect(find.text('토 13:22'), findsNothing);
      expect(find.text('토 13:24'), findsNothing);
      expect(
        tester.getTopLeft(find.text(cleaner)).dy,
        lessThan(tester.getTopLeft(find.text('아이 안전 모드')).dy),
      );
    },
  );

  testWidgets('live S7 appears with a newly dated order and recorded runs', (
    tester,
  ) async {
    final peer = Peer();
    final episode = peer.episodes['ep_9031'] = fixture('episode.json')
      ..['status'] = 'notified'
      ..['shared_at'] = '2026-11-21T18:03:00+09:00';
    final rationale = peer.rationales['ep_9031']!;
    final observations = rationale['observations'] as List;
    final feedback = (observations.single as Map)['task_feedback'] as List;
    final change = (feedback[2] as Map)['changes'] as List;
    (change.single as Map)
      ..['property'] = 'color'
      ..['after_start_minutes'] = 1;
    rationale['observations'] = [];
    final live = fixture('card.v1.json')
      ..['starts_at'] = '2026-11-21T18:04:00+09:00'
      ..['updated_at'] = '2026-11-21T18:04:30+09:00';
    peer.cards = [live];
    final app = controller(peer);
    await openApp(tester, app);
    await tapText(tester, '자세히');
    expect(find.text('판단을 확인했어요'), findsNothing);

    rationale['observations'] = observations;
    peer.cards = [
      fixture('card.final.json')
        ..['starts_at'] = live['starts_at']
        ..['updated_at'] = '2026-11-21T18:06:00+09:00',
    ];
    episode['status'] = 'closed';
    await tester.pump(const Duration(seconds: 3));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(AppBar, '토요일 생일 준비'), findsOneWidget);
    expect(find.text('판단을 확인했어요'), findsOneWidget);
    expect(find.text('다음 생일 준비 때 참고할게요'), findsOneWidget);
    expect(find.text('조명 · 2700K로 바꾸셨어요 · 시작 1분 뒤'), findsNWidgets(2));
    expect(find.text('금 18:05'), findsNothing);
    expect(find.text('토 13:52'), findsNothing);
    expect(find.text('토 18:06'), findsNothing);
  });

  testWidgets(
    'WHY replaces an early derived clock with the confirmed run or share time',
    (tester) async {
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified'
          ..['shared_at'] = '2026-10-17T07:22:00Z');
      final card = fixture('card.v1.json')
        ..['starts_at'] = '2026-10-17T16:24:00+09:00';
      lines(card)[0]['when'] = {'time': '2026-10-17T16:21:00+09:00'};
      lines(card)[1]['when'] = {'time': '2026-10-17T16:23:00+09:00'};
      lines(card)[3]['when'] = {'time': '2026-10-17T16:24:00+09:00'};
      peer.cards = [card];
      final app = controller(peer);
      await openApp(tester, app);
      await tapText(tester, '손님 오기 전 거실 청소');
      final earlierClock = find.textContaining('토 16:21');
      final fallback = find.text('파티(16:24) 3분 전, 토 16:22에 바로 실행 예정');
      expect(earlierClock, findsNothing);
      expect(fallback, findsOneWidget);
      expect(find.text('파티(16:24) 1분 전, 16:23 예정'), findsNothing);

      final updated = phase(card, 4);
      lines(updated).first['state'] = 'done';
      peer.cards = [updated];
      peer.rationales['ep_9031']!['executions'] = [
        {
          'task_id': 't_clean#1',
          'device': 'cleaner_01',
          'status': 'completed',
          'substrate': 'virtual',
          'at': '2026-10-17T16:25:03+09:00',
        },
        {
          'task_id': 't_clean#1',
          'device': 'cleaner_01',
          'status': 'running',
          'substrate': 'virtual',
          'at': '2026-10-17T16:23:09+09:00',
        },
      ];
      await app.sync();
      await tester.pumpAndSettle();
      expect(earlierClock, findsNothing);
      expect(fallback, findsNothing);
      expect(find.text('파티(16:24) 3분 전, 토 16:23에 바로 실행'), findsOneWidget);
    },
  );

  testWidgets(
    'two card lines open two distinct details through the order story',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      await openApp(tester, controller(peer), size: const Size(390, 760));

      await tapText(tester, '손님 오시면 공주 분위기 화면·조명');
      expect(
        find.widgetWithText(AppBar, '손님 오시면 공주 분위기 화면·조명'),
        findsOneWidget,
      );
      expect(find.text('손님이 오면 공주 테마 분위기'), findsOneWidget);
      expect(find.text('파티 중 오븐을 바로 쓰기'), findsNothing);
      expect(find.text('이 판단에서 나왔어요'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(AppBar, '토요일 생일 준비'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      await tapText(tester, '오븐 컵케이크 설정 대기');
      expect(find.widgetWithText(AppBar, '오븐 컵케이크 설정 대기'), findsOneWidget);
      expect(find.text('파티 중 오븐을 바로 쓰기'), findsOneWidget);
      expect(find.text('손님이 오면 공주 테마 분위기'), findsNothing);
      expect(find.text('이 판단에서 나왔어요'), findsOneWidget);
    },
  );

  testWidgets(
    'line WHY links the re-enabled mood task to its basis and current state',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      final card = fixture('card.v1.json');
      final mood = lines(card)[2]
        ..['task_id'] = 't_mood#7'
        ..['state'] = 'held';
      final lineText = mood['text'] as String;
      // The stored oven task says it completed, but has no live line here.
      lines(card).removeLast();
      peer.cards = [card];
      final app = controller(peer);
      await openApp(tester, app, size: const Size(390, 760));
      await tapText(tester, lineText);

      expect(find.text('이 일').hitTestable(), findsOneWidget);
      expect(find.widgetWithText(AppBar, lineText), findsOneWidget);
      expect(find.text('손님이 오면 공주 테마 분위기').hitTestable(), findsOneWidget);
      expect(find.text('손님이 오면').hitTestable(), findsWidgets);
      expect(find.text('파티 중 오븐을 바로 쓰기'), findsNothing);
      expect(find.text('완료'), findsNothing);
      expect(find.text('직접 바꾸셨어요'), findsNothing);
      expect(find.text('시간을 기다리는 중'), findsOneWidget);
      expect(find.text('이 할 일의 자세한 근거를 볼 수 없어요.'), findsNothing);
      final running = phase(card, 1);
      lines(running)[2]['state'] = 'running';
      peer.cards = [running];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('진행 중').hitTestable(), findsOneWidget);
      expect(find.text('직접 바꾸셨어요'), findsNothing);
      expect(find.text('이 판단에서 나왔어요'), findsOneWidget);
    },
  );

  testWidgets(
    'WHY shows a missing slot without exposing an unresolved calendar ID',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      final rationale = peer.rationales['ep_9031']!;
      final evidence = rationale['evidence'] as Map<String, dynamic>;
      evidence['calendar'] = [];
      final intent = (rationale['intents'] as List).single as Map;
      (intent['situation'] as Map)['guests'] = null;

      await openApp(tester, controller(peer));
      await tapText(tester, '손님 오기 전 거실 청소');
      expect(find.text('토 12:30 예정'), findsOneWidget);
      expect(find.textContaining('분 전 →'), findsNothing);
      expect(find.textContaining('끝난 걸 확인하면 풀어요'), findsNothing);
      await tapText(tester, '전체 근거 보기');
      expect(find.text('연결된 일정'), findsNothing);
      expect(find.text('c1'), findsNothing);
      expect(find.text('손님'), findsOneWidget);
      expect(find.text('알 수 없어요'), findsOneWidget);
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
      expect(find.text('보관 방법'), findsOneWidget);
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
      expect(find.text('주문에서 읽은 것 · 6개'), findsOneWidget);
      expect(find.text('상황 칸과 근거'), findsNothing);
      expect(find.text('그래서 할 일'), findsNothing);
      expect(find.text('연결된 일정'), findsNothing);
      expect(find.text('평소와 달랐던 물건'), findsNothing);
      expect(find.text('준비할 일 없는 주문 11건'), findsOneWidget);
      expect(find.text('4개 중 4개가 같아요 · 계란 · 딸기 · 우유 · 휴지'), findsOneWidget);
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
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.final.json')];
      final store = TestStore();
      await openApp(tester, controller(peer, store: store));
      expect(find.textContaining('미리보기'), findsNothing);
      expect(find.text('예시 주문으로 공유'), findsNothing);
      expect(find.text('계약 테스트 서버'), findsNothing);
      expect(find.byType(Card), findsOneWidget);
      await settings(tester);
      expect(find.text('계약 테스트 서버'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      peer.unavailable = true;
      await openApp(tester, controller(peer, store: store, fixture: false));
      expect(find.byType(Card), findsNothing);
      await settings(tester);
      expect(find.text('실제 서버 프로필'), findsOneWidget);
      expect(find.text('계약 테스트 서버'), findsNothing);
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
        final menu = find.byTooltip('준비 더보기 · ${active['text']}');
        final off = find.bySemanticsLabel(RegExp(r'손님 오기 전 거실 청소 끄기'));
        expect(
          tester.getSemantics(menu).getSemanticsData().tooltip,
          startsWith('준비 더보기 · 토요일 생일'),
        );
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
        await tester.ensureVisible(find.byType(Switch));
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
        await openStopConfirmation(tester);
        await tester.tap(find.text('중지'));
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
