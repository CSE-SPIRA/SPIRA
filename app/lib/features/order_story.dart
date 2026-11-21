// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../design_vocabulary.g.dart';
import '../korean_text.dart';
import '../preparation_history.dart';
import '../theme.dart';
import 'labels.dart';
import 'rationale.dart';
import 'settings.dart';
import 'status_badge.dart';

part 'order_story_details.dart';

String closedPreparationSummary(
  AppController app,
  wire.Card card,
  wire.Rationale? rationale,
) {
  final devices = _restoredDeviceNames(app, card, rationale);
  if (devices.isEmpty) {
    return card.stopped ? '이 준비가 중지됐어요.' : '준비를 마쳤어요.';
  }
  final subject = card.stopped
      ? '준비를 중지해'
      : isPartyPreparation(card)
      ? '파티가 끝나'
      : '준비를 마쳐';
  // Zero-width breaks let a long device list wrap between names.
  final names = devices.join('·\u200B');
  final particle = _hasFinalConsonant(names) ? '을' : '를';
  return '$subject $names$particle 원래대로 돌렸어요.';
}

Set<String> _restoredDeviceNames(
  AppController app,
  wire.Card card,
  wire.Rationale? rationale,
) {
  final tasks = rationale?.tasks ?? const <wire.Task>[];
  final inventory = app.homeInventory ?? app.discovered;
  return {
    for (final task in tasks)
      if (task.cardId == card.cardId &&
          rationaleLine(task, tasks, card)?.endState == wire.EndState.RESTORED)
        for (final device in task.devices)
          _restoreDeviceName(device, inventory),
  };
}

String _restoreDeviceName(wire.Device device, wire.Devices? inventory) {
  final appliance = device.type == 'smart_plug'
      ? inventory?.devices
            .where((entry) => entry.id == device.id)
            .firstOrNull
            ?.label
            ?.trim()
      : null;
  return appliance == null || appliance.isEmpty
      ? deviceNames[device.type] ?? '기기'
      : appliance;
}

bool _hasFinalConsonant(String text) {
  final last = text.codeUnitAt(text.length - 1);
  return last >= 0xAC00 && last <= 0xD7A3 && (last - 0xAC00) % 28 != 0;
}

void openOrderStory(
  BuildContext context,
  AppController app,
  wire.Card card, {
  wire.LineElement? line,
}) {
  final navigator = Navigator.of(context);
  navigator.push<void>(
    MaterialPageRoute(builder: (_) => _OrderStory(app, card)),
  );
  if (line != null) {
    _openStoryLine(navigator, app, card, line.taskId, line.text);
  }
}

void _openStoryLine(
  NavigatorState navigator,
  AppController app,
  wire.Card card,
  String taskId,
  String text,
) {
  navigator.push<void>(
    MaterialPageRoute(builder: (_) => _StoryLine(app, card, taskId, text)),
  );
}

class _StoryData {
  _StoryData(this.app, this.card)
    : episode = app.episodes[card.episodeId],
      result = app.rationaleFor(card.episodeId);

  final AppController app;
  final wire.Card card;
  final wire.Episode? episode;
  final wire.Rationale? result;

  bool get closed =>
      episode?.status == wire.EpisodeStatus.CLOSED ||
      (episode != null && !episode!.cardIds.contains(card.cardId));

  wire.IntentElement? get intent => result?.intents
      .where((intent) => intent.cardId == card.cardId)
      .firstOrNull;

  wire.CalendarElement? get calendar => result?.evidence.calendar
      .where((event) => event.id == intent?.calendarEventId)
      .firstOrNull;

  List<wire.Task> get tasks =>
      result?.tasks.where((task) => task.cardId == card.cardId).toList() ??
      const [];

  List<String> get aside =>
      result == null ? const [] : setAsideItems(result!, episode);

  late final List<wire.Execution> executions = _orderedExecutions();

  List<wire.Execution> _orderedExecutions() {
    final sharedAt = DateTime.tryParse(episode?.sharedAt ?? '');
    final records = result?.executions ?? const <wire.Execution>[];
    return [
      for (final execution in records)
        if (sharedAt == null ||
            !DateTime.parse(execution.at).isBefore(sharedAt))
          execution,
    ]..sort((a, b) => DateTime.parse(a.at).compareTo(DateTime.parse(b.at)));
  }

  wire.Observation? get observation => result?.observations
      .where((entry) => entry.cardId == card.cardId && entry.verdict != null)
      .firstOrNull;

  wire.Task? taskFor(String id) {
    final stored = tasks;
    return stored.where((task) => task.taskId == id).firstOrNull ??
        stored
            .where((task) => rationaleLine(task, stored, card)?.taskId == id)
            .singleOrNull;
  }

  String deviceName(String id, wire.Task? task) {
    final inventory = app.homeInventory ?? app.discovered;
    final entry = inventory?.devices
        .where((device) => device.id == id)
        .firstOrNull;
    final device = task?.devices.where((device) => device.id == id).firstOrNull;
    return entry?.label ?? deviceLabel(device?.type ?? entry?.type ?? '');
  }

  String? get occasion => [
    calendar?.tags.join(' · '),
    intent?.calendarTags.join(' · '),
    intent?.situation.event,
  ].whereType<String>().where((name) => name.trim().isNotEmpty).firstOrNull;

  String get title {
    final start = card.startsAt;
    final name = occasion;
    if (name == null) return card.text;
    return '${start == null ? name : scheduleDayLabel(start, name)} 준비';
  }
}

class _OrderStory extends StatefulWidget {
  const _OrderStory(this.app, this.initialCard);
  final AppController app;
  final wire.Card initialCard;

  @override
  State<_OrderStory> createState() => _OrderStoryState();
}

class _OrderStoryState extends State<_OrderStory> {
  bool _expanded = false;
  late final _request = widget.app.rationale(widget.initialCard.episodeId);

  @override
  void initState() {
    super.initState();
    widget.app.setOrderStoryOpen(widget.initialCard.episodeId, true);
  }

  @override
  void dispose() {
    widget.app.setOrderStoryOpen(widget.initialCard.episodeId, false);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<wire.Rationale>(
    future: _request,
    builder: (context, snapshot) => ListenableBuilder(
      listenable: widget.app,
      builder: (context, _) => _story(context, snapshot),
    ),
  );

  Widget _story(BuildContext context, AsyncSnapshot<wire.Rationale> request) {
    final app = widget.app;
    final card = app.cards[widget.initialCard.cardId] ?? widget.initialCard;
    final data = _StoryData(app, card);
    final reasons = _judgmentReasons(data);
    final theme = Theme.of(context);
    final intent = data.intent;
    final episode = data.episode;
    final initial = app.initialPreparation(card.cardId) ?? card;
    final loading =
        app.loadingRationale(card.episodeId) ||
        request.connectionState != ConnectionState.done;
    return EvidencePage(
      title: data.title,
      children: [
        _StorySummary(data),
        _Timeline([
          if (episode != null)
            _TimelineRow(
              heading: '주문을 읽었어요',
              moment: seoulDateTime(episode.sharedAt),
              detail: [
                '${episode.itemCount}개',
                if (data.aside.isNotEmpty) '따로 본 물건 ${data.aside.join(' · ')}',
              ].join(' · '),
            ),
          if (intent != null)
            _TimelineRow(
              heading: '이렇게 판단했어요',
              emphasis: true,
              expand: _expanded,
              onTap: () => setState(() => _expanded = !_expanded),
              extra: _expanded
                  ? _ExpandedJudgment(data, reasons)
                  : Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      spacing: DesignTokens.space4,
                      children: [
                        KoreanText.rich(
                          highlightTheme(
                            intent.intentText,
                            intent.situation.theme,
                            DesignTokens.pinkInk,
                          ),
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: DesignTokens.muted,
                          ),
                        ),
                        if (reasons.isNotEmpty)
                          EvidenceChips(
                            reasons.map((reason) => reason.chip).toList(),
                          ),
                      ],
                    ),
            ),
          _TimelineRow(heading: '할 일 ${initial.lines.length}개를 정했어요'),
          for (final entry in _storyEntries(data))
            _TimelineRow(
              key: ValueKey(entry.id),
              heading: entry.title,
              moment: entry.at == null || !entry.showTime
                  ? null
                  : '${entry.timePrefix}${seoulDateTime(entry.at!)}',
              detail: entry.detail,
              emphasis: entry.observation != null,
              extra: entry.observation != null
                  ? _StoryObservation(data, entry.observation!)
                  : null,
              onTap: entry.taskId == null
                  ? null
                  : () => _openStoryLine(
                      Navigator.of(context),
                      app,
                      card,
                      entry.taskId!,
                      entry.title,
                    ),
            ),
          if (!data.closed && !card.stopped)
            for (final line in card.lines)
              if (_isUpcoming(line) && line.endState == null)
                _TimelineRow(
                  key: ValueKey(line.taskId),
                  heading: _lineTitle(line.text),
                  moment: lineTimeLabel(line) ?? lineLabel(line.state),
                  upcoming: true,
                  onTap: () => _openStoryLine(
                    Navigator.of(context),
                    app,
                    card,
                    line.taskId,
                    line.text,
                  ),
                ),
        ]),
        if (data.result == null && !loading)
          const EvidenceCaption('저장된 이유를 볼 수 없어요.'),
        _FullEvidenceLink(app, card.episodeId),
      ],
    );
  }
}

String _lineTitle(String text) => text.split(' (').first;

bool _isUpcoming(wire.LineElement line) =>
    line.state == wire.LineState.HELD || line.state == wire.LineState.SCHEDULED;

class _StoryEntry {
  const _StoryEntry({
    required this.id,
    required this.title,
    this.detail,
    this.at,
    this.showTime = true,
    this.timePrefix = '',
    this.taskId,
    this.observation,
  });

  final Object id;
  final String title;
  final String? detail;
  final String? at;
  final bool showTime;
  final String timePrefix;
  final String? taskId;
  final wire.Observation? observation;
}

Iterable<_StoryEntry> _storyEntries(_StoryData data) sync* {
  final card = data.card;
  final changes = data.app.preparationChanges(card.cardId);
  final observedOff = {
    for (final change in changes)
      for (final line in change.switchedOff) line.taskId,
  };
  final initiallyOff = card.lines.where(
    (line) =>
        line.state == wire.LineState.OFF && !observedOff.contains(line.taskId),
  );
  if (initiallyOff.isNotEmpty) {
    yield _StoryEntry(
      id: 'lines-already-off',
      title: '준비를 바꿨어요',
      detail: _switchNote(initiallyOff, on: false),
    );
  }

  final runs = <String, List<wire.Execution>>{};
  for (final run in data.executions) {
    runs.putIfAbsent(run.taskId, () => []).add(run);
  }
  final entries = [
    for (final change in changes)
      _StoryEntry(
        id: ('plan', change.revision),
        title: '준비를 바꿨어요',
        detail: _changeText(change),
        at: change.revision,
        showTime: false,
      ),
    ..._noticeEntries(data.episode?.itemTasks ?? const [], runs),
    for (final line in card.lines)
      if (!_isUpcoming(line) && line.state != wire.LineState.OFF)
        _lineEntry(line, runs[line.taskId] ?? const []),
  ];
  final ordered =
      [
        for (final (index, entry) in entries.indexed)
          if (entry.at case final at?) (DateTime.parse(at), index, entry),
      ]..sort((a, b) {
        final dateOrder = a.$1.compareTo(b.$1);
        return dateOrder == 0 ? a.$2.compareTo(b.$2) : dateOrder;
      });
  yield* ordered.map((row) => row.$3);
  yield* entries.where((entry) => entry.at == null);

  if (_restoreEntry(data) case final entry?) yield entry;
  if (data.observation case final observation?) {
    yield _StoryEntry(
      id: 'observation',
      title: '판단을 확인했어요',
      observation: observation,
    );
  }
}

_StoryEntry _lineEntry(wire.LineElement line, List<wire.Execution> runs) {
  final latestByDevice =
      {for (final run in runs) run.device: run}.values.toList()
        ..sort((a, b) => DateTime.parse(a.at).compareTo(DateTime.parse(b.at)));
  final moment = switch (line.state) {
    wire.LineState.RUNNING => runs.where(_startedExecution).firstOrNull?.at,
    wire.LineState.DONE
        when latestByDevice.every(
          (run) => run.status == wire.ExecutionStatus.COMPLETED,
        ) =>
      latestByDevice.lastOrNull?.at,
    wire.LineState.PARTIAL
        when latestByDevice.any(
              (run) => run.status == wire.ExecutionStatus.COMPLETED,
            ) &&
            latestByDevice.any((run) => !_startedExecution(run)) &&
            latestByDevice.every(
              (run) => run.status != wire.ExecutionStatus.RUNNING,
            ) =>
      latestByDevice.last.at,
    wire.LineState.FAILED || wire.LineState.BLOCKED || wire.LineState.UNKNOWN
        when latestByDevice.any(
              (run) => _executionLineState(run.status) == line.state,
            ) &&
            latestByDevice.every((run) => !_startedExecution(run)) =>
      latestByDevice.last.at,
    // The App reads the device execution time, while S7 gives the change as
    // a relative number of minutes. Keep the execution time labeled as such.
    wire.LineState.USER_CHANGED =>
      runs
          .where((run) => run.status == wire.ExecutionStatus.COMPLETED)
          .lastOrNull
          ?.at,
    _ => null,
  };
  return _StoryEntry(
    id: line.taskId,
    title: _lineTitle(line.text),
    detail: [
      lineLabel(line.state),
      if (line.endState != wire.EndState.KEPT_USER_CHANGE) ?line.note,
    ].join(' · '),
    taskId: line.taskId,
    at: moment,
    timePrefix: line.state == wire.LineState.USER_CHANGED ? '실행 ' : '',
  );
}

bool _startedExecution(wire.Execution run) =>
    run.status == wire.ExecutionStatus.RUNNING ||
    run.status == wire.ExecutionStatus.COMPLETED;

Iterable<_StoryEntry> _noticeEntries(
  List<wire.ItemTaskElement> items,
  Map<String, List<wire.Execution>> runs,
) sync* {
  final notices = <(bool, int?), List<({String label, String? at})>>{};
  for (final item in items) {
    if (!{
      wire.LineState.DONE,
      wire.LineState.PARTIAL,
      wire.LineState.RUNNING,
      wire.LineState.USER_CHANGED,
    }.contains(item.state)) {
      continue;
    }
    final showing = item.state == wire.LineState.RUNNING;
    final at = runs[item.taskId]
        ?.where(
          (run) => showing
              ? _startedExecution(run)
              : run.status == wire.ExecutionStatus.COMPLETED,
        )
        .firstOrNull
        ?.at;
    final minute = at == null ? null : _minute(DateTime.parse(at));
    final label = switch (item.kind) {
      wire.NoticeKind.STORAGE => '${item.item} 보관 방법',
      wire.NoticeKind.PREP => '${item.item} 준비 방법',
      null => item.item,
    };
    notices.putIfAbsent((showing, minute), () => []).add((
      label: label,
      at: at,
    ));
  }
  for (final MapEntry(key: (showing, minute), value: items)
      in notices.entries) {
    final times = [
      for (final item in items)
        if (item.at case final at?) DateTime.parse(at),
    ]..sort();
    yield _StoryEntry(
      id: ('notice', showing, minute),
      title: showing ? '냉장고에 안내를 띄우는 중이에요' : '냉장고에 안내를 띄웠어요',
      detail: items.map((item) => item.label).join(' · '),
      at: times.firstOrNull?.toIso8601String(),
    );
  }
}

_StoryEntry? _restoreEntry(_StoryData data) {
  final card = data.card;
  final restored = card.lines.any(
    (line) => line.endState == wire.EndState.RESTORED,
  );
  final kept = <String>{};
  var keptUnknownDevice = false;
  final otherOutcomes = <String>[];
  for (final line in card.lines) {
    if (line.endState == wire.EndState.KEPT_USER_CHANGE) {
      final changes = data.observation?.taskFeedback
          .where((entry) => entry.taskId == line.taskId)
          .firstOrNull
          ?.changes;
      final task = data.taskFor(line.taskId);
      if (changes?.isNotEmpty == true) {
        kept.addAll(changes!.map((change) => deviceLabel(change.deviceType)));
      } else if (task?.devices.singleOrNull case final device?) {
        kept.add(
          _restoreDeviceName(
            device,
            data.app.homeInventory ?? data.app.discovered,
          ),
        );
      } else {
        keptUnknownDevice = true;
      }
    } else if (endLabel(line.endState) case final detail?
        when line.endState != wire.EndState.RESTORED) {
      otherOutcomes.add('${_lineTitle(line.text)} · $detail');
    }
  }
  if (!data.closed &&
      !restored &&
      kept.isEmpty &&
      !keptUnknownDevice &&
      otherOutcomes.isEmpty) {
    return null;
  }
  final devices = _restoredDeviceNames(data.app, card, data.result);
  return _StoryEntry(
    id: 'end',
    title: restored
        ? '원래대로 돌렸어요'
        : data.closed
        ? (card.stopped ? '준비를 중지했어요' : '준비가 끝났어요')
        : '되돌리기 결과',
    detail: [
      if (devices.isNotEmpty) devices.join(' · '),
      for (final name in kept)
        '$name${_hasFinalConsonant(name) ? '은' : '는'} 바꾸신 그대로 두었어요',
      if (keptUnknownDevice) '바꾸신 기기 설정은 그대로 두었어요',
      ...otherOutcomes,
    ].join('\n'),
  );
}

int _minute(DateTime time) =>
    time.millisecondsSinceEpoch ~/ Duration.millisecondsPerMinute;

String _switchNote(Iterable<wire.LineElement> lines, {required bool on}) =>
    '${lines.map((line) => '‘${_lineTitle(line.text)}’').join(' · ')} ${on ? '항목을 다시 켰어요.' : '항목을 껐어요.'}';

String _changeText(PreparationChange change) => [
  if (change.switchedOff.isNotEmpty) _switchNote(change.switchedOff, on: false),
  if (change.switchedOn.isNotEmpty) _switchNote(change.switchedOn, on: true),
  if (change.timingChanged) '준비할 시간이 바뀌었어요.',
  if (change.tasksChanged && change.switchedOn.isEmpty) '할 일이 바뀌었어요.',
].join(' ');

wire.LineState _executionLineState(wire.ExecutionStatus status) =>
    switch (status) {
      wire.ExecutionStatus.COMPLETED => wire.LineState.DONE,
      wire.ExecutionStatus.RUNNING => wire.LineState.RUNNING,
      wire.ExecutionStatus.BLOCKED => wire.LineState.BLOCKED,
      wire.ExecutionStatus.FAILED => wire.LineState.FAILED,
      wire.ExecutionStatus.UNKNOWN ||
      wire.ExecutionStatus.UNVERIFIABLE => wire.LineState.UNKNOWN,
    };

String _executionLabel(wire.ExecutionStatus status) =>
    lineLabel(_executionLineState(status));

class _StorySummary extends StatelessWidget {
  const _StorySummary(this.data);
  final _StoryData data;

  @override
  Widget build(BuildContext context) {
    final card = data.card;
    final count = '${card.summary.total}개 중 ${card.summary.done}개 끝남';
    final title = data.closed
        ? closedPreparationSummary(data.app, card, data.result)
        : card.stopped
        ? '이 준비가 중지됐어요.'
        : switch (card.summary.waitingFor ??
              card.lines
                  .where((line) => _isUpcoming(line) && line.endState == null)
                  .map((line) => line.when?.event)
                  .whereType<wire.TriggerEvent>()
                  .firstOrNull) {
            wire.TriggerEvent.GUEST_ARRIVED => '손님 오시기를 기다리고 있어요',
            wire.TriggerEvent.EVENT_END => '일정이 끝나기를 기다리고 있어요',
            wire.TriggerEvent.PACKAGE_BROUGHT_IN => '택배를 집 안으로 들이기를 기다리고 있어요',
            null => count,
          };
    final off = card.lines.where((line) => line.state == wire.LineState.OFF);
    return EvidencePanel(
      border: DesignTokens.greenLine,
      child: Semantics(
        liveRegion: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          spacing: DesignTokens.space4,
          children: [
            EvidenceCaption(data.closed ? '끝났어요' : '지금'),
            KoreanText(
              title,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontSize: DesignTokens.size17,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (!data.closed &&
                !card.stopped &&
                (title != count || off.isNotEmpty))
              EvidenceCaption(
                [
                  if (title != count) count,
                  if (off.isNotEmpty) _switchNote(off, on: false),
                ].join(' · '),
              ),
          ],
        ),
      ),
    );
  }
}

class _Timeline extends StatelessWidget {
  const _Timeline(this.entries);
  final List<Widget> entries;

  @override
  Widget build(BuildContext context) => Stack(
    children: [
      const Positioned(
        left: DesignTokens.space4,
        top: DesignTokens.space8,
        bottom: DesignTokens.space8,
        child: VerticalDivider(
          width: DesignTokens.space4,
          color: DesignTokens.line,
        ),
      ),
      Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: entries),
    ],
  );
}

class _TimelineRow extends StatelessWidget {
  const _TimelineRow({
    super.key,
    required this.heading,
    this.moment,
    this.detail,
    this.extra,
    this.onTap,
    this.emphasis = false,
    this.upcoming = false,
    this.expand,
  });

  final String heading;
  final String? moment;
  final String? detail;
  final Widget? extra;
  final VoidCallback? onTap;
  final bool emphasis;
  final bool upcoming;
  final bool? expand;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final headingColor = emphasis
        ? DesignTokens.pinkInk
        : upcoming
        ? DesignTokens.muted
        : DesignTokens.ink;
    final header = Padding(
      padding: const EdgeInsets.symmetric(vertical: DesignTokens.space4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Column(
              spacing: DesignTokens.space4,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (moment case final label?) EvidenceCaption(label),
                KoreanText(
                  heading,
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: headingColor,
                    fontSize: DesignTokens.size15,
                    fontWeight: upcoming ? FontWeight.w500 : FontWeight.w600,
                  ),
                ),
                if (detail case final text? when text.isNotEmpty)
                  EvidenceCaption(text),
              ],
            ),
          ),
          if (onTap != null)
            Icon(
              switch (expand) {
                true => Icons.expand_less,
                false => Icons.expand_more,
                null => Icons.chevron_right,
              },
              size: DesignTokens.size18,
              color: headingColor,
            ),
        ],
      ),
    );
    return Padding(
      padding: const EdgeInsets.only(bottom: DesignTokens.space8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(
              top: DesignTokens.space8,
              right: DesignTokens.space8,
            ),
            child: Icon(
              upcoming ? Icons.radio_button_unchecked : Icons.circle,
              size: DesignTokens.size12,
              color: upcoming ? DesignTokens.greenLine : DesignTokens.green,
            ),
          ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (onTap == null)
                  header
                else
                  Semantics(
                    expanded: expand,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(DesignTokens.radius8),
                      onTap: onTap,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(
                          minHeight: DesignTokens.space48,
                        ),
                        child: header,
                      ),
                    ),
                  ),
                ?extra,
              ],
            ),
          ),
        ],
      ),
    );
  }
}
