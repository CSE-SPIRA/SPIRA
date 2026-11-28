import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart' show SynchronousFuture;
// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:spira_app/api/app_api.dart';
import 'package:spira_app/app_controller.dart';
import 'package:spira_app/contracts.dart' as wire;
import 'package:spira_app/design_tokens.g.dart';
import 'package:spira_app/features/brand.dart';
import 'package:spira_app/features/status_badge.dart';
import 'package:spira_app/household_types.dart';
import 'package:spira_app/main.dart';
import 'package:spira_app/features/labels.dart';
import 'package:spira_app/platform/android_bridge.dart';
import 'package:spira_app/platform/google_calendar.dart';
import 'package:spira_app/platform/gallery.dart';

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
  bool failSetupWrite = false;

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async {
    if (failSetupWrite && key.startsWith('spira.setup.')) {
      throw StateError('Storage unavailable');
    }
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
  static const initialServerTime = '2026-11-05T01:02:03+09:00';
  final episodes = <String, Map<String, dynamic>>{};
  final requests = <http.Request>[];
  final reactions = <(String, Map<String, dynamic>)>[];
  final profiles = <Object?>[];
  final calendars = <wire.Calendar>[];
  List<Map<String, dynamic>> cards = [];
  final rationales = {
    'ep_9031': fixture('rationale.json')
      ..['observations'] = []
      ..['executions'] = [],
    'ep_9150': fixture('rationale.json', episode: 'ep_9150'),
  };
  Map<String, dynamic> get birthday => episodes['ep_9031']!;
  bool invalidProfile = false;
  bool unavailable = false;
  bool failCalendar = false;
  int rationaleReads = 0;
  int pollCount = 0;
  String serverTime = initialServerTime;
  int? episodeListError;
  int? episodePageSize;
  Future<http.Response> Function(http.Request)? reaction;
  Future<http.Response> Function(http.Request)? upload;
  Future<http.Response> Function()? readRationale;
  List<Map<String, dynamic>>? openCards;

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
    if (request.url.origin != 'https://test.invalid') {
      throw StateError('Unexpected App API origin ${request.url.origin}');
    }
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
      profiles.add(jsonDecode(request.body));
      if (invalidProfile) {
        return response({
          'code': 'household_types_invalid',
          'message': '가구 인원과 구성의 조합을 확인해 주세요',
        }, 422);
      }
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
    if (method == 'GET' && path == '$householdPath/cards') {
      pollCount++;
      return response({
        'cards': request.url.queryParameters.containsKey('since')
            ? cards
            : openCards ?? cards,
        'server_time': serverTime,
      });
    }
    if (method == 'GET' && path == '$householdPath/episodes') {
      if (episodeListError case final status?) {
        return response({
          'code': 'validation_error',
          'message': 'failed',
        }, status);
      }
      final before = request.url.queryParameters['before'];
      final eligible = episodes.values.where((episode) {
        return before == null ||
            DateTime.parse(episode['shared_at'] as String)
                .isBefore(DateTime.parse(before));
      }).toList();
      final page = eligible.take(episodePageSize ?? eligible.length).toList();
      return response({
        'episodes': [
          for (final episode in page)
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
        'next_before': page.length < eligible.length
            ? page.last['shared_at']
            : null,
      });
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

Map<String, dynamic> heldEpisode() => fixture('episode.json')
  ..['episode_id'] = 'ep_9120'
  ..['status'] = 'held'
  ..['shared_at'] = '2026-10-16T21:00:00+09:00'
  ..['card_ids'] = ['nc_340'];

Map<String, dynamic> phase(Map<String, dynamic> card, int minute) => {
  ...card,
  'updated_at': '2026-10-17T14:${minute.toString().padLeft(2, '0')}:00+09:00',
  'notify': false,
};

AppController controller(
  Peer peer, {
  TestPlatform? platform,
  TestStore? store,
  GalleryPicker? gallery,
  Future<void> Function()? disconnect,
  CalendarReader? calendar,
  bool setup = false,
  bool fixture = true,
  bool firstRun = false,
  bool hasDelegationRoute = false,
}) => AppController(
  api: peer.client(),
  platform: platform ?? TestPlatform(),
  store: store ?? TestStore(),
  fixture: fixture,
  firstRun: firstRun,
  hasDelegationRoute: hasDelegationRoute,
  configuredHousehold: setup ? null : 'h_042',
  pickImages: gallery,
  disconnectCalendar: disconnect,
  readCalendar: calendar,
);

class TestAppAssets extends CachingAssetBundle {
  @override
  Future<ByteData> load(String key) =>
      key == 'assets/sample-home.json' || key == HouseholdTypeCatalog.asset
      ? SynchronousFuture(ByteData.sublistView(File(key).readAsBytesSync()))
      : rootBundle.load(key);
}

Future<void> openApp(
  WidgetTester tester,
  AppController app, {
  Size size = const Size(850, 1700),
  bool reducedMotion = true,
  bool devTools = false,
}) async {
  tester.binding.platformDispatcher.accessibilityFeaturesTestValue =
      FakeAccessibilityFeatures(reduceMotion: reducedMotion);
  addTearDown(
    tester.binding.platformDispatcher.clearAccessibilityFeaturesTestValue,
  );
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetDevicePixelRatio);
  addTearDown(tester.view.resetPhysicalSize);
  await tester.pumpWidget(
    DefaultAssetBundle(
      bundle: TestAppAssets(),
      child: SpiraApp(app: app, devTools: devTools),
    ),
  );
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
const delegationHint = '기기별로 맡길지는 집 허브가 연결되면 고를 수 있어요.';

Future<void> tapTab(WidgetTester tester, String label) async {
  await tester.tap(
    find.descendant(
      of: find.byKey(const ValueKey('home-tabs')),
      matching: find.text(label),
    ),
  );
  await tester.pumpAndSettle();
}

void expectTopBar(WidgetTester tester) {
  final topBar = find.byType(SpiraTopBar);
  final mark = find.descendant(of: topBar, matching: find.byType(SpiraMark));
  final material = find.descendant(of: topBar, matching: find.byType(Material));
  expect(topBar, findsOneWidget);
  expect(mark, findsOneWidget);
  expect(find.text('SPIRA'), findsOneWidget);
  expect(tester.getSize(topBar).height, kToolbarHeight);
  expect(tester.getCenter(mark), tester.getCenter(topBar));
  expect(tester.widget<Material>(material.first).color, DesignTokens.paper);
}

Future<void> resumeApp(WidgetTester tester) async {
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
  await tester.pump();
  tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  await tester.idle();
  await tester.pumpAndSettle();
}

Future<void> connectCalendar(WidgetTester tester, AppController app) async {
  await openApp(tester, app);
  await tapText(tester, '시작하기');
  await tapText(tester, 'Google로 계속');
  await tapText(tester, '2인');
  await tapText(tester, '우리 집 만들기');
  await tapText(tester, '다음');
  await tapText(tester, '저장');
}

Future<void> openStopConfirmation(WidgetTester tester) =>
    tapText(tester, '멈추기');

Finder get mainCards => find.descendant(
  of: find.byKey(const ValueKey('main-preparations')),
  matching: find.byType(Card),
);

Finder get stopButton => find.widgetWithText(OutlinedButton, '멈추기');

void main() {
  testWidgets('AP-AT-16 an order shared elsewhere shows the staged wait', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'reading'
        ..['items'] = []
        ..['item_count'] = 0
        ..['item_tasks'] = []
        ..['card_ids'] = []);
    peer.rationales.remove('ep_9031');
    await openApp(tester, controller(peer, fixture: false));
    expect(find.byKey(const ValueKey('order-progress')), findsOneWidget);
    expect(find.text('주문을 읽고 있어요'), findsOneWidget);
  });

  testWidgets('AP-AT-14/16 stored stages reach a card with no episode list', (
    tester,
  ) async {
    final image = File('assets/example-order.png').readAsBytesSync();
    final peer = Peer()
      ..episodeListError = 404
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'received'
        ..['items'] = []
        ..['item_count'] = 0
        ..['item_tasks'] = []
        ..['card_ids'] = [])
      ..upload = (_) async =>
          Peer.response({'episode_id': 'ep_9031', 'status': 'received'}, 202);
    final rationale = peer.rationales.remove('ep_9031')!;
    final intents = rationale['intents'] as List;
    final intent = (intents.first as Map)['intent_text'] as String;
    const items = '품목 2개를 읽었어요';
    const context = '일정과 지난 주문을 살펴봤어요';
    final pulse = find.byKey(const ValueKey('order-progress-pulse'));
    int listReads() => peer.requests
        .where((r) => r.url.path == '/v1/households/h_042/episodes')
        .length;
    final store = TestStore();
    final app = controller(
      peer,
      store: store,
      gallery: () async => [GalleryImage(image, png: true)],
      fixture: false,
    );
    await openApp(
      tester,
      app,
      reducedMotion: false,
      size: const Size(390, 844),
    );
    await tester.tap(find.text('주문 분석하기'));
    await tester.pump();
    expect(find.text('받았어요'), findsOneWidget);
    expect(find.byType(Image), findsOneWidget);
    expect(pulse, findsOneWidget);
    final opacity = tester.widget<FadeTransition>(pulse).opacity.value;
    await tester.pump(const Duration(milliseconds: 600));
    expect(tester.widget<FadeTransition>(pulse).opacity.value, isNot(opacity));

    tester.binding.platformDispatcher.accessibilityFeaturesTestValue =
        const FakeAccessibilityFeatures(reduceMotion: true);
    await tester.pumpAndSettle();
    expect(pulse, findsNothing);
    final before = peer.pollCount;
    await tester.pump(const Duration(seconds: 12));
    expect(peer.pollCount, greaterThan(before));
    expect(find.text(items), findsNothing);
    expect(find.text(context), findsNothing);
    expect(find.text(intent), findsNothing);
    expect(listReads(), 1);

    peer.birthday
      ..['status'] = 'reading'
      ..['items'] = (fixture('episode.json')['items'] as List).take(2).toList()
      ..['item_count'] = 2;
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text(items), findsOneWidget);
    expect(find.text('설향 딸기 500g (냉장)'), findsOneWidget);
    expect(find.text(context), findsNothing);
    expect(find.text(intent), findsNothing);
    expect(find.byIcon(Icons.check), findsNWidgets(2));

    peer.rationales['ep_9031'] = rationale..['intents'] = [];
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text(context), findsOneWidget);
    expect(find.text(intent), findsNothing);
    expect(find.byIcon(Icons.check), findsNWidgets(3));

    rationale['intents'] = intents;
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text(intent), findsOneWidget);
    expect(find.byIcon(Icons.check), findsNWidgets(4));
    expect(
      tester.getTopLeft(find.text(items)).dy,
      lessThan(tester.getTopLeft(find.text(context)).dy),
    );
    expect(
      tester.getTopLeft(find.text(context)).dy,
      lessThan(tester.getTopLeft(find.text(intent)).dy),
    );
    expect(mainCards, findsNothing);
    expect(listReads(), 1);

    peer.birthday
      ..['status'] = 'notified'
      ..['card_ids'] = ['nc_331'];
    peer.cards = [fixture('card.v1.json')];
    await app.sync();
    await tester.pumpAndSettle();
    expect(orderScan, findsOneWidget);
    expect(find.byKey(const ValueKey('order-progress')), findsNothing);
    expect(mainCards, findsOneWidget);
    expect(app.refreshError, isNull);

    await tester.pump(const Duration(seconds: 60));
    await app.sync();
    expect(listReads(), 2);
    peer.birthday
      ..['status'] = 'closed'
      ..['card_ids'] = [];
    peer.cards = [fixture('card.final.json')];
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('nc_331')), findsNothing);
    expect(find.byKey(const ValueKey('memory-nc_331')), findsOneWidget);
    expect(app.memoryDates.single.startsAt, peer.cards.single['starts_at']);
    await tester.pumpWidget(const SizedBox.shrink());
    peer.cards = [];
    final reopened = controller(peer, store: store, fixture: false);
    await openApp(tester, reopened);
    expect(reopened.memoryDates.single.cardId, 'nc_331');
    expect(find.byKey(const ValueKey('memory-nc_331')), findsOneWidget);
    await tapTab(tester, '캘린더');
    await tester.tap(find.byTooltip('이전 달'));
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('memory-dot-ep_9031')), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('2026-10-17')));
    await tester.pumpAndSettle();
    await tapText(tester, '준비 기억');
    expect(find.text('설향 딸기 500g (냉장)'), findsOneWidget);
    expect(find.text('아직 판정 전'), findsOneWidget);
  });

  for (final status in [404, 405, 501]) {
    testWidgets('AP-AT-14 opens existing cards when the list returns $status', (
      tester,
    ) async {
      final peer = Peer()
        ..episodeListError = status
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified')
        ..cards = [fixture('card.v1.json')];
      final app = controller(peer, fixture: false);
      await openApp(tester, app);
      expect(mainCards, findsOneWidget);
      expect(app.canControl, isTrue);
      expect(app.refreshError, isNull);
    });
  }

  for (final reaction in ['line_off', 'line_on', 'stop']) {
    testWidgets('AP-AT-15 restores the control after $reaction returns 404', (
      tester,
    ) async {
      final card = fixture('card.v1.json');
      card['lines'] = [
        {
          ...lines(card).first,
          if (reaction == 'line_on') ...{'state': 'off', 'checked': false},
        },
      ];
      final receipt = Completer<http.Response>();
      final peer = Peer()
        ..episodeListError = 404
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified')
        ..cards = [card]
        ..reaction = (_) => receipt.future;
      final app = controller(peer, fixture: false);
      await openApp(tester, app);
      final toggle = find.byType(Switch);
      if (reaction == 'stop') {
        await openStopConfirmation(tester);
        await tapText(tester, '멈추기', index: 1);
      } else {
        await tester.tap(toggle);
        await tester.pumpAndSettle();
      }
      expect(find.text('요청함'), findsOneWidget);
      expect(peer.reactions.single.$2['reaction'], reaction);
      receipt.complete(Peer.response({'detail': 'Not Found'}, 404));
      await tester.pumpAndSettle();
      expect(find.text('아직 이 서버에서는 끌 수 없어요'), findsOneWidget);
      expect(find.text('요청함'), findsNothing);
      if (reaction == 'stop') {
        expect(tester.widget<OutlinedButton>(stopButton).onPressed, isNotNull);
      } else {
        expect(tester.widget<Switch>(toggle).onChanged, isNotNull);
        expect(tester.widget<Switch>(toggle).value, reaction != 'line_on');
      }
      await tester.pump(const Duration(seconds: 12));
      expect(peer.reactions, hasLength(1));
      expect(find.text('아직 이 서버에서는 끌 수 없어요'), findsOneWidget);
    });
  }

  testWidgets('AP-AT-17 guidance uses the first item of each type', (
    tester,
  ) async {
    final order = fixture('episode.json')
      ..['status'] = 'judged'
      ..['card_ids'] = [];
    final items = order['items'] as List;
    items.insert(1, {
      ...items.first as Map,
      'name': '딸기 추가',
      'item_id': 'it_10',
    });
    final tasks = (order['item_tasks'] as List).cast<Map<String, dynamic>>();
    tasks.first['state'] = 'scheduled';
    final peer = Peer()..episodes['ep_9031'] = order;
    final app = controller(peer);
    await openApp(tester, app);
    final heading = find.text('냉장고에 보관 안내');
    expect(heading, findsOneWidget);
    expect(find.text(tasks.first['text'] as String), findsOneWidget);
    expect(find.text('택배가 들어오면 보여 드려요'), findsOneWidget);
    expect(find.text('냉장고에 띄웠어요'), findsOneWidget);
    expect(
      tester.getTopLeft(heading).dy,
      greaterThan(tester.getTopLeft(find.text('설향 딸기 500g (냉장)')).dy),
    );
    expect(
      tester.getTopLeft(heading).dy,
      lessThan(tester.getTopLeft(find.text('딸기 추가')).dy),
    );

    tasks.first['state'] = 'done';
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text('택배가 들어오면 보여 드려요'), findsNothing);
    expect(find.text('냉장고에 띄웠어요'), findsNWidgets(2));
    expect(heading, findsOneWidget);
  });
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
      await tapText(tester, '시작하기');
      await tapText(tester, 'Google로 계속');
      await tapText(tester, '2인');
      await tapText(tester, '우리 집 만들기');
      expect(
        jsonDecode(
          peer.requests
              .singleWhere((r) => r.url.path.endsWith('/calendar'))
              .body,
        ),
        calendar,
      );
      await tapText(tester, '다음');
      await tapText(tester, '저장');
    },
  );

  testWidgets('Setup Google distinguishes OAuth, calendar and save errors', (
    tester,
  ) async {
    final peer = Peer();
    final store = TestStore();
    Object? failure;
    final app = controller(
      peer,
      setup: true,
      store: store,
      calendar: ({required interactive}) async {
        expect(interactive, isTrue);
        if (failure case final error?) throw error;
        return wire.Calendar(events: []);
      },
    );
    await openApp(tester, app);
    await tapText(tester, '시작하기');
    expect(find.text('Google 계정으로 시작'), findsOneWidget);
    expect(find.text('앞으로 14일의 일정을 참고해 준비할게요.'), findsOneWidget);
    const oauthMessage = 'Google에 연결하지 못했어요. 건너뛰고 나중에 우리 집에서 연결할 수 있어요.';
    const syncMessage = '캘린더를 동기화하지 못했어요.';
    const saveMessage = '설정을 저장하지 못했어요. 다시 시도해 주세요.';
    final messages = [oauthMessage, syncMessage, saveMessage];
    for (final (error, message) in [
      (
        const GoogleSignInException(
          code: GoogleSignInExceptionCode.interrupted,
        ),
        oauthMessage,
      ),
      (
        const GoogleSignInException(code: GoogleSignInExceptionCode.canceled),
        null,
      ),
      (
        GoogleAuthorizationException(StateError('Authorization failed')),
        oauthMessage,
      ),
      (StateError('Calendar read failed'), syncMessage),
      (null, saveMessage),
    ]) {
      failure = error;
      store.failSetupWrite = error == null;
      await tapText(tester, 'Google로 계속');
      expect(app.step, SetupStep.calendar);
      expect(app.calendarConnected, isFalse);
      for (final candidate in messages) {
        expect(
          find.text(candidate),
          candidate == message ? findsOneWidget : findsNothing,
        );
      }
    }
    expect(peer.requests, isEmpty);
    store.failSetupWrite = false;
    await tapText(tester, '건너뛰기');
    expect(app.step, SetupStep.household);
    expect(app.calendarConnected, isFalse);
  });

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
    await resumeApp(tester);

    expect(reads, 4);
    expect(peer.calendars, hasLength(1));
  });

  testWidgets('APP-03 foreground sends a title edit', (tester) async {
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

    expect(peer.calendars, hasLength(2));
    expect(peer.calendars.last.toJson(), calendar.toJson());
  });

  testWidgets(
    'APP-03 foreground sends an empty replacement and retries quietly',
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
      calendar = wire.Calendar(events: []);
      failRead = true;
      await resumeApp(tester);
      expect(peer.calendars, hasLength(1));

      failRead = false;
      peer.failCalendar = true;
      await resumeApp(tester);
      expect(peer.calendars, hasLength(2));

      peer.failCalendar = false;
      await resumeApp(tester);
      expect(peer.calendars, hasLength(3));
      expect(peer.calendars.last.events, isEmpty);
      await resumeApp(tester);
      expect(peer.calendars, hasLength(3));
      expect(platform.deliveries, isEmpty);
      expect(find.byType(SnackBar), findsNothing);
    },
  );

  testWidgets('APP-03 skipped fixture calendar resends samples after restart', (
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
    await tapText(tester, '시작하기');
    await tapText(tester, '건너뛰기');
    await tapText(tester, '2인');
    await tapText(tester, '우리 집 만들기');
    await tapText(tester, '다음');
    await tapText(tester, '저장');
    await tester.pumpWidget(const SizedBox.shrink());
    await openApp(
      tester,
      controller(peer, setup: true, store: store, calendar: read),
    );
    await resumeApp(tester);
    await tapTab(tester, '우리 집');

    expect(reads, 0);
    expect(peer.calendars, hasLength(2));
    expect(peer.calendars.first.toJson(), peer.calendars.last.toJson());
    expect(peer.calendars.last.events.first.title, '생일 파티');
    expect(find.text('연결 안 됨'), findsOneWidget);
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
      expect(stopButton, findsNWidgets(2));
      expect(find.text('승인'), findsNothing);
      expect(find.text('4개 중 0개 끝남'), findsOneWidget);
      expect(find.text('손님 도착을 기다리는 중'), findsOneWidget);
      expect(
        find.text(fixture('card.v1.json')['text'] as String),
        findsOneWidget,
      );
      expect(find.textContaining('· 파티 전'), findsNWidgets(2));
      expect(find.textContaining('· 파티 시작에 맞춰'), findsOneWidget);
      expect(find.text('손님이 오면'), findsNWidgets(2));
      expect(find.text('예정됨'), findsWidgets);
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
        ('user_changed', '사람이 바꿈'),
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
      expect(find.text('사용자가 조명을 바꿔 현재 상태를 유지했어요'), findsOneWidget);
      expect(find.text('원래대로 돌렸어요'), findsOneWidget);
      expect(find.text('복원 대상 없음'), findsNothing);
      expect(find.textContaining('종료 조건'), findsNothing);

      final failedRestore = fixture('card.final.json')
        ..['updated_at'] = '2026-10-17T17:50:17+09:00';
      lines(failedRestore)[1]['end_state'] = 'restore_failed';
      peer.cards = [failedRestore];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('되돌리지 못했어요'), findsOneWidget);
      expect(find.text('원래대로 돌렸어요'), findsNothing);

      peer.unavailable = true;
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('서버에 연결할 수 없어요 · 마지막 확인 01:02'), findsOneWidget);
      expect(tester.widget<OutlinedButton>(stopButton.first).onPressed, isNull);
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
        final row = find.byKey(ValueKey(('nc_331', line['task_id'] as String)));
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
      peer.episodes['ep_9120'] = heldEpisode();
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
      await tester.idle();
      expect(peer.pollCount, 1);
      await tester.pump(const Duration(seconds: 1));
      await tester.idle();
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
      await tester.idle();
      expect(peer.pollCount, 3);
      await tester.pump(const Duration(milliseconds: 1));
      await tester.idle();
      expect(peer.pollCount, 4);

      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      await tester.pump(const Duration(seconds: 3));
      await tester.idle();
      expect(peer.pollCount, 5);
      expect(app.accepted, isEmpty);
      await tester.pump(const Duration(seconds: 3));
      await tester.idle();
      expect(peer.pollCount, 6);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump(const Duration(seconds: 29));
      await tester.idle();
      expect(peer.pollCount, 6);
      await tester.pump(const Duration(seconds: 1));
      await tester.idle();
      expect(peer.pollCount, 7);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      await tester.idle();
      expect(peer.pollCount, 8);
      peer.cards = [fixture('card.final.json')];
      peer.birthday['status'] = 'closed';
      await tester.pump(const Duration(seconds: 3));
      await tester.idle();
      expect(peer.pollCount, 9);
      await tester.pump(const Duration(seconds: 29));
      await tester.idle();
      expect(peer.pollCount, 9);
      await tester.pump(const Duration(seconds: 1));
      await tester.idle();
      expect(peer.pollCount, 10);
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
    await switched;
    expect(peer.reactions.single.$2, {
      'reaction': 'line_off',
      'task_id': line.taskId,
    });
    expect(app.lineStarted(card, line), isTrue);
    final off = app.cards['nc_331']!;
    await app.switchLine(off, off.lines.first);
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
    await app.switchLine(card, card.lines[1]);
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
      final guidance = find.text('설향 딸기 500g (냉장)');
      expect(guidance, findsNothing);
      await tester.tap(orderScan);
      await tester.pumpAndSettle();
      expect(guidance, findsOneWidget);
      expect(
        find.ancestor(of: guidance, matching: find.byType(Card)),
        findsNothing,
      );

      final receipt = Completer<http.Response>();
      peer.reaction = (_) => receipt.future;
      await openStopConfirmation(tester);
      expect(find.text('이 준비를 멈출까요?'), findsOneWidget);
      expect(peer.reactions, isEmpty);
      await tapText(tester, '취소');
      expect(peer.reactions, isEmpty);
      await openStopConfirmation(tester);
      await tester.tap(find.text('멈추기').last);
      await tester.pump();
      await tester.pumpAndSettle();
      expect(find.text('요청함'), findsOneWidget);
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
      expect(find.text('요청함'), findsOneWidget);
      expect(find.text('이 준비가 중지됐어요.'), findsNothing);
      peer.cards = [stopped];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('요청함'), findsOneWidget);
      final restored = phase(stopped, 3);
      lines(restored)[0]['end_state'] = 'restored';
      lines(restored)[2]['end_state'] = 'kept_user_change';
      peer.cards = [restored];
      await app.sync();
      await tester.pumpAndSettle();
      expect(find.text('이 준비가 중지됐어요.'), findsOneWidget);
      expect(find.text('원래대로 돌렸어요'), findsOneWidget);
      expect(find.text('바꾸신 그대로 두었어요'), findsOneWidget);
      expect(find.text('사용자가 시작한 조리를 유지했어요.'), findsOneWidget);
      expect(guidance, findsOneWidget);
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

  testWidgets(
    'a closed order whose card was never seen is dated by its share time',
    (tester) async {
      final episode = fixture('episode.json')..['status'] = 'closed';
      final peer = Peer()
        ..cards = []
        ..episodes['ep_9031'] = episode;
      final app = controller(peer, store: TestStore(), fixture: false);
      await openApp(tester, app);
      expect(app.memoryDates.single.episodeId, 'ep_9031');
      expect(app.memoryDates.single.startsAt, episode['shared_at']);
    },
  );

  for (final rewound in [false, true]) {
    testWidgets(
      'empty Server lists clear the restored closed preparation (clock rewound: $rewound)',
      (tester) async {
        final peer = Peer()
          ..cards = [fixture('card.v1.json')]
          ..episodes['ep_9031'] = (fixture('episode.json')
            ..['status'] = 'notified');
        final store = TestStore();
        final first = controller(peer, store: store, fixture: false);
        await openApp(tester, first);
        peer.birthday['status'] = 'closed';
        peer.cards = [fixture('card.final.json')];
        await first.sync();
        await tester.pumpAndSettle();
        final card = find.byKey(const ValueKey('nc_331'));
        expect(card, findsNothing);
        expect(first.memoryDates.single.episodeId, 'ep_9031');

        await tester.pumpWidget(const SizedBox.shrink());
        peer.episodes.clear();
        peer.cards = [];
        peer.episodeListError = 422;
        if (rewound) peer.serverTime = '2026-11-04T01:02:03+09:00';
        final relaunched = controller(peer, store: store, fixture: false);
        await openApp(tester, relaunched);
        const error = '새로 불러오지 못했어요. 다시 시도해 주세요.';
        expect(find.text(error), findsOneWidget);
        expect(card, findsNothing);
        expect(relaunched.lastServerCheck, Peer.initialServerTime);

        peer.episodeListError = null;
        await tapText(tester, '다시 시도');
        expect(relaunched.lastServerCheck, peer.serverTime);
        expect(relaunched.episodes, isEmpty);
        expect(relaunched.cards, isEmpty);
        expect(relaunched.memoryDates, isEmpty);
        expect(card, findsNothing);
        expect(find.text('지난 준비 1개'), findsNothing);
        expect(find.text(error), findsNothing);
        expect(find.text('다시 시도'), findsNothing);
        expect(
          find.text('주문 화면을 캡처하고 공유 메뉴에서 SPIRA를 선택해 주세요.'),
          findsOneWidget,
        );
        final saved = store.saved.whereType<Map<String, dynamic>>().last;
        expect(saved['episodes'], isEmpty);
        expect(saved['cards'], isEmpty);
      },
    );
  }

  testWidgets(
    'the episode list reconciles cached cards beyond the first page',
    (tester) async {
      final peer = Peer()
        ..cards = [fixture('card.v1.json')]
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified');
      final app = controller(peer);
      await openApp(tester, app);
      expect(app.cards, contains('nc_331'));

      final newer = fixture('episode.json', episode: 'ep_9150')
        ..['shared_at'] = '2026-11-04T01:00:00+09:00';
      final older = peer.birthday;
      peer.episodes
        ..clear()
        ..addAll({'ep_9150': newer, 'ep_9031': older});
      peer.episodePageSize = 1;
      peer.cards = [];
      await app.sync();
      expect(app.episodes, contains('ep_9031'));
      expect(app.cards, contains('nc_331'));

      older['card_ids'] = [];
      await app.sync();
      expect(app.episodes, contains('ep_9031'));
      expect(app.cards, isEmpty);
      expect(app.refreshError, isNull);
    },
  );

  testWidgets('a rewound cursor reloads cards for surviving orders', (
    tester,
  ) async {
    final peer = Peer()
      ..cards = [fixture('card.final.json')]
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'notified');
    final app = controller(peer);
    await openApp(tester, app);
    final previous = app.cards['nc_331']!;

    final current = fixture('card.final.json')
      ..['updated_at'] = '2026-10-17T17:50:00+09:00';
    expect(
      DateTime.parse(current['updated_at'] as String)
          .isBefore(DateTime.parse(previous.updatedAt)),
      isTrue,
    );
    peer.cards = [];
    peer.openCards = [current];
    peer.serverTime = '2026-11-04T01:02:03+09:00';
    await app.sync();
    expect(app.lastServerCheck, peer.serverTime);
    expect(app.cards['nc_331']?.updatedAt, current['updated_at']);
    expect(app.refreshError, isNull);

    await app.sync();
    final lastPoll = peer.requests.lastWhere(
      (r) => r.url.path.endsWith('/cards'),
    );
    expect(lastPoll.url.queryParameters['since'], peer.serverTime);
    expect(app.cards['nc_331']?.updatedAt, current['updated_at']);
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

    expect(find.text('10월 17일 (토) 00:05'), findsOneWidget);
    expect(find.textContaining('· 파티 시작에 맞춰'), findsOneWidget);
    expect(find.text('택배가 들어오면'), findsOneWidget);
    expect(find.text('손님이 오면'), findsOneWidget);
    expect(find.textContaining('· 파티 시작 후'), findsOneWidget);
    expect(find.textContaining('00:05'), findsNWidgets(2));
  });

  testWidgets('empty Android preparation explains how to share an order', (
    tester,
  ) async {
    await openApp(tester, controller(Peer()), size: const Size(412, 1350));

    expect(find.text('쇼핑 앱에서 주문 화면을 공유하면, 그 주문에 맞춰 집을 준비해요.'), findsOneWidget);
    expect(find.text('주문 화면을 캡처하고 공유 메뉴에서 SPIRA를 선택해 주세요.'), findsOneWidget);
    expect(find.textContaining('예시 주문으로 공유'), findsNothing);
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
      AppController open() =>
          controller(peer, store: store, platform: platform);
      const offline = '서버에 연결할 수 없어요 · 마지막 확인 01:02';
      const queued = '연결되면 공유한 주문을 보낼게요.';
      await openApp(tester, open(), size: const Size(412, 1350));
      await tapTab(tester, '우리 집');
      expect(find.text('예시 집'), findsOneWidget);

      peer.unavailable = true;
      await tester.pumpWidget(const SizedBox.shrink());
      await openApp(tester, open(), size: const Size(412, 1350));
      expect(find.text(offline).hitTestable(), findsOneWidget);
      expect(find.byType(AlertDialog), findsNothing);
      expect(find.byType(Card), findsOneWidget);
      expect(find.text('완료'), findsWidgets);
      await tapTab(tester, '우리 집');
      expect(find.text(offline).hitTestable(), findsOneWidget);
      expect(find.text('예시 집'), findsOneWidget);
      expect(find.textContaining('집 기기 목록을 받지 못'), findsNothing);
      await tapTab(tester, '메인');

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
    'APP-AT-14 labels both configured peers and keeps their cached observations separate',
    (tester) async {
      final peer = Peer();
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.final.json')];
      final store = TestStore();
      await openApp(tester, controller(peer, store: store), devTools: true);
      expect(find.text('미리보기 · 계약 테스트 서버'), findsOneWidget);
      expect(find.text('예시 주문으로 공유'), findsNothing);
      expect(find.byType(Card), findsOneWidget);
      await tapTab(tester, '우리 집');
      expect(find.text('미리보기 · 계약 테스트 서버'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      peer.unavailable = true;
      await openApp(
        tester,
        controller(peer, store: store, fixture: false),
        devTools: true,
      );
      expect(find.byType(Card), findsNothing);
      expect(find.text('미리보기 · 계약 테스트 서버'), findsNothing);
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
    'default fixture preview uses one top bar without developer tools',
    (tester) async {
      final app = AppController(
        api: Peer().client(),
        platform: null,
        store: TestStore(),
        fixture: true,
        browserPreview: true,
        configuredHousehold: 'h_042',
      );
      await openApp(tester, app, size: const Size(390, 844));
      for (final (tab, title) in [
        ('메인', '주문'),
        ('캘린더', '2026년 10월'),
        ('우리 집', '기기'),
      ]) {
        await tapTab(tester, tab);
        expectTopBar(tester);
        expect(find.text(fixturePreviewLabel), findsNothing);
        expect(find.text('예시 주문으로 공유'), findsNothing);
        expect(find.byTooltip('서버 접속 토큰 입력'), findsNothing);
        expect(find.text('서버 연결에 필요한 접속 토큰 입력'), findsNothing);
        expect(
          tester.getTopLeft(find.text(title)).dy,
          greaterThan(tester.getBottomLeft(find.byType(SpiraTopBar)).dy),
        );
      }
    },
  );

  for (final setup in [false, true]) {
    testWidgets('default token entry recovers from 401 (setup: $setup)', (
      tester,
    ) async {
      final peer = Peer();
      final client = MockClient((request) async {
        if (request.headers['authorization'] != 'Bearer test-app-token') {
          return Peer.response({
            'code': 'unauthorized',
            'message': 'token',
          }, 401);
        }
        return peer.handle(request);
      });
      final app = AppController(
        api: AppApi(Uri.parse('https://test.invalid'), client: client),
        platform: null,
        store: TestStore(),
        fixture: true,
        configuredHousehold: setup ? null : 'h_042',
      );
      await openApp(tester, app);
      if (setup) {
        await tapText(tester, '시작하기');
        await tapText(tester, '건너뛰기');
        await tapText(tester, '2인');
        await tapText(tester, '우리 집 만들기');
      }
      const prompt = '서버 연결에 필요한 접속 토큰 입력';
      expect(app.needsToken, isTrue);
      expect(find.byTooltip('서버 접속 토큰 입력'), findsNothing);
      expect(find.text(prompt).hitTestable(), findsOneWidget);
      await tapText(tester, prompt);
      await tester.enterText(find.byType(TextField), 'test-app-token');
      await tapText(tester, '연결');
      expect(app.needsToken, isFalse);
      expect(find.text(prompt), findsNothing);
      if (setup) {
        await tapText(tester, '우리 집 만들기');
        expect(find.text('집 허브 연결 코드'), findsOneWidget);
      } else {
        expect(app.refreshed, isTrue);
      }
    });
  }

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
        final off = find.bySemanticsLabel(RegExp(r'손님 오기 전 거실 청소 끄기'));
        await tester.scrollUntilVisible(stopButton, 200);
        expect(stopButton, findsOneWidget);
        await tester.ensureVisible(find.byType(Switch));
        await tester.pumpAndSettle();
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
        await tester.tap(find.byType(Switch));
        await tester.pumpAndSettle();
        final on = find.bySemanticsLabel(RegExp('손님 오기 전 거실 청소 켜기'));
        expect(on, findsOneWidget);
        await tester.tap(find.byType(Switch));
        await tester.pumpAndSettle();
        expect(off, findsOneWidget);
        final receipt = Completer<http.Response>();
        peer.reaction = (_) => receipt.future;
        await openStopConfirmation(tester);
        await tester.tap(find.text('멈추기').last);
        await tester.pump();
        await tester.ensureVisible(find.text('요청함'));
        await tester.pumpAndSettle();
        expect(find.bySemanticsLabel('요청함'), findsOneWidget);
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
        await tapTab(tester, '우리 집');
        expect(find.bySemanticsLabel('자동 준비 일시정지'), findsNothing);
        expect(tester.takeException(), isNull);
      } finally {
        semantics.dispose();
      }
    },
  );
  testWidgets('fixture sample preserves its ordered upload identity on retry', (
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
    final app = AppController(
      api: peer.client()..token = 'test-app-token',
      platform: null,
      store: TestStore(),
      fixture: true,
      browserPreview: true,
      configuredHousehold: 'h_042',
    );
    await openApp(tester, app, size: const Size(390, 844), devTools: true);
    final share = find.text('예시 주문으로 공유');
    expect(share.hitTestable(), findsOneWidget);
    expect(find.text(fixturePreviewLabel), findsOneWidget);
    expectTopBar(tester);
    expect(
      find.descendant(
        of: find.byType(SpiraTopBar),
        matching: find.text(fixturePreviewLabel),
      ),
      findsNothing,
    );
    await tapText(tester, '예시 주문으로 공유');
    expect(find.text('예시 주문을 보내지 못했어요. 다시 시도해 주세요.'), findsOneWidget);
    expect(mainCards, findsNothing);

    await tapText(tester, '예시 주문으로 공유');
    expect(orderScan, findsOneWidget);
    expect(
      find.descendant(of: orderScan, matching: find.byType(Image)),
      findsOneWidget,
    );
    expect(find.text('품목 9개를 읽었어요'), findsNothing);
    await tester.tap(orderScan);
    await tester.pumpAndSettle();
    expect(find.text('받았어요'), findsOneWidget);
    expect(find.text('품목 9개를 읽었어요'), findsOneWidget);
    await tester.scrollUntilVisible(find.byKey(const ValueKey('nc_331')), 180);
    expect(mainCards, findsNWidgets(2));
    await tapTab(tester, '우리 집');
    expectTopBar(tester);
    final tokenKey = find.byTooltip('서버 접속 토큰 입력');
    expect(
      find.ancestor(of: tokenKey, matching: find.byType(IconButton)),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byType(SpiraTopBar),
        matching: find.text(fixturePreviewLabel),
      ),
      findsOneWidget,
    );
    expect(find.text('예시 집'), findsOneWidget);
    expect(find.text('우리 집 접속 키 입력'), findsNothing);
  });

  testWidgets('Setup keeps chips in place at 170% text and blocks submission', (
    tester,
  ) async {
    final peer = Peer();
    tester.platformDispatcher.textScaleFactorTestValue = 1.7;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    await openApp(
      tester,
      controller(peer, setup: true),
      size: const Size(390, 844),
    );
    await tapText(tester, '시작하기');
    await tapText(tester, '건너뛰기');

    final size = find.widgetWithText(FilterChip, '3~4인');
    final largerSize = find.widgetWithText(FilterChip, '5인 이상');
    final nextGroup = find.text('구성');
    final originalRects = [
      for (final target in [size, largerSize, nextGroup])
        tester.getRect(target),
    ];
    await tester.tap(size);
    await tester.pumpAndSettle();
    expect([
      for (final target in [size, largerSize, nextGroup])
        tester.getRect(target),
    ], originalRects);
    expect(tester.widget<FilterChip>(size).selected, isTrue);

    await tapText(tester, '맞벌이');
    final reason = find.text('맞벌이는 부부·커플과 함께 골라 주세요.');
    final create = find.widgetWithText(FilledButton, '우리 집 만들기');
    await tester.ensureVisible(create);
    await tester.pumpAndSettle();
    expect(reason, findsOneWidget);
    expect(
      tester.getBottomLeft(reason).dy,
      lessThan(tester.getTopLeft(create).dy),
    );
    expect(tester.widget<FilledButton>(create).onPressed, isNull);
    await tester.tap(create);
    expect(peer.requests, isEmpty);

    await tapText(tester, '부부·커플');
    expect(reason, findsNothing);
    expect(tester.widget<FilledButton>(create).onPressed, isNotNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('AP-AT-1 onboarding validates types and copies its Server code', (
    tester,
  ) async {
    final peer = Peer()..invalidProfile = true;
    final store = TestStore();
    final clipboard = <String>[];
    final code = fixture('household.created.json')['hub_api_key'] as String;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          clipboard.add((call.arguments as Map)['text'] as String);
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );

    await openApp(tester, controller(peer, setup: true, store: store));
    expect(find.byKey(const ValueKey('home-tabs')), findsNothing);
    await tapText(tester, '시작하기');
    expect(find.text('Google 캘린더'), findsOneWidget);
    await tapText(tester, '건너뛰기');
    await tapText(tester, '2인');
    await tapText(tester, '부부·커플');
    await tapText(tester, '우리 집 만들기');
    expect(find.text('가구 인원과 구성의 조합을 확인해 주세요'), findsOneWidget);
    expect(find.text(code), findsNothing);
    expect(peer.profiles.single, {
      'household_types': ['2인', '부부·커플'],
    });

    peer.invalidProfile = false;
    await tapText(tester, '우리 집 만들기');
    expect(find.text(code), findsOneWidget);
    expect(find.text('이 코드를 집 허브에 입력하세요'), findsOneWidget);
    await tapText(tester, '연결 코드 복사');
    expect(clipboard, [code]);
    final create = peer.requests.where((r) => r.url.path == '/v1/households');
    expect(create, hasLength(1));
    expect(jsonDecode(create.single.body), {
      'household_types': ['2인', '부부·커플'],
    });

    await tester.pumpWidget(const SizedBox.shrink());
    await openApp(tester, controller(peer, setup: true, store: store));
    expect(find.text(code), findsOneWidget);
    await tapText(tester, '다음');
    expect(find.text('예시 집'), findsOneWidget);
    await tapText(tester, '저장');
    expect(store.values.values, isNot(contains(code)));
    expect(find.text('메인'), findsOneWidget);
    expect(find.text('캘린더'), findsOneWidget);
    expect(find.text('우리 집'), findsOneWidget);
    expect(find.text('설정'), findsNothing);
    expect(
      peer.requests.every(
        (request) =>
            request.url.origin == 'https://test.invalid' &&
            request.url.path.startsWith('/v1/households') &&
            !request.url.path.contains('/devices'),
      ),
      isTrue,
    );
  });

  for (final gallery in [false, true]) {
    testWidgets(
      'AP-AT-2 ${gallery ? 'gallery' : 'Android share'} reaches M1–M4a',
      (tester) async {
        final peer = Peer();
        final platform = TestPlatform();
        final image = File('assets/example-order.png').readAsBytesSync();
        final count = gallery ? 1 : 2;
        final app = controller(
          peer,
          platform: platform,
          gallery: () async => [GalleryImage(image, png: true)],
        );
        peer.upload = (request) async {
          final multipart = utf8.decode(
            request.bodyBytes,
            allowMalformed: true,
          );
          expect(
            RegExp('name="images"').allMatches(multipart),
            hasLength(count),
          );
          expect(
            RegExp('name="source_id"').allMatches(multipart),
            hasLength(1),
          );
          expect(multipart, contains(gallery ? 'gallery_' : 'test-share'));
          return Peer.response({
            'episode_id': 'ep_9031',
            'status': 'received',
          }, 202);
        };

        await openApp(tester, app);
        if (gallery) {
          await tapText(tester, '주문 분석하기');
        } else {
          platform.orders.add(
            SharedOrder('test-share', Peer.initialServerTime, [
              TestImage(preview: image),
              TestImage(preview: image),
            ]),
          );
          platform.changes.add(null);
          await tester.pumpAndSettle();
        }
        expect(find.text('받았어요'), findsOneWidget);
        // One large photo, plus a row of all photos when there are several.
        expect(find.byType(Image), findsNWidgets(count > 1 ? count + 1 : 1));
        expect(mainCards, findsNothing);

        peer.episodes['ep_9031'] = fixture('episode.json')
          ..['status'] = 'reading'
          ..['item_count'] = 0
          ..['items'] = []
          ..['item_tasks'] = []
          ..['card_ids'] = [];
        await app.sync();
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('order-progress')), findsOneWidget);
        expect(find.text('설향 딸기 500g (냉장)'), findsNothing);

        peer.episodes['ep_9031'] = fixture('episode.json')
          ..['status'] = 'judged'
          ..['card_ids'] = []
          ..['masked_count'] = 2
          ..['item_count'] = 11;
        await app.sync();
        await tester.pumpAndSettle();
        expect(find.byKey(const ValueKey('order-progress')), findsNothing);
        expect(find.text('품목 11개를 읽었어요'), findsOneWidget);
        expect(find.text('설향 딸기 500g (냉장)'), findsOneWidget);
        expect(find.text('2개'), findsOneWidget);
        expect(find.text('가린 품목 2개'), findsOneWidget);
        expect(find.text('냉장고에 띄웠어요'), findsNWidgets(2));
        expect(mainCards, findsNothing);
        expect(find.text('읽은 품목 수정'), findsNothing);

        peer.birthday['status'] = 'read_failed';
        await app.sync();
        await tester.pumpAndSettle();
        expect(find.text('읽지 못했어요. 다시 보내 주세요'), findsOneWidget);
        expect(find.text('설향 딸기 500g (냉장)'), findsNothing);
      },
    );
  }

  testWidgets('gallery groups images under one source and reuses it on retry', (
    tester,
  ) async {
    final peer = Peer();
    final image = File('assets/example-order.png').readAsBytesSync();
    var selections = 0;
    final app = controller(
      peer,
      gallery: () async {
        selections++;
        return List.filled(
          selections == 1 ? 4 : 3,
          GalleryImage(image, png: true),
        );
      },
    );
    final sources = <String>[];
    peer.upload = (request) async {
      final body = utf8.decode(request.bodyBytes, allowMalformed: true);
      sources.add(
        RegExp('name="source_id"\r\n\r\n([^\r]+)').firstMatch(body)!.group(1)!,
      );
      expect(RegExp('name="images"').allMatches(body), hasLength(3));
      if (sources.length == 1) throw const SocketException('response lost');
      return Peer.response({
        'episode_id': 'ep_9031',
        'status': 'received',
      }, 200);
    };
    await openApp(tester, app);
    await tapText(tester, '주문 분석하기');
    expect(find.text('사진을 1~3장 골라 주세요.'), findsOneWidget);
    expect(sources, isEmpty);

    await tapText(tester, '주문 분석하기');
    expect(find.text('다시 보내기'), findsOneWidget);
    expect(find.text('받았어요'), findsNothing);
    await tapText(tester, '다시 보내기');
    expect(sources, hasLength(2));
    expect(sources.toSet(), hasLength(1));
    // One large photo and a row of the three.
    expect(find.byType(Image), findsNWidgets(4));
    expect(find.text('받았어요'), findsOneWidget);

    await tapText(tester, '주문 분석하기');
    expect(sources, hasLength(3));
    expect(sources.toSet(), hasLength(2));
  });

  testWidgets(
    'Main guides a first order and opens its screenshots separately',
    (tester) async {
      final first = File('assets/example-order.png').readAsBytesSync();
      final second = Uint8List.fromList(first);
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
      final app = controller(
        peer,
        gallery: () async => [
          GalleryImage(first, png: true),
          GalleryImage(second, png: true),
        ],
      );
      await openApp(tester, app, size: const Size(390, 844));
      expect(find.byKey(const ValueKey('upload-box')), findsOneWidget);
      expect(find.text('최근 이 집의 기억'), findsOneWidget);
      const steps = [
        '1. 온라인 주문 화면 캡처를 올려요',
        '2. SPIRA가 그날에 맞는 준비를 정해요',
        '3. 그날 집이 알아서 맞춰 움직여요',
      ];
      for (final step in steps) {
        expect(find.text(step), findsOneWidget);
      }
      expect(find.text('아직 쌓인 기억이 없어요.'), findsNothing);

      await tapText(tester, '주문 분석하기');
      expect(find.text(steps.first), findsNothing);
      final thumbnail = find.byTooltip('주문 사진 크게 보기');
      expect(
        tester.getSize(thumbnail),
        const Size.square(DesignTokens.space48),
      );
      await tester.tap(thumbnail);
      await tester.pumpAndSettle();
      final viewer = find.byType(InteractiveViewer);
      final screenshot = find.descendant(
        of: viewer,
        matching: find.byType(Image),
      );
      expect(tester.getSize(find.byType(Dialog)), const Size(390, 844));
      expect(
        (tester.widget<Image>(screenshot).image as MemoryImage).bytes,
        same(first),
      );
      await tester.tap(find.byTooltip('다음 사진'));
      await tester.pumpAndSettle();
      expect(
        (tester.widget<Image>(screenshot).image as MemoryImage).bytes,
        same(second),
      );
      await tester.tap(find.byTooltip('이전 사진'));
      await tester.pumpAndSettle();
      expect(
        (tester.widget<Image>(screenshot).image as MemoryImage).bytes,
        same(first),
      );
      await tester.tap(find.byTooltip('닫기'));
      await tester.pumpAndSettle();
      expect(viewer, findsNothing);
      expect(find.text('품목 9개를 읽었어요'), findsNothing);
      await tester.tap(orderScan);
      await tester.pumpAndSettle();
      expect(find.text('품목 9개를 읽었어요'), findsOneWidget);
    },
  );

  testWidgets('M4b displays the held card Server text verbatim', (
    tester,
  ) async {
    const id = 'ep_9120';
    final held = fixture('card.held.json', episode: id);
    final peer = Peer()
      ..episodes[id] = heldEpisode()
      ..cards = [held];
    await openApp(tester, controller(peer));
    expect(mainCards, findsOneWidget);
    expect(find.text(held['text'] as String), findsOneWidget);
    expect(find.text('일정이 잡히기를 기다리고 있어요.'), findsNothing);
  });

  testWidgets('AP-AT-5 running line off waits for a confirming card', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'notified');
    final running = phase(fixture('card.v1.json'), 1);
    running['lines'] = [lines(running).first..['state'] = 'running'];
    peer.cards = [running];
    final app = controller(peer);
    await openApp(tester, app);
    final toggle = find.byType(Switch);
    expect(tester.widget<Switch>(toggle).value, isTrue);
    expect(find.text('진행 중'), findsOneWidget);
    expect(find.bySemanticsLabel(RegExp('거실 청소 켜기')), findsNothing);

    final receipt = Completer<http.Response>();
    peer.reaction = (_) => receipt.future;
    await tester.tap(toggle);
    await tester.pumpAndSettle();
    expect(find.text('요청함'), findsOneWidget);
    expect(peer.reactions.single.$1, 'nc_331');
    expect(peer.reactions.single.$2, {
      'reaction': 'line_off',
      'task_id': 't_clean#1',
    });
    final off = phase(running, 2)
      ..['lines'] = [
        {...lines(running).first, 'state': 'off', 'checked': false},
      ];
    receipt.complete(Peer.response(off));
    await tester.pumpAndSettle();
    expect(find.text('요청함'), findsOneWidget);
    expect(find.text('꺼짐'), findsNothing);
    expect(tester.widget<Switch>(toggle).onChanged, isNull);

    peer.cards = [off];
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text('요청함'), findsNothing);
    expect(find.text('꺼짐'), findsOneWidget);
    expect(toggle, findsNothing);
    expect(stopButton, findsOneWidget);
  });

  testWidgets(
    'AP-AT-5 pre-start off/on tracks a replacement ID and hides on after 409',
    (tester) async {
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified');
      final scheduled = phase(fixture('card.v1.json'), 1);
      scheduled['lines'] = [lines(scheduled).first];
      peer.cards = [scheduled];
      final app = controller(peer);
      await openApp(tester, app);
      final toggle = find.byType(Switch);
      final switchStyle = tester.widget<Switch>(toggle);
      expect(
        switchStyle.trackColor?.resolve({WidgetState.selected}),
        DesignTokens.greenSoft,
      );
      expect(
        switchStyle.thumbColor?.resolve({WidgetState.selected}),
        DesignTokens.greenDeep,
      );
      expect(tester.getSize(toggle).height, greaterThanOrEqualTo(48));
      Future<void> tapToggle() async {
        await tester.tap(toggle);
        await tester.pumpAndSettle();
      }

      final off = phase(scheduled, 2)
        ..['lines'] = [
          {...lines(scheduled).first, 'state': 'off', 'checked': false},
        ];
      peer.reaction = (_) async {
        peer.cards = [off];
        return Peer.response(off);
      };
      await tapToggle();
      expect(tester.widget<Switch>(toggle).value, isFalse);
      expect(stopButton, findsOneWidget);

      final replacement = phase(scheduled, 3)
        ..['lines'] = [
          {...lines(scheduled).first, 'task_id': 't_clean#7'},
        ];
      peer.reaction = (_) async => Peer.response(replacement);
      await tapToggle();
      expect(find.text('요청함'), findsOneWidget);
      expect(peer.reactions.last.$2, {
        'reaction': 'line_on',
        'task_id': 't_clean#1',
      });
      peer.cards = [replacement];
      await app.sync();
      await tester.pumpAndSettle();
      expect(tester.widget<Switch>(toggle).value, isTrue);
      expect(find.text('요청함'), findsNothing);

      final secondOff = phase(off, 4)
        ..['lines'] = [
          {...lines(off).first, 'task_id': 't_clean#7'},
        ];
      peer.reaction = (_) async {
        peer.cards = [secondOff];
        return Peer.response(secondOff);
      };
      await tapToggle();
      expect(tester.widget<Switch>(toggle).value, isFalse);
      peer.reaction = (_) async => Peer.response({
        'code': 'line_started',
        'message': 'Already started',
      }, 409);
      await tapToggle();
      expect(peer.reactions.last.$2, {
        'reaction': 'line_on',
        'task_id': 't_clean#7',
      });
      expect(find.text('이미 시작된 항목은 바꿀 수 없어요.'), findsOneWidget);
      expect(find.text('요청함'), findsNothing);
      expect(toggle, findsNothing);
    },
  );

  testWidgets(
    'AP-AT-7 and AP-AT-8 memory stays through close and acknowledgment keeps the dot',
    (tester) async {
      final store = TestStore();
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified');
      // UTC date differs from the Seoul start day and the order share day.
      peer.cards = [
        fixture('card.v1.json')..['starts_at'] = '2026-10-16T16:15:00Z',
      ];
      final app = controller(peer, store: store);
      await openApp(tester, app);
      final card = find.byKey(const ValueKey('nc_331'));
      final memory = find.byKey(const ValueKey('memory-nc_331'));
      final heldId = 'ep_9120';
      final rationale = fixture('rationale.json');
      final intent =
          (rationale['intents'] as List)
                  .cast<Map<String, dynamic>>()
                  .first['intent_text']
              as String;
      final evidence = rationale['evidence'] as Map;
      evidence['kb_examples'] = [
        {
          'case_id': 'syn_demo_0001',
          'items': ['Hidden KB ingredient'],
          'intent_id': 'kid_birthday_party',
          'intent_text': 'Hidden KB example',
          'overlap': {
            'k': 1,
            'n': 2,
            'items': ['Hidden KB overlap'],
          },
        },
      ];
      evidence['unusual_items'] = {
        'status': 'list',
        'items': [
          {'item': 'Hidden unusual item', 'why': 'Hidden item reason'},
        ],
      };
      rationale['unbundled'] = ['Hidden unbundled item'];

      expect(card, findsOneWidget);
      expect(memory, findsNothing);
      peer.rationales['ep_9031'] = rationale;
      await app.sync();
      await tester.idle();
      await tester.pumpAndSettle();
      expect(card, findsNothing);
      expect(memory, findsOneWidget);
      expect(find.text('이렇게 기억할게요'), findsOneWidget);
      expect(find.text(intent), findsOneWidget);
      expect(find.text('예상대로 쓰였어요'), findsOneWidget);
      expect(find.text('끔'), findsOneWidget);
      expect(find.text('바꿈'), findsOneWidget);
      expect(find.text('그대로'), findsNWidgets(2));
      expect(find.textContaining('Hidden '), findsNothing);

      peer.episodes[heldId] = heldEpisode();
      peer.cards = [fixture('card.held.json', episode: heldId)];
      await app.sync();
      peer.birthday
        ..['status'] = 'closed'
        ..['masked_count'] = 1;
      peer.episodes[heldId]!['status'] = 'closed';
      peer.cards = [];
      Iterable<http.Request> birthdayRationaleReads() => peer.requests.where(
        (r) => r.url.path == '/v1/episodes/ep_9031/rationale',
      );
      final rationaleReadsBeforeClose = birthdayRationaleReads().length;
      await app.sync();
      await tester.pumpAndSettle();
      expect(memory, findsOneWidget);
      expect(card, findsNothing);
      expect(find.text('확인'), findsOneWidget);
      expect(app.cards, isEmpty);
      expect(birthdayRationaleReads(), hasLength(rationaleReadsBeforeClose + 1));
      expect(store.values.values.join(), isNot(contains('Hidden KB example')));

      await tester.pumpWidget(const SizedBox.shrink());
      final cuts = controller(peer, store: store);
      await openApp(tester, cuts);
      expect(memory, findsOneWidget);
      await tapText(tester, '확인');
      expect(memory, findsNothing);
      await cuts.sync();
      await tester.pumpAndSettle();
      expect(memory, findsNothing);
      await tapTab(tester, '캘린더');
      final dot = find.byKey(const ValueKey('memory-dot-ep_9031'));
      final date = find.byKey(const ValueKey('2026-10-17'));
      expect(find.descendant(of: date, matching: dot), findsOneWidget);
      expect(
        find.descendant(
          of: find.byKey(const ValueKey('2026-10-15')),
          matching: dot,
        ),
        findsNothing,
      );
      expect(find.byKey(ValueKey('memory-dot-$heldId')), findsNothing);
      expect(
        find.text(rationale['none_reason'] as String? ?? '근거'),
        findsNothing,
      );
      expect(
        peer.requests
            .where((r) => r.url.path.endsWith('/cards'))
            .every(
              (r) => r.url.queryParameters['since'] != '1970-01-01T00:00:00Z',
            ),
        isTrue,
      );

      await tester.tap(date);
      await tester.pumpAndSettle();
      final requestCount = peer.requests.length;
      final memoryEntry = find.byKey(const ValueKey('calendar-memory-ep_9031'));
      await tester.ensureVisible(memoryEntry);
      await tester.tap(memoryEntry);
      await tester.pumpAndSettle();
      expect(peer.requests.skip(requestCount).map((r) => r.url.path).toSet(), {
        '/v1/episodes/ep_9031',
        '/v1/episodes/ep_9031/rationale',
      });
      expect(find.text(intent), findsOneWidget);
      expect(find.text('예상대로 쓰였어요'), findsOneWidget);
      expect(find.text('설향 딸기 500g (냉장)'), findsOneWidget);
      expect(find.text('가린 품목 1개'), findsOneWidget);
      expect(find.text('10월 17일 (토) 01:15'), findsOneWidget);
      expect(find.textContaining('Hidden '), findsNothing);
      expect(find.textContaining('다음 준비에'), findsNothing);
    },
  );

  for (final (verdict, label) in [
    ('stopped', '멈추셨어요'),
    ('unconfirmed', '확인하지 못했어요'),
  ]) {
    testWidgets('M9 uses the Server $verdict verdict', (tester) async {
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified')
        ..cards = [fixture('card.v1.json')];
      final rationale = fixture('rationale.json');
      (rationale['observations'] as List)
              .cast<Map<String, dynamic>>()
              .single['verdict'] =
          verdict;
      peer.rationales['ep_9031'] = rationale;
      await openApp(tester, controller(peer));
      expect(find.text(label), findsOneWidget);
      expect(find.byKey(const ValueKey('memory-nc_331')), findsOneWidget);
    });
  }

  testWidgets(
    'AP-AT-11 Google events replace the synced samples until disconnect',
    (tester) async {
      final today = seoulDay(DateTime.now().toIso8601String());
      final eventTime = today.add(const Duration(hours: 10));
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified')
        ..cards = [fixture('card.v1.json')];
      final event = wire.EventElement(
        id: 'upcoming',
        title: 'Google 일정 제목',
        start: eventTime.toIso8601String(),
        end: eventTime.add(const Duration(hours: 1)).toIso8601String(),
      );
      var disconnected = false;
      final app = controller(
        peer,
        calendar: ({required interactive}) async =>
            wire.Calendar(events: [event]),
        disconnect: () async {
          disconnected = true;
        },
      );
      await openApp(tester, app);
      await tapTab(tester, '우리 집');
      await tapText(tester, '2인');
      final selected = tester.widget<FilterChip>(
        find.widgetWithText(FilterChip, '2인'),
      );
      expect(selected.showCheckmark, isFalse);
      expect(selected.selectedColor, DesignTokens.greenSoft);
      expect(selected.side!.color, DesignTokens.greenLine);
      expect(selected.labelStyle!.color, DesignTokens.greenDeep);
      await tapText(tester, '가구 유형 저장');
      expect(peer.profiles.single, {
        'household_types': ['2인'],
      });
      expect(find.text('예시 집'), findsOneWidget);
      final samples = peer.calendars.single;
      expect(samples.events.first.title, '생일 파티');
      await tapText(tester, 'Google 연결');
      expect(peer.calendars, hasLength(2));
      expect(peer.calendars.last.events.single.title, event.title);
      await tapTab(tester, '캘린더');
      final bar = find.byKey(const ValueKey('event-upcoming'));
      expect(find.text('예시 일정'), findsNothing);
      expect(
        find.descendant(of: bar, matching: find.textContaining(event.title)),
        findsOneWidget,
      );
      expect(find.text(peer.cards.single['text'] as String), findsNothing);
      expect(find.byKey(const ValueKey('memory-dot-ep_9031')), findsNothing);

      await tapTab(tester, '우리 집');
      await tapText(tester, 'Google 연결 해제');
      expect(disconnected, isTrue);
      expect(peer.calendars, hasLength(3));
      expect(peer.calendars.last.toJson(), samples.toJson());
      await tapTab(tester, '캘린더');
      expect(find.text('예시 일정'), findsOneWidget);
      expect(bar, findsNothing);
    },
  );
  testWidgets('AP-AT-10 navigates the month grid and selects an event day', (
    tester,
  ) async {
    final peer = Peer();
    await openApp(tester, controller(peer), size: const Size(390, 844));
    await tapTab(tester, '캘린더');
    final birthday = find.byKey(const ValueKey('2026-10-17'));
    final bar = find.byKey(const ValueKey('event-c1'));
    const label = '생일 파티 14:00–18:00';
    expect(find.descendant(of: birthday, matching: bar), findsOneWidget);
    expect(
      find.descendant(of: bar, matching: find.text('생일 파티')),
      findsOneWidget,
    );
    expect(find.byTooltip(label), findsOneWidget);
    expect(peer.calendars.single.events.first.title, '생일 파티');
    expect(peer.calendars.single.events.first.end, '2026-10-17T18:00:00+09:00');

    await tester.tap(find.byTooltip('다음 달'));
    await tester.pumpAndSettle();
    expect(find.text('2026년 11월'), findsOneWidget);
    expect(bar, findsNothing);
    await tester.tap(find.byTooltip('이전 달'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('2026-10-20')));
    await tester.pumpAndSettle();
    expect(find.text('10월 20일'), findsOneWidget);
    expect(find.text('예방접종 09:30–10:00'), findsOneWidget);
    await tapText(tester, '오늘');
    final date = seoulDay(DateTime.now().toIso8601String());
    expect(
      find.descendant(
        of: find.byKey(ValueKey(date.toIso8601String().substring(0, 10))),
        matching: find.byKey(const ValueKey('calendar-today')),
      ),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('Calendar fits a single chip and its event count at 170% text', (
    tester,
  ) async {
    tester.platformDispatcher.textScaleFactorTestValue = 1.7;
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final today = seoulDay(DateTime.now().toIso8601String());
    final events = [
      for (final (index, title) in ['예방접종', '가족 저녁', '병원 예약'].indexed)
        wire.EventElement(
          id: 'event$index',
          title: title,
          start: today.add(Duration(hours: index)).toIso8601String(),
          end: today.add(Duration(hours: index + 1)).toIso8601String(),
        ),
    ];
    final app = controller(
      Peer(),
      calendar: ({required interactive}) async => wire.Calendar(events: events),
    );
    await openApp(tester, app, size: const Size(390, 844));
    await app.connectGoogle();
    await tester.pumpAndSettle();
    await tapTab(tester, '캘린더');
    final day = find.byKey(ValueKey(today.toIso8601String().substring(0, 10)));
    await tester.ensureVisible(day);
    await tester.pumpAndSettle();
    final chip = find.byKey(const ValueKey('event-event0'));
    final label = find.descendant(of: chip, matching: find.byType(RichText));
    final count = find.descendant(of: day, matching: find.text('+2'));
    final richText = tester.widget<RichText>(label);
    expect(richText.text.toPlainText(), '예방접종');
    expect(richText.text.style?.fontSize, DesignTokens.size12);
    expect(richText.textScaler.scale(10), 17);
    expect(richText.maxLines, 1);
    expect(richText.overflow, TextOverflow.ellipsis);
    final painter = TextPainter(
      text: richText.text,
      textDirection: TextDirection.ltr,
      textScaler: richText.textScaler,
      maxLines: 1,
      ellipsis: '…',
    )..layout(maxWidth: tester.getSize(label).width);
    addTearDown(painter.dispose);
    expect(painter.didExceedMaxLines, isTrue);
    expect(find.byKey(const ValueKey('event-event1')), findsNothing);
    expect(find.byKey(const ValueKey('event-event2')), findsNothing);
    expect(
      tester.getTopLeft(count).dy,
      greaterThanOrEqualTo(tester.getBottomLeft(chip).dy),
    );
    expect(
      tester.getBottomLeft(count).dy,
      lessThanOrEqualTo(tester.getBottomLeft(day).dy),
    );

    await tester.tap(day);
    await tester.pumpAndSettle();
    expect(find.text('예방접종 09:00–10:00'), findsOneWidget);
    expect(find.text('가족 저녁 10:00–11:00'), findsOneWidget);
    expect(find.text('병원 예약 11:00–12:00'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('AP-AT-18 sends one sample anchored to the Server clock', (
    tester,
  ) async {
    final peer = Peer()..serverTime = '2026-11-30T23:53:05+09:00';
    final store = TestStore();
    final app = controller(peer, store: store, fixture: false);
    await openApp(tester, app);
    await tapTab(tester, '캘린더');
    expect(find.text('예시 일정'), findsOneWidget);
    expect(find.text('2026년 12월'), findsOneWidget);
    expect(find.text('생일 파티 00:13–01:13'), findsOneWidget);
    final sample = peer.calendars.single;
    final birthday = sample.events.first;
    final start = DateTime.parse(birthday.start);
    expect(start, DateTime.parse('2026-12-01T00:13:05+09:00'));
    expect(
      DateTime.parse(birthday.end).difference(start),
      const Duration(hours: 1),
    );
    expect(sample.events.map((event) => event.title), [
      '생일 파티',
      '예방접종',
      '가족 저녁',
    ]);
    expect(sample.events.skip(1).map((event) => seoulDay(event.start).day), [
      4,
      7,
    ]);
    expect(app.displayCalendar.toJson(), sample.toJson());
    await app.sync();
    await resumeApp(tester);
    expect(peer.calendars, hasLength(1));

    await tester.pumpWidget(const SizedBox.shrink());
    peer.serverTime = '2026-12-01T00:03:05+09:00'; // Exactly ten minutes.
    final reopened = controller(peer, store: store, fixture: false);
    await openApp(tester, reopened);
    expect(reopened.displayCalendar.toJson(), sample.toJson());
    expect(peer.calendars, hasLength(1));
  });

  testWidgets(
    'AP-AT-18 renews near or after the birthday only without a card',
    (tester) async {
      final peer = Peer()..serverTime = '2026-11-26T14:00:00+09:00';
      final app = controller(peer, fixture: false);
      await openApp(tester, app);
      expect(peer.calendars, hasLength(1));

      peer.serverTime = '2026-11-26T14:11:00+09:00';
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      await app.sync();
      expect(app.activeCards, hasLength(1));
      expect(peer.calendars, hasLength(1));

      peer.birthday
        ..['status'] = 'closed'
        ..['card_ids'] = [];
      peer.cards = [];
      await app.sync();
      expect(app.activeCards, isEmpty);
      expect(peer.calendars, hasLength(2));
      expect(
        DateTime.parse(peer.calendars.last.events.first.start),
        DateTime.parse('2026-11-26T14:31:00+09:00'),
      );
      for (final time in ['14:31:00', '15:30:59']) {
        peer.serverTime = '2026-11-26T$time+09:00';
        await app.sync();
        expect(peer.calendars, hasLength(2));
      }

      peer.serverTime = '2026-11-26T15:31:00+09:00';
      peer.episodes['ep_9031'] = fixture('episode.json')
        ..['status'] = 'notified';
      peer.cards = [fixture('card.v1.json')];
      await app.sync();
      expect(app.activeCards, hasLength(1));
      expect(peer.calendars, hasLength(2));

      peer.birthday
        ..['status'] = 'closed'
        ..['card_ids'] = [];
      peer.cards = [];
      await app.sync();
      expect(peer.calendars, hasLength(3));
      expect(
        DateTime.parse(peer.calendars.last.events.first.start),
        DateTime.parse('2026-11-26T15:51:00+09:00'),
      );
      expect(app.displayCalendar.toJson(), peer.calendars.last.toJson());
    },
  );

  testWidgets(
    'AP-AT-18 an empty connected Google calendar suppresses samples',
    (tester) async {
      final peer = Peer();
      final store = TestStore();
      final empty = wire.Calendar(events: []);
      final app = controller(
        peer,
        store: store,
        fixture: false,
        setup: true,
        calendar: ({required interactive}) async => empty,
      );
      await connectCalendar(tester, app);
      expect(app.calendarConnected, isTrue);
      expect(peer.calendars.single.events, isEmpty);
      peer.serverTime = '2026-12-03T14:00:00+09:00';
      await app.sync();
      expect(peer.calendars, hasLength(1));

      await tester.pumpWidget(const SizedBox.shrink());
      final reopened = controller(
        peer,
        store: store,
        fixture: false,
        setup: true,
        calendar: ({required interactive}) async => empty,
      );
      await openApp(tester, reopened);
      await tapTab(tester, '캘린더');
      expect(reopened.calendarConnected, isTrue);
      expect(find.text('예시 일정'), findsNothing);
      expect(peer.calendars, hasLength(1));
      expect(peer.calendars.single.events, isEmpty);
      await reopened.disconnectGoogle();
      await tester.pumpAndSettle();
      expect(peer.calendars, hasLength(2));
      expect(find.text('예시 일정'), findsOneWidget);
      expect(
        DateTime.parse(peer.calendars.last.events.first.start),
        DateTime.parse('2026-12-03T14:20:00+09:00'),
      );
    },
  );

  testWidgets('AP-AT-18 syncs the sample before a share that opens the App', (
    tester,
  ) async {
    final peer = Peer()
      ..episodeListError = 404
      ..upload = (_) async => Peer.response({
        'episode_id': 'ep_9031',
        'status': 'received',
      }, 202);
    final platform = TestPlatform()
      ..orders.add(
        SharedOrder('cold-share', Peer.initialServerTime, [TestImage()]),
      );
    await openApp(tester, controller(peer, fixture: false, platform: platform));
    final writes = peer.requests.where((r) => r.method != 'GET');
    expect(writes.map((r) => r.url.path), [
      '/v1/households/h_042/calendar',
      '/v1/orders',
    ]);
    expect(find.text('받았어요'), findsOneWidget);
  });

  testWidgets(
    'AP-AT-19 opens the configured Server household or forces setup',
    (tester) async {
      final peer = Peer()..episodeListError = 404;
      final store = TestStore();
      final app = controller(peer, store: store, fixture: false);
      await openApp(tester, app);
      expect(app.household, 'h_042');
      expect(app.step, SetupStep.ready);
      expect(find.byKey(const ValueKey('home-tabs')), findsOneWidget);
      expect(find.text('Google로 계속'), findsNothing);
      expect(peer.requests.map((r) => r.url.path), [
        '/v1/households/h_042/cards',
        '/v1/households/h_042/episodes',
        '/v1/households/h_042/calendar',
      ]);
      expect(
        peer.requests.every((r) => r.url.origin == 'https://test.invalid'),
        isTrue,
      );

      await tester.pumpWidget(const SizedBox.shrink());
      final setup = controller(
        peer,
        store: store,
        fixture: false,
        firstRun: true,
      );
      await openApp(tester, setup);
      expect(setup.household, isNull);
      expect(setup.step, SetupStep.welcome);
      expect(find.text('시작하기'), findsOneWidget);
      expect(find.byKey(const ValueKey('home-tabs')), findsNothing);
      expect(peer.requests, hasLength(3));
    },
  );

  testWidgets('AP-AT-12 a card collapses the order and hides item guidance', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')
        ..['status'] = 'judged'
        ..['card_ids'] = []);
    final app = controller(peer);
    await openApp(tester, app);
    const first = '설향 딸기 500g (냉장)';
    final orderPanel = find.byKey(const ValueKey('main-order'));
    final guidance = find.descendant(
      of: orderPanel,
      matching: find.text('냉장고에 띄웠어요'),
    );
    expect(orderScan, findsNothing);
    expect(find.text(first), findsOneWidget);
    expect(guidance, findsNWidgets(2));

    peer.birthday
      ..['status'] = 'notified'
      ..['card_ids'] = ['nc_331'];
    peer.cards = [fixture('card.v1.json')];
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.text('주문 9개 · $first 외 8개'), findsOneWidget);
    expect(find.text(first), findsNothing);
    expect(guidance, findsNothing);
    expect(mainCards, findsOneWidget);
    await tester.tap(orderScan);
    await tester.pumpAndSettle();
    expect(find.text(first), findsOneWidget);
    expect(guidance, findsNWidgets(2));
    await tester.tap(orderScan);
    await tester.pumpAndSettle();
    expect(find.text(first), findsNothing);
    expect(guidance, findsNothing);
  });

  testWidgets('AP-AT-7 a newly shared order dismisses the closed memory', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')..['status'] = 'notified')
      ..cards = [fixture('card.v1.json')];
    final platform = TestPlatform();
    final app = controller(peer, platform: platform);
    await openApp(tester, app);
    peer.birthday['status'] = 'closed';
    peer.rationales['ep_9031'] = fixture('rationale.json');
    peer.cards = [];
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('memory-nc_331')), findsOneWidget);

    peer.upload = (_) async {
      peer.episodes['ep_9150'] = fixture('episode.json', episode: 'ep_9150');
      return Peer.response({
        'episode_id': 'ep_9150',
        'status': 'received',
      }, 202);
    };
    platform.orders.add(
      SharedOrder('new-order', '2026-11-04T19:30:41+09:00', [TestImage()]),
    );
    await app.sync();
    await tester.pumpAndSettle();
    expect(find.byKey(const ValueKey('memory-nc_331')), findsNothing);
    expect(app.currentOrderId, 'ep_9150');
    await tapTab(tester, '캘린더');
    expect(find.byKey(const ValueKey('memory-dot-ep_9031')), findsOneWidget);
  });

  testWidgets(
    'AP-AT-9 groups sample devices and turns off their matched card line',
    (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 1.7;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final running = fixture('card.v1.json');
      lines(running).first['state'] = 'running';
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified')
        ..cards = [running];
      final rationale = peer.rationales['ep_9031']!;
      (rationale['evidence'] as Map)['kb_note'] = 'Hidden inventory evidence';
      final reply = Completer<http.Response>();
      peer.reaction = (_) => reply.future;
      final app = controller(peer);
      await openApp(tester, app, size: const Size(390, 844));
      await tapTab(tester, '우리 집');
      expect(find.text('현관'), findsNothing);
      expect(find.text('기기가 없어요.'), findsNothing);
      for (final room in ['거실', '주방']) {
        final group = find.byKey(ValueKey('device-room-$room'));
        expect(
          find.descendant(of: group, matching: find.text(room)),
          findsOneWidget,
        );
      }
      final cleaner = find.byKey(const ValueKey('sample-device-cleaner_01'));
      final living = find.byKey(const ValueKey('device-room-거실'));
      expect(find.descendant(of: living, matching: cleaner), findsOneWidget);
      expect(
        find.descendant(of: cleaner, matching: find.text('로봇청소기')),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: cleaner,
          matching: find.byIcon(Icons.circle_outlined),
        ),
        findsOneWidget,
      );
      final kitchen = find.byKey(const ValueKey('device-room-주방'));
      expect(
        find.descendant(of: kitchen, matching: find.text('전기포트')),
        findsOneWidget,
      );
      expect(find.text('Hidden inventory evidence'), findsNothing);
      expect(find.byType(Switch), findsNothing);
      expect(find.text('맡기기'), findsNothing);
      expect(find.text('집 연결 후'), findsNothing);
      expect(find.text(delegationHint), findsOneWidget);
      final status = find.descendant(
        of: cleaner,
        matching: find.byType(StatusBadge),
      );
      final line = lines(running).first;
      final lineText = tester.widget<Text>(
        find.descendant(
          of: cleaner,
          matching: find.text(line['text'] as String),
        ),
      );
      expect(lineText.maxLines, 1);
      expect(lineText.overflow, TextOverflow.ellipsis);
      final fridge = find.byKey(const ValueKey('sample-device-fridge_01'));
      expect(
        find.descendant(
          of: fridge,
          matching: find.byWidgetPredicate((widget) => widget is Text),
        ),
        findsOneWidget,
      );
      expect(tester.widget<StatusBadge>(status).label, '진행 중');

      final off = find.descendant(
        of: cleaner,
        matching: find.widgetWithText(TextButton, '끄기'),
      );
      expect(
        tester.getTopRight(off).dx,
        closeTo(tester.getTopRight(cleaner).dx - DesignTokens.space12, 0.1),
      );
      await tester.tap(off);
      await tester.pump();
      final pending = find.descendant(
        of: cleaner,
        matching: find.widgetWithText(TextButton, '요청함'),
      );
      expect(pending, findsOneWidget);
      expect(tester.widget<TextButton>(pending).onPressed, isNull);
      expect(peer.reactions.single.$1, 'nc_331');
      expect(peer.reactions.single.$2, {
        'reaction': 'line_off',
        'task_id': line['task_id'],
      });
      expect(tester.widget<StatusBadge>(status).label, '진행 중');

      final updated = phase(running, 1);
      lines(updated).first['state'] = 'off';
      peer.cards = [updated];
      reply.complete(Peer.response(updated));
      await tester.pumpAndSettle();
      expect(pending, findsNothing);
      expect(tester.widget<StatusBadge>(status).label, '꺼짐');
      expect(tester.widget<TextButton>(off).onPressed, isNull);
      expect(
        peer.requests.every(
          (request) =>
              request.url.origin == 'https://test.invalid' &&
              request.url.path.startsWith('/v1/') &&
              !request.url.path.startsWith('/v1/hub/') &&
              !request.url.path.startsWith('/v1/sim/'),
        ),
        isTrue,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Delegation route flag restores the switch column in Setup and Our Home',
    (tester) async {
      final app = controller(Peer(), setup: true, hasDelegationRoute: true);
      await openApp(tester, app);
      await tapText(tester, '시작하기');
      await tapText(tester, '건너뛰기');
      await tapText(tester, '2인');
      await tapText(tester, '우리 집 만들기');
      await tapText(tester, '다음');
      expect(find.text('집 기기 확인'), findsOneWidget);
      expect(find.byType(Switch), findsNWidgets(7));
      expect(find.text('맡기기'), findsOneWidget);
      expect(find.text(delegationHint), findsNothing);

      await tapText(tester, '저장');
      await tapTab(tester, '우리 집');
      expect(find.byType(Switch), findsNWidgets(7));
      expect(find.text('맡기기'), findsOneWidget);
      expect(find.text(delegationHint), findsNothing);
      expect(find.text('집 연결 후'), findsNothing);
    },
  );

  testWidgets(
    'AP-AT-1 first-run fixture ignores a configured and saved household',
    (tester) async {
      final peer = Peer();
      final store = TestStore();
      final previous = controller(peer, store: store);
      await openApp(tester, previous);
      await previous.updateHousehold({'2인'});
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox.shrink());
      final initialRequests = peer.requests.length;

      final app = AppController(
        api: peer.client(),
        platform: null,
        store: store,
        fixture: true,
        browserPreview: true,
        firstRun: true,
        configuredHousehold: 'h_042',
      );
      await openApp(tester, app, size: const Size(390, 844), devTools: true);
      expect(app.household, isNull);
      expect(find.byType(SpiraTopBar), findsNothing);
      expect(tester.widget<SpiraMark>(find.byType(SpiraMark)).large, isTrue);
      expect(find.text('온라인 주문을 보고, 그날에 맞춰 집을 미리 준비해요.'), findsOneWidget);
      expect(find.text('1 / 4'), findsNothing);
      expect(peer.requests, hasLength(initialRequests));
      await tapText(tester, '시작하기');
      expect(find.text('Google 캘린더'), findsOneWidget);
      expect(find.text('Google 연결 없이 시작할 수 있어요.'), findsOneWidget);
      expect(find.widgetWithText(FilledButton, '건너뛰기'), findsOneWidget);
      expect(find.text('Google로 계속'), findsNothing);
      expect(find.text('1 / 4'), findsOneWidget);
      expectTopBar(tester);
      expect(peer.requests, hasLength(initialRequests));
      await tapText(tester, '건너뛰기');
      expect(find.text('2 / 4'), findsOneWidget);
      expectTopBar(tester);
      await tapText(tester, '2인');
      await tapText(tester, '부부·커플');
      final create = find.widgetWithText(FilledButton, '우리 집 만들기');
      await tester.scrollUntilVisible(create, 200);
      await tapText(tester, '우리 집 만들기');
      final code = fixture('household.created.json')['hub_api_key'] as String;
      expect(find.text(code), findsOneWidget);
      expect(find.text('3 / 4'), findsOneWidget);
      expectTopBar(tester);
      await tapText(tester, '다음');
      expect(find.text('예시 집'), findsOneWidget);
      expect(find.text('4 / 4'), findsOneWidget);
      expectTopBar(tester);
      expect(find.text('로봇청소기'), findsOneWidget);
      expect(find.text('냉장고'), findsOneWidget);
      expect(find.byType(Switch), findsNothing);
      expect(find.text('맡기기'), findsNothing);
      expect(find.text('집 연결 후'), findsNothing);
      expect(find.text(delegationHint), findsOneWidget);
      expect(find.text('끄기'), findsNothing);
      await tapText(tester, '저장');
      expect(find.byKey(const ValueKey('home-tabs')), findsOneWidget);
      expect(find.text('예시 주문으로 공유'), findsOneWidget);
      expectTopBar(tester);
      expect(app.household, 'h_042');
      expect(
        peer.requests
            .skip(initialRequests)
            .where(
              (request) =>
                  request.method == 'POST' &&
                  request.url.path == '/v1/households',
            ),
        hasLength(1),
      );
      expect(peer.profiles.last, {
        'household_types': ['2인', '부부·커플'],
      });
      expect(
        peer.requests
            .skip(initialRequests)
            .every(
              (request) =>
                  request.url.origin == 'https://test.invalid' &&
                  request.url.path.startsWith('/v1/households') &&
                  !request.url.path.contains('/devices'),
            ),
        isTrue,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('AP-AT-7 web preview restores a verified memory and its date', (
    tester,
  ) async {
    final peer = Peer()
      ..episodes['ep_9031'] = (fixture('episode.json')..['status'] = 'notified')
      ..cards = [fixture('card.v1.json')];
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
    await openApp(tester, app);
    peer.birthday['status'] = 'closed';
    peer.cards = [];
    peer.rationales['ep_9031'] = fixture('rationale.json');
    await app.sync();
    await tester.pumpAndSettle();
    final memory = find.byKey(const ValueKey('memory-nc_331'));
    expect(memory, findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
    await openApp(tester, preview());
    expect(memory, findsOneWidget);
    await tapText(tester, '확인');

    await tester.pumpWidget(const SizedBox.shrink());
    await openApp(tester, preview());
    expect(memory, findsNothing);
    await tapTab(tester, '캘린더');
    expect(
      find.descendant(
        of: find.byKey(const ValueKey('2026-10-17')),
        matching: find.byKey(const ValueKey('memory-dot-ep_9031')),
      ),
      findsOneWidget,
    );
  });

  testWidgets(
    'AP-AT-13 card title, line time and state have a phone hierarchy',
    (tester) async {
      final card = fixture('card.v1.json');
      final peer = Peer()
        ..episodes['ep_9031'] = (fixture('episode.json')
          ..['status'] = 'notified')
        ..cards = [card];
      await openApp(
        tester,
        controller(peer),
        size: const Size(390, 844),
        devTools: true,
      );
      final title = find.text(card['text'] as String);
      final row = find.byKey(const ValueKey(('nc_331', 't_clean#1')));
      final time = find.descendant(
        of: row,
        matching: find.textContaining('12:30'),
      );
      final state = find.descendant(of: row, matching: find.text('예정됨'));
      final qualifier = find.text('미리보기 · 계약 테스트 서버');
      expect(tester.widget<Text>(title).style!.fontSize, DesignTokens.size27);
      expect(
        tester.widget<Text>(qualifier).style!.fontSize,
        DesignTokens.size13,
      );
      expect(
        Theme.of(tester.element(title)).textTheme.bodyMedium!.fontFamily,
        'packages/spira_fonts/${DesignTokens.font}',
      );
      expect(tester.getTopLeft(time).dx, lessThan(tester.getTopLeft(state).dx));
      expect(tester.getTopLeft(title).dy, lessThan(tester.getTopLeft(time).dy));
      expect(tester.takeException(), isNull);
    },
  );
}
