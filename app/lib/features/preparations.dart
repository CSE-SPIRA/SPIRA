import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../korean_text.dart';
import '../theme.dart';
import 'calendar.dart';
import 'labels.dart';
import 'order_extraction.dart';
import 'memory_sheet.dart';
import 'status_badge.dart';

class Preparations extends StatelessWidget {
  const Preparations(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    final orderId = app.currentOrderId;
    final cards = app.activeCards;
    final memory = app.mainMemory;
    final main = RefreshIndicator(
      onRefresh: app.sync,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
          DesignTokens.space20,
          DesignTokens.space12,
          DesignTokens.space20,
          DesignTokens.space32,
        ),
        children: [
          if (app.refreshError case final error?) StatusMessage(error),
          if (app.uploadError case final error?) StatusMessage(error),
          if (app.shareIssue case final issue?)
            StatusMessage(switch (issue) {
              'count' => '주문 화면을 한 번에 1~3장 공유해 주세요.',
              'size' => '이미지 한 장은 5MB 이하여야 해요.',
              'format' => 'JPG 또는 PNG 주문 화면을 공유해 주세요.',
              'rejected' => '서버가 이미지를 읽을 수 없어요. 새 캡처를 공유해 주세요.',
              _ => '공유한 이미지를 열 수 없어요. 주문 화면을 다시 공유해 주세요.',
            }),
          if (app.uploadDeferred)
            const StatusMessage('연결되면 공유한 주문을 보낼게요.')
          else if (app.queuedShares > 0 && app.uploadError == null)
            const StatusMessage('공유한 주문을 보내는 중이에요…'),
          if ((app.refreshError != null || app.uploadError != null) &&
              !app.needsToken)
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton(
                onPressed: app.sync,
                child: const KoreanText('다시 시도'),
              ),
            ),
          _OrderPanel(
            key: ValueKey(orderId),
            app: app,
            orderId: orderId,
            collapsible:
                orderId != null &&
                (memory?.episodeId == orderId ||
                    cards.any((card) => card.episodeId == orderId)),
          ),
          const SizedBox(height: 18),
          Column(
            key: const ValueKey('main-preparations'),
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (memory != null)
                MemorySheet(
                  key: ValueKey('memory-${app.mainMemoryCardIds.first}'),
                  rationale: app.rationaleFor(memory.episodeId),
                  episode: memory,
                  startsAt: app.memoryStart(
                    memory.episodeId,
                    app.mainMemoryCardIds,
                  ),
                  cardIds: app.mainMemoryCardIds,
                  onAcknowledge: app.acknowledgeMemory,
                ),
              if (orderId == null && memory == null) _RecentMemories(app: app),
              for (final (index, card) in cards.indexed)
                if (app.isMemory(card))
                  MemorySheet(
                    key: ValueKey('memory-${card.cardId}'),
                    rationale: app.rationaleFor(card.episodeId),
                    episode: app.episodes[card.episodeId],
                    startsAt: card.startsAt,
                    cardIds: [card.cardId],
                  )
                else
                  _PreparationCard(app: app, card: card, hero: index == 0),
            ],
          ),
        ],
      ),
    );
    if (!app.demoPreview) return main;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Expanded(child: main),
        _PreviewStrip(app: app),
      ],
    );
  }
}

class _OrderPanel extends StatefulWidget {
  const _OrderPanel({
    super.key,
    required this.app,
    required this.orderId,
    required this.collapsible,
  });

  final AppController app;
  final String? orderId;
  final bool collapsible;

  @override
  State<_OrderPanel> createState() => _OrderPanelState();
}

class _OrderPanelState extends State<_OrderPanel> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final app = widget.app;
    final orderId = widget.orderId;
    final order = app.episodes[orderId];
    final images = orderId == null
        ? const <Uint8List>[]
        : app.orderImages(orderId);
    final theme = Theme.of(context);
    return Column(
      key: const ValueKey('main-order'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: DesignTokens.space8,
      children: [
        if (widget.collapsible)
          _OrderSummary(
            order: order,
            thumbnail: images.firstOrNull,
            expanded: _expanded,
            onTap: () => setState(() => _expanded = !_expanded),
          ),
        if (!widget.collapsible || _expanded) ...[
          if (!widget.collapsible)
            KoreanText('주문', style: theme.textTheme.headlineMedium),
          if (app.pickImages != null && orderId == null)
            _UploadBox(app: app)
          else if (app.pickImages != null)
            Align(
              alignment: Alignment.centerLeft,
              child: _galleryButton(app, secondary: widget.collapsible),
            ),
          if (app.galleryError case final error?) StatusMessage(error),
          if (app.hasPendingSelection && !app.pickingImages)
            Wrap(
              spacing: 8,
              children: [
                OutlinedButton(
                  onPressed: app.retryGallery,
                  child: const KoreanText('다시 보내기'),
                ),
                TextButton(
                  onPressed: app.discardGallery,
                  child: const KoreanText('선택 취소'),
                ),
              ],
            ),
          if (orderId != null)
            OrderExtraction(
              key: ValueKey(orderId),
              episode: order,
              images: images,
              rationale: app.rationaleFor(orderId),
              // An order shared elsewhere (another device or the presenter)
              // shows the same staged wait while the Server reads it.
              processing:
                  !widget.collapsible &&
                  (app.isSharedOrder(orderId) ||
                      order?.status == wire.EpisodeStatus.RECEIVED ||
                      order?.status == wire.EpisodeStatus.READING),
              received:
                  app.accepted.contains(orderId) ||
                  app.orderImages(orderId).isNotEmpty,
            )
          else if (app.pickImages != null)
            const SizedBox.shrink()
          else if (app.platform != null) ...[
            const KoreanText('쇼핑 앱에서 주문 화면을 공유하면, 그 주문에 맞춰 집을 준비해요.'),
            const KoreanText('주문 화면을 캡처하고 공유 메뉴에서 SPIRA를 선택해 주세요.'),
          ] else
            const KoreanText('주문 화면을 보내면 필요한 준비를 찾아드려요.'),
        ],
      ],
    );
  }

  Widget _galleryButton(AppController app, {required bool secondary}) {
    final select = app.pickingImages || app.hasPendingSelection
        ? null
        : app.chooseOrderImages;
    const icon = Icon(Icons.photo_library_outlined);
    const label = KoreanText('주문 분석하기');
    return secondary
        ? OutlinedButton.icon(onPressed: select, icon: icon, label: label)
        : FilledButton.icon(onPressed: select, icon: icon, label: label);
  }
}

// Before an order: a large box to send the order screenshots (gallery on Android, file picker on the web).
class _UploadBox extends StatelessWidget {
  const _UploadBox({required this.app});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final select = app.pickingImages || app.hasPendingSelection
        ? null
        : app.chooseOrderImages;
    return Semantics(
      button: true,
      label: '주문 분석하기',
      child: Material(
        key: const ValueKey('upload-box'),
        color: colors.surfaceContainerLow,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.radius8 * 2),
          side: BorderSide(color: colors.primary, width: 1.5),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: select,
          child: Padding(
            padding: const EdgeInsets.symmetric(
              vertical: DesignTokens.space32,
              horizontal: DesignTokens.space20,
            ),
            child: Column(
              spacing: DesignTokens.space12,
              children: [
                CircleAvatar(
                  radius: 32,
                  backgroundColor: colors.primary,
                  foregroundColor: colors.onPrimary,
                  child: app.pickingImages
                      ? const SizedBox.square(
                          dimension: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.add, size: 36),
                ),
                KoreanText('주문 분석하기', style: theme.textTheme.titleLarge),
                KoreanText(
                  '온라인 주문 화면 캡처를 올려 주세요 (1~3장)',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: colors.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// Below the upload box: this home's recent memories as cards. Preparation memories (closed orders with cards,
// as on Calendar) first, then recent orders without cards, five at most.
class _RecentMemories extends StatelessWidget {
  const _RecentMemories({required this.app});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final prepared = app.memoryDates.toList()
      ..sort((a, b) => b.startsAt.compareTo(a.startsAt));
    final shown = prepared.take(5).toList();
    final memoryIds = {for (final m in prepared) m.episodeId};
    final orders = app.recentHistory
        .where((row) => !memoryIds.contains(row.episodeId))
        .take(5 - shown.length)
        .toList();
    String day(String raw) {
      final d = seoulDay(raw);
      return '${d.month}월 ${d.day}일';
    }

    Widget tile({
      required Key key,
      required IconData icon,
      required String title,
      required String subtitle,
      VoidCallback? onTap,
    }) => Card(
      key: key,
      margin: EdgeInsets.zero,
      elevation: 0,
      color: colors.surfaceContainerLow,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(DesignTokens.radius8 * 1.5),
        side: BorderSide(color: colors.outlineVariant),
      ),
      child: ListTile(
        leading: Icon(icon, color: colors.primary),
        title: KoreanText(title),
        subtitle: KoreanText(subtitle),
        trailing: onTap == null ? null : const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );

    return Column(
      key: const ValueKey('recent-memories'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: DesignTokens.space8,
      children: [
        KoreanText('최근 이 집의 기억', style: theme.textTheme.titleMedium),
        if (shown.isEmpty && orders.isEmpty)
          const KoreanText('아직 쌓인 기억이 없어요.'),
        for (final memory in shown)
          tile(
            key: ValueKey('recent-memory-${memory.episodeId}'),
            icon: Icons.event_available_outlined,
            title: '${day(memory.startsAt)} · 준비 기억',
            subtitle: '그날의 준비와 집의 반응',
            onTap: () => showModalBottomSheet<void>(
              context: context,
              isScrollControlled: true,
              useSafeArea: true,
              showDragHandle: true,
              builder: (context) => MemoryDetailSheet(app, memory),
            ),
          ),
        for (final row in orders)
          tile(
            key: ValueKey('recent-order-${row.episodeId}'),
            icon: Icons.shopping_bag_outlined,
            title: '${day(row.sharedAt)} · 주문',
            subtitle: switch (app.episodes[row.episodeId]) {
              final episode? when episode.items.isNotEmpty =>
                episode.items.map((item) => item.type).take(4).join(', '),
              _ => '품목 ${row.itemCount}개',
            },
          ),
      ],
    );
  }
}

class _OrderSummary extends StatelessWidget {
  const _OrderSummary({
    required this.order,
    required this.thumbnail,
    required this.expanded,
    required this.onTap,
  });

  final wire.Episode? order;
  final Uint8List? thumbnail;
  final bool expanded;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final count = order?.itemCount ?? 0;
    final first = order?.items.firstOrNull?.name;
    final summary = [
      '주문 $count개',
      if (first != null) '$first${count > 1 ? ' 외 ${count - 1}개' : ''}',
      if (first == null && (order?.maskedCount ?? 0) > 0)
        '가린 품목 ${order!.maskedCount}개',
    ].join(' · ');
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(DesignTokens.radius12),
      clipBehavior: Clip.antiAlias,
      child: Semantics(
        expanded: expanded,
        child: InkWell(
          key: const ValueKey('order-scan-line'),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.all(DesignTokens.space8),
            child: Row(
              spacing: DesignTokens.space8,
              children: [
                SizedBox.square(
                  dimension: DesignTokens.space32,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(DesignTokens.radius6),
                    child: thumbnail == null
                        ? const Icon(Icons.receipt_long_outlined, size: 20)
                        : Image.memory(
                            thumbnail!,
                            fit: BoxFit.cover,
                            cacheWidth: 96,
                            semanticLabel: '주문 사진',
                            errorBuilder: (_, _, _) => const Icon(
                              Icons.receipt_long_outlined,
                              size: 20,
                            ),
                          ),
                  ),
                ),
                Expanded(
                  child: KoreanText(
                    summary,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                Icon(
                  expanded ? Icons.expand_less : Icons.expand_more,
                  color: colors.onSurfaceVariant,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _PreviewStrip extends StatelessWidget {
  const _PreviewStrip({required this.app});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.space20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Divider(height: 1),
          if (app.exampleShareError case final error?) StatusMessage(error),
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              KoreanText(
                fixturePreviewLabel,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              TextButton(
                onPressed: app.canShareExample ? app.shareExample : null,
                child: KoreanText(
                  app.sharingExample ? '주문을 보내는 중…' : '예시 주문으로 공유',
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
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
      animationStyle: MediaQuery.disableAnimationsOf(context)
          ? AnimationStyle.noAnimation
          : null,
      builder: (context) => AlertDialog(
        title: const KoreanText('이 준비를 멈출까요?'),
        content: const KoreanText('이 카드의 준비만 멈춰요.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const KoreanText('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const KoreanText('멈추기'),
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
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(appCardRadius),
        side: BorderSide(color: hero ? colors.outline : colors.outlineVariant),
      ),
      margin: const EdgeInsets.only(bottom: DesignTokens.space12),
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 8,
          children: [
            Semantics(
              header: true,
              child: KoreanText(
                card.text,
                style: theme.textTheme.headlineMedium,
              ),
            ),
            if (card.startsAt case final start?)
              Wrap(
                spacing: 12,
                runSpacing: 4,
                children: [
                  KoreanText(
                    seoulDateTime(start, fullDate: true),
                    style: theme.textTheme.bodySmall,
                  ),
                  KoreanText(
                    '${card.summary.total}개 중 ${card.summary.done}개 끝남',
                    style: theme.textTheme.bodySmall,
                  ),
                  if (card.summary.waitingFor case final event?)
                    KoreanText(
                      waitingLabel(event),
                      style: theme.textTheme.bodySmall,
                    ),
                ],
              ),
            if (stopPending)
              const StatusMessage('요청함')
            else if (card.stopped)
              const StatusMessage('이 준비가 중지됐어요.'),
            if (app.controlErrors[card.cardId] case final error?)
              StatusMessage(error),
            for (final line in card.lines) ...[
              const Divider(height: 1),
              _PreparationLine(app: app, card: card, line: line),
            ],
            if (!card.stopped && card.buttons.contains(wire.CardButton.STOP))
              Align(
                alignment: Alignment.centerRight,
                child: OutlinedButton(
                  onPressed: !app.canControl || (stopPending && !stopUncertain)
                      ? null
                      : () => _confirmStop(context),
                  child: KoreanText(stopUncertain ? '멈추기 다시 요청' : '멈추기'),
                ),
              ),
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
    final timing = switch (line.when?.time) {
      final time? => seoulDateTime(time),
      null => triggerLabel(line.when?.event),
    };
    final relation = lineRelationLabel(line, card);
    final pending = app.linePending(card, line);
    final outcome = endLabel(line.endState);
    final on = line.state != wire.LineState.OFF;
    return Padding(
      key: ValueKey((card.cardId, line.taskId)),
      padding: const EdgeInsets.symmetric(vertical: DesignTokens.space4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        spacing: DesignTokens.space12,
        children: [
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: DesignTokens.space4,
              children: [
                if (timing != null)
                  KoreanText(
                    relation == null || relation == timing
                        ? timing
                        : '$timing · $relation',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                KoreanText(
                  normalizeKelvin(line.text),
                  style: theme.textTheme.titleMedium,
                ),
                if (outcome != null) KoreanText(outcome),
                if (line.note case final note?
                    when note.isNotEmpty && note != outcome)
                  KoreanText(note),
              ],
            ),
          ),
          Flexible(
            flex: 2,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              spacing: DesignTokens.space4,
              children: [
                StatusBadge(
                  lineLabel(line.state),
                  color: lineStatusColor(context, line.state),
                ),
                if (pending) const StatusMessage('요청함'),
                if (app.canSwitch(card, line))
                  Semantics(
                    label: '${line.text} ${on ? '끄기' : '켜기'}',
                    child: Switch(
                      value: pending ? !on : on,
                      padding: EdgeInsets.zero,
                      trackColor: const WidgetStateProperty.fromMap({
                        WidgetState.disabled: null,
                        WidgetState.selected: DesignTokens.greenSoft,
                      }),
                      thumbColor: const WidgetStateProperty.fromMap({
                        WidgetState.disabled: null,
                        WidgetState.selected: DesignTokens.greenDeep,
                      }),
                      onChanged: pending
                          ? null
                          : (_) => app.switchLine(card, line),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
