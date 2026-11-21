import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:shared_preferences/shared_preferences.dart';

import 'api/app_api.dart';
import 'contracts.dart' as wire;
import 'design_vocabulary.g.dart';
import 'platform/android_bridge.dart';
import 'platform/google_calendar.dart';
import 'platform/home_hub_onboarding.dart';
import 'preparation_history.dart';

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

enum SetupStep { household, calendar, devices, ready }

enum DeviceChoice { undecided, delegated, never }

const _idlePollInterval = Duration(seconds: 30);
const _activePollInterval = Duration(seconds: 3);
const _closedPreparationDuration = Duration(minutes: 30);

class AppController extends ChangeNotifier {
  AppController({
    required this.api,
    required this.platform,
    required this.store,
    required this.fixture,
    this.browserPreview = false,
    this.homeHub,
    this.readCalendar,
    this.discovered,
    this.configuredHousehold,
  });

  final AppApi api;
  final AppPlatform? platform;
  final AppStore store;
  final bool fixture;
  final bool browserPreview;
  final HttpHomeHubOnboarding? homeHub;
  final CalendarReader? readCalendar;
  final wire.Devices? discovered;
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

  String? household;
  SetupStep step = SetupStep.household;
  bool starting = true;
  bool busy = false;
  bool stale = true;
  bool? paused;
  bool pausePending = false;
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
  final deviceChoices = <String, Map<String, DeviceChoice>>{};
  final episodes = <String, wire.Episode>{};
  final cards = <String, wire.Card>{};
  final accepted = <String>{};
  final _orderCaptures = <String, Queue<List<Uint8List>>>{};
  // Keep the last shown capture per order for this session only.
  final _shownCaptures = <String, List<Uint8List>>{};
  final _recentClosures = <String, DateTime>{};
  final _startedTasks = <String, Set<String>>{};
  final _pendingStops = <String, Set<String>>{};
  final _uncertainStops = <String>{};
  final _historyChecked = <String>{};
  final pendingLines = <String>{};
  final controlErrors = <String, String>{};
  final _notifications = <String, List<String>>{};
  final _rationales =
      <String, ({Future<wire.Rationale> future, bool loading})>{};
  final _storedRationales = <String, wire.Rationale>{};
  final _preparationChanges = <String, List<PreparationChange>>{};
  final _initialPreparations = <String, wire.Card>{};
  final _openOrderStories = <String>{};

  void setOrderStoryOpen(String episodeId, bool open) {
    if (open) {
      _openOrderStories.add(episodeId);
    } else {
      _openOrderStories.remove(episodeId);
    }
  }

  Iterable<PreparationChange> preparationChanges(String cardId) =>
      _preparationChanges[cardId] ?? const [];
  wire.Card? initialPreparation(String cardId) => _initialPreparations[cardId];
  wire.Devices? homeInventory;
  Future<void>? _homeInventoryRefresh;

  String? _cursor;
  String? get lastServerCheck => _cursor;
  Timer? _timer;
  Timer? _closureTimer;
  DateTime? _closureDeadline;
  Duration? _pollInterval;
  bool _foreground = true;
  StreamSubscription<void>? _shareSubscription;
  Future<void> _queue = Future<void>.value();
  Future<void> _calendarQueue = Future<void>.value();
  Future<void>? _sync;
  String? _calendarFingerprint;
  bool _calendarFingerprintDirty = false;
  bool _calendarConnected = false;
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

  wire.Episode? get currentPreparationOrder {
    final ordered = orderedEpisodes;
    final candidates = demoPreview ? ordered.take(1) : ordered;
    for (final episode in candidates) {
      if (episode.status == wire.EpisodeStatus.CLOSED) continue;
      if (cardsFor(episode).isNotEmpty) return episode;
    }
    return null;
  }

  List<Uint8List> orderImages(String episodeId) =>
      _orderCaptures[episodeId]?.first ?? const [];

  List<Uint8List> sharedOrderImages(String episodeId) =>
      _orderCaptures[episodeId]?.first ?? _shownCaptures[episodeId] ?? const [];

  bool recentlyClosed(String episodeId) =>
      _recentClosures.containsKey(episodeId);

  void _scheduleClosureExpiry() {
    final next = _recentClosures.values.fold<DateTime?>(
      null,
      (earliest, expiry) =>
          earliest == null || expiry.isBefore(earliest) ? expiry : earliest,
    );
    if (next == _closureDeadline && _closureTimer?.isActive == true) return;
    _closureTimer?.cancel();
    _closureDeadline = next;
    if (next == null || _disposed) return;
    _closureTimer = Timer(next.difference(DateTime.now()), () {
      final now = DateTime.now();
      _recentClosures.removeWhere(
        (_, expiry) => !expiry.isAfter(next) || !expiry.isAfter(now),
      );
      _scheduleClosureExpiry();
      _change();
      unawaited(_serialize(_save).catchError((Object _) {}));
    });
  }

  void _queueCapture(String episodeId, List<Uint8List> images) {
    if (images.isEmpty) return;
    _orderCaptures.putIfAbsent(episodeId, Queue.new).addLast(images);
  }

  void finishOrderCapture(String episodeId, List<Uint8List> images) {
    final captures = _orderCaptures[episodeId];
    if (captures == null || !identical(captures.first, images)) return;
    _shownCaptures[episodeId] = captures.removeFirst();
    if (captures.isEmpty) _orderCaptures.remove(episodeId);
    _change();
  }

  bool stopPending(String cardId) => _pendingStops.containsKey(cardId);
  bool stopUncertain(String cardId) => _uncertainStops.contains(cardId);
  bool get canControl => !stale && !pausePending;
  bool get canResendCalendar => _calendarConnected && readCalendar != null;

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

  bool _cardIsActive(wire.Card card) {
    if (stopPending(card.cardId)) return true;
    final episode = episodes[card.episodeId];
    if (episode != null &&
        (episode.status == wire.EpisodeStatus.CLOSED ||
            !episode.cardIds.contains(card.cardId))) {
      return false;
    }
    return card.lines.any(
      (line) => switch (line.state) {
        wire.LineState.HELD ||
        wire.LineState.SCHEDULED ||
        wire.LineState.RUNNING => true,
        wire.LineState.OFF ||
        wire.LineState.CANCELLED ||
        wire.LineState.DROPPED ||
        wire.LineState.STOPPED => false,
        _ => line.endState == null,
      },
    );
  }

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
      for (final entry in (setup['choices'] as Map<String, dynamic>).entries) {
        deviceChoices[entry.key] = (entry.value as Map<String, dynamic>).map(
          (command, choice) =>
              MapEntry(command, DeviceChoice.values.byName(choice as String)),
        );
      }
    } else if (configuredHousehold != null) {
      household = configuredHousehold;
      step = SetupStep.ready;
    }
    if (household == null) return;
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
    final now = DateTime.now();
    final closures = value['recentClosures'] as Map<String, dynamic>? ?? {};
    for (final entry in closures.entries) {
      final expiry = DateTime.tryParse(entry.value as String);
      if (expiry != null &&
          expiry.isAfter(now) &&
          episodes[entry.key]?.status == wire.EpisodeStatus.CLOSED) {
        _recentClosures[entry.key] = expiry;
      }
    }
    _scheduleClosureExpiry();
    _cursor = value['cursor'] as String?;
    if (value['inventory'] case final Map<String, dynamic> inventory) {
      final manifest = wire.Devices.fromJson(inventory);
      if (manifest.householdId == household) homeInventory = manifest;
    }
    for (final data in (value['rationales'] as List<dynamic>? ?? const [])) {
      final rationale = wire.Rationale.fromJson(data as Map<String, dynamic>);
      if (episodes.containsKey(rationale.episodeId)) {
        _storedRationales[rationale.episodeId] = rationale;
      }
    }
    paused = value['paused'] as bool?;
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
      'choices': deviceChoices.map(
        (key, value) => MapEntry(
          key,
          value.map((command, choice) => MapEntry(command, choice.name)),
        ),
      ),
    }),
  );

  Future<void> _save() => store.write(
    _snapshotKey,
    jsonEncode({
      'cursor': _cursor,
      'paused': paused,
      'accepted': accepted.toList(),
      'episodes': episodes.values.map((episode) => episode.toJson()).toList(),
      'cards': cards.values.map((card) => card.toJson()).toList(),
      'recentClosures': _recentClosures.map(
        (id, expiry) => MapEntry(id, expiry.toIso8601String()),
      ),
      'rationales': _storedRationales.values
          .map((value) => value.toJson())
          .toList(),
      'inventory': homeInventory?.toJson(),
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
    if (busy) return;
    await _setup(() async {
      householdTypes
        ..clear()
        ..addAll(types);
      await _saveSetup();
      if (household == null) {
        final created = await api.createHousehold(
          wire.HouseholdCreate(householdTypes: []),
        );
        household = created.householdId;
        homeHub?.useApiKey(created.hubApiKey);
        await _saveSetup();
      }
      await api.profile(
        household!,
        wire.Profile(householdTypes: types.toList()),
      );
      step = SetupStep.calendar;
      await _saveSetup();
    });
  }

  Future<void> finishCalendar({required bool connect}) async {
    if (busy) return;
    await _setup(() async {
      if (connect) {
        final reader = readCalendar;
        if (reader == null) throw StateError('Calendar unavailable');
        await _sendCalendar(household!, await reader(interactive: true));
      }
      _calendarConnected = connect;
      step = SetupStep.devices;
      await _saveSetup();
    });
  }

  Future<void> resendCalendar() {
    final id = household;
    final reader = readCalendar;
    if (starting ||
        _disposed ||
        !_calendarConnected ||
        id == null ||
        reader == null) {
      return Future<void>.value();
    }
    // Each trigger reads after the previous request completes, so an older
    // full list can't replace a newer one.
    return _calendarQueue = _calendarQueue.then((_) async {
      if (_disposed) return;
      try {
        final calendar = await reader(interactive: false);
        if (!_disposed) await _sendCalendar(id, calendar);
      } catch (_) {
        // Leave calendar failures silent. The next trigger reads again.
      }
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

  Future<void> finishDevices(
    Map<String, Map<String, DeviceChoice>> choices,
  ) async {
    if (busy) return;
    await _setup(() async {
      deviceChoices
        ..clear()
        ..addAll(choices);
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

  void useToken(String token) {
    api.token = token;
    needsToken = false;
    _change();
    unawaited(sync());
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
        if (receipt.isNew) _onNewShare(episodeId);
        accepted.add(episodeId);
        await _save();
        final images = <Uint8List>[];
        if (receipt.isNew) {
          for (final image in order.images) {
            try {
              images.add(await image.readAsBytes());
            } on FileSystemException {
              // The upload is already accepted even if its local preview is gone.
            }
          }
        }
        await platform.acknowledge(_scope, order.sourceId, episodeId);
        _queueCapture(episodeId, images);
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
        if (receipt.isNew) {
          _onNewShare(episodeId);
          _queueCapture(episodeId, [image]);
        }
        accepted.add(episodeId);
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

  void _onNewShare(String episodeId) {
    _rationales.remove(episodeId);
    _recentClosures.clear();
    _scheduleClosureExpiry();
  }

  Future<void> _refresh() async {
    final id = household!;
    try {
      final poll = await api.cards(id, since: _cursor);
      final list = await api.episodes(id);
      final listed = list.episodes.map((row) => row.episodeId).toSet();
      final details = (await Future.wait(
        {...listed, ...accepted}.map((episodeId) async {
          try {
            final episode = await api.episode(episodeId);
            if (episode.episodeId != episodeId) {
              throw const FormatException('Wrong episode');
            }
            return episode;
          } on AppApiException catch (error) {
            if (error.status == 404 && !listed.contains(episodeId)) return null;
            rethrow;
          }
        }),
      )).whereType<wire.Episode>().toList();
      for (final episode in details) {
        if (episode.householdId != id) {
          throw const FormatException('Wrong household');
        }
      }
      final serverTime = DateTime.parse(poll.serverTime);
      final cursor = _cursor;
      if (cursor != null && serverTime.isBefore(DateTime.parse(cursor))) {
        throw const FormatException('Card cursor moved backwards');
      }
      for (final card in poll.cards) {
        DateTime.parse(card.updatedAt);
      }
      await _loadMissingHistory(id, details, poll.cards);
      final changedRationaleEpisodes = <String>{};
      for (final card in poll.cards) {
        final previous = cards[card.cardId];
        if (previous != null &&
            DateTime.parse(card.updatedAt)
                .isBefore(DateTime.parse(previous.updatedAt))) {
          continue;
        }
        if (previous == null || previous.updatedAt != card.updatedAt) {
          changedRationaleEpisodes.add(card.episodeId);
          if (previous != null) {
            final change = PreparationChange.between(previous, card);
            if (change != null) {
              _initialPreparations.putIfAbsent(card.cardId, () => previous);
              _preparationChanges
                  .putIfAbsent(card.cardId, () => [])
                  .add(change);
            }
          }
        }
        cards[card.cardId] = card;
        if (platform != null && card.notify) {
          _notifications[jsonEncode([card.cardId, card.updatedAt])] = [
            '준비 카드',
            card.text,
          ];
        }
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
      }
      final newOrders = details
          .where((episode) => !episodes.containsKey(episode.episodeId))
          .toList();
      bool superseded(wire.Episode episode) => newOrders.any(
        (order) =>
            DateTime.parse(order.sharedAt)
                .isAfter(DateTime.parse(episode.sharedAt)),
      );
      _recentClosures.removeWhere((id, _) => superseded(episodes[id]!));
      var showClosure = false;
      for (final episode in details) {
        final previous = episodes[episode.episodeId];
        if (previous?.status != episode.status ||
            !listEquals(previous?.cardIds, episode.cardIds) ||
            changedRationaleEpisodes.contains(episode.episodeId) ||
            !listEquals(
              previous?.itemTasks
                  .map((task) => (task.taskId, task.state, task.text))
                  .toList(),
              episode.itemTasks
                  .map((task) => (task.taskId, task.state, task.text))
                  .toList(),
            )) {
          _rationales.remove(episode.episodeId);
        } else if (episode.status != wire.EpisodeStatus.CLOSED &&
            _openOrderStories.contains(episode.episodeId) &&
            !loadingRationale(episode.episodeId)) {
          // An observation or another device result can arrive before the
          // card's aggregate state changes. Use the existing polling cycle.
          _rationales.remove(episode.episodeId);
        }
        if (episode.status != wire.EpisodeStatus.CLOSED) {
          _recentClosures.remove(episode.episodeId);
        } else if (previous != null &&
            previous.status != wire.EpisodeStatus.CLOSED &&
            episode.cardIds.isNotEmpty &&
            !superseded(episode)) {
          _recentClosures[episode.episodeId] = DateTime.now().add(
            _closedPreparationDuration,
          );
          showClosure = true;
        }
        episodes[episode.episodeId] = episode;
        accepted.remove(episode.episodeId);
        if (platform != null &&
            episode.status == wire.EpisodeStatus.READ_FAILED) {
          _notifications[jsonEncode(['read_failed', episode.episodeId])] = [
            '주문을 읽지 못했어요',
            '주문 화면을 캡처해서 다시 공유해 주세요.',
          ];
        }
      }
      _scheduleClosureExpiry();
      if (showClosure && homeHub != null && homeInventory == null) {
        unawaited(refreshHomeInventory().catchError((Object _) {}));
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
      // Card themes and set-aside items come from the stored rationale.
      for (final episode in episodes.values) {
        if (_disposed ||
            (cardsFor(episode).isEmpty && episode.itemTasks.isEmpty)) {
          continue;
        }
        unawaited(
          rationale(episode.episodeId)
              .then<void>((_) {}, onError: (Object _) {}),
        );
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

  Future<void> _loadMissingHistory(
    String householdId,
    List<wire.Episode> details,
    List<wire.Card> updates,
  ) async {
    final available = {...cards.keys, ...updates.map((card) => card.cardId)};
    final missing = {
      for (final episode in details)
        if (episode.status == wire.EpisodeStatus.CLOSED)
          for (final cardId in episode.cardIds)
            if (!available.contains(cardId) &&
                !_historyChecked.contains(cardId))
              cardId: episode.episodeId,
    };
    if (missing.isEmpty) return;
    try {
      // The cursorless read only returns open cards. Fetch missing history
      // without moving the live cursor or sending old notifications.
      final history = await api.cards(
        householdId,
        since: '1970-01-01T00:00:00Z',
      );
      for (final card in history.cards) {
        if (missing[card.cardId] == card.episodeId) cards[card.cardId] = card;
      }
      _historyChecked.addAll(missing.keys);
    } catch (_) {
      // Keep the live refresh usable and retry missing history next time.
    }
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
    wire.LineState.USER_CHANGED => true,
    _ => false,
  };

  String _taskKey(wire.Card card, wire.LineElement line) =>
      jsonEncode([card.cardId, line.taskId]);

  bool canSwitch(wire.Card card, wire.LineElement line) =>
      canControl &&
      !card.stopped &&
      !stopPending(card.cardId) &&
      line.endState == null &&
      !(_startedTasks[card.cardId]?.contains(line.taskId) ?? false) &&
      (line.state == wire.LineState.HELD ||
          line.state == wire.LineState.SCHEDULED ||
          line.state == wire.LineState.OFF);

  bool canEdit(wire.Episode episode) {
    if (!canControl ||
        episode.items.isEmpty ||
        accepted.contains(episode.episodeId) ||
        (episode.status != wire.EpisodeStatus.READING &&
            episode.status != wire.EpisodeStatus.JUDGED &&
            episode.status != wire.EpisodeStatus.HELD &&
            episode.status != wire.EpisodeStatus.NOTIFIED)) {
      return false;
    }
    final related = cardsFor(episode);
    return related.length == episode.cardIds.length &&
        !related.any((card) => card.stopped || stopPending(card.cardId)) &&
        !cards.values.any(
          (card) =>
              card.episodeId == episode.episodeId &&
              (_startedTasks[card.cardId]?.isNotEmpty ?? false),
        ) &&
        related.every(
          (card) => card.lines.every(
            (line) =>
                line.endState == null &&
                (line.state == wire.LineState.HELD ||
                    line.state == wire.LineState.SCHEDULED ||
                    line.state == wire.LineState.OFF ||
                    line.state == wire.LineState.CANCELLED ||
                    line.state == wire.LineState.DROPPED),
          ),
        );
  }

  Future<void> edit(wire.Episode episode, wire.OrderEdit order) async {
    await _serialize(() async {
      if (!canEdit(episodes[episode.episodeId] ?? episode)) {
        throw StateError('Edit unavailable');
      }
      final receipt = await api.editOrder(episode.episodeId, order);
      accepted.add(receipt.episodeId);
      await _save();
      _change();
      await _refresh();
    });
  }

  Future<void> stop(wire.Card card) async {
    if (!canControl ||
        episodes[card.episodeId]?.status == wire.EpisodeStatus.CLOSED ||
        card.stopped ||
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
      pendingLines.contains(_taskKey(card, line));

  Future<bool> switchLine(wire.Card card, wire.LineElement line) async {
    final key = _taskKey(card, line);
    if (!canSwitch(card, line) || !pendingLines.add(key)) return false;
    controlErrors.remove(card.cardId);
    _change();
    var switched = false;
    await _serialize(() async {
      try {
        final current = cards[card.cardId];
        final matching = current?.lines
            .where((entry) => entry.taskId == line.taskId)
            .firstOrNull;
        if (current == null ||
            matching == null ||
            !canSwitch(current, matching) ||
            matching.state != line.state) {
          return;
        }
        final updated = await api.react(
          card.cardId,
          wire.Reaction(
            reaction: line.state == wire.LineState.OFF
                ? wire.ReactionEnum.LINE_ON
                : wire.ReactionEnum.LINE_OFF,
            taskId: line.taskId,
          ),
        );
        switched =
            line.state == wire.LineState.OFF ||
            updated.lines.any(
              (entry) =>
                  entry.taskId == line.taskId &&
                  entry.state == wire.LineState.OFF,
            );
      } catch (error) {
        if (error is AppApiException &&
            error.code == wire.ErrorCode.LINE_STARTED) {
          _startedTasks.putIfAbsent(card.cardId, () => {}).add(line.taskId);
        }
        controlErrors[card.cardId] = _error(error, '준비 항목 변경을 확인하지 못했어요.');
      } finally {
        await _refresh();
        pendingLines.remove(key);
        _change();
      }
    });
    return switched;
  }

  Future<void> undoLineOff(String cardId, String taskId) async {
    final card = cards[cardId];
    if (card == null) return;
    final line = card.lines.where((line) => line.taskId == taskId).firstOrNull;
    if (line != null && line.state == wire.LineState.OFF) {
      await switchLine(card, line);
    }
  }

  Future<void> setPaused(bool value) async {
    if (pausePending) return;
    pausePending = true;
    controlErrors.remove('pause');
    _change();
    await _serialize(() async {
      try {
        paused = null;
        await _save();
        final response = await api.pause(household!, wire.Pause(paused: value));
        if (response.householdId != null && response.householdId != household) {
          throw const FormatException('Wrong household');
        }
        paused = response.paused;
      } catch (error) {
        paused = null;
        controlErrors['pause'] = _error(error, '자동 준비 상태를 확인하지 못했어요.');
      } finally {
        pausePending = false;
        await _refresh();
      }
    });
  }

  wire.Rationale? rationaleFor(String episode) => _storedRationales[episode];

  Future<wire.Rationale> rationale(String episode) {
    final cached = _storedRationales[episode];
    if (stale && cached != null) return Future.value(cached);
    return _rationales.putIfAbsent(episode, () {
      late final Future<wire.Rationale> request;
      request = api
          .rationale(episode)
          .then((rationale) {
            if (rationale.episodeId != episode) {
              throw const FormatException('Wrong episode');
            }
            if (identical(_rationales[episode]?.future, request) &&
                !_disposed) {
              _rationales[episode] = (future: request, loading: false);
              _storedRationales[episode] = rationale;
              _change();
              unawaited(_serialize(_save).catchError((Object _) {}));
            }
            return rationale;
          })
          .catchError((Object error, StackTrace stackTrace) {
            if (identical(_rationales[episode]?.future, request)) {
              _rationales.remove(episode);
              _change();
            }
            Error.throwWithStackTrace(error, stackTrace);
          });
      return (future: request, loading: true);
    }).future;
  }

  bool loadingRationale(String episode) =>
      _rationales[episode]?.loading ?? false;

  Future<void> refreshHomeInventory() => _homeInventoryRefresh ??=
      _loadHomeInventory().whenComplete(() => _homeInventoryRefresh = null);

  Future<void> _loadHomeInventory() async {
    final inventory = await homeHub?.fetchDevices(household!);
    if (_disposed || inventory == null) return;
    homeInventory = inventory;
    _change();
    await _serialize(_save).catchError((Object _) {});
  }

  Future<wire.Memory> memory() async {
    final result = await api.memory(household!);
    if (result.householdId != household) {
      throw const FormatException('Wrong household');
    }
    return result;
  }

  Future<void> deleteCase(String caseId) => api.deleteCase(household!, caseId);

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
          '선택한 ${stateWords['household_profile']} 항목을 함께 사용할 수 없어요.',
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
    _closureTimer?.cancel();
    unawaited(_shareSubscription?.cancel());
    homeHub?.close();
    super.dispose();
  }
}
