import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';

import 'api/app_api.dart';
import 'contracts.dart' as wire;
import 'platform/android_bridge.dart';
import 'platform/app_store.dart';
import 'platform/google_calendar.dart';
import 'platform/home_hub_onboarding.dart';

enum SetupStep { start, household, calendar, devices, ready }

class DevicePreparation {
  const DevicePreparation(this.card, this.line, {required this.sharedLine});

  final wire.Card card;
  final wire.LineElement line;
  final bool sharedLine;
}

const _pollInterval = Duration(seconds: 30);
const _connectionCodeHint = '설정에서 연결 코드를 입력해 주세요.';
const _homeCodeHint = '설정에서 집 허브 연결 코드를 입력해 주세요.';

class AppController extends ChangeNotifier {
  AppController({
    required this.api,
    required this.platform,
    required this.store,
    required this.fixture,
    required this.homeHub,
    this.readCalendar,
    this.configuredHousehold,
  });

  final AppApi api;
  final AppPlatform platform;
  final AppStore store;
  final bool fixture;
  final CalendarReader? readCalendar;
  final HomeHubOnboardingPort homeHub;
  final String? configuredHousehold;

  String get _environment =>
      jsonEncode([fixture, api.baseUrl.toString(), configuredHousehold]);
  String get _scope => jsonEncode([_environment, household]);
  String get _setupKey => 'spira.setup.v1.$_environment';
  String get _snapshotKey => 'spira.snapshot.v1.$_scope';
  String get _calendarKey => 'spira.calendar.v1.$_scope';

  String? household;
  SetupStep step = SetupStep.start;
  bool starting = true;
  bool busy = false;
  bool stale = true;
  bool? paused;
  bool pausePending = false;
  bool needsToken = false;
  bool refreshed = false;
  String? setupError;
  String? refreshError;
  String? uploadError;
  String? shareIssue;
  int queuedShares = 0;

  final householdTypes = <String>{};
  HomeDiscovery home = const HomeDiscovery();
  bool homeLoading = false;
  String? homeReadError;
  final _legacyDelegation = <String, Set<String>>{};
  final episodes = <String, wire.Episode>{};
  final cards = <String, wire.Card>{};
  final accepted = <String>{};
  final _startedTasks = <String, Set<String>>{};
  final _pendingStops = <String, Set<String>>{};
  final _uncertainStops = <String>{};
  final pendingLines = <String>{};
  final controlErrors = <String, String>{};
  final _notifications = <String, List<String>>{};
  final _rationales = <String, Future<wire.Rationale>>{};
  final _rationaleData = <String, wire.Rationale>{};
  bool _homeOpen = false;

  String? _cursor;
  Timer? _timer;
  StreamSubscription<void>? _shareSubscription;
  Future<void> _queue = Future<void>.value();
  Future<void> _homeQueue = Future<void>.value();
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

  bool get hasHomeHub => homeHub is HttpHomeHubOnboarding;

  Set<String>? savedDelegation(HomeDevice device) {
    final saved =
        home.settings[device.id]?.delegated ??
        (hasHomeHub ? null : _legacyDelegation[device.id]);
    return saved?.intersection(device.selectableCommands);
  }

  Map<String, List<DevicePreparation>> get devicePreparations {
    final result = <String, List<DevicePreparation>>{};
    final devices = {for (final device in home.devices) device.id: device.type};
    for (final episode in orderedEpisodes) {
      final rationale = _rationaleData[episode.episodeId];
      if (rationale == null) continue;
      final tasks = {
        for (final task in rationale.tasks) (task.cardId, task.taskId): task,
      };
      for (final card in cardsFor(episode)) {
        for (final line in card.lines) {
          final mapped = tasks[(card.cardId, line.taskId)]?.devices;
          if (mapped == null) continue;
          final ids = {for (final device in mapped) device.id};
          // The current room label can change without changing device identity.
          for (final device in mapped) {
            if (devices[device.id] == device.type && ids.remove(device.id)) {
              result
                  .putIfAbsent(device.id, () => [])
                  .add(
                    DevicePreparation(
                      card,
                      line,
                      sharedLine: mapped.length > 1,
                    ),
                  );
            }
          }
        }
      }
    }
    return result;
  }

  void openHome() {
    _homeOpen = true;
    if (hasHomeHub) unawaited(refreshHome());
    unawaited(_loadHomeRationales(refresh: true));
  }

  void closeHome() => _homeOpen = false;

  Future<void> _loadHomeRationales({bool refresh = false}) async {
    final reads = <Future<void>>[];
    for (final episode in episodes.values) {
      if (cardsFor(episode).isEmpty) continue;
      if (refresh) _invalidateRationale(episode.episodeId);
      reads.add(
        rationale(episode.episodeId).then<void>((_) {}, onError: (Object _) {}),
      );
    }
    await Future.wait(reads);
  }

  bool stopPending(String cardId) => _pendingStops.containsKey(cardId);
  bool stopUncertain(String cardId) => _uncertainStops.contains(cardId);
  bool get canControl => !stale && !pausePending;
  bool get canResendCalendar => _calendarConnected && readCalendar != null;

  Future<void> start() async {
    _shareSubscription = platform.sharesChanged.listen((_) {
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
    _startTimer();
    await Future.wait([resendCalendar(), sync()]);
  }

  void _startTimer() {
    _timer ??= Timer.periodic(_pollInterval, (_) => unawaited(sync()));
  }

  void setForeground(bool foreground) {
    if (_disposed || starting) return;
    if (foreground) {
      _startTimer();
      unawaited(resendCalendar());
      unawaited(sync());
    } else {
      _timer?.cancel();
      _timer = null;
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
      if (setup['choices'] case final Map<String, dynamic> choices) {
        for (final entry in choices.entries) {
          final commands = entry.value as Map<String, dynamic>;
          _legacyDelegation[entry.key] = {
            for (final command in commands.entries)
              if (command.value == 'delegated') command.key,
          };
        }
      }
    } else if (configuredHousehold != null) {
      household = configuredHousehold;
      step = SetupStep.ready;
    }
    if (household == null) return;
    if (step == SetupStep.devices || (step == SetupStep.ready && !hasHomeHub)) {
      await refreshHome();
    }
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

  Future<void> _saveSetup({SetupStep? nextStep}) => store.write(
    _setupKey,
    jsonEncode({
      'household': household,
      'step': (nextStep ?? step).name,
      'calendarConnected': _calendarConnected,
      'types': householdTypes.toList(),
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
    if (busy || step != SetupStep.household) return;
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
        if (homeHub case final HttpHomeHubOnboarding hub) {
          hub.useApiKey(created.hubApiKey);
        }
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

  void beginSetup() {
    step = SetupStep.household;
    _change();
  }

  Future<void> finishCalendar({required bool connect}) async {
    if (busy || step != SetupStep.calendar) return;
    await _setup(() async {
      if (connect) {
        final reader = readCalendar;
        if (reader == null) throw StateError('Calendar unavailable');
        await _sendCalendar(household!, await reader(interactive: true));
      }
      _calendarConnected = connect;
      await _saveSetup(nextStep: SetupStep.devices);
      step = SetupStep.devices;
      await refreshHome();
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

  Future<HomeSaveResult?> finishDevices(
    Map<String, HomeDeviceSettings> settings,
  ) async {
    if (busy || step != SetupStep.devices) return null;
    HomeSaveResult? result;
    await _setup(() async {
      result = await _saveHome(settings);
      await _saveSetup(nextStep: SetupStep.ready);
      step = SetupStep.ready;
    });
    if (step == SetupStep.ready) {
      _requestNotificationPermission();
      await sync();
      return result;
    }
    return null;
  }

  Future<HomeSaveResult> editHomeDevice(
    String id,
    HomeDeviceSettings settings,
  ) => _saveHome({id: settings});

  Future<T> _serializeHome<T>(Future<T> Function() work) {
    final next = _homeQueue.then((_) => work());
    _homeQueue = next.then<void>((_) {}, onError: (Object _, StackTrace _) {});
    return next;
  }

  Future<void> refreshHome() => _serializeHome(() async {
    if (!_disposed) await _readHome();
  });

  Future<bool> _readHome() async {
    homeLoading = true;
    _change();
    try {
      home = await homeHub.discover(_scope);
      homeReadError = null;
      return true;
    } catch (error) {
      homeReadError = _error(error, '기기 설정을 불러오지 못했어요.');
      return false;
    } finally {
      homeLoading = false;
      _change();
    }
  }

  Future<HomeSaveResult> _saveHome(Map<String, HomeDeviceSettings> settings) =>
      _serializeHome(() async {
        final result = await homeHub.saveRoomsNamesDelegation(
          _scope,
          home,
          settings,
        );
        if (result == HomeSaveResult.uploadPending) {
          // A peer failure can happen after the Hub has saved the settings.
          if (!await _readHome() ||
              !settings.entries.every((entry) {
                final stored = home.settings[entry.key];
                return stored != null &&
                    stored.room == entry.value.room &&
                    stored.name == entry.value.name &&
                    setEquals(stored.delegated, entry.value.delegated);
              })) {
            throw const HomeHubException(502);
          }
        } else {
          home = home.withSettings(settings);
          _change();
        }
        return result;
      });

  void useHomeHubKey(String key) {
    if (homeHub case final HttpHomeHubOnboarding hub) {
      hub.useApiKey(key);
      if (setupError == _homeCodeHint) setupError = null;
      if (step == SetupStep.devices || step == SetupStep.ready) {
        unawaited(refreshHome());
      }
    }
  }

  String homeSettingsError(Object error) =>
      _error(error, '설정을 저장하지 못했어요. 다시 시도해 주세요.');

  void _requestNotificationPermission() {
    unawaited(
      platform.requestNotificationPermission().catchError((Object _) {}),
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
    if (setupError == _connectionCodeHint) setupError = null;
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
    final id = household!;
    try {
      final inbox = await platform.inbox(_scope);
      queuedShares = inbox.orders.length;
      shareIssue = inbox.issue;
      uploadError = null;
      _change();
      for (final order in inbox.orders) {
        final wire.OrderAccepted receipt;
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
        accepted.add(receipt.episodeId);
        await _save();
        await platform.acknowledge(_scope, order.sourceId, receipt.episodeId);
        queuedShares--;
        _change();
      }
    } catch (error) {
      uploadError = _error(error, '주문을 보내지 못했어요. 다시 시도해 주세요.');
    }
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
      )).whereType<wire.Episode>();
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
      for (final card in poll.cards) {
        final previous = cards[card.cardId];
        if (previous != null &&
            DateTime.parse(card.updatedAt)
                .isBefore(DateTime.parse(previous.updatedAt))) {
          continue;
        }
        if (previous == null ||
            (_homeOpen && card.updatedAt != previous.updatedAt) ||
            !setEquals(
              previous.lines.map((line) => line.taskId).toSet(),
              card.lines.map((line) => line.taskId).toSet(),
            )) {
          _invalidateRationale(card.episodeId);
        }
        cards[card.cardId] = card;
        if (card.notify) {
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
      for (final episode in details) {
        if (episodes[episode.episodeId]?.status != episode.status) {
          _invalidateRationale(episode.episodeId);
        }
        episodes[episode.episodeId] = episode;
        accepted.remove(episode.episodeId);
        if (episode.status == wire.EpisodeStatus.READ_FAILED) {
          _notifications[jsonEncode(['read_failed', episode.episodeId])] = [
            '주문을 읽지 못했어요',
            '주문 화면을 캡처해서 다시 공유해 주세요.',
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
      refreshError = null;
    } catch (error) {
      stale = true;
      refreshError = _error(error, '새로 불러오지 못했어요. 다시 시도해 주세요.');
    }
    _change();
    await Future.wait([
      _deliverNotifications(),
      if (_homeOpen) _loadHomeRationales(),
    ]);
  }

  Future<void> _deliverNotifications() async {
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

  Future<void> switchLine(wire.Card card, wire.LineElement line) async {
    final key = _taskKey(card, line);
    if (!canSwitch(card, line) || !pendingLines.add(key)) return;
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
            matching.state != line.state) {
          return;
        }
        await api.react(
          card.cardId,
          wire.Reaction(
            reaction: line.state == wire.LineState.OFF
                ? wire.ReactionEnum.LINE_ON
                : wire.ReactionEnum.LINE_OFF,
            taskId: line.taskId,
          ),
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

  Future<wire.Rationale> rationale(String episode) {
    if (_rationales[episode] case final request?) return request;
    late final Future<wire.Rationale> request;
    request = api
        .rationale(episode)
        .then((result) {
          if (result.episodeId != episode) {
            throw const FormatException('Wrong episode');
          }
          if (_rationales[episode] == request) {
            _rationaleData[episode] = result;
            if (_homeOpen) _change();
          }
          return result;
        })
        .catchError((Object error, StackTrace stack) {
          if (_rationales[episode] == request) _rationales.remove(episode);
          Error.throwWithStackTrace(error, stack);
        });
    return _rationales[episode] = request;
  }

  void _invalidateRationale(String episode) {
    _rationales.remove(episode);
    _rationaleData.remove(episode);
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
    if (error is HomeHubException) {
      return switch (error.status) {
        401 => _homeCodeHint,
        422 =>
          error.message == null || error.message!.trim().isEmpty
              ? '집 허브가 이 설정을 받아들이지 않았어요.'
              : '집 허브가 이 설정을 받아들이지 않았어요. ${error.message}',
        502 => '전송이 아직 끝나지 않았어요. 집 허브에 저장됐는지 확인하지 못했어요.',
        503 => '집 허브에 연결할 수 없어요. 다시 시도해 주세요.',
        _ => fallback,
      };
    }
    if (error is AppApiException) {
      if (error.status == 401) {
        needsToken = true;
        return _connectionCodeHint;
      }
      return switch (error.code) {
        wire.ErrorCode.LINE_STARTED => '이미 시작된 항목은 바꿀 수 없어요.',
        wire.ErrorCode.INVALID_IMAGE => '주문 화면을 읽을 수 없어요. 다시 찍어서 공유해 주세요.',
        wire.ErrorCode.HOUSEHOLD_TYPES_INVALID => '함께 고를 수 없는 항목이 있어요.',
        _ => fallback,
      };
    }
    return fallback;
  }

  void _change() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    if (homeHub case final HttpHomeHubOnboarding hub) hub.close();
    unawaited(_shareSubscription?.cancel());
    super.dispose();
  }
}
