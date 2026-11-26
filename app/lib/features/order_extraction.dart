import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../contracts.dart' as wire;
import '../korean_text.dart';
import 'labels.dart';

class OrderExtraction extends StatelessWidget {
  const OrderExtraction({
    super.key,
    required this.episode,
    required this.images,
    required this.received,
    required this.rationale,
    required this.processing,
  });

  final wire.Episode? episode;
  final List<Uint8List> images;
  final bool received;
  final wire.Rationale? rationale;
  final bool processing;

  @override
  Widget build(BuildContext context) {
    final order = episode;
    final status = order?.status;
    final intake =
        processing &&
        (status == null ||
            status == wire.EpisodeStatus.RECEIVED ||
            status == wire.EpisodeStatus.READING ||
            (status != wire.EpisodeStatus.CLOSED && order!.cardIds.isNotEmpty));
    final photos = Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final (index, image) in images.indexed)
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.memory(
              image,
              width: 48,
              height: 62,
              fit: BoxFit.cover,
              cacheWidth: 160,
              semanticLabel: '보낸 사진 ${index + 1}',
              errorBuilder: (_, _, _) => const SizedBox(
                width: 48,
                height: 62,
                child: Icon(Icons.image_not_supported_outlined),
              ),
            ),
          ),
      ],
    );
    if (intake) {
      final hasItems = order?.items.isNotEmpty ?? false;
      final hasContext = hasItems && rationale != null;
      final intent = hasContext
          ? rationale!.intents.firstOrNull?.intentText
          : null;
      final current = intent?.isNotEmpty == true
          ? 3
          : hasContext
          ? 2
          : hasItems
          ? 1
          : 0;
      final labels = [
        '받았어요',
        if (hasItems) '품목 ${order!.itemCount}개를 읽었어요' else '품목 읽기',
        if (hasContext) '일정과 지난 주문을 살펴봤어요' else '일정과 지난 주문 살펴보기',
        if (current == 3) intent! else '주문에 담긴 준비 살펴보기',
      ];
      return Column(
        key: const ValueKey('order-progress'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 8,
        children: [
          if (images.isNotEmpty) photos,
          for (final (index, label) in labels.indexed)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 8,
              children: [
                _StepIndicator(
                  done: index < current,
                  current: index == current,
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    spacing: 4,
                    children: [
                      KoreanText(
                        label,
                        style: TextStyle(
                          color: index > current
                              ? Theme.of(context).colorScheme.onSurfaceVariant
                              : null,
                        ),
                      ),
                      if (index == 1 && hasItems)
                        OrderItems(
                          episode: order!,
                          showGuidance: true,
                          showHeading: false,
                        ),
                    ],
                  ),
                ),
              ],
            ),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 8,
      children: [
        if (images.isNotEmpty) photos,
        if (received || status == wire.EpisodeStatus.RECEIVED)
          const KoreanText('받았어요'),
        if (status == wire.EpisodeStatus.READ_FAILED)
          const KoreanText('읽지 못했어요. 다시 보내 주세요')
        else if (order != null && status != wire.EpisodeStatus.RECEIVED)
          OrderItems(episode: order, showGuidance: true),
      ],
    );
  }
}

class OrderItems extends StatelessWidget {
  const OrderItems({
    super.key,
    required this.episode,
    this.showGuidance = false,
    this.showHeading = true,
  });

  final wire.Episode episode;
  final bool showGuidance;
  final bool showHeading;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final guidance = <String, List<wire.ItemTaskElement>>{};
    if (showGuidance) {
      for (final task in episode.itemTasks) {
        guidance.putIfAbsent(task.item, () => []).add(task);
      }
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 8,
      children: [
        if (showGuidance && showHeading)
          KoreanText(
            '품목 ${episode.itemCount}개를 읽었어요',
            style: theme.textTheme.titleSmall,
          ),
        for (final item in episode.items)
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            spacing: 4,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 8,
                children: [
                  Expanded(child: KoreanText(item.name)),
                  if (item.qty case final quantity?) KoreanText('$quantity개'),
                ],
              ),
              for (final task in guidance.remove(item.type) ?? const [])
                _ItemGuidance(task: task),
            ],
          ),
        if (episode.maskedCount > 0)
          KoreanText('가린 품목 ${episode.maskedCount}개'),
      ],
    );
  }
}

class _ItemGuidance extends StatelessWidget {
  const _ItemGuidance({required this.task});

  final wire.ItemTaskElement task;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final kind = switch (task.kind) {
      wire.NoticeKind.STORAGE => '냉장고에 보관 안내',
      wire.NoticeKind.PREP => '냉장고에 손질 안내',
      null => '품목 안내',
    };
    final state = switch (task.state) {
      wire.LineState.SCHEDULED => '택배가 들어오면 보여 드려요',
      wire.LineState.DONE => '냉장고에 띄웠어요',
      _ => lineLabel(task.state),
    };
    return Padding(
      padding: const EdgeInsets.only(left: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 2,
        children: [
          KoreanText(kind, style: theme.textTheme.labelLarge),
          if (task.text case final text? when text.isNotEmpty)
            KoreanText(text, style: theme.textTheme.bodySmall),
          KoreanText(
            state,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }
}

class _StepIndicator extends StatelessWidget {
  const _StepIndicator({required this.done, required this.current});

  final bool done;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final icon = Icon(
      done
          ? Icons.check
          : current
          ? Icons.circle
          : Icons.circle_outlined,
      size: 16,
      color: done || current ? colors.primary : colors.outlineVariant,
    );
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child:
          current &&
              !MediaQuery.disableAnimationsOf(context) &&
              !MediaQuery.reduceMotionOf(context)
          ? _StepPulse(child: icon)
          : icon,
    );
  }
}

class _StepPulse extends StatefulWidget {
  const _StepPulse({required this.child});

  final Widget child;

  @override
  State<_StepPulse> createState() => _StepPulseState();
}

class _StepPulseState extends State<_StepPulse>
    with SingleTickerProviderStateMixin {
  late final _animation = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1200),
  )..repeat(reverse: true);
  late final _opacity = _animation.drive(
    Tween(begin: 0.55, end: 1.0).chain(CurveTween(curve: Curves.easeInOut)),
  );

  @override
  void dispose() {
    _animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
    key: const ValueKey('order-progress-pulse'),
    opacity: _opacity,
    child: widget.child,
  );
}
