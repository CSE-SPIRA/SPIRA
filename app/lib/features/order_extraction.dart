import 'dart:math' as math;
import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../contracts.dart' as wire;
import '../theme.dart';

class OrderExtraction extends StatefulWidget {
  const OrderExtraction({
    super.key,
    required this.episode,
    required this.images,
    required this.rationale,
    required this.child,
  });

  final wire.Episode? episode;
  final List<Uint8List> images;
  final Future<wire.Rationale>? rationale;
  final Widget child;

  bool get hasRows =>
      (episode?.items.isNotEmpty ?? false) || (episode?.maskedCount ?? 0) > 0;

  bool get reading =>
      !hasRows &&
      (episode == null ||
          episode!.status == wire.EpisodeStatus.RECEIVED ||
          episode!.status == wire.EpisodeStatus.READING);

  @override
  State<OrderExtraction> createState() => _OrderExtractionState();
}

class _OrderExtractionState extends State<OrderExtraction>
    with SingleTickerProviderStateMixin {
  late final _reveal = AnimationController(vsync: this, value: 1)
    ..addStatusListener((status) {
      if (status == AnimationStatus.completed) _revealingImages = const [];
    });

  bool _expanded = false;
  bool _initialized = false;
  bool _reduceMotion = false;
  bool _previewFirst = false;
  List<Uint8List> _revealingImages = const [];

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduceMotion = MediaQuery.disableAnimationsOf(context);
    if (!_initialized) {
      _initialized = true;
      if (widget.hasRows && widget.images.isNotEmpty) {
        _showItems(previewFirst: true);
      }
    } else if (_reduceMotion && _reveal.isAnimating) {
      _reveal.value = 1;
    }
  }

  @override
  void didUpdateWidget(OrderExtraction oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.hasRows && !oldWidget.hasRows) {
      _showItems(previewFirst: oldWidget.images.isEmpty);
    } else if (!widget.hasRows && oldWidget.hasRows) {
      _expanded = false;
      _reveal.value = 1;
    }
  }

  void _showItems({required bool previewFirst}) {
    _expanded = true;
    if (_reduceMotion || widget.images.isEmpty) return;
    _previewFirst = previewFirst;
    _revealingImages = widget.images;
    _reveal.duration = previewFirst ? appSettle * 2 : appSettle;
    _reveal.forward(from: 0);
  }

  @override
  void dispose() {
    _reveal.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<wire.Rationale>(
    future: widget.rationale,
    builder: (context, snapshot) => AnimatedBuilder(
      animation: _reveal,
      child: widget.child,
      builder: (context, following) {
        final episode = widget.episode;
        final revealing = _reveal.value < 1;
        final progress = appEase.transform(
          revealing && _previewFirst
              ? const Interval(.5, 1).transform(_reveal.value)
              : _reveal.value,
        );
        final images = widget.reading ? widget.images : _revealingImages;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (images.isNotEmpty)
              ClipRect(
                child: Align(
                  alignment: Alignment.topCenter,
                  heightFactor: 1 - (revealing ? progress : 0),
                  child: Opacity(
                    opacity: 1 - (revealing ? progress : 0),
                    child: _CapturePreview(
                      images: images,
                      animate: !_reduceMotion,
                    ),
                  ),
                ),
              ),
            if (episode != null && widget.hasRows) ...[
              Align(
                alignment: Alignment.centerLeft,
                child: Semantics(
                  expanded: _expanded,
                  child: TextButton.icon(
                    onPressed: revealing
                        ? null
                        : () => setState(() => _expanded = !_expanded),
                    icon: Icon(
                      _expanded ? Icons.expand_less : Icons.expand_more,
                    ),
                    label: Text('읽은 품목 ${episode.itemCount}개'),
                  ),
                ),
              ),
              if (_expanded)
                ClipRect(
                  child: Align(
                    alignment: Alignment.topCenter,
                    heightFactor: progress,
                    child: OrderItemList(
                      episode: episode,
                      unbundled: snapshot.data?.unbundled ?? const [],
                      reveal: progress,
                    ),
                  ),
                ),
            ] else if (episode != null && episode.itemCount > 0)
              Text('읽은 품목 ${episode.itemCount}개'),
            if (!revealing) following!,
          ],
        );
      },
    ),
  );
}

class _CapturePreview extends StatelessWidget {
  const _CapturePreview({required this.images, required this.animate});

  final List<Uint8List> images;
  final bool animate;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final pictures = Row(
      children: [
        for (final (index, image) in images.indexed)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4),
              child: Image(
                image: ResizeImage(
                  MemoryImage(image),
                  width: 360,
                  height: 400,
                  policy: ResizeImagePolicy.fit,
                ),
                fit: BoxFit.contain,
                semanticLabel: images.length == 1
                    ? '공유한 주문 화면'
                    : '공유한 주문 화면 ${index + 1}',
                errorBuilder: (_, _, _) => const SizedBox.shrink(),
              ),
            ),
          ),
      ],
    );
    return Container(
      constraints: const BoxConstraints(maxWidth: 400),
      height: 184,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: colors.surfaceContainerHighest,
        border: Border.all(color: colors.outlineVariant),
        borderRadius: BorderRadius.circular(12),
      ),
      padding: const EdgeInsets.all(8),
      child: animate ? _ScanningCapture(child: pictures) : pictures,
    );
  }
}

class _ScanningCapture extends StatefulWidget {
  const _ScanningCapture({required this.child});

  final Widget child;

  @override
  State<_ScanningCapture> createState() => _ScanningCaptureState();
}

class _ScanningCaptureState extends State<_ScanningCapture>
    with SingleTickerProviderStateMixin {
  late final _scan = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat();

  @override
  void dispose() {
    _scan.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _scan,
    child: widget.child,
    builder: (context, pictures) {
      final opacity = math.sin(_scan.value * math.pi);
      final color = Theme.of(context).colorScheme.outline;
      return Stack(
        fit: StackFit.expand,
        children: [
          Transform.rotate(
            angle: .025 * math.sin(_scan.value * 2 * math.pi),
            child: pictures,
          ),
          Align(
            alignment: Alignment(0, 2 * _scan.value - 1),
            child: FractionallySizedBox(
              widthFactor: .8,
              child: ExcludeSemantics(
                child: DecoratedBox(
                  key: const ValueKey('order-scan-line'),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: .75 * opacity),
                    boxShadow: [
                      BoxShadow(
                        color: color.withValues(alpha: .55 * opacity),
                        blurRadius: 12,
                        spreadRadius: 3,
                      ),
                    ],
                  ),
                  child: const SizedBox(height: 2),
                ),
              ),
            ),
          ),
        ],
      );
    },
  );
}

class OrderItemList extends StatelessWidget {
  const OrderItemList({
    super.key,
    required this.episode,
    required this.unbundled,
    this.reveal = 1,
  });

  final wire.Episode episode;
  final List<String> unbundled;
  final double reveal;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final small = theme.textTheme.bodySmall?.copyWith(
      color: colors.onSurfaceVariant,
    );
    final rows = [
      for (final item in episode.items)
        _ItemRow(item: item, setAside: unbundled.contains(item.type)),
      if (episode.maskedCount > 0)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text('가린 물건 ${episode.maskedCount}개', style: small),
        ),
    ];
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.outlineVariant),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (final (index, row) in rows.indexed)
            _RevealRow(
              progress: reveal,
              delay: index / rows.length * .25,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [if (index > 0) const Divider(height: 1), row],
              ),
            ),
        ],
      ),
    );
  }
}

class _RevealRow extends StatelessWidget {
  const _RevealRow({
    required this.progress,
    required this.delay,
    required this.child,
  });

  final double progress;
  final double delay;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (progress == 1) return child;
    final position = Interval(delay, 1).transform(progress);
    return Opacity(
      opacity: position,
      child: Transform.translate(
        offset: Offset(0, -28 * (1 - position)),
        child: child,
      ),
    );
  }
}

class _ItemRow extends StatelessWidget {
  const _ItemRow({required this.item, required this.setAside});

  final wire.EpisodeItem item;
  final bool setAside;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final small = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 3,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(item.type, style: theme.textTheme.titleMedium),
                Text(item.name, style: small),
                if (setAside) Text('이번 준비와 따로 본 물건', style: small),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              item.qty == null ? '수량 미확인' : '${item.qty}개',
              style: small,
            ),
          ),
        ],
      ),
    );
  }
}
