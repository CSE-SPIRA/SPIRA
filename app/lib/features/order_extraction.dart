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
const _itemsDuration = Duration(milliseconds: 1500);
const _reducedDwell = Duration(milliseconds: 800);

enum JudgmentStep {
  situation(Duration(seconds: 2)),
  intent(Duration(milliseconds: 2500)),
  tasks(Duration(milliseconds: 1500));

  const JudgmentStep(this.dwell);

  final Duration dwell;
}

class OrderExtraction extends StatefulWidget {
  const OrderExtraction({
    super.key,
    required this.episode,
    required this.images,
    required this.sharedImages,
    required this.status,
    required this.awaitingEpisode,
    required this.onComplete,
    required this.rationale,
    required this.waitingForJudgment,
    required this.canShowJudgment,
    required this.judgment,
    required this.edit,
    required this.child,
  });

  final wire.Episode? episode;
  final List<Uint8List> images;
  final List<Uint8List> sharedImages;
  final String? status;
  final bool awaitingEpisode;
  final ValueChanged<List<Uint8List>> onComplete;
  final wire.Rationale? rationale;
  final bool waitingForJudgment;
  final bool canShowJudgment;
  final Widget Function(JudgmentStep step, wire.Rationale result) judgment;
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
      _holdStep(_itemsDuration);
    });

  Timer? _scanWindow;
  Timer? _stepTimer;
  JudgmentStep? _step;
  wire.Rationale? _judgmentResult;
  bool _holdingStep = false;
  bool _finished = false;
  bool _expanded = false;
  bool _reduceMotion = false;

  @override
  bool get wantKeepAlive => widget.images.isNotEmpty;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _reduceMotion = MediaQuery.disableAnimationsOf(context);
    if (_reduceMotion && _reveal.isAnimating) _reveal.value = 1;
    _advance();
  }

  @override
  void didUpdateWidget(OrderExtraction oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(widget.images, oldWidget.images)) {
      updateKeepAlive();
      _scanWindow?.cancel();
      _scanWindow = null;
      _stepTimer?.cancel();
      _holdingStep = false;
      _step = null;
      _judgmentResult = null;
      _finished = false;
      _reveal.reset();
    }
    if ((!widget.hasRows && widget.sharedImages.isEmpty) ||
        widget.images.isNotEmpty) {
      _expanded = false;
    }
    _advance();
  }

  void _finish() {
    if (_finished) return;
    _finished = true;
    _scanWindow?.cancel();
    _stepTimer?.cancel();
    _reveal.stop();
    final images = widget.images;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && identical(widget.images, images)) {
        widget.onComplete(images);
      }
    });
  }

  void _holdStep(Duration duration) {
    _holdingStep = true;
    final images = widget.images;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !identical(widget.images, images) || _finished) return;
      _stepTimer = Timer(_reduceMotion ? _reducedDwell : duration, () {
        _holdingStep = false;
        setState(_advance);
      });
    });
  }

  void _previewFrame() {
    if (_scanWindow != null) return;
    final images = widget.images;
    // Start the scan window after the decoded preview has had a frame to paint.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          !identical(widget.images, images) ||
          _scanWindow != null ||
          _finished) {
        return;
      }
      setState(() {
        _scanWindow = Timer(
          _reduceMotion ? _reducedDwell : _scanDuration,
          () => setState(_advance),
        );
      });
    });
  }

  void _advance() {
    if (widget.images.isEmpty || _finished) return;
    if (_reveal.isCompleted) {
      if (_holdingStep) return;
      if (_step == null) {
        if (widget.waitingForJudgment) return;
        final result = widget.rationale;
        if (!widget.canShowJudgment ||
            result == null ||
            result.intents.isEmpty) {
          _finish();
          return;
        }
        _judgmentResult = result;
      } else if (_step == JudgmentStep.tasks) {
        _finish();
        return;
      }
      final next = JudgmentStep.values[(_step?.index ?? -1) + 1];
      _step = next;
      _holdStep(appSettle + next.dwell);
    } else if (_scanWindow != null &&
        !_scanWindow!.isActive &&
        widget.hasResult &&
        !_reveal.isAnimating) {
      if (!widget.hasRows) {
        _finish();
        return;
      }
      if (_reduceMotion) {
        _reveal.value = 1;
      } else {
        _reveal.forward();
      }
    }
  }

  void _openSharedOrder() {
    final images = widget.sharedImages;
    Navigator.push<void>(
      context,
      MaterialPageRoute(
        builder: (context) => Scaffold(
          appBar: AppBar(title: const KoreanText('공유한 주문 보기')),
          body: SafeArea(
            top: false,
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                spacing: 12,
                children: [
                  for (final (index, image) in images.indexed)
                    Image.memory(
                      image,
                      fit: BoxFit.contain,
                      semanticLabel: _captureLabel(index, images.length),
                      errorBuilder: (_, _, _) =>
                          const StatusMessage('공유한 주문 화면을 열 수 없어요.'),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _scanWindow?.cancel();
    _stepTimer?.cancel();
    _reveal.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return AnimatedBuilder(
      animation: _reveal,
      child: widget.child,
      builder: (context, following) {
        final episode = widget.episode;
        final presenting = widget.images.isNotEmpty && !_finished;
        final revealing = presenting && _reveal.isAnimating;
        final previewing = presenting && !_reveal.isCompleted && !revealing;
        final expanded =
            _expanded || (presenting && !previewing && _step == null);
        final progress = revealing ? appEase.transform(_reveal.value) : 1.0;
        final canOpenCapture = !presenting && widget.sharedImages.isNotEmpty;
        final captureButton = Align(
          alignment: Alignment.centerLeft,
          child: TextButton(
            onPressed: _openSharedOrder,
            child: const KoreanText('공유한 주문 보기'),
          ),
        );
        final status = presenting && episode != null
            ? (previewing ? '주문을 읽고 있어요.' : null)
            : widget.status;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (status != null) StatusMessage(status),
            if (presenting)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () => setState(_finish),
                  child: const KoreanText('바로 보기'),
                ),
              ),
            if (previewing)
              _CapturePreview(
                images: widget.images,
                animate: _scanWindow != null && !_reduceMotion,
                onFrame: _previewFrame,
              ),
            if (!previewing && episode != null)
              if (widget.hasRows ||
                  (canOpenCapture && episode.itemCount > 0)) ...[
                Align(
                  alignment: Alignment.centerLeft,
                  child: Semantics(
                    expanded: expanded,
                    child: TextButton.icon(
                      onPressed: presenting
                          ? null
                          : () => setState(() => _expanded = !_expanded),
                      icon: Icon(
                        expanded ? Icons.expand_less : Icons.expand_more,
                      ),
                      label: KoreanText('읽은 품목 ${episode.itemCount}개'),
                    ),
                  ),
                ),
                if (_expanded && canOpenCapture) captureButton,
                if (expanded && widget.hasRows)
                  ClipRect(
                    child: Align(
                      alignment: Alignment.topCenter,
                      heightFactor: progress,
                      child: OrderItemList(
                        episode: episode,
                        unbundled: presenting
                            ? const []
                            : widget.rationale?.unbundled ?? const [],
                        reveal: progress,
                      ),
                    ),
                  ),
                if (_expanded && !previewing && widget.edit != null)
                  Align(alignment: Alignment.centerLeft, child: widget.edit),
              ] else if (episode.itemCount > 0)
                KoreanText('읽은 품목 ${episode.itemCount}개')
              else if (canOpenCapture)
                captureButton,
            if (!presenting)
              following!
            else if (_step case final step?)
              KeyedSubtree(
                key: ValueKey(step),
                child: widget.judgment(step, _judgmentResult!),
              ),
          ],
        );
      },
    );
  }
}

String _captureLabel(int index, int count) =>
    count == 1 ? '공유한 주문 화면' : '공유한 주문 화면 ${index + 1}';

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
                  height: 600,
                  policy: ResizeImagePolicy.fit,
                ),
                fit: BoxFit.contain,
                semanticLabel: _captureLabel(index, images.length),
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
      height: 240,
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
