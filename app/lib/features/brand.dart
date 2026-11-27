// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'labels.dart';

class SpiraMark extends StatelessWidget {
  const SpiraMark({super.key, this.large = false});

  final bool large;

  @override
  Widget build(BuildContext context) {
    final wordmarkSize = large ? DesignTokens.size34 : DesignTokens.size22;
    final markScale = wordmarkSize / DesignTokens.size22;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        CustomPaint(
          size: Size.square(26 * markScale),
          painter: const _SpiraLogoPainter(),
        ),
        SizedBox(width: 13 * markScale),
        KoreanText(
          'SPIRA',
          maxLines: 1,
          style: TextStyle(
            color: DesignTokens.green,
            fontSize: wordmarkSize,
            fontWeight: FontWeight.w700,
            letterSpacing: wordmarkSize * 0.16,
          ),
        ),
      ],
    );
  }
}

class _SpiraLogoPainter extends CustomPainter {
  const _SpiraLogoPainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Coordinates are measured on the 460 × 460 CSE-SPIRA organisation avatar.
    canvas.save();
    canvas.scale(size.shortestSide / 460);

    final roof = Path()
      ..moveTo(101.5, 248.5)
      ..lineTo(230, 152.5)
      ..lineTo(357.5, 248.5);
    canvas.drawPath(
      roof,
      Paint()
        ..color = const Color(0xFF1F2328)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 27
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );

    final brown = Paint()..color = const Color(0xFFA8743F);
    canvas.drawCircle(const Offset(230, 82), 23, brown);
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        const Rect.fromLTRB(157, 262, 303, 367),
        const Radius.circular(10),
      ),
      brown,
    );
    canvas.drawRect(
      const Rect.fromLTRB(216, 262, 244, 367),
      Paint()..color = const Color(0xFF865C32),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_SpiraLogoPainter oldDelegate) => false;
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
