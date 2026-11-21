// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_vocabulary.g.dart';
import '../theme.dart';
import '../korean_text.dart';
import 'labels.dart';
import 'order_extraction.dart';
import 'setup.dart';
import 'status_badge.dart';

typedef RationaleTaskLink = ({String cardId, String taskId});
typedef _BasisLabels = List<String> Function(
  List<String> sources, {
  bool productName,
});

_BasisLabels _basisLabelsFor(
  wire.Rationale result,
  Iterable<wire.EpisodeItem> items,
) {
  final itemsByType = {for (final item in items) item.type: item};
  final calendar = {
    for (final event in result.evidence.calendar) event.id: event,
  };
  return (sources, {productName = false}) => [
    for (final source in sources.toSet())
      if (calendar[source] case final event?)
        _calendarLabel(event)
      else if (source == '가구 유형')
        stateWords['household_profile']!
      else if (itemsByType[source] case final item?)
        if (productName && item.name.trim().isNotEmpty)
          item.name
        else
          item.type,
  ];
}

List<(String, String?, List<String>)> _situationSlots(
  wire.IntentElement intent,
) => [
  ('행사', intent.situation.event, intent.basis.event),
  ('손님', intent.situation.guests, intent.basis.guests),
  ('활동', intent.situation.activity, intent.basis.activity),
  ('테마', intent.situation.theme, intent.basis.theme),
];

class OrderJudgment extends StatelessWidget {
  const OrderJudgment({
    super.key,
    required this.step,
    required this.result,
    required this.episode,
  });

  final JudgmentStep step;
  final wire.Rationale result;
  final wire.Episode episode;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final basisLabels = _basisLabelsFor(result, episode.items);
    final title = switch (step) {
      JudgmentStep.situation => '상황',
      JudgmentStep.intent => '의도',
      JudgmentStep.tasks => '할 일',
    };
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0.0, end: 1.0),
      duration: MediaQuery.disableAnimationsOf(context)
          ? Duration.zero
          : appSettle,
      curve: appEase,
      builder: (context, progress, child) =>
          Opacity(opacity: progress, child: child),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 8,
        children: [
          Semantics(
            header: true,
            liveRegion: true,
            child: KoreanText(title, style: theme.textTheme.titleMedium),
          ),
          if (step == JudgmentStep.situation)
            for (final intent in result.intents)
              _Panel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  spacing: 6,
                  children: [
                    for (final (label, value, sources) in _situationSlots(
                      intent,
                    ))
                      _EvidenceRow(
                        title:
                            '$label · ${value == null || value.trim().isEmpty ? '알 수 없어요' : value}',
                        detail: basisLabels(
                          sources,
                          productName: label == '테마',
                        ).join(' · '),
                      ),
                  ],
                ),
              ),
          if (step == JudgmentStep.intent) ...[
            for (final intent in result.intents)
              _IntentPanel(
                sentence: intent.intentText,
                themePhrase: intent.situation.theme,
                clues: basisLabels(intent.basis.intent),
                showLabel: false,
              ),
            if (result.unbundled.isNotEmpty)
              KoreanText(
                '이번 준비와 상관없는 물건 ${result.unbundled.length}개',
                style: theme.textTheme.bodySmall,
              ),
          ],
          if (step == JudgmentStep.tasks)
            _Panel(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final (index, task) in result.tasks.indexed) ...[
                    if (index > 0) const Divider(height: 14),
                    KoreanText(task.line, style: theme.textTheme.bodyMedium),
                  ],
                ],
              ),
            ),
        ],
      ),
    );
  }
}

void openRationale(
  BuildContext context,
  AppController app,
  String episode, {
  RationaleTaskLink? focus,
}) {
  late final rationale = app.rationale(episode);
  Navigator.push<void>(
    context,
    MaterialPageRoute(
      builder: (_) =>
          _RationaleScreen(app: app, rationale: rationale, focus: focus),
    ),
  );
}

class _RationaleScreen extends StatelessWidget {
  const _RationaleScreen({
    required this.app,
    required this.rationale,
    required this.focus,
  });

  final AppController app;
  final Future<wire.Rationale> rationale;
  final RationaleTaskLink? focus;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const KoreanText('판단 근거')),
    body: SafeArea(
      top: false,
      child: FutureBuilder<wire.Rationale>(
        future: rationale,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(
              child: CircularProgressIndicator(semanticsLabel: '준비 이유 불러오는 중'),
            );
          }
          final result = snapshot.data;
          if (result == null) {
            return const Center(child: StatusMessage('저장된 이유를 볼 수 없어요.'));
          }
          return ListenableBuilder(
            listenable: app,
            builder: (context, _) => _RationaleContent(
              result: app.rationaleFor(result.episodeId) ?? result,
              app: app,
              focus: focus,
            ),
          );
        },
      ),
    ),
  );
}

wire.LineElement? rationaleLine(
  wire.Task task,
  List<wire.Task> tasks,
  wire.Card? card,
) {
  if (card == null) return null;
  final exact = card.lines
      .where((line) => line.taskId == task.taskId)
      .firstOrNull;
  if (exact != null) return exact;
  // Re-enabling a line assigns a new task number. Reuse the basis only
  // when the task name and displayed line still agree within this card.
  String taskName(String id) => id.split('#').first;
  bool matches(String id, String text) =>
      text == task.line && taskName(id) == taskName(task.taskId);
  final matchingBasis = tasks.where(
    (other) => other.cardId == task.cardId && matches(other.taskId, other.line),
  );
  if (matchingBasis.singleOrNull == null) return null;
  final taskIds = {
    for (final other in tasks)
      if (other.cardId == task.cardId) other.taskId,
  };
  return card.lines
      .where(
        (line) =>
            !taskIds.contains(line.taskId) && matches(line.taskId, line.text),
      )
      .singleOrNull;
}

class _RationaleContent extends StatefulWidget {
  const _RationaleContent({
    required this.result,
    required this.app,
    required this.focus,
  });

  final wire.Rationale result;
  final AppController app;
  final RationaleTaskLink? focus;

  @override
  State<_RationaleContent> createState() => _RationaleContentState();
}

class _RationaleContentState extends State<_RationaleContent> {
  final _taskAnchor = GlobalKey();
  final _situationAnchor = GlobalKey();

  @override
  void initState() {
    super.initState();
    if (widget.focus != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _reveal(_taskAnchor));
    }
  }

  void _reveal(GlobalKey anchor, {bool animate = false}) {
    if (anchor.currentContext case final target?) {
      Scrollable.ensureVisible(
        target,
        alignment: 0.05,
        duration: animate && !MediaQuery.disableAnimationsOf(target)
            ? appSettle
            : Duration.zero,
        curve: appEase,
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final result = widget.result;
    final app = widget.app;
    final episode = app.episodes[result.episodeId];
    final items = episode?.items ?? const [];
    final calendar = {
      for (final event in result.evidence.calendar) event.id: event,
    };
    final linkedEvents = {
      for (final intent in result.intents) ?calendar[intent.calendarEventId],
    };
    final scheduleStarts = {
      for (final intent in result.intents)
        if (intent.cardId case final cardId?
            when calendar.containsKey(intent.calendarEventId))
          cardId: app.cards[cardId]?.startsAt,
    };
    wire.LineElement? cardLine(String cardId, String taskId) => app
        .cards[cardId]
        ?.lines
        .where((line) => line.taskId == taskId)
        .firstOrNull;

    final liveLines = {
      for (final task in result.tasks)
        task: rationaleLine(task, result.tasks, app.cards[task.cardId]),
    };
    final shared = episode == null ? null : DateTime.parse(episode.sharedAt);
    final runTimes = <String, DateTime>{};
    for (final execution in result.executions) {
      if (execution.status != wire.ExecutionStatus.RUNNING &&
          execution.status != wire.ExecutionStatus.COMPLETED) {
        continue;
      }
      final time = DateTime.parse(execution.at);
      if (shared == null || time.isBefore(shared)) continue;
      final first = runTimes[execution.taskId];
      if (first == null || time.isBefore(first)) {
        runTimes[execution.taskId] = time;
      }
    }

    String? immediateTime(wire.LineElement? line) {
      final time = line?.when?.time;
      if (time == null ||
          shared == null ||
          !DateTime.parse(time).isBefore(shared)) {
        return null;
      }
      return seoulDateTime(
        (runTimes[line!.taskId] ?? shared).toIso8601String(),
      );
    }

    final focus = widget.focus;
    final focusedTask = focus == null
        ? null
        : result.tasks
              .where(
                (task) =>
                    task.cardId == focus.cardId &&
                    (task.taskId == focus.taskId ||
                        liveLines[task]?.taskId == focus.taskId),
              )
              .firstOrNull;
    final unmatchedLine = focus != null && focusedTask == null
        ? cardLine(focus.cardId, focus.taskId)
        : null;
    // The card links the task to its intent and the intent's situation.
    final focusedIntent = focusedTask != null || unmatchedLine != null
        ? result.intents
              .where((intent) => intent.cardId == focus?.cardId)
              .firstOrNull
        : null;
    final showSituation = focusedIntent == null
        ? null
        : () => _reveal(_situationAnchor, animate: true);

    final basisLabels = _basisLabelsFor(result, items);

    final orders = _ChainSection(
      title: '주문에서 읽은 것',
      children: [
        if (episode != null && (items.isNotEmpty || episode.maskedCount > 0))
          OrderItemList(episode: episode, unbundled: result.unbundled),
      ],
    );

    final situation = _ChainSection(
      title: '알아낸 상황',
      children: [
        for (final intent in result.intents)
          _Situation(
            key: intent == focusedIntent ? _situationAnchor : null,
            intent: intent,
            basisLabels: basisLabels,
            showTask: intent == focusedIntent
                ? () => _reveal(_taskAnchor, animate: true)
                : null,
          ),
      ],
    );

    final tasks = _ChainSection(
      title: '그래서 집이 할 일',
      children: [
        if (unmatchedLine != null)
          _TaskPanel(
            key: _taskAnchor,
            current: unmatchedLine,
            scheduleStart: scheduleStarts[focus?.cardId],
            immediateTime: immediateTime(unmatchedLine),
            selected: true,
            showSituation: showSituation,
          ),
        for (final task in result.tasks)
          _TaskPanel(
            key: task == focusedTask ? _taskAnchor : null,
            task: task,
            current: liveLines[task],
            scheduleStart: scheduleStarts[task.cardId],
            immediateTime: immediateTime(liveLines[task]),
            selected: task == focusedTask,
            showSituation: task == focusedTask ? showSituation : null,
          ),
      ],
    );
    final notices = _ChainSection(
      title: '냉장고 안내',
      children: [
        for (final notice in result.itemTasks)
          if (notice.text case final detail? when detail.trim().isNotEmpty)
            _Panel(
              child: _EvidenceRow(title: notice.item, detail: detail),
            ),
      ],
    );

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 600),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              orders,
              _ContextSection(
                evidence: result.evidence,
                linkedEvents: linkedEvents,
              ),
              situation,
              if (result.intents.isEmpty &&
                  (result.noneReason?.trim().isNotEmpty ?? false))
                Padding(
                  padding: const EdgeInsets.only(bottom: 24),
                  child: _Panel(child: KoreanText(result.noneReason!)),
                ),
              tasks,
              notices,
            ],
          ),
        ),
      ),
    );
  }
}

class _ContextSection extends StatelessWidget {
  const _ContextSection({required this.evidence, required this.linkedEvents});

  final wire.Evidence evidence;
  final Set<wire.CalendarElement> linkedEvents;

  static final _rarePurchase = RegExp(r'^(\d+)일에 (\d+)번 산 드문 물건$');

  String _unusualReason(String reason) {
    final match = _rarePurchase.firstMatch(reason);
    return match == null ? reason : '지난 ${match[1]}일 동안 ${match[2]}번 샀어요';
  }

  @override
  Widget build(BuildContext context) {
    final counts = evidence.kbCounts ?? const [];
    final examples = evidence.kbExamples;
    final unusual = evidence.unusualItems?.items ?? const [];
    final intentNames = {
      for (final count in counts)
        count.intentId: count.intentId == 'none'
            ? stateWords['order_without_preparation']!
            : count.name,
    };
    return _ChainSection(
      title: '이 집과 함께 본 것',
      children: [
        if (linkedEvents.isNotEmpty)
          _EvidenceGroup(
            title: '연결된 일정',
            rows: [
              for (final event in linkedEvents)
                _EvidenceRow(
                  title: _calendarLabel(event),
                  detail:
                      '${event.day} ${event.start}–${event.day} ${event.end}',
                ),
            ],
          ),
        if (unusual.isNotEmpty)
          _EvidenceGroup(
            title: '평소와 달랐던 물건',
            rows: [
              for (final entry in unusual)
                _EvidenceRow(
                  title: entry.item,
                  detail: _unusualReason(entry.why),
                ),
            ],
          ),
        if (counts.isNotEmpty || examples.isNotEmpty)
          _EvidenceGroup(
            title: '비슷한 주문',
            rows: [
              if (counts.isNotEmpty)
                _Chips([
                  for (final count in counts)
                    '${intentNames[count.intentId]} ${count.n}건',
                ]),
              for (final example in examples)
                _EvidenceRow(
                  title:
                      example.intentText ??
                      intentNames[example.intentId] ??
                      '비슷한 주문',
                  detail: [
                    '${example.overlap.n}개 중 ${example.overlap.k}개가 같아요',
                    ...example.overlap.items,
                  ].join(' · '),
                ),
            ],
          ),
      ],
    );
  }
}

class _Situation extends StatelessWidget {
  const _Situation({
    super.key,
    required this.intent,
    required this.basisLabels,
    required this.showTask,
  });

  final wire.IntentElement intent;
  final _BasisLabels basisLabels;
  final VoidCallback? showTask;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final situation = intent.situation;
    final basis = intent.basis;
    final selected = showTask != null;
    final slots = _situationSlots(intent);
    final firstConnected = slots.indexWhere(
      (slot) => slot.$2?.trim().isNotEmpty ?? false,
    );
    final caption = theme.textTheme.bodySmall?.copyWith(
      color: colors.onSurfaceVariant,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (selected)
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: KoreanText('선택한 할 일의 근거'),
          ),
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: [
              Expanded(
                flex: 6,
                child: KoreanText('주문과 일정에서 찾은 근거', style: caption),
              ),
              const SizedBox(width: _proofGap),
              Expanded(flex: 5, child: KoreanText('짐작한 상황', style: caption)),
              const SizedBox(width: _proofGap),
            ],
          ),
        ),
        for (final (index, (label, value, sources)) in slots.indexed)
          _ProofRow(
            slot: _SituationSlot(
              label: label,
              value: value,
              isTheme: label == '테마',
              selected: selected,
            ),
            clues: basisLabels(sources, productName: label == '테마'),
            hasValue: value?.trim().isNotEmpty ?? false,
            branch: firstConnected >= 0 && index >= firstConnected,
            first: index == firstConnected,
          ),
        _IntentPanel(
          sentence: intent.intentText,
          themePhrase: situation.theme,
          clues: basisLabels(basis.intent),
        ),
        if (selected)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: showTask,
              icon: const Icon(Icons.arrow_downward),
              label: const KoreanText('선택한 할 일 보기'),
            ),
          ),
      ],
    );
  }
}

const _proofGap = 16.0;

class _ProofRow extends StatelessWidget {
  const _ProofRow({
    required this.slot,
    required this.clues,
    required this.hasValue,
    required this.branch,
    required this.first,
  });

  final Widget slot;
  final List<String> clues;
  final bool hasValue;
  final bool branch;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final line = Theme.of(context).colorScheme.outline;
    return CustomPaint(
      painter: branch ? _IntentBranch(line, first, hasValue) : null,
      child: Padding(
        padding: const EdgeInsets.only(right: _proofGap, bottom: 8),
        child: Row(
          children: [
            Expanded(
              flex: 6,
              child: _Panel(
                padding: const EdgeInsets.all(8),
                child: _Chips(clues, onSurface: true),
              ),
            ),
            SizedBox(
              width: _proofGap,
              child: clues.isNotEmpty && hasValue
                  ? Row(
                      children: [
                        Expanded(
                          child: ColoredBox(
                            color: line,
                            child: const SizedBox(height: 1),
                          ),
                        ),
                        Container(
                          width: 4,
                          height: 4,
                          decoration: BoxDecoration(
                            color: appGreen,
                            shape: BoxShape.circle,
                          ),
                        ),
                      ],
                    )
                  : null,
            ),
            Expanded(flex: 5, child: slot),
          ],
        ),
      ),
    );
  }
}

class _IntentBranch extends CustomPainter {
  const _IntentBranch(this.color, this.first, this.hasValue);

  final Color color;
  final bool first;
  final bool hasValue;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = color;
    final x = size.width - _proofGap / 2;
    final y = (size.height - 8) / 2;
    if (hasValue) {
      canvas.drawLine(Offset(size.width - _proofGap, y), Offset(x, y), paint);
    }
    canvas.drawLine(Offset(x, first ? y : 0), Offset(x, size.height), paint);
  }

  @override
  bool shouldRepaint(_IntentBranch old) =>
      color != old.color || first != old.first || hasValue != old.hasValue;
}

String _calendarLabel(wire.CalendarElement event) {
  final day = event.day;
  final weekday = day.length == 1 ? '$day요일' : day;
  return [
    weekday,
    event.tags.join(' · '),
    '일정',
  ].where((part) => part.isNotEmpty).join(' ');
}

class _ChainSection extends StatelessWidget {
  const _ChainSection({required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    if (children.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            header: true,
            child: KoreanText(
              title,
              style: Theme.of(context).textTheme.titleLarge,
            ),
          ),
          for (final child in children) ...[const SizedBox(height: 10), child],
        ],
      ),
    );
  }
}

class _Panel extends StatelessWidget {
  const _Panel({
    required this.child,
    this.color,
    this.selected = false,
    this.padding = const EdgeInsets.all(14),
    this.radius = 12,
  });

  final Widget child;
  final Color? color;
  final bool selected;
  final EdgeInsets padding;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color ?? colors.surface,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(
          color: selected ? colors.primary : colors.outlineVariant,
          width: selected ? 2 : 1,
        ),
      ),
      child: child,
    );
  }
}

class _EvidenceGroup extends StatelessWidget {
  const _EvidenceGroup({required this.title, required this.rows});

  final String title;
  final List<Widget> rows;

  @override
  Widget build(BuildContext context) => _Panel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Semantics(
          header: true,
          child: KoreanText(
            title,
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ),
        for (final row in rows) ...[const Divider(height: 16), row],
      ],
    ),
  );
}

class _EvidenceRow extends StatelessWidget {
  const _EvidenceRow({required this.title, required this.detail});

  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        KoreanText(
          title,
          style: theme.textTheme.bodyMedium?.copyWith(
            fontWeight: FontWeight.w600,
          ),
        ),
        if (detail.trim().isNotEmpty)
          KoreanText(
            detail,
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
      ],
    );
  }
}

class _SituationSlot extends StatelessWidget {
  const _SituationSlot({
    required this.label,
    required this.value,
    required this.isTheme,
    required this.selected,
  });

  final String label;
  final String? value;
  final bool isTheme;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final hasValue = value?.trim().isNotEmpty ?? false;
    final themed = isTheme && hasValue;
    final foreground = themed
        ? colors.onSecondaryContainer
        : colors.onPrimaryContainer;
    return _Panel(
      selected: selected,
      padding: const EdgeInsets.all(8),
      color: themed
          ? colors.secondaryContainer
          : hasValue
          ? colors.primaryContainer
          : colors.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          KoreanText(
            label,
            style: theme.textTheme.bodySmall?.copyWith(color: foreground),
          ),
          KoreanText(
            hasValue ? value! : '알 수 없어요',
            style: theme.textTheme.titleMedium?.copyWith(color: foreground),
          ),
        ],
      ),
    );
  }
}

class _Chips extends StatelessWidget {
  const _Chips(this.labels, {this.onSurface = false});

  final List<String> labels;
  final bool onSurface;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final label in labels)
          DecoratedBox(
            decoration: BoxDecoration(
              color: onSurface
                  ? colors.surface
                  : colors.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: colors.outlineVariant),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              child: KoreanText(
                label,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: colors.primary,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
      ],
    );
  }
}

class _IntentPanel extends StatelessWidget {
  const _IntentPanel({
    required this.sentence,
    required this.themePhrase,
    required this.clues,
    this.showLabel = true,
  });

  final String sentence;
  final String? themePhrase;
  final List<String> clues;
  final bool showLabel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return _Panel(
      color: colors.primary,
      radius: appCardRadius,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (showLabel) ...[
            KoreanText(
              '주문의 의도',
              style: theme.textTheme.bodySmall?.copyWith(
                color: colors.onPrimary,
              ),
            ),
            const SizedBox(height: 6),
          ],
          KoreanText.rich(
            highlightTheme(sentence, themePhrase, appPinkOnGreen),
            style: theme.textTheme.titleLarge?.copyWith(
              color: colors.onPrimary,
              fontWeight: FontWeight.w600,
            ),
          ),
          if (clues.isNotEmpty) ...[
            const SizedBox(height: 12),
            KoreanText(
              '함께 본 근거',
              style: theme.textTheme.bodySmall?.copyWith(
                color: colors.onPrimary,
              ),
            ),
            const SizedBox(height: 4),
            _Chips(clues, onSurface: true),
          ],
        ],
      ),
    );
  }
}

final _taskWords = RegExp(r'[\p{L}\p{N}]+', unicode: true);

bool _repeatsTask(String need, String line) {
  final a = _taskWords.allMatches(need).map((word) => word[0]).toList();
  final b = _taskWords.allMatches(line).map((word) => word[0]).toList();
  if (a.isEmpty || b.isEmpty) return false;
  if (a.length == b.length) {
    final differences = a.indexed.where((pair) => pair.$2 != b[pair.$1]).length;
    return differences == 0 || (differences == 1 && a.length >= 3);
  }
  final shorter = a.length < b.length ? a : b;
  final longer = a.length < b.length ? b : a;
  if (shorter.length < 3 || longer.length != shorter.length + 1) return false;
  final added =
      shorter.indexed
          .where((pair) => pair.$2 != longer[pair.$1])
          .firstOrNull
          ?.$1 ??
      shorter.length;
  return shorter
      .skip(added)
      .indexed
      .every((pair) => pair.$2 == longer[added + pair.$1 + 1]);
}

class _TaskPanel extends StatelessWidget {
  const _TaskPanel({
    super.key,
    this.task,
    required this.current,
    required this.scheduleStart,
    required this.immediateTime,
    required this.selected,
    required this.showSituation,
  }) : assert(task != null || current != null);

  final wire.Task? task;
  final wire.LineElement? current;
  final String? scheduleStart;
  final String? immediateTime;
  final bool selected;
  final VoidCallback? showSituation;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final need = task?.need.trim() ?? '';
    final line = current?.text ?? task!.line;
    final repeated = need.isNotEmpty && _repeatsTask(need, line);
    final devices = (task?.devices ?? const <wire.Device>[])
        .map((device) {
          final type = deviceLabel(device.type, unknownLabel: '기기');
          final room = roomLabel(device.room) ?? '';
          return room.isEmpty ? type : '$room $type';
        })
        .toSet()
        .join(' · ');
    final way = switch (task?.way) {
      wire.Way.RUN => ('실행', colors.primary),
      wire.Way.STANDBY => ('설정 대기', colors.onSurfaceVariant),
      wire.Way.NOTICE => ('안내', colors.onSurfaceVariant),
      null => null,
    };
    final timing = lineTimeDerivation(
      current,
      scheduleStart,
      immediateTime: immediateTime,
    );
    final status = switch (current?.state) {
      null || wire.LineState.HELD || wire.LineState.SCHEDULED => null,
      final state => (lineLabel(state), lineStatusColor(context, state)),
    };
    final timingStyle = theme.textTheme.bodySmall?.copyWith(
      color: colors.onSurfaceVariant,
      fontFeatures: const [FontFeature.tabularFigures()],
    );

    return _Panel(
      selected: selected,
      color: selected ? colors.primaryContainer : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (selected)
            KoreanText(
              '선택한 할 일',
              style: theme.textTheme.bodySmall?.copyWith(color: colors.primary),
            ),
          if (need.isNotEmpty && !repeated) ...[
            KoreanText(need, style: theme.textTheme.bodyMedium),
            Align(
              alignment: Alignment.centerLeft,
              child: ExcludeSemantics(
                child: Icon(
                  Icons.arrow_downward,
                  size: 16,
                  color: colors.primary,
                ),
              ),
            ),
          ],
          KoreanText(line, style: theme.textTheme.titleMedium),
          if (timing != null) KoreanText(timing, style: timingStyle),
          if (devices.isNotEmpty) ...[
            const SizedBox(height: 8),
            KoreanText(
              devices,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: colors.onSurfaceVariant,
              ),
            ),
          ],
          if (way != null || status != null) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 12,
              runSpacing: 4,
              children: [
                for (final (label, color) in [?way, ?status])
                  StatusBadge(label, color: color),
              ],
            ),
          ],
          if (repeated)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: () => showDialog<void>(
                  context: context,
                  animationStyle: MediaQuery.disableAnimationsOf(context)
                      ? AnimationStyle.noAnimation
                      : null,
                  builder: (context) => AlertDialog(
                    title: const KoreanText('왜 이 일?'),
                    content: KoreanText(need),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const KoreanText('닫기'),
                      ),
                    ],
                  ),
                ),
                child: const KoreanText('왜 이 일?'),
              ),
            ),
          if (task == null) const KoreanText('이 할 일의 자세한 근거를 볼 수 없어요.'),
          if (current?.endState == wire.EndState.WITHHELD)
            KoreanText(endLabel(wire.EndState.WITHHELD)!),
          if (showSituation != null)
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: showSituation,
                icon: const Icon(Icons.arrow_upward),
                label: const KoreanText('이 일을 정한 근거 보기'),
              ),
            ),
        ],
      ),
    );
  }
}
