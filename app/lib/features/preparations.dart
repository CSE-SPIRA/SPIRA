// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../theme.dart';
import 'labels.dart';
import 'order_extraction.dart';
import 'rationale.dart';
import 'setup.dart';

class Preparations extends StatelessWidget {
  const Preparations(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    final known = app.orderedEpisodes.toList();
    final latest = known.firstOrNull;
    final current = app.currentPreparationOrder;
    final reading = known.where(
      (episode) =>
          episode != current &&
          (app.accepted.contains(episode.episodeId) ||
              app.orderImages(episode.episodeId).isNotEmpty ||
              episode.status == wire.EpisodeStatus.READING ||
              episode.status == wire.EpisodeStatus.RECEIVED),
    );
    final visible = {...reading, ?current, ?latest};
    final previous = known.where((episode) => !visible.contains(episode));
    return RefreshIndicator(
      onRefresh: app.sync,
      child: ListView(
        primary: false,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        children: [
          if (app.browserPreview && app.fixture)
            Align(
              alignment: Alignment.centerLeft,
              child: FilledButton(
                onPressed: app.canControl && !app.sharingExample
                    ? app.shareExample
                    : null,
                child: Text(app.sharingExample ? '주문을 보내는 중…' : '예시 주문으로 공유'),
              ),
            ),
          if (app.exampleShareError case final error?) StatusMessage(error),
          if (app.refreshError case final error?) StatusMessage(error),
          if (app.stale && known.isNotEmpty)
            const StatusMessage('마지막으로 확인한 정보예요. 현재 상태를 확인하는 중이에요.'),
          if (app.uploadError case final error?) StatusMessage(error),
          if (app.shareIssue case final issue?)
            StatusMessage(switch (issue) {
              'count' => '주문 화면을 한 번에 1~3장 공유해 주세요.',
              'size' => '이미지 한 장은 5MB 이하여야 해요.',
              'format' => 'JPG 또는 PNG 주문 화면을 공유해 주세요.',
              'rejected' => '서버가 이미지를 읽을 수 없어요. 새 캡처를 공유해 주세요.',
              _ => '공유한 이미지를 열 수 없어요. 주문 화면을 다시 공유해 주세요.',
            }),
          if (app.queuedShares > 0) const StatusMessage('공유한 주문을 보내는 중이에요…'),
          if ((app.refreshError != null || app.uploadError != null) &&
              !app.needsToken)
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: app.sync,
                child: const Text('다시 시도'),
              ),
            ),
          if (!app.refreshed &&
              app.refreshError == null &&
              app.accepted.isEmpty)
            const StatusMessage('준비를 불러오는 중이에요…'),
          if (app.platform != null &&
              known.isEmpty &&
              app.refreshed &&
              app.accepted.isEmpty &&
              app.queuedShares == 0)
            const StatusMessage('주문 화면을 캡처한 뒤 안드로이드 공유 메뉴에서 SPIRA를 선택해 주세요.'),
          for (final id in app.accepted)
            if (!app.episodes.containsKey(id))
              _OrderSection(key: ValueKey(id), app: app, episodeId: id),
          for (final episode in visible)
            _OrderSection(
              key: ValueKey(episode.episodeId),
              app: app,
              episodeId: episode.episodeId,
              current: episode == current,
            ),
          if (previous.isNotEmpty)
            ExpansionTile(
              key: const PageStorageKey('past-preparations'),
              tilePadding: EdgeInsets.zero,
              title: const Text('지난 준비'),
              shape: const Border(),
              expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                for (final episode in previous)
                  _OrderSection(
                    key: ValueKey(episode.episodeId),
                    app: app,
                    episodeId: episode.episodeId,
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

class _OrderSection extends StatelessWidget {
  const _OrderSection({
    super.key,
    required this.app,
    required this.episodeId,
    this.current = false,
  });

  final AppController app;
  final String episodeId;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final episode = app.episodes[episodeId];
    final theme = Theme.of(context);
    final status = switch (episode?.status) {
      null => '주문을 받았어요. 읽기 결과를 기다리는 중이에요.',
      wire.EpisodeStatus.RECEIVED => '주문을 받았어요. 읽기 대기 중이에요.',
      wire.EpisodeStatus.READING => '주문을 읽고 있어요.',
      wire.EpisodeStatus.READ_FAILED => '주문을 읽지 못했어요. 주문 화면을 캡처해서 다시 공유해 주세요.',
      wire.EpisodeStatus.JUDGED => '집에서 준비할 일이 없어요.',
      wire.EpisodeStatus.NOTIFIED => current ? null : '준비를 확인했어요.',
      wire.EpisodeStatus.HELD => '준비할 시간을 기다리고 있어요.',
      wire.EpisodeStatus.CLOSED => '주문을 마쳤어요.',
      wire.EpisodeStatus.PAUSED_SKIP =>
        '주문을 보관했어요. 자동 준비가 일시정지 중이라 주문을 판단하지 않았어요.',
    };
    return Padding(
      padding: EdgeInsets.only(top: current ? 8 : 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (episode != null && !current)
            Text(
              seoulDateTime(episode.sharedAt),
              style: theme.textTheme.titleMedium,
            ),
          OrderExtraction(
            episode: episode,
            images: app.orderImages(episodeId),
            status: status,
            awaitingEpisode: app.accepted.contains(episodeId),
            onComplete: (images) => app.finishOrderCapture(episodeId, images),
            rationale: app.requestedRationale(episodeId),
            edit: episode != null && app.canEdit(episode)
                ? TextButton(
                    onPressed: () => Navigator.push<void>(
                      context,
                      MaterialPageRoute(
                        builder: (_) =>
                            _OrderEditor(app: app, episode: episode),
                      ),
                    ),
                    child: const Text('읽은 품목 수정'),
                  )
                : null,
            child: episode == null
                ? const SizedBox.shrink()
                : _OrderPreparation(
                    app: app,
                    episode: episode,
                    current: current,
                  ),
          ),
        ],
      ),
    );
  }
}

class _OrderPreparation extends StatelessWidget {
  const _OrderPreparation({
    required this.app,
    required this.episode,
    required this.current,
  });

  final AppController app;
  final wire.Episode episode;
  final bool current;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (episode.cardIds.isEmpty &&
          const {
            wire.EpisodeStatus.JUDGED,
            wire.EpisodeStatus.CLOSED,
          }.contains(episode.status))
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: () => openRationale(context, app, episode.episodeId),
            child: const Text('WHY · 이유 보기'),
          ),
        ),
      for (final (index, card) in app.cardsFor(episode).indexed)
        _PreparationCard(app: app, card: card, hero: current && index == 0),
      if (episode.itemTasks.isNotEmpty) ...[
        const SizedBox(height: 12),
        _ItemGuidance(episode: episode),
      ],
    ],
  );
}

class _PreparationCard extends StatelessWidget {
  const _PreparationCard({
    required this.app,
    required this.card,
    required this.hero,
  });

  final AppController app;
  final wire.Card card;
  final bool hero;

  Future<void> _confirmStop(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('이 준비를 중지할까요?'),
        content: const Text('이 카드의 준비를 중지해요. 품목 안내는 계속돼요.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('중지'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    final latest = app.cards[card.cardId];
    if (latest != null) await app.stop(latest);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final stopPending = app.stopPending(card.cardId);
    final stopUncertain = app.stopUncertain(card.cardId);
    return Card(
      key: ValueKey(card.cardId),
      color: hero ? appPaper : colors.surface,
      clipBehavior: Clip.antiAlias,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(appCardRadius),
        side: BorderSide(color: hero ? colors.outline : colors.outlineVariant),
      ),
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 10, 10, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Semantics(
                    header: true,
                    hint: '판단 근거 열기',
                    child: InkWell(
                      borderRadius: BorderRadius.circular(8),
                      onTap: () => openRationale(context, app, card.episodeId),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 5),
                        child: FutureBuilder<wire.Rationale>(
                          future: app.requestedRationale(card.episodeId),
                          builder: (context, snapshot) {
                            final intent = snapshot.data?.intents
                                .where((intent) => intent.cardId == card.cardId)
                                .firstOrNull;
                            return Text.rich(
                              highlightTheme(
                                card.text,
                                intent?.situation.theme,
                                colors.onSecondaryContainer,
                              ),
                              style: theme.textTheme.titleLarge,
                            );
                          },
                        ),
                      ),
                    ),
                  ),
                ),
                if (!card.stopped &&
                    card.buttons.contains(wire.CardButton.STOP))
                  PopupMenuButton<bool>(
                    tooltip: '준비 더보기 · ${card.text}',
                    icon: const Icon(Icons.more_horiz),
                    color: colors.surface,
                    enabled: app.canControl && (!stopPending || stopUncertain),
                    onSelected: (_) => _confirmStop(context),
                    itemBuilder: (_) => [
                      PopupMenuItem(
                        value: true,
                        child: Text(stopUncertain ? '중지 요청 재시도' : '이 준비 중지'),
                      ),
                    ],
                  ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 8),
              child: Wrap(
                spacing: 10,
                runSpacing: 4,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    card.startsAt == null
                        ? '일정이 잡히기를 기다리고 있어요.'
                        : '${seoulWeekdayTime(card.startsAt!)} 일정',
                    style: theme.textTheme.bodySmall,
                  ),
                  DecoratedBox(
                    decoration: ShapeDecoration(
                      color: colors.primaryContainer,
                      shape: const StadiumBorder(),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 3,
                      ),
                      child: Text(
                        '${card.summary.done}/${card.summary.total} 준비',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: colors.onPrimaryContainer,
                        ),
                      ),
                    ),
                  ),
                  if (card.summary.waitingFor case final event?)
                    Text(
                      '${eventLabel(event)} 기다리는 중',
                      style: theme.textTheme.bodySmall,
                    ),
                ],
              ),
            ),
            if (stopPending)
              StatusMessage(card.stopped ? '종료 결과 확인 중…' : '이 준비의 중지 요청 확인 중…')
            else if (card.stopped)
              const StatusMessage('이 준비가 중지됐어요.'),
            if (app.controlErrors[card.cardId] case final error?)
              StatusMessage(error),
            for (final line in card.lines.take(4)) ...[
              const Divider(height: 1),
              _PreparationLine(app: app, card: card, line: line),
            ],
          ],
        ),
      ),
    );
  }
}

class _PreparationLine extends StatelessWidget {
  const _PreparationLine({
    required this.app,
    required this.card,
    required this.line,
  });

  final AppController app;
  final wire.Card card;
  final wire.LineElement line;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final timing = lineTimeLabel(line) ?? lineLabel(wire.LineState.HELD);
    final state = visibleLineLabel(line.state);
    final pending = app.linePending(card, line);
    final canSwitch = app.canSwitch(card, line);
    final on = line.state != wire.LineState.OFF;
    final end = line.endState;
    final outcome = end == null ? null : endLabel(end);
    final note = line.note;
    return Row(
      children: [
        Expanded(
          child: Semantics(
            hint: '판단 근거 열기',
            child: InkWell(
              borderRadius: BorderRadius.circular(8),
              onTap: () => openRationale(
                context,
                app,
                card.episodeId,
                focus: (cardId: card.cardId, taskId: line.taskId),
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: 48),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  child: Row(
                    children: [
                      if (!canSwitch) ...[
                        Icon(
                          line.checked ? Icons.check : Icons.circle_outlined,
                          color: appGreen,
                          size: 17,
                          semanticLabel: line.checked ? '선택됨' : '선택 해제됨',
                        ),
                        const SizedBox(width: 8),
                      ],
                      Expanded(
                        child: Column(
                          spacing: 2,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(line.text, style: theme.textTheme.titleMedium),
                            Wrap(
                              spacing: 8,
                              children: [
                                Text(
                                  timing,
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    color: theme.colorScheme.onSurfaceVariant,
                                    fontFeatures: const [
                                      FontFeature.tabularFigures(),
                                    ],
                                  ),
                                ),
                                if (state != null && state != timing)
                                  Text(state, style: theme.textTheme.bodySmall),
                              ],
                            ),
                            if (outcome != null) Text(outcome),
                            if (note != null && note != outcome) Text(note),
                            if (pending) const StatusMessage('항목 변경 확인 중…'),
                          ],
                        ),
                      ),
                      Icon(
                        Icons.chevron_right,
                        size: 18,
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        if (canSwitch)
          Semantics(
            label: '${line.text} ${on ? '끄기' : '켜기'}',
            child: Transform.scale(
              scale: .78,
              transformHitTests: false,
              child: Switch(
                value: on,
                onChanged: pending ? null : (_) => app.switchLine(card, line),
              ),
            ),
          ),
      ],
    );
  }
}

class _ItemGuidance extends StatelessWidget {
  const _ItemGuidance({required this.episode});

  final wire.Episode episode;

  bool _waitingForPackage(wire.ItemTaskElement task) =>
      task.state == wire.LineState.HELD ||
      task.state == wire.LineState.SCHEDULED;

  @override
  Widget build(BuildContext context) {
    final closed = episode.status == wire.EpisodeStatus.CLOSED;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('품목 안내', style: Theme.of(context).textTheme.titleLarge),
        if (closed)
          const Text('품목 안내가 종료됐어요.')
        else if (episode.itemTasks.any(_waitingForPackage))
          const Text('택배를 집 안으로 들이면 안내를 볼 수 있어요.'),
        for (final task in episode.itemTasks)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(task.item, style: Theme.of(context).textTheme.titleMedium),
                if (!closed && !_waitingForPackage(task)) ...[
                  if (task.text case final text?) Text(text),
                  Text(lineLabel(task.state)),
                ],
              ],
            ),
          ),
      ],
    );
  }
}

class _OrderEditor extends StatefulWidget {
  const _OrderEditor({required this.app, required this.episode});

  final AppController app;
  final wire.Episode episode;

  @override
  State<_OrderEditor> createState() => _OrderEditorState();
}

class _OrderEditorState extends State<_OrderEditor> {
  final _form = GlobalKey<FormState>();
  late final _names = [
    for (final item in widget.episode.items)
      TextEditingController(text: item.name),
  ];
  late final _quantities = [
    for (final item in widget.episode.items)
      TextEditingController(text: item.qty?.toString()),
  ];
  bool _busy = false;
  String? _error;

  Future<void> _save() async {
    if (_busy || !_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.app.edit(
        widget.episode,
        wire.OrderEdit(
          items: [
            for (var index = 0; index < _names.length; index++)
              wire.OrderEditItem(
                itemId: widget.episode.items[index].itemId,
                name: _names[index].text.trim(),
                qty: int.tryParse(_quantities[index].text.trim()),
              ),
          ],
        ),
      );
      if (mounted) Navigator.pop(context);
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = '품목을 수정하지 못했어요.';
        });
      }
    }
  }

  @override
  void dispose() {
    for (final controller in [..._names, ..._quantities]) {
      controller.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.app,
    builder: (context, _) {
      final editable = widget.app.canEdit(
        widget.app.episodes[widget.episode.episodeId] ?? widget.episode,
      );
      return Scaffold(
        appBar: AppBar(title: const Text('읽은 품목 수정')),
        body: Form(
          key: _form,
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              if (!editable && !_busy) const StatusMessage('현재 주문은 수정할 수 없어요.'),
              if (_error case final error?) StatusMessage(error),
              for (var index = 0; index < _names.length; index++) ...[
                TextFormField(
                  controller: _names[index],
                  enabled: editable && !_busy,
                  decoration: InputDecoration(labelText: '품목 ${index + 1} 이름'),
                  validator: (value) => value == null || value.trim().isEmpty
                      ? '품목 이름을 입력해 주세요.'
                      : null,
                ),
                TextFormField(
                  controller: _quantities[index],
                  enabled: editable && !_busy,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(labelText: '품목 ${index + 1} 수량'),
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) return null;
                    return (int.tryParse(value.trim()) ?? 0) >= 1
                        ? null
                        : '1 이상의 수량을 입력해 주세요.';
                  },
                ),
                const SizedBox(height: 12),
              ],
              FilledButton(
                onPressed: editable && !_busy ? _save : null,
                child: Text(_busy ? '저장 중…' : '수정 저장'),
              ),
            ],
          ),
        ),
      );
    },
  );
}
