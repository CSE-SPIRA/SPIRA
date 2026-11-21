// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../design_vocabulary.g.dart';
import '../korean_text.dart';
import '../theme.dart';
import 'order_extraction.dart';
import 'setup.dart';

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
        calendarEvidenceLabel(event)
      else if (source == '가구 유형')
        stateWords['household_profile']!
      else if (itemsByType[source] case final item?)
        if (productName && item.name.trim().isNotEmpty)
          item.name
        else
          item.type,
  ];
}

List<(String, String?, List<String>)> situationSlots(
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
              EvidencePanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  spacing: 6,
                  children: [
                    for (final (label, value, sources) in situationSlots(
                      intent,
                    ))
                      EvidenceRow(
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
              IntentPanel(
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
            EvidencePanel(
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

String calendarEvidenceLabel(wire.CalendarElement event) {
  final day = event.day;
  final weekday = day.length == 1 ? '$day요일' : day;
  return [
    weekday,
    event.tags.join(' · '),
    '일정',
  ].where((part) => part.isNotEmpty).join(' ');
}

class IntentPanel extends StatelessWidget {
  const IntentPanel({
    super.key,
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
    return EvidencePanel(
      color: colors.primary,
      radius: appCardRadius,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (showLabel) ...[
            KoreanText(
              '이렇게 판단했어요',
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
            EvidenceChips(clues, onGreen: true),
          ],
        ],
      ),
    );
  }
}

String similarOrderName(wire.KbCount count) => count.intentId == 'none'
    ? stateWords['order_without_preparation']!
    : count.name;

class EvidencePanel extends StatelessWidget {
  const EvidencePanel({
    super.key,
    required this.child,
    this.color,
    this.border,
    this.radius = DesignTokens.radius16,
  });

  final Widget child;
  final Color? color;
  final Color? border;
  final double radius;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(
      vertical: DesignTokens.space12,
      horizontal: DesignTokens.space16,
    ),
    decoration: BoxDecoration(
      color: color ?? DesignTokens.surface,
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: border ?? DesignTokens.line),
    ),
    child: child,
  );
}

class EvidenceSection extends StatelessWidget {
  const EvidenceSection(this.title, {super.key, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    spacing: DesignTokens.space4,
    children: [
      Semantics(header: true, child: EvidenceCaption(title)),
      child,
    ],
  );
}

class EvidenceCaption extends StatelessWidget {
  const EvidenceCaption(this.text, {super.key});
  final String text;

  @override
  Widget build(BuildContext context) => KoreanText(
    text,
    style: Theme.of(context).textTheme.bodySmall
        ?.copyWith(color: DesignTokens.muted),
  );
}

class EvidenceRow extends StatelessWidget {
  const EvidenceRow({super.key, required this.title, this.detail = ''});

  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: DesignTokens.space4,
    children: [
      KoreanText(title),
      if (detail.isNotEmpty) EvidenceCaption(detail),
    ],
  );
}

class EvidenceRows extends StatelessWidget {
  const EvidenceRows(this.children, {super.key});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (final (index, child) in children.indexed) ...[
        if (index > 0)
          const Divider(height: DesignTokens.space16, color: DesignTokens.soft),
        child,
      ],
    ],
  );
}

class EvidenceChips extends StatelessWidget {
  const EvidenceChips(
    this.values, {
    super.key,
    this.theme,
    this.onGreen = false,
    this.onTap,
  });

  final List<String> values;
  final String? theme;
  final bool onGreen;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Wrap(
    spacing: DesignTokens.space4,
    runSpacing: DesignTokens.space4,
    children: [
      for (final value in values)
        if (onTap != null)
          ActionChip(
            label: KoreanText(value),
            labelStyle: Theme.of(context).textTheme.bodySmall,
            onPressed: onTap,
            backgroundColor: DesignTokens.soft,
            side: BorderSide.none,
            shape: const StadiumBorder(),
          )
        else
          DecoratedBox(
            decoration: BoxDecoration(
              color: value == theme
                  ? DesignTokens.pinkSoft
                  : onGreen
                  ? DesignTokens.greenSoft
                  : DesignTokens.soft,
              borderRadius: BorderRadius.circular(DesignTokens.radiusPill),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(
                vertical: DesignTokens.space4,
                horizontal: DesignTokens.space8,
              ),
              child: KoreanText(
                value,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: value == theme
                      ? DesignTokens.pinkInk
                      : DesignTokens.ink,
                ),
              ),
            ),
          ),
    ],
  );
}

class EvidencePage extends StatelessWidget {
  const EvidencePage({super.key, required this.title, required this.children});

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: KoreanText(title, overflow: TextOverflow.ellipsis, maxLines: 2),
    ),
    body: SafeArea(
      top: false,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(
          DesignTokens.space16,
          0,
          DesignTokens.space16,
          DesignTokens.space24,
        ),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 600),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              spacing: DesignTokens.space12,
              children: children,
            ),
          ),
        ),
      ),
    ),
  );
}

void openFullEvidence(
  BuildContext context,
  AppController app,
  String episodeId,
) {
  Navigator.of(context).push<void>(
    MaterialPageRoute(builder: (_) => FullEvidenceScreen(app, episodeId)),
  );
}

class FullEvidenceScreen extends StatefulWidget {
  const FullEvidenceScreen(this.app, this.episodeId, {super.key});

  final AppController app;
  final String episodeId;

  @override
  State<FullEvidenceScreen> createState() => _FullEvidenceScreenState();
}

class _FullEvidenceScreenState extends State<FullEvidenceScreen> {
  late final _request = widget.app.rationale(widget.episodeId);
  static final _rarePurchase = RegExp(r'^(\d+)일에 (\d+)번 산 드문 물건$');

  String _unusualReason(String reason) {
    final match = _rarePurchase.firstMatch(reason);
    return match == null ? reason : '지난 ${match[1]}일 동안 ${match[2]}번 샀어요';
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<wire.Rationale>(
    future: _request,
    builder: (context, snapshot) => ListenableBuilder(
      listenable: widget.app,
      builder: (context, _) {
        final result =
            widget.app.rationaleFor(widget.episodeId) ?? snapshot.data;
        return EvidencePage(
          title: '전체 근거',
          children: result == null
              ? [
                  if (snapshot.connectionState != ConnectionState.done)
                    const Center(
                      child: CircularProgressIndicator(
                        semanticsLabel: '준비 이유 불러오는 중',
                      ),
                    )
                  else
                    const StatusMessage('저장된 이유를 볼 수 없어요.'),
                ]
              : _evidence(result, widget.app.episodes[widget.episodeId]),
        );
      },
    ),
  );

  List<Widget> _evidence(wire.Rationale result, wire.Episode? episode) {
    final items = episode?.items ?? const <wire.EpisodeItem>[];
    final basis = _basisLabelsFor(result, items);
    final unusual = <String, List<String>>{};
    for (final entry
        in result.evidence.unusualItems?.items ??
            const <wire.UnusualItemsItem>[]) {
      unusual.putIfAbsent(_unusualReason(entry.why), () => []).add(entry.item);
    }
    final counts = result.evidence.kbCounts ?? const <wire.KbCount>[];
    final examples = result.evidence.kbExamples;
    final linked = result.intents
        .map((intent) => intent.calendarEventId)
        .toSet();
    final calendar = result.evidence.calendar.where(
      (event) => linked.contains(event.id),
    );
    return [
      if (episode != null)
        EvidenceSection(
          '주문에서 읽은 것 · ${episode.itemCount}개',
          child: EvidencePanel(
            child: Column(
              spacing: DesignTokens.space4,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (items.isNotEmpty)
                  KoreanText(
                    [
                      for (final item in items)
                        item.qty == null
                            ? '${item.type} (수량 미확인)'
                            : item.qty == 1
                            ? item.type
                            : '${item.type} ${item.qty}개',
                    ].join(' · '),
                  ),
                if (setAsideItems(result, episode) case final aside
                    when aside.isNotEmpty)
                  EvidenceCaption('${aside.join(' · ')}은 이번 준비와 따로 봤어요.'),
                if (episode.maskedCount > 0)
                  EvidenceCaption('가린 물건 ${episode.maskedCount}개'),
              ],
            ),
          ),
        ),
      if (unusual.isNotEmpty)
        EvidenceSection(
          '평소와 달랐던 물건',
          child: EvidencePanel(
            child: EvidenceRows([
              for (final entry in unusual.entries)
                KoreanText('${entry.value.join(' · ')} — ${entry.key}'),
            ]),
          ),
        ),
      if (counts.isNotEmpty || examples.isNotEmpty)
        EvidenceSection(
          '비슷한 주문 (다른 집들)',
          child: EvidencePanel(
            child: EvidenceRows([
              if (counts.isNotEmpty)
                EvidenceChips([
                  for (final count in counts)
                    '${similarOrderName(count)} ${count.n}건',
                ]),
              for (final example in examples)
                EvidenceRow(
                  title:
                      example.intentText ??
                      counts
                          .where((count) => count.intentId == example.intentId)
                          .map(similarOrderName)
                          .firstOrNull ??
                      '비슷한 주문',
                  detail: [
                    '${example.overlap.n}개 중 ${example.overlap.k}개가 같아요',
                    ...example.overlap.items,
                  ].join(' · '),
                ),
            ]),
          ),
        ),
      if (result.intents.isNotEmpty)
        EvidenceSection(
          '상황 칸과 근거',
          child: EvidencePanel(
            child: EvidenceRows([
              for (final intent in result.intents) ...[
                if (result.intents.length > 1) KoreanText(intent.intentText),
                for (final (label, value, sources) in situationSlots(intent))
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: DesignTokens.space48,
                        child: EvidenceCaption(label),
                      ),
                      Expanded(
                        child: KoreanText(
                          [
                            if (value == null || value.trim().isEmpty)
                              '알 수 없어요'
                            else ...[
                              value,
                              if (basis(sources, productName: label == '테마')
                                  case final clues when clues.isNotEmpty)
                                '← ${clues.join(' · ')}',
                            ],
                          ].join(' '),
                          style: label == '테마' && value != null
                              ? const TextStyle(color: DesignTokens.pinkInk)
                              : null,
                        ),
                      ),
                    ],
                  ),
              ],
            ]),
          ),
        ),
      if (calendar.isNotEmpty)
        EvidenceSection(
          '연결된 일정',
          child: EvidencePanel(
            child: EvidenceRows([
              for (final event in calendar)
                EvidenceRow(
                  title: calendarEvidenceLabel(event),
                  detail: '${event.day} ${event.start}–${event.end}',
                ),
            ]),
          ),
        ),
      if (result.intents.isEmpty) ...[
        if (result.noneReason case final reason? when reason.trim().isNotEmpty)
          EvidencePanel(child: KoreanText(reason)),
        if (result.itemTasks.any(
          (task) => task.text?.trim().isNotEmpty ?? false,
        ))
          EvidenceSection(
            '냉장고 안내',
            child: EvidencePanel(
              child: EvidenceRows([
                for (final task in result.itemTasks)
                  if (task.text case final detail?
                      when detail.trim().isNotEmpty)
                    EvidenceRow(title: task.item, detail: detail),
              ]),
            ),
          ),
      ],
    ];
  }
}

List<String> setAsideItems(wire.Rationale result, wire.Episode? episode) {
  final visibleTypes =
      episode?.items.map((item) => item.type).toSet() ?? const <String>{};
  return result.unbundled.toSet().where(visibleTypes.contains).toList();
}
