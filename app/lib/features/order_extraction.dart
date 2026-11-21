import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../contracts.dart' as wire;
import '../theme.dart';
import '../korean_text.dart';
import 'setup.dart';

const _scanDuration = Duration(milliseconds: 2400);

class OrderExtraction extends StatefulWidget {
  const OrderExtraction({
    super.key,
    required this.episode,
    required this.images,
    required this.status,
    required this.awaitingEpisode,
    required this.onComplete,
    required this.rationale,
    required this.edit,
    required this.child,
  });

  final wire.Episode? episode;
  final List<Uint8List> images;
  final String? status;
  final bool awaitingEpisode;
  final ValueChanged<List<Uint8List>> onComplete;
  final Future<wire.Rationale>? rationale;
  final Widget? edit;
  final Widget child;

  bool get hasRows =>
      (episode?.items.isNotEmpty ?? false) || (episode?.maskedCount ?? 0) > 0;

  bool get hasResult =>
      !awaitingEpisode &&
      episode != null &&
      (hasRows ||
          (episode!.status != wire.EpisodeStatus.RECEIVED &&
              episode!.status != wire.EpisodeStatus.READING));

  @override
  State<OrderExtraction> createState() => _OrderExtractionState();
}

class _OrderExtractionState extends State<OrderExtraction>
    with SingleTickerProviderStateMixin, AutomaticKeepAliveClientMixin {
  late final _reveal = AnimationController(vsync: this, duration: appSettle)
    ..addStatusListener((status) {
      if (status != AnimationStatus.completed) return;
      final images = widget.images;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && identical(widget.images, images)) {
          widget.onComplete(images);
        }
      });
    });

  Timer? _scanWindow;
  bool _expanded = false;
  bool _reduceMotion = false;

  @override
  bool get wantKeepAlive => widget.images.isNotEmpty;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduceMotion = MediaQuery.disableAnimationsOf(context);
    if (_reduceMotion && _reveal.isAnimating) _reveal.value = 1;
  }

  @override
  void didUpdateWidget(OrderExtraction oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(widget.images, oldWidget.images)) {
      updateKeepAlive();
      _scanWindow?.cancel();
      _scanWindow = null;
      if (widget.images.isNotEmpty) _reveal.reset();
    }
    if (!widget.hasRows || widget.images.isNotEmpty) {
      _expanded = false;
    }
    _advance();
  }

  void _previewFrame() {
    if (_scanWindow != null) return;
    final images = widget.images;
    // Start the scan window after the decoded preview has had a frame to paint.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          !identical(widget.images, images) ||
          _scanWindow != null) {
        return;
      }
      setState(() {
        _scanWindow = Timer(_scanDuration, () => setState(_advance));
      });
    });
  }

  void _advance() {
    if (widget.images.isEmpty ||
        _scanWindow == null ||
        _scanWindow!.isActive ||
        !widget.hasResult ||
        _reveal.isAnimating ||
        _reveal.isCompleted) {
      return;
    }
    if (_reduceMotion || !widget.hasRows) {
      _reveal.value = 1;
    } else {
      _reveal.forward();
    }
  }

  @override
  void dispose() {
    _scanWindow?.cancel();
    _reveal.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return FutureBuilder<wire.Rationale>(
      future: widget.rationale,
      builder: (context, snapshot) => AnimatedBuilder(
        animation: _reveal,
        child: widget.child,
        builder: (context, following) {
          final episode = widget.episode;
          final previewing = widget.images.isNotEmpty && !_reveal.isCompleted;
          final revealing = previewing && _reveal.isAnimating;
          final expanded = _expanded || revealing;
          final progress = revealing ? appEase.transform(_reveal.value) : 1.0;
          final preview = revealing ? 1 - progress : 1.0;
          final status = previewing && episode != null
              ? '주문을 읽고 있어요.'
              : widget.status;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (status != null) StatusMessage(status),
              if (previewing)
                ClipRect(
                  child: Align(
                    alignment: Alignment.topCenter,
                    heightFactor: preview,
                    child: Opacity(
                      opacity: preview,
                      child: _CapturePreview(
                        images: widget.images,
                        animate:
                            _scanWindow != null && !revealing && !_reduceMotion,
                        onFrame: _previewFrame,
                      ),
                    ),
                  ),
                ),
              if ((!previewing || revealing) && episode != null)
                if (widget.hasRows) ...[
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Semantics(
                      expanded: expanded,
                      child: TextButton.icon(
                        onPressed: revealing
                            ? null
                            : () => setState(() => _expanded = !_expanded),
                        icon: Icon(
                          expanded ? Icons.expand_less : Icons.expand_more,
                        ),
                        label: KoreanText('읽은 품목 ${episode.itemCount}개'),
                      ),
                    ),
                  ),
                  if (expanded)
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
                  if (_expanded && !previewing && widget.edit != null)
                    Align(alignment: Alignment.centerLeft, child: widget.edit),
                ] else if (episode.itemCount > 0)
                  KoreanText('읽은 품목 ${episode.itemCount}개'),
              if (!previewing) following!,
            ],
          );
        },
      ),
    );
  }
}

class _CapturePreview extends StatelessWidget {
  const _CapturePreview({
    required this.images,
    required this.animate,
    required this.onFrame,
  });

  final List<Uint8List> images;
  final bool animate;
  final VoidCallback onFrame;

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
                frameBuilder: (_, child, frame, _) {
                  if (frame != null) onFrame();
                  return child;
                },
                errorBuilder: (_, _, _) {
                  onFrame();
                  return const SizedBox.shrink();
                },
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
  late final _scan = AnimationController(vsync: this, duration: _scanDuration)
    ..repeat();

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
          pictures!,
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
          child: KoreanText('가린 물건 ${episode.maskedCount}개', style: small),
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
                KoreanText(item.type, style: theme.textTheme.titleMedium),
                KoreanText(item.name, style: small),
                if (setAside) KoreanText('이번 준비와 따로 본 물건', style: small),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: KoreanText(
              item.qty == null ? '수량 미확인' : '${item.qty}개',
              style: small,
            ),
          ),
        ],
      ),
    );
  }
}
