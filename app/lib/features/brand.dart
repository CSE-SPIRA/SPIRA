import 'dart:math' as math;

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'labels.dart';

class SpiraMark extends StatelessWidget {
  const SpiraMark({super.key});

  static const _wordmarkSize = DesignTokens.size22;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Transform.rotate(
        angle: -34 * math.pi / 180,
        child: const CustomPaint(
          size: Size.square(26),
          painter: _SpiraLeafPainter(),
        ),
      ),
      const SizedBox(width: 13),
      const KoreanText(
        'SPIRA',
        maxLines: 1,
        style: TextStyle(
          color: DesignTokens.green,
          fontSize: _wordmarkSize,
          fontWeight: FontWeight.w700,
          letterSpacing: _wordmarkSize * 0.16,
        ),
      ),
    ],
  );
}

class _SpiraLeafPainter extends CustomPainter {
  const _SpiraLeafPainter();

  static RRect _outline(Rect box) {
    final large = Radius.elliptical(box.width * 0.74, box.height * 0.74);
    final small = Radius.elliptical(box.width * 0.43, box.height * 0.43);
    // CSS scales overlapping radii together before subtracting the border.
    return RRect.fromRectAndCorners(
      box,
      topLeft: large,
      topRight: small,
      bottomLeft: small,
      bottomRight: large,
    ).scaleRadii();
  }

  @override
  void paint(Canvas canvas, Size size) {
    const outerStroke = 1.8;
    const innerStroke = 1.4;
    final paint = Paint()..color = DesignTokens.green;
    final box = Offset.zero & size;
    final outer = _outline(box);
    // The pseudo-element's inset is measured from the parent's padding edge.
    final inner = _outline(box.deflate(outerStroke + 4));
    canvas.drawDRRect(outer, outer.deflate(outerStroke), paint);
    canvas.drawDRRect(inner, inner.deflate(innerStroke), paint);
  }

  @override
  bool shouldRepaint(_SpiraLeafPainter oldDelegate) => false;
}

class SpiraTopBar extends StatelessWidget implements PreferredSizeWidget {
  const SpiraTopBar({
    super.key,
    this.showFixtureLabel = false,
    this.onEnterToken,
  });

  final bool showFixtureLabel;
  final VoidCallback? onEnterToken;

  @override
  Size get preferredSize => const Size.fromHeight(kToolbarHeight);

  @override
  Widget build(BuildContext context) => AppBar(
    automaticallyImplyLeading: false,
    excludeHeaderSemantics: true,
    scrolledUnderElevation: 0,
    titleSpacing: DesignTokens.space12,
    title: Row(
      children: [
        Expanded(
          child: showFixtureLabel
              ? KoreanText(
                  fixturePreviewLabel,
                  style: Theme.of(context).textTheme.bodySmall,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                )
              : const SizedBox.shrink(),
        ),
        Semantics(header: true, child: const SpiraMark()),
        Expanded(
          child: Align(
            alignment: Alignment.centerRight,
            child: onEnterToken == null
                ? null
                : IconButton(
                    tooltip: '서버 접속 토큰 입력',
                    onPressed: onEnterToken,
                    icon: const Icon(Icons.key),
                  ),
          ),
        ),
      ],
    ),
  );
}
