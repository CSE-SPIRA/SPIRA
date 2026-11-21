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
        chip: '${calendar.day} ${calendar.start} ${calendar.tags.join(' · ')}'
            .trim(),
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
        chip: '비슷한 주문 ${matching == null ? '$total건' : '${matching.n}/$total'}',
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
    final card = data.card;
    final usual =
        data.result?.evidence.unusualItems?.usual?.toSet() ?? const <String>{};
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
            '이렇게 봤어요',
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
        if (data.aside.isNotEmpty)
          EvidenceCaption(
            '${usual.containsAll(data.aside) ? '평소에 사던 물건은 따로 봤어요.' : '이번 준비와 따로 봤어요.'} ${data.aside.join(' · ')}',
          ),
        EvidenceSection(
          '그래서 할 일',
          child: EvidencePanel(
            child: EvidenceRows([
              for (final line in card.lines)
                InkWell(
                  borderRadius: BorderRadius.circular(DesignTokens.radius8),
                  onTap: () => _openStoryLine(
                    Navigator.of(context),
                    data.app,
                    card,
                    line.taskId,
                    line.text,
                  ),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(
                      minHeight: DesignTokens.space48,
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: EvidenceRow(
                            title: _lineTitle(line.text),
                            detail: data.taskFor(line.taskId)?.need ?? '',
                          ),
                        ),
                        const Icon(
                          Icons.chevron_right,
                          size: DesignTokens.size18,
                          color: DesignTokens.muted,
                        ),
                      ],
                    ),
                  ),
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
      final text = current?.text ?? task?.line ?? initialText;
      final relation = lineRelationLabel(current, card);
      final runs = data.executions
          .where((entry) => entry.taskId == id)
          .toList();
      final shared = data.episode?.sharedAt;
      final planned = current?.when?.time;
      final firstRun = runs
          .where(
            (run) =>
                run.status == wire.ExecutionStatus.RUNNING ||
                run.status == wire.ExecutionStatus.COMPLETED,
          )
          .firstOrNull;
      final immediateTime =
          planned != null &&
              shared != null &&
              DateTime.parse(planned).isBefore(DateTime.parse(shared))
          ? seoulDateTime(firstRun?.at ?? shared)
          : null;
      final timing = lineTimeDerivation(
        current,
        data.calendar == null ? null : card.startsAt,
        immediateTime: immediateTime,
      );
      final state = line?.state ?? task?.state ?? fallback?.state;
      final end = endLabel(current?.endState);
      final note = current?.note;
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
                task?.need.trim().isNotEmpty == true
                    ? task!.need
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
                if (end != null) KoreanText(end),
                if (note != null && note.trim().isNotEmpty && note != end)
                  KoreanText(note),
                if (runs.isEmpty &&
                    end == null &&
                    (note?.trim().isNotEmpty != true))
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

class _StoryObservation extends StatelessWidget {
  const _StoryObservation(this.data, this.observation);

  final _StoryData data;
  final wire.Observation observation;

  @override
  Widget build(BuildContext context) {
    final verdict = switch (observation.verdict!) {
      wire.Verdict.MATCH => '집에서 일어난 일과 판단이 맞았어요.',
      wire.Verdict.STOPPED => '이 준비를 중지하셨어요.',
      wire.Verdict.UNCONFIRMED => '이 준비가 맞았는지 확인하기 어려웠어요.',
    };
    final occasion = data.occasion;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: DesignTokens.space4,
      children: [
        EvidenceCaption(verdict),
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
                style: Theme.of(context).textTheme.titleMedium
                    ?.copyWith(color: DesignTokens.pinkInk),
              ),
              for (final feedback in observation.taskFeedback)
                for (final text in _feedback(feedback))
                  KoreanText(
                    '· $text',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
            ],
          ),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: () => openHomeMemory(context, data.app),
            child: const KoreanText('설정 › 우리 집 기억'),
          ),
        ),
      ],
    );
  }

  Iterable<String> _feedback(wire.TaskFeedbackElement feedback) sync* {
    final line = data.card.lines
        .where((line) => line.taskId == feedback.taskId)
        .firstOrNull;
    final name = _lineTitle(
      line?.text ?? data.taskFor(feedback.taskId)?.line ?? '이 할 일',
    );
    final label = '‘$name’ 항목';
    switch (feedback.user) {
      case wire.TaskFeedback.OFF:
        final when = switch (feedback.when) {
          wire.OffWhen.BEFORE_RUN => '실행 전에 ',
          wire.OffWhen.DURING_RUN => '실행 중에 ',
          null => '',
        };
        final date = DateTime.tryParse(feedback.at ?? '');
        final day = date == null ? '' : '${date.month}월 ${date.day}일 ';
        yield '$day$label을 $when끄셨어요.';
      case wire.TaskFeedback.KEPT:
        yield '$label을 그대로 두셨어요.';
      case wire.TaskFeedback.CHANGED:
        final changes = feedback.changes ?? const <wire.Change>[];
        if (changes.isEmpty) yield '$label의 설정을 바꾸셨어요.';
        for (final change in changes) {
          final device = deviceLabel(change.deviceType);
          final kelvin = change.to is Map ? (change.to as Map)['kelvin'] : null;
          final setting = switch (change.property) {
            'color_temp' when kelvin is num => '빛을 ${kelvin}K로',
            'color_temp' => '빛의 색을',
            'brightness' => '밝기를',
            'color' => '색을',
            'power' => '전원 상태를',
            _ => '설정을',
          };
          final minutes = change.afterStartMinutes;
          final when = switch (minutes) {
            < 0 => '일정 시작 ${minutes.abs()}분 전',
            0 => '일정이 시작할 때',
            _ => '일정 시작 $minutes분 뒤',
          };
          yield '$when $device $setting 바꾸셨어요.';
        }
    }
  }
}
