part of 'order_story.dart';

typedef _Reason = ({IconData icon, String chip, String title, String detail});

List<_Reason> _judgmentReasons(_StoryData data) {
  final evidence = data.result?.evidence;
  final calendar = data.calendar;
  final day = calendar?.day ?? '';
  final weekday = day.length == 1 ? '$day요일' : day;
  final unusual =
      evidence?.unusualItems?.items ?? const <wire.UnusualItemsItem>[];
  final newItems = unusual
      .where((entry) => entry.why.contains('산 적 없는'))
      .toList();
  final highlighted = newItems.isEmpty ? unusual : newItems;
  final counts = evidence?.kbCounts ?? const <wire.KbCount>[];
  final total = counts.fold(0, (sum, row) => sum + row.n);
  final matching = counts
      .where((row) => row.intentId == data.intent?.intentId)
      .firstOrNull;
  final qty = {
    for (final item in data.episode?.items ?? const <wire.EpisodeItem>[])
      item.type: item.qty,
  };
  return [
    if (calendar != null)
      (
        icon: Icons.calendar_today_outlined,
        chip: calendarEvidenceLabel(calendar),
        title:
            '$weekday ${calendar.start}에 ${calendar.tags.isEmpty ? '' : '${calendar.tags.join(' · ')} '}일정',
        detail: [
          '연결된 캘린더',
          if (calendar.daysAfter == 0) '공유한 날',
          if (calendar.daysAfter > 0) '공유하고 ${calendar.daysAfter}일 뒤',
        ].join(' · '),
      ),
    if (highlighted.isNotEmpty)
      (
        icon: Icons.shopping_basket_outlined,
        chip: newItems.isEmpty
            ? '평소와 다른 ${highlighted.length}가지'
            : '산 적 없는 ${newItems.length}가지',
        title: newItems.isEmpty ? '평소와 달랐던 물건' : '이 집이 산 적 없는 물건',
        detail: [
          for (final row in highlighted)
            switch (qty[row.item]) {
              final count? when count > 1 => '${row.item} $count개',
              _ => row.item,
            },
        ].join(' · '),
      ),
    if (total > 0)
      (
        icon: Icons.people_outline,
        chip: matching == null
            ? '비슷한 주문 $total건'
            : '비슷한 주문 $total건 중 ${matching.n}건',
        title: matching == null
            ? '비슷한 주문을 $total건 찾았어요'
            : '비슷한 주문 $total건 중 ${matching.n}건이 ${similarOrderName(matching)}',
        detail: '다른 집들의 주문과 비교했어요',
      ),
  ];
}

class _ExpandedJudgment extends StatelessWidget {
  const _ExpandedJudgment(this.data, this.reasons);
  final _StoryData data;
  final List<_Reason> reasons;

  @override
  Widget build(BuildContext context) {
    final intent = data.intent!;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: DesignTokens.space12,
      children: [
        IntentPanel(
          sentence: intent.intentText,
          themePhrase: intent.situation.theme,
          clues: const [],
          showLabel: false,
        ),
        if (reasons.isNotEmpty)
          EvidenceSection(
            '판단 근거',
            child: EvidencePanel(
              child: EvidenceRows([
                for (final reason in reasons)
                  Row(
                    spacing: DesignTokens.space8,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      DecoratedBox(
                        decoration: BoxDecoration(
                          color: DesignTokens.greenSoft,
                          borderRadius: BorderRadius.circular(
                            DesignTokens.radius8,
                          ),
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(DesignTokens.space8),
                          child: Icon(
                            reason.icon,
                            size: DesignTokens.size15,
                            color: DesignTokens.green,
                          ),
                        ),
                      ),
                      Expanded(
                        child: EvidenceRow(
                          title: reason.title,
                          detail: reason.detail,
                        ),
                      ),
                    ],
                  ),
              ]),
            ),
          ),
      ],
    );
  }
}

class _StoryLine extends StatelessWidget {
  const _StoryLine(this.app, this.initialCard, this.id, this.initialText);

  final AppController app;
  final wire.Card initialCard;
  final String id;
  final String initialText;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) {
      final card = app.cards[initialCard.cardId] ?? initialCard;
      final data = _StoryData(app, card);
      final line = card.lines.where((line) => line.taskId == id).firstOrNull;
      final fallback = initialCard.lines
          .where((line) => line.taskId == id)
          .firstOrNull;
      final task = data.taskFor(id);
      final current = line ?? fallback;
      final text = normalizeKelvin(current?.text ?? task?.line ?? initialText);
      final relation = lineRelationLabel(current, card);
      final runs = data.executions
          .where((entry) => entry.taskId == id)
          .toList();
      final timing = storyLineTiming(
        current,
        scheduleStart: data.calendar == null ? null : card.startsAt,
        scheduleName: isPartyPreparation(card) ? '파티' : '일정',
        sharedAt: data.episode?.sharedAt,
        runAt: runs.where(_startedExecution).firstOrNull?.at,
      );
      final state = line?.state ?? task?.state ?? fallback?.state;
      final end = endLabel(current?.endState);
      final note = lineNoteLabel(current?.note);
      final changes = data.changesFor(id);
      final need = task?.need.trim();
      final intent = data.intent;
      final details = RegExp(r' \((.+)\)$')
          .firstMatch(text)
          ?.group(1)
          ?.replaceAll('·', ' · ');
      return EvidencePage(
        title: _lineTitle(text),
        children: [
          EvidenceSection(
            '이 일',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: DesignTokens.space4,
              children: [
                KoreanText(
                  details ?? text,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Wrap(
                  spacing: DesignTokens.space8,
                  runSpacing: DesignTokens.space4,
                  children: [
                    if (relation != null) EvidenceCaption(relation),
                    if (state != null)
                      StatusBadge(
                        lineLabel(state),
                        color: lineStatusColor(context, state),
                      ),
                    if (task?.way == wire.Way.STANDBY)
                      const EvidenceCaption('설정 대기'),
                    if (task?.way == wire.Way.NOTICE)
                      const EvidenceCaption('안내'),
                  ],
                ),
              ],
            ),
          ),
          EvidenceSection(
            '왜',
            child: EvidencePanel(
              child: KoreanText(
                need != null && need.isNotEmpty
                    ? normalizeKelvin(need)
                    : '이 할 일의 자세한 근거를 볼 수 없어요.',
              ),
            ),
          ),
          if (timing != null)
            EvidenceSection(
              '언제',
              child: EvidencePanel(child: KoreanText(timing)),
            ),
          EvidenceSection(
            '집에서 실제로 일어난 일',
            child: EvidencePanel(
              child: EvidenceRows([
                for (final run in runs)
                  EvidenceRow(
                    title: data.deviceName(run.device, task),
                    detail:
                        '${seoulDateTime(run.at)} · ${_executionLabel(run.status)}',
                  ),
                for (final change in changes) KoreanText(_changeLabel(change)),
                if (end != null) KoreanText(end),
                if (note != null && note != end) KoreanText(note),
                if (runs.isEmpty &&
                    changes.isEmpty &&
                    end == null &&
                    note == null)
                  const EvidenceCaption('아직 표시할 실행 기록이 없어요.'),
              ]),
            ),
          ),
          if (intent != null)
            EvidenceSection(
              '이 판단에서 나왔어요',
              child: EvidencePanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: DesignTokens.space8,
                  children: [
                    KoreanText.rich(
                      highlightTheme(
                        intent.intentText,
                        intent.situation.theme,
                        DesignTokens.pinkInk,
                      ),
                    ),
                    EvidenceChips([
                      for (final (_, value, _) in situationSlots(intent))
                        if (value != null && value.trim().isNotEmpty) value,
                    ], theme: intent.situation.theme),
                  ],
                ),
              ),
            ),
          _FullEvidenceLink(app, card.episodeId),
        ],
      );
    },
  );
}

class _FullEvidenceLink extends StatelessWidget {
  const _FullEvidenceLink(this.app, this.episodeId);
  final AppController app;
  final String episodeId;

  @override
  Widget build(BuildContext context) => OutlinedButton(
    style: OutlinedButton.styleFrom(
      side: const BorderSide(color: DesignTokens.greenLine),
    ),
    onPressed: () => openFullEvidence(context, app, episodeId),
    child: const KoreanText('전체 근거 보기'),
  );
}

String _changeLabel(wire.Change change) {
  final device = deviceLabel(change.deviceType);
  final value = change.to;
  final kelvin = value is Map ? value['kelvin'] : null;
  final action = switch ((change.property, value)) {
    ('color' || 'color_temp', _) when kelvin is num => '${kelvin}K로 바꾸셨어요',
    ('color_temp', final num temperature) => '${temperature}K로 바꾸셨어요',
    ('power', true || 'on') => '전원을 켜셨어요',
    ('power', false || 'off') => '전원을 끄셨어요',
    (_, final num amount) => '설정값을 $amount로 바꾸셨어요',
    (_, final String setting) when setting.trim().isNotEmpty =>
      '‘${normalizeKelvin(setting)}’ 값으로 바꾸셨어요',
    _ => '설정을 바꾸셨어요',
  };
  final minutes = change.afterStartMinutes;
  final when = switch (minutes) {
    < 0 => '시작 ${minutes.abs()}분 전',
    0 => '시작할 때',
    _ => '시작 $minutes분 뒤',
  };
  return '$device · $action · $when';
}

class _StoryObservation extends StatelessWidget {
  const _StoryObservation(
    this.data,
    this.observation, {
    this.showHeading = true,
  });

  final _StoryData data;
  final wire.Observation observation;
  final bool showHeading;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final feedback = observation.taskFeedback;
    final adjusted = feedback.any(
      (entry) => entry.user != wire.TaskFeedback.KEPT,
    );
    final verdict = switch (observation.verdict!) {
      wire.Verdict.MATCH when adjusted => verdictWords['match_adjusted']!,
      wire.Verdict.MATCH => verdictWords['match']!,
      wire.Verdict.STOPPED => verdictWords['stopped']!,
      wire.Verdict.UNCONFIRMED => verdictWords['unconfirmed']!,
    };
    final occasion = data.occasion;
    final kept = feedback
        .where((entry) => entry.user == wire.TaskFeedback.KEPT)
        .length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: DesignTokens.space4,
      children: [
        if (showHeading)
          Semantics(
            header: true,
            child: KoreanText(
              '판단을 확인했어요',
              style: theme.textTheme.titleMedium?.copyWith(
                color: DesignTokens.pinkInk,
              ),
            ),
          ),
        EvidenceCaption(verdict),
        if (feedback.isNotEmpty)
          EvidencePanel(
            color: DesignTokens.pinkSoft,
            border: DesignTokens.pinkEdge,
            radius: DesignTokens.radius12,
            child: Column(
              spacing: DesignTokens.space4,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                KoreanText(
                  '다음 ${occasion == null ? '' : '$occasion '}준비 때 참고할게요',
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: DesignTokens.pinkInk,
                  ),
                ),
                for (final entry in feedback.where(
                  (entry) => entry.user == wire.TaskFeedback.CHANGED,
                ))
                  if (entry.changes case final changes? when changes.isNotEmpty)
                    for (final change in changes)
                      EvidenceCaption(_changeLabel(change))
                  else
                    EvidenceCaption('${_lineName(entry.taskId)}의 설정을 바꾸셨어요.'),
                for (final entry in feedback.where(
                  (entry) => entry.user == wire.TaskFeedback.OFF,
                ))
                  EvidenceCaption(_offLabel(entry)),
                if (kept > 0)
                  EvidenceCaption('${adjusted ? '나머지 ' : ''}$kept개는 그대로 쓰셨어요'),
              ],
            ),
          ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            style: TextButton.styleFrom(padding: EdgeInsets.zero),
            onPressed: () => openHomeMemory(context, data.app),
            child: const KoreanText('우리 집 기억 보기'),
          ),
        ),
      ],
    );
  }

  String _lineName(String taskId) {
    final line = data.card.lines
        .where((line) => line.taskId == taskId)
        .firstOrNull;
    final name = line?.text ?? data.taskFor(taskId)?.line;
    return name == null ? '이 항목' : '‘${_lineTitle(name)}’ 항목';
  }

  String _offLabel(wire.TaskFeedbackElement feedback) {
    final when = switch (feedback.when) {
      wire.OffWhen.BEFORE_RUN => '실행 전에 ',
      wire.OffWhen.DURING_RUN => '실행 중에 ',
      null => '',
    };
    final date = DateTime.tryParse(feedback.at ?? '');
    final day = date == null ? '' : '${date.month}월 ${date.day}일 ';
    return '$day${_lineName(feedback.taskId)}을 $when끄셨어요.';
  }
}
