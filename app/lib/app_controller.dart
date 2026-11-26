import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:shared_preferences/shared_preferences.dart';

import 'api/app_api.dart';
import 'contracts.dart' as wire;
import 'platform/android_bridge.dart';
import 'platform/google_calendar.dart';
import 'platform/gallery.dart';

abstract interface class AppStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
}

class PreferencesAppStore implements AppStore {
  final _preferences = SharedPreferencesAsync();

  @override
  Future<String?> read(String key) => _preferences.getString(key);

  @override
  Future<void> write(String key, String value) =>
      _preferences.setString(key, value);
}

enum SetupStep { calendar, household, connection, devices, ready }

const _idlePollInterval = Duration(seconds: 30);
const _activePollInterval = Duration(seconds: 3);

typedef MemoryDate = ({String episodeId, String cardId, String startsAt});
typedef _LineRequest = ({
  String taskId,
  String text,
  bool turningOn,
  Set<String> previousTasks,
});

class AppController extends ChangeNotifier {
  AppController({
    required this.api,
    required this.platform,
    required this.store,
    required this.fixture,
    this.browserPreview = false,
    this.readCalendar,
    this.disconnectCalendar,
    this.pickImages,
    this.recoverImages,
    this.configuredHousehold,
  });

  final AppApi api;
  final AppPlatform? platform;
  final AppStore store;
  final bool fixture;
  final bool browserPreview;
  final CalendarReader? readCalendar;
  final Future<void> Function()? disconnectCalendar;
  final GalleryPicker? pickImages;
  final GalleryPicker? recoverImages;
  final String? configuredHousehold;

  bool get demoPreview => browserPreview && fixture && platform == null;
  bool get canShareExample =>
      demoPreview && !sharingExample && (canControl || serverUnavailable);

  String get _environment =>
      jsonEncode([fixture, api.baseUrl.toString(), configuredHousehold]);
  String get _scope => jsonEncode([_environment, household]);
  String get _setupKey => 'spira.setup.v1.$_environment';
  String get _snapshotKey => 'spira.snapshot.v1.$_scope';
  String get _calendarKey => 'spira.calendar.v1.$_scope';
  String get _serverTokenKey => 'spira.server-token.v1.$_environment';
  String get _connectionKey => 'spira.connection.v1.$_environment';

  String? household;
  SetupStep step = SetupStep.calendar;
  String? connectionCode;
  bool starting = true;
  bool busy = false;
  bool stale = true;
  bool needsToken = false;
  bool refreshed = false;
  bool sharingExample = false;
  String? setupError;
  String? refreshError;
  String? uploadError;
  bool uploadDeferred = false;
  bool serverUnavailable = false;
  String? shareIssue;
  String? exampleShareError;
  int queuedShares = 0;
  ({String sourceId, String sharedAt})? _exampleShare;

  final householdTypes = <String>{};
  final episodes = <String, wire.Episode>{};
  final cards = <String, wire.Card>{};
  final accepted = <String>{};
  final _episodeHistory = <String, wire.EpisodeListEpisode>{};
  final _cardStarts = <String, MemoryDate>{};
  final _captures = <String, List<Uint8List>>{};
  String? _lastIntake;
  final _startedTasks = <String, Set<String>>{};
  final _pendingStops = <String, Set<String>>{};
  final _uncertainStops = <String>{};
  final _pendingLines = <(String, String), _LineRequest>{};
  final controlErrors = <String, String>{};
  final _notifications = <String, List<String>>{};
  final _memoryReads = <String, Future<void>>{};
  final _rationales = <String, wire.Rationale>{};
  bool pickingImages = false;
  String? galleryError;
  ({String sourceId, String sharedAt, List<GalleryImage> images})? _gallery;
  bool get hasPendingSelection => _gallery != null;

  wire.Calendar _googleCalendar = wire.Calendar(events: []);
  wire.Calendar get googleCalendar => _googleCalendar;
  bool get calendarConnected => _calendarConnected;
  String? calendarError;

  String? _cursor;
  String? get lastServerCheck => _cursor;
  Timer? _timer;
  Duration? _pollInterval;
  bool _foreground = true;
  StreamSubscription<void>? _shareSubscription;
  Future<void> _queue = Future<void>.value();
  Future<void> _calendarQueue = Future<void>.value();
  Future<void>? _sync;
  String? _calendarFingerprint;
  bool _calendarFingerprintDirty = false;
  bool _calendarConnected = false;
  bool _calendarClearPending = false;
  wire.Calendar? _initialCalendar;
  bool _inboxChanged = false;
  bool _disposed = false;

  Iterable<wire.Episode> get orderedEpisodes => episodes.values.toList()
    ..sort(
      (a, b) =>
          DateTime.parse(b.sharedAt).compareTo(DateTime.parse(a.sharedAt)),
    );

  List<wire.Card> cardsFor(wire.Episode episode) => [
    for (final id in episode.cardIds.take(2))
      if (cards[id] case final card? when card.episodeId == episode.episodeId)
        card,
  ];

  String? get currentOrderId =>
      _lastIntake ??
      accepted.lastOrNull ??
      orderedEpisodes.firstOrNull?.episodeId;

  List<Uint8List> orderImages(String episodeId) =>
      _captures[episodeId] ?? const [];

  List<wire.Card> get activeCards => [
    for (final episode in orderedEpisodes)
      if (episode.status != wire.EpisodeStatus.CLOSED) ...cardsFor(episode),
  ];

  List<MemoryDate> get memoryDates => [
    for (final row in _episodeHistory.values)
      if (row.status == wire.EpisodeStatus.CLOSED && row.cardIds.isNotEmpty)
        // A closed card cannot be fetched again. When this device never saw
        // the card, the order's share date marks the memory; a card seen
        // without a time (held) has no day.
        ?_memoryDate(row),
  ];

  MemoryDate? _memoryDate(wire.EpisodeListEpisode row) {
    final seen = row.cardIds.map((id) => _cardStarts[id]).nonNulls;
    if (seen.isEmpty) {
      return (
        episodeId: row.episodeId,
        cardId: row.cardIds.first,
        startsAt: row.sharedAt,
      );
    }
    return seen.where((date) => date.startsAt.isNotEmpty).firstOrNull;
  }

  bool stopPending(String cardId) => _pendingStops.containsKey(cardId);
  bool stopUncertain(String cardId) => _uncertainStops.contains(cardId);
  bool get canControl => !stale;

  Future<void> start() async {
    _shareSubscription = platform?.sharesChanged.listen((_) {
      _inboxChanged = true;
      unawaited(sync());
    });
    try {
      await _restore();
    } catch (_) {
      setupError = '저장된 정보를 불러오지 못했어요.';
    }
    if (_disposed) return;
    starting = false;
    if (step == SetupStep.ready) _requestNotificationPermission();
    _change();
    await Future.wait([resendCalendar(), sync()]);
    final recover = recoverImages;
    if (!_disposed && step == SetupStep.ready && recover != null) {
      await _chooseImages(recover);
    }
  }

  bool get _hasActiveWork =>
      sharingExample ||
      queuedShares > 0 ||
      accepted.isNotEmpty ||
      episodes.values.any(
        (episode) =>
            episode.status == wire.EpisodeStatus.RECEIVED ||
            episode.status == wire.EpisodeStatus.READING ||
            (episode.status != wire.EpisodeStatus.CLOSED &&
                cardsFor(episode).length < episode.cardIds.length) ||
            // The first card may follow the initial item projection.
            (const {
                  wire.EpisodeStatus.JUDGED,
                  wire.EpisodeStatus.NOTIFIED,
                }.contains(episode.status) &&
                episode.cardIds.isEmpty &&
                _sharedRecently(episode)),
      ) ||
      cards.values.any(_cardIsActive);

  // A judged order that produces no card must not keep fast polling forever.
  bool _sharedRecently(wire.Episode episode) {
    final shared = DateTime.tryParse(episode.sharedAt);
    return shared != null &&
        DateTime.now().toUtc().difference(shared.toUtc()) <
            const Duration(minutes: 2);
  }

  bool _cardIsActive(wire.Card card) =>
      episodes[card.episodeId]?.status != wire.EpisodeStatus.CLOSED;

  void _schedulePoll() {
    if (starting || step != SetupStep.ready) return;
    final interval = _foreground && _hasActiveWork
        ? _activePollInterval
        : _idlePollInterval;
    if (_pollInterval == interval) return;
    _timer?.cancel();
    _pollInterval = interval;
    _timer = Timer.periodic(interval, (_) => unawaited(sync()));
  }

  void setForeground(bool foreground) {
    if (_disposed || _foreground == foreground) return;
    _foreground = foreground;
    _schedulePoll();
    if (foreground && !starting) {
      unawaited(resendCalendar());
      unawaited(sync());
    }
  }

  Future<void> _restore() async {
    final saved = await store.read(_setupKey);
    if (saved != null) {
      final setup = jsonDecode(saved) as Map<String, dynamic>;
      household = setup['household'] as String?;
      step = SetupStep.values.byName(setup['step'] as String);
      _calendarConnected = setup['calendarConnected'] as bool? ?? false;
      householdTypes.addAll((setup['types'] as List<dynamic>).cast<String>());
      _calendarClearPending = setup['calendarClearPending'] as bool? ?? false;
      // An older calendar checkpoint already had a household but no code step.
      if (step == SetupStep.calendar && household != null) {
        step = SetupStep.household;
      }
      if (step == SetupStep.connection || step == SetupStep.household) {
        connectionCode = await store.read(_connectionKey);
        if (connectionCode?.isEmpty == true) connectionCode = null;
      }
    } else if (configuredHousehold != null) {
      household = configuredHousehold;
      step = SetupStep.ready;
    }
    if (!browserPreview) {
      api.token = await store.read(_serverTokenKey) ?? api.token;
    }
    // The browser preview talks to a fixture that starts fresh each run with the same IDs;
    // a cached snapshot from an earlier run would show its finished cards before the share.
    if (household == null || demoPreview) return;
    final cached = await store.read(_snapshotKey);
    if (cached == null) return;
    final value = jsonDecode(cached) as Map<String, dynamic>;
    for (final data
        in (value['episodes'] as List<dynamic>).cast<Map<String, dynamic>>()) {
      final episode = wire.Episode.fromJson(data);
      if (episode.householdId == household) {
        episodes[episode.episodeId] = episode;
      }
    }
    for (final data
        in (value['cards'] as List<dynamic>).cast<Map<String, dynamic>>()) {
      final card = wire.Card.fromJson(data);
      cards[card.cardId] = card;
    }
    _cursor = value['cursor'] as String?;
    for (final entry in (value['cardStarts'] as List<dynamic>? ?? const [])) {
      final fields = (entry as List<dynamic>).cast<String>();
      final date = (
        episodeId: fields[0],
        cardId: fields[1],
        startsAt: fields[2],
      );
      _cardStarts[date.cardId] = date;
    }
    // Migrate dates already supplied by the Server in older snapshots.
    for (final card in cards.values) {
      _recordStart(card);
    }
    cards.removeWhere(
      (_, card) =>
          episodes[card.episodeId]?.status == wire.EpisodeStatus.CLOSED,
    );
    accepted.addAll((value['accepted'] as List<dynamic>).cast<String>());
    final started = value['started'] as Map<String, dynamic>;
    for (final entry in started.entries) {
      _startedTasks[entry.key] = (entry.value as List<dynamic>)
          .cast<String>()
          .toSet();
    }
    final stops = value['stops'] as Map<String, dynamic>;
    for (final entry in stops.entries) {
      _pendingStops[entry.key] = (entry.value as List<dynamic>)
          .cast<String>()
          .toSet();
      _uncertainStops.add(entry.key);
    }
    final outbox = value['notifications'] as Map<String, dynamic>;
    _notifications.addAll(
      outbox.map(
        (key, value) => MapEntry(key, (value as List<dynamic>).cast<String>()),
      ),
    );
  }

  Future<void> _saveSetup() => store.write(
    _setupKey,
    jsonEncode({
      'household': household,
      'step': step.name,
      'calendarConnected': _calendarConnected,
      'types': householdTypes.toList(),
      'calendarClearPending': _calendarClearPending,
    }),
  );

  Future<void> _save() => store.write(
    _snapshotKey,
    jsonEncode({
      'cursor': _cursor,
      'accepted': accepted.toList(),
      'episodes': episodes.values.map((episode) => episode.toJson()).toList(),
      'cards': cards.values.map((card) => card.toJson()).toList(),
      'cardStarts': _cardStarts.values
          .map((date) => [date.episodeId, date.cardId, date.startsAt])
          .toList(),
      'started': _startedTasks.map(
        (card, tasks) => MapEntry(card, tasks.toList()),
      ),
      'stops': _pendingStops.map((key, value) => MapEntry(key, value.toList())),
      'notifications': _notifications,
    }),
  );

  Future<void> _serialize(Future<void> Function() work) {
    final next = _queue.then((_) async {
      if (!_disposed) await work();
    });
    _queue = next.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return next;
  }

  Future<void> submitHousehold(Set<String> types) async {
    if (busy || types.isEmpty) return;
    await _setup(() async {
      if (household == null) {
        final created = await api.createHousehold(
          wire.HouseholdCreate(householdTypes: types.toList()),
        );
        household = created.householdId;
        connectionCode = created.hubApiKey;
        await store.write(_connectionKey, created.hubApiKey);
        await _saveSetup();
      }
      final profile = await api.profile(
        household!,
        wire.Profile(householdTypes: types.toList()),
      );
      householdTypes
        ..clear()
        ..addAll(profile.householdTypes);
      step = connectionCode == null ? SetupStep.devices : SetupStep.connection;
      await _saveSetup();
      unawaited(resendCalendar(selected: _initialCalendar));
      _initialCalendar = null;
    });
  }

  Future<void> completeConnection() async {
    if (busy) return;
    await _setup(() async {
      step = SetupStep.devices;
      await _saveSetup();
      await store.write(_connectionKey, '');
      connectionCode = null;
    });
  }

  Future<void> updateHousehold(Set<String> types) async {
    if (busy || types.isEmpty) return;
    await _setup(() async {
      final profile = await api.profile(
        household!,
        wire.Profile(householdTypes: types.toList()),
      );
      householdTypes
        ..clear()
        ..addAll(profile.householdTypes);
      await _saveSetup();
    });
  }

  Future<void> finishCalendar({required bool connect}) async {
    if (busy) return;
    await _setup(() async {
      if (connect) {
        await _connectCalendar();
        _initialCalendar = _googleCalendar;
      }
      step = SetupStep.household;
      await _saveSetup();
    });
  }

  Future<void> connectGoogle() async {
    if (busy || _calendarConnected) return;
    await _setup(() async {
      await _connectCalendar();
      await _saveSetup();
      await resendCalendar(selected: _googleCalendar);
    });
    if (setupError case final error?) {
      calendarError = error;
      _change();
    }
  }

  Future<void> _connectCalendar() async {
    final reader = readCalendar;
    if (reader == null) throw StateError('Calendar unavailable');
    _googleCalendar = await reader(interactive: true);
    _calendarConnected = true;
    _calendarClearPending = false;
    calendarError = null;
  }

  Future<void> disconnectGoogle() async {
    if (busy || !_calendarConnected) return;
    await _setup(() async {
      await disconnectCalendar?.call();
      _calendarConnected = false;
      _googleCalendar = wire.Calendar(events: []);
      _calendarClearPending = true;
      await _saveSetup();
      await resendCalendar();
    });
    if (setupError case final error?) {
      calendarError = error;
      _change();
    }
  }

  Future<void> resendCalendar({wire.Calendar? selected}) {
    final id = household;
    if (starting || _disposed || id == null) return Future<void>.value();
    // A full replacement must follow any older read already in flight.
    return _calendarQueue = _calendarQueue.then((_) async {
      if (_disposed) return;
      try {
        if (_calendarClearPending) {
          await _sendCalendar(id, wire.Calendar(events: []));
          _calendarClearPending = false;
          await _saveSetup();
        } else if (readCalendar case final reader? when _calendarConnected) {
          final calendar = selected ?? await reader(interactive: false);
          if (_disposed || !_calendarConnected) return;
          _googleCalendar = calendar;
          await _sendCalendar(id, calendar);
        }
        calendarError = null;
      } catch (_) {
        calendarError = 'Google 캘린더를 새로 불러오지 못했어요.';
      }
      _change();
    });
  }

  Future<void> _sendCalendar(String id, wire.Calendar calendar) async {
    // The peer replaces the list, so event order alone is immaterial.
    final events =
        calendar.events.map((event) => jsonEncode(event.toJson())).toList()
          ..sort();
    final fingerprint = sha256
        .convert(utf8.encode(jsonEncode(events)))
        .toString();
    final key = _calendarKey;
    final previous = _calendarFingerprint ??= await store.read(key);
    if (_disposed) return;
    if (previous != fingerprint) {
      await api.calendar(id, calendar);
      _calendarFingerprint = fingerprint;
      _calendarFingerprintDirty = true;
    }
    if (_calendarFingerprintDirty) {
      await store.write(key, fingerprint);
      _calendarFingerprintDirty = false;
    }
  }

  Future<void> finishDevices() async {
    if (busy) return;
    await _setup(() async {
      step = SetupStep.ready;
      await _saveSetup();
    });
    if (step == SetupStep.ready) {
      _requestNotificationPermission();
      await sync();
    }
  }

  void _requestNotificationPermission() {
    unawaited(
      platform?.requestNotificationPermission().catchError((Object _) {}),
    );
  }

  Future<void> _setup(Future<void> Function() work) async {
    setupError = null;
    busy = true;
    _change();
    try {
      await work();
    } catch (error) {
      setupError = _error(error, '설정을 저장하지 못했어요. 다시 시도해 주세요.');
    } finally {
      busy = false;
      _change();
    }
  }

  Future<void> useToken(String token) async {
    api.token = token;
    needsToken = false;
    _change();
    unawaited(sync());
    if (!browserPreview) await store.write(_serverTokenKey, token);
  }

  Future<void> sync() {
    if (starting || _disposed) return Future<void>.value();
    return _sync ??= _serialize(() async {
      if (step != SetupStep.ready) return;
      do {
        _inboxChanged = false;
        await _upload();
        await _refresh();
      } while (_inboxChanged && !_disposed);
    }).whenComplete(() => _sync = null);
  }

  Future<void> _upload() async {
    final platform = this.platform;
    if (platform == null) return;
    final id = household!;
    try {
      final inbox = await platform.inbox(_scope);
      queuedShares = inbox.orders.length;
      if (queuedShares == 0) uploadDeferred = false;
      shareIssue = inbox.issue;
      uploadError = null;
      _change();
      for (final order in inbox.orders) {
        final ShareReceipt receipt;
        try {
          receipt = await api.share(id, order);
        } on AppApiException catch (error) {
          if (error.code != wire.ErrorCode.INVALID_IMAGE) rethrow;
          await platform.discardInvalid(_scope, order.sourceId);
          queuedShares--;
          shareIssue = 'rejected';
          _change();
          continue;
        }
        // Persist the receipt before allowing Android to discard the images.
        final episodeId = receipt.accepted.episodeId;
        final showIntake = receipt.isNew || !episodes.containsKey(episodeId);
        _recordReceipt(episodeId, const [], showIntake: showIntake);
        await _save();
        final images = <Uint8List>[];
        if (showIntake) {
          for (final image in order.images) {
            try {
              images.add(await image.readAsBytes());
            } on FileSystemException {
              // The upload is already accepted even if its local preview is gone.
            }
          }
        }
        await platform.acknowledge(_scope, order.sourceId, episodeId);
        if (images.isNotEmpty) _captures[episodeId] = images;
        queuedShares--;
        _change();
      }
      uploadDeferred = false;
    } catch (error) {
      uploadDeferred = queuedShares > 0 && isServerUnavailable(error);
      if (!uploadDeferred) {
        uploadError = _error(error, '주문을 보내지 못했어요. 다시 시도해 주세요.');
      }
    }
  }

  Future<void> shareExample() async {
    if (!canShareExample) return;
    sharingExample = true;
    exampleShareError = null;
    _change();
    try {
      await _serialize(() async {
        final asset = await rootBundle.load('assets/example-order.png');
        final image = Uint8List.sublistView(asset);
        final random = Random.secure();
        final share = _exampleShare ??= (
          sourceId:
              'preview_${base64UrlEncode(List.generate(12, (_) => random.nextInt(256)))}',
          sharedAt: DateTime.now().toUtc().toIso8601String(),
        );
        final receipt = await api.shareExample(
          household!,
          share.sourceId,
          share.sharedAt,
          image,
        );
        _exampleShare = null;
        final episodeId = receipt.accepted.episodeId;
        _recordReceipt(episodeId, [image], showIntake: receipt.isNew);
        _change();
        await _save();
        await _refresh();
      });
    } catch (error) {
      exampleShareError = _error(error, '예시 주문을 보내지 못했어요. 다시 시도해 주세요.');
    } finally {
      sharingExample = false;
      _change();
    }
  }

  Future<void> chooseOrderImages() async {
    if (pickImages case final pick?) await _chooseImages(pick);
  }

  Future<void> _chooseImages(GalleryPicker pick) async {
    if (pickingImages || _gallery != null) return;
    pickingImages = true;
    galleryError = null;
    _change();
    try {
      final images = await pick();
      if (images.isEmpty || _disposed) return;
      if (images.length > 3) throw const GalleryException('사진을 1~3장 골라 주세요.');
      final random = Random.secure();
      _gallery = (
        sourceId:
            'gallery_${base64UrlEncode(List.generate(12, (_) => random.nextInt(256)))}',
        sharedAt: DateTime.now().toUtc().toIso8601String(),
        images: images,
      );
      await _sendSelection();
    } on GalleryException catch (error) {
      galleryError = error.message;
    } catch (_) {
      galleryError = '선택한 사진을 열 수 없어요. 다시 골라 주세요.';
    } finally {
      pickingImages = false;
      _change();
    }
  }

  Future<void> retryGallery() async {
    if (pickingImages || _gallery == null) return;
    pickingImages = true;
    galleryError = null;
    _change();
    try {
      await _sendSelection();
    } finally {
      pickingImages = false;
      _change();
    }
  }

  void discardGallery() {
    if (pickingImages) return;
    _gallery = null;
    galleryError = null;
    _change();
  }

  Future<void> _sendSelection() => _serialize(() async {
    final selection = _gallery;
    if (selection == null) return;
    try {
      final receipt = await api.shareGallery(
        household!,
        selection.sourceId,
        selection.sharedAt,
        selection.images,
      );
      _gallery = null;
      _recordReceipt(
        receipt.accepted.episodeId,
        selection.images.map((image) => image.bytes).toList(),
      );
      _change();
      await _save();
      await _refresh();
    } catch (error) {
      if (error is AppApiException &&
          error.code == wire.ErrorCode.INVALID_IMAGE) {
        _gallery = null;
      }
      galleryError = _error(error, '주문을 보내지 못했어요. 다시 시도해 주세요.');
    }
  });

  void _recordReceipt(
    String episodeId,
    List<Uint8List> images, {
    bool showIntake = true,
  }) {
    accepted.add(episodeId);
    if (!showIntake) return;
    _lastIntake = episodeId;
    _captures.clear();
    if (images.isNotEmpty) _captures[episodeId] = images;
  }

  void _recordStart(wire.Card card) {
    if (card.startsAt case final startsAt?) {
      DateTime.parse(startsAt);
      _cardStarts[card.cardId] = (
        episodeId: card.episodeId,
        cardId: card.cardId,
        startsAt: startsAt,
      );
    } else {
      // Seen without a time (held): no calendar day, and no share-date guess.
      _cardStarts[card.cardId] = (
        episodeId: card.episodeId,
        cardId: card.cardId,
        startsAt: '',
      );
    }
  }

  Future<void> _refresh() async {
    final id = household!;
    try {
      final cursor = _cursor;
      var poll = await api.cards(id, since: cursor);
      final rewound =
          cursor != null &&
          DateTime.parse(poll.serverTime).isBefore(DateTime.parse(cursor));
      final reconcile = cursor != null && (rewound || stale);
      final open = reconcile ? await api.cards(id) : null;
      if (rewound) poll = open!;
      DateTime.parse(poll.serverTime);
      final returnedOpenIds = open?.cards.map((card) => card.cardId).toSet();

      final listed = <String, wire.EpisodeListEpisode>{};
      String? before;
      do {
        final list = await api.episodes(id, before: before);
        for (final row in list.episodes) {
          DateTime.parse(row.sharedAt);
          listed[row.episodeId] = row;
        }
        final next = list.nextBefore;
        if (next != null &&
            before != null &&
            !DateTime.parse(next).isBefore(DateTime.parse(before))) {
          throw const FormatException('Episode history did not advance');
        }
        before = next;
      } while (before != null);

      final latest = listed.values.firstOrNull?.episodeId;
      final details = (await Future.wait(
        {
          ?latest,
          ...accepted,
          if (_lastIntake != null && listed.containsKey(_lastIntake))
            _lastIntake!,
          for (final row in listed.values)
            if (row.status != wire.EpisodeStatus.CLOSED) row.episodeId,
        }.map((episodeId) async {
          try {
            final episode = await api.episode(episodeId);
            if (episode.episodeId != episodeId || episode.householdId != id) {
              throw const FormatException('Wrong episode');
            }
            return episode;
          } on AppApiException catch (error) {
            if (error.status == 404 && !listed.containsKey(episodeId)) {
              return null;
            }
            rethrow;
          }
        }),
      )).whereType<wire.Episode>().toList();
      if (_disposed) return;
      final cardUpdates = rewound
          ? poll.cards
          : [...?open?.cards, ...poll.cards];
      for (final card in cardUpdates) {
        DateTime.parse(card.updatedAt);
        if (card.startsAt case final start?) DateTime.parse(start);
      }

      for (final episode in details) {
        listed[episode.episodeId] = wire.EpisodeListEpisode(
          episodeId: episode.episodeId,
          cardIds: episode.cardIds,
          itemCount: episode.itemCount,
          sharedAt: episode.sharedAt,
          status: episode.status,
        );
      }
      final currentCards = {
        for (final row in listed.values)
          for (final cardId in row.cardIds) cardId: row,
      };
      if (rewound) {
        cards.clear();
        _cardStarts.clear();
        _startedTasks.clear();
        _rationales.clear();
      }
      for (final card in cardUpdates) {
        final row = currentCards[card.cardId];
        if (row == null || row.episodeId != card.episodeId) continue;
        final previous = cards[card.cardId];
        if (previous != null &&
            DateTime.parse(card.updatedAt)
                .isBefore(DateTime.parse(previous.updatedAt))) {
          continue;
        }
        _recordStart(card);
        if (row.status == wire.EpisodeStatus.CLOSED) continue;
        cards[card.cardId] = card;
        _confirmControls(card);
        if (platform != null && card.notify) {
          _notifications[jsonEncode([card.cardId, card.updatedAt])] = [
            '준비 카드',
            card.text,
          ];
        }
      }

      cards.removeWhere((id, card) {
        final row = currentCards[id];
        return row?.episodeId != card.episodeId ||
            row?.status == wire.EpisodeStatus.CLOSED ||
            (returnedOpenIds != null &&
                !returnedOpenIds.contains(id) &&
                !poll.cards.any((update) => update.cardId == id));
      });
      _pendingLines.removeWhere((key, _) => !cards.containsKey(key.$1));
      _pendingStops.removeWhere((id, _) => !cards.containsKey(id));
      _uncertainStops.retainAll(cards.keys.toSet());
      controlErrors.removeWhere((id, _) => !cards.containsKey(id));
      _startedTasks.removeWhere((id, _) => !cards.containsKey(id));
      _notifications.removeWhere((key, _) {
        final pair = jsonDecode(key) as List<dynamic>;
        return pair.first == 'read_failed'
            ? !listed.containsKey(pair.last)
            : !currentCards.containsKey(pair.first);
      });
      _cardStarts.removeWhere(
        (id, date) => currentCards[id]?.episodeId != date.episodeId,
      );
      _rationales.removeWhere(
        (id, _) =>
            !listed.containsKey(id) ||
            listed[id]!.status == wire.EpisodeStatus.CLOSED,
      );
      _captures.removeWhere(
        (id, _) =>
            id != _lastIntake &&
            !listed.containsKey(id) &&
            !accepted.contains(id),
      );
      if (!listed.containsKey(_lastIntake) && !accepted.contains(_lastIntake)) {
        _lastIntake = null;
      }
      _episodeHistory
        ..clear()
        ..addAll(listed);
      episodes.clear();
      for (final episode in details) {
        episodes[episode.episodeId] = episode;
        accepted.remove(episode.episodeId);
        if (platform != null &&
            episode.status == wire.EpisodeStatus.READ_FAILED) {
          _notifications[jsonEncode(['read_failed', episode.episodeId])] = [
            '주문을 읽지 못했어요',
            '읽지 못했어요. 다시 보내 주세요',
          ];
        }
      }

      final previousCursor = _cursor;
      _cursor = poll.serverTime;
      try {
        await _save();
      } catch (_) {
        _cursor = previousCursor;
        rethrow;
      }
      stale = false;
      refreshed = true;
      serverUnavailable = false;
      refreshError = null;
      for (final card in activeCards) {
        if (!isMemory(card)) {
          unawaited(_loadObservation(card.episodeId));
        }
      }
    } catch (error) {
      stale = true;
      serverUnavailable = isServerUnavailable(error);
      refreshError = serverUnavailable
          ? null
          : _error(error, '새로 불러오지 못했어요. 다시 시도해 주세요.');
    }
    _change();
    await _deliverNotifications();
  }

  void _confirmControls(wire.Card card) {
    for (final line in card.lines) {
      if (_hasStarted(line.state) || line.endState != null) {
        _startedTasks.putIfAbsent(card.cardId, () => {}).add(line.taskId);
      }
    }
    final awaiting = _pendingStops[card.cardId];
    if (card.stopped &&
        awaiting != null &&
        awaiting.every(
          (id) => card.lines.any(
            (line) => line.taskId == id && line.endState != null,
          ),
        )) {
      _pendingStops.remove(card.cardId);
      _uncertainStops.remove(card.cardId);
    }
    _pendingLines.removeWhere((key, request) {
      if (key.$1 != card.cardId) return false;
      if (card.stopped) return true;
      final line = card.lines
          .where((line) => line.taskId == request.taskId)
          .firstOrNull;
      if (!request.turningOn) return line?.state == wire.LineState.OFF;
      if (line != null) return line.state != wire.LineState.OFF;
      return card.lines.any(
        (replacement) =>
            replacement.text == request.text &&
            !request.previousTasks.contains(replacement.taskId) &&
            replacement.state != wire.LineState.OFF,
      );
    });
  }

  Future<void> _deliverNotifications() async {
    final platform = this.platform;
    if (platform == null) return;
    final sent = <String>[];
    for (final entry in _notifications.entries) {
      try {
        if (await platform.notify(
          _scope,
          entry.key,
          entry.value.first,
          entry.value.last,
        )) {
          sent.add(entry.key);
        }
      } catch (_) {
        // Keep the notification queued for the next foreground refresh.
      }
    }
    if (sent.isEmpty) return;
    _notifications.removeWhere((key, _) => sent.contains(key));
    try {
      await _save();
    } catch (_) {
      // Android retains its own notification key across restarts.
    }
  }

  static bool _hasStarted(wire.LineState state) => switch (state) {
    wire.LineState.RUNNING ||
    wire.LineState.DONE ||
    wire.LineState.PARTIAL ||
    wire.LineState.USER_CHANGED ||
    wire.LineState.UNKNOWN => true,
    _ => false,
  };

  (String, String) _taskKey(wire.Card card, wire.LineElement line) =>
      (card.cardId, line.taskId);

  // Line off works until the line ends (a started line is cancelled with restore);
  // line on only before it starts (contract: line_on after start is 409 line_started).
  bool canSwitch(wire.Card card, wire.LineElement line) =>
      canControl &&
      episodes[card.episodeId]?.status != wire.EpisodeStatus.CLOSED &&
      !card.stopped &&
      !isMemory(card) &&
      !stopPending(card.cardId) &&
      line.endState == null &&
      switch (line.state) {
        wire.LineState.HELD ||
        wire.LineState.SCHEDULED ||
        wire.LineState.BLOCKED => true,
        wire.LineState.FAILED => lineStarted(card, line),
        wire.LineState.OFF => !lineStarted(card, line),
        final state => _hasStarted(state),
      };

  bool lineStarted(wire.Card card, wire.LineElement line) =>
      (_startedTasks[card.cardId]?.contains(line.taskId) ?? false) ||
      // Off and failed can hide a dispatch. A non-blocked execution is
      // either a confirmed start or an uncertain start that forbids line on.
      (_rationales[card.episodeId]?.executions.any(
            (result) =>
                result.taskId == line.taskId &&
                result.status != wire.ExecutionStatus.BLOCKED,
          ) ??
          false);

  Future<void> stop(wire.Card card) async {
    if (!canControl ||
        episodes[card.episodeId]?.status == wire.EpisodeStatus.CLOSED ||
        card.stopped ||
        isMemory(card) ||
        !card.buttons.contains(wire.CardButton.STOP)) {
      return;
    }
    if (stopPending(card.cardId) && !_uncertainStops.remove(card.cardId)) {
      return;
    }
    _pendingStops.putIfAbsent(
      card.cardId,
      () => {
        for (final line in card.lines)
          if (line.endState == null &&
              (_startedTasks[card.cardId]?.contains(line.taskId) ?? false))
            line.taskId,
      },
    );
    controlErrors.remove(card.cardId);
    _change();
    await _serialize(() async {
      try {
        final latest = cards[card.cardId] ?? card;
        final awaiting = _pendingStops[card.cardId];
        if (latest.stopped || awaiting == null) return;
        awaiting.addAll(
          latest.lines
              .where(
                (line) =>
                    line.endState == null &&
                    (_startedTasks[card.cardId]?.contains(line.taskId) ??
                        false),
              )
              .map((line) => line.taskId),
        );
        await _save();
        await api.react(
          card.cardId,
          wire.Reaction(reaction: wire.ReactionEnum.STOP),
        );
      } catch (error) {
        if (error is AppApiException && error.status < 500) {
          _pendingStops.remove(card.cardId);
        } else {
          _uncertainStops.add(card.cardId);
        }
        controlErrors[card.cardId] = _error(error, '중지 요청을 확인하지 못했어요.');
      }
      await _refresh();
    });
  }

  bool linePending(wire.Card card, wire.LineElement line) =>
      _pendingLines.containsKey(_taskKey(card, line));

  Future<void> switchLine(wire.Card card, wire.LineElement line) async {
    final key = _taskKey(card, line);
    if (!canSwitch(card, line) || _pendingLines.containsKey(key)) return;
    final turningOn = line.state == wire.LineState.OFF;
    _pendingLines[key] = (
      taskId: line.taskId,
      text: line.text,
      turningOn: turningOn,
      previousTasks: card.lines.map((entry) => entry.taskId).toSet(),
    );
    controlErrors.remove(card.cardId);
    _change();
    await _serialize(() async {
      try {
        final current = cards[card.cardId];
        final matching = current?.lines
            .where((entry) => entry.taskId == line.taskId)
            .firstOrNull;
        if (current == null ||
            matching == null ||
            !canSwitch(current, matching) ||
            (matching.state == wire.LineState.OFF) != turningOn) {
          _pendingLines.remove(key);
          return;
        }
        await api.react(
          card.cardId,
          wire.Reaction(
            reaction: turningOn
                ? wire.ReactionEnum.LINE_ON
                : wire.ReactionEnum.LINE_OFF,
            taskId: line.taskId,
          ),
        );
      } catch (error) {
        if (error is AppApiException &&
            error.status < 500 &&
            error.status != 408) {
          _pendingLines.remove(key);
          if (error.code == wire.ErrorCode.LINE_STARTED) {
            _startedTasks.putIfAbsent(card.cardId, () => {}).add(line.taskId);
            await _save();
          }
        }
        controlErrors[card.cardId] = _error(error, '준비 항목 변경을 확인하지 못했어요.');
      } finally {
        await _refresh();
      }
    });
  }

  wire.Rationale? rationaleFor(String episodeId) => _rationales[episodeId];

  bool isMemory(wire.Card card) =>
      _rationales[card.episodeId]?.observations.any(
        (observation) =>
            observation.cardId == card.cardId && observation.verdict != null,
      ) ??
      false;

  Future<void> _loadObservation(String id) =>
      _memoryReads.putIfAbsent(id, () async {
        try {
          final result = await api.rationale(id);
          if (result.episodeId != id) {
            throw const FormatException('Wrong episode');
          }
          if (!_disposed &&
              episodes[id]?.status != wire.EpisodeStatus.CLOSED &&
              episodes.containsKey(id)) {
            _rationales[id] = result;
            _change();
          }
        } catch (_) {
          // The observation may arrive on a later poll.
        } finally {
          _memoryReads.remove(id);
        }
      });

  Future<({wire.Episode episode, wire.Rationale rationale})> readMemory(
    String id,
  ) async {
    final (episode, rationale) = await (
      api.episode(id),
      api.rationale(id),
    ).wait;
    if (episode.householdId != household ||
        episode.episodeId != id ||
        rationale.episodeId != id ||
        episode.status != wire.EpisodeStatus.CLOSED) {
      throw const FormatException('Wrong episode');
    }
    return (episode: episode, rationale: rationale);
  }

  String _error(Object error, String fallback) {
    if (error is AppApiException) {
      if (error.status == 401) {
        needsToken = true;
        return '서버 접속 토큰을 입력해 주세요.';
      }
      return switch (error.code) {
        wire.ErrorCode.LINE_STARTED => '이미 시작된 항목은 바꿀 수 없어요.',
        wire.ErrorCode.INVALID_IMAGE => '서버가 이미지를 읽을 수 없어요. 새 캡처를 공유해 주세요.',
        wire.ErrorCode.HOUSEHOLD_TYPES_INVALID =>
          error.reason ?? '선택한 가구 유형을 함께 사용할 수 없어요.',
        _ => fallback,
      };
    }
    return fallback;
  }

  void _change() {
    if (_disposed) return;
    _schedulePoll();
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    unawaited(_shareSubscription?.cancel());
    super.dispose();
  }
}
