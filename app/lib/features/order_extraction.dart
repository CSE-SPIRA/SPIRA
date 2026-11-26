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
      final lines = [
        '받았어요',
        if (current >= 1) '품목 ${order!.itemCount}개를 읽었어요',
        if (current >= 2) '일정과 지난 주문을 살펴봤어요',
        if (current >= 3) intent!,
      ];
      const working = [
        '주문을 읽고 있어요',
        '일정과 지난 주문을 살펴보고 있어요',
        '어떤 준비인지 보고 있어요',
        '집에서 할 일을 정리하고 있어요',
      ];
      final still =
          MediaQuery.disableAnimationsOf(context) ||
          MediaQuery.reduceMotionOf(context);
      return Column(
        key: const ValueKey('order-progress'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 12,
        children: [
          _LoadingPanel(
            status: working[current],
            progress: (current + 1) / (working.length + 1),
            still: still,
          ),
          if (images.isNotEmpty) photos,
          for (final (index, line) in lines.indexed)
            _Appear(
              key: ValueKey('order-progress-line-$index'),
              still: still,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 8,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Icon(
                      Icons.check,
                      size: 16,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                  ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      spacing: 6,
                      children: [
                        KoreanText(line),
                        if (index == 1) _ItemNames(episode: order!),
                      ],
                    ),
                  ),
                ],
              ),
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

class _LoadingPanel extends StatelessWidget {
  const _LoadingPanel({
    required this.status,
    required this.progress,
    required this.still,
  });

  final String status;
  final double progress;
  final bool still;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final label = Row(
      spacing: 12,
      children: [
        SizedBox.square(
          dimension: 18,
          child: still
              ? Icon(Icons.hourglass_top, size: 18, color: colors.primary)
              : CircularProgressIndicator(
                  strokeWidth: 2.4,
                  color: colors.primary,
                ),
        ),
        Expanded(child: KoreanText(status, style: theme.textTheme.titleSmall)),
      ],
    );
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.surfaceContainerLow,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 12,
        children: [
          Semantics(
            liveRegion: true,
            child: still ? label : _StepPulse(child: label),
          ),
          TweenAnimationBuilder<double>(
            tween: Tween(end: progress),
            duration: still ? Duration.zero : const Duration(milliseconds: 400),
            curve: Curves.easeOut,
            builder: (context, value, _) => ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(
                value: value,
                minHeight: 4,
                color: colors.primary,
                backgroundColor: colors.surfaceContainerHighest,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ItemNames extends StatelessWidget {
  const _ItemNames({required this.episode});

  final wire.Episode episode;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final item in episode.items)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
            ),
            child: KoreanText(item.name, style: theme.textTheme.bodySmall),
          ),
      ],
    );
  }
}

class _Appear extends StatefulWidget {
  const _Appear({required this.still, required this.child, super.key});

  final bool still;
  final Widget child;

  @override
  State<_Appear> createState() => _AppearState();
}

class _AppearState extends State<_Appear> with SingleTickerProviderStateMixin {
  late final _animation = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 350),
  )..forward();
  late final _curve = CurvedAnimation(
    parent: _animation,
    curve: Curves.easeOut,
  );

  @override
  void dispose() {
    _animation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.still
      ? widget.child
      : FadeTransition(
          opacity: _curve,
          child: SlideTransition(
            position: _curve.drive(
              Tween(begin: const Offset(0, 0.25), end: Offset.zero),
            ),
            child: widget.child,
          ),
        );
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
