// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:spira_app/design_tokens.g.dart';
import 'package:spira_app/features/brand.dart';

void main() {
  testWidgets('the top bar shows the CSE-SPIRA logo before the wordmark', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(appBar: SpiraTopBar())),
    );

    final brand = find.descendant(
      of: find.byType(SpiraTopBar),
      matching: find.byType(SpiraMark),
    );
    final logo = find.descendant(of: brand, matching: find.byType(CustomPaint));
    final wordmark = find.descendant(of: brand, matching: find.text('SPIRA'));

    expect(tester.getSize(logo), const Size.square(26));
    expect(
      logo,
      paints
        ..path(
          color: const Color(0xFF1F2328),
          style: PaintingStyle.stroke,
          strokeWidth: 27,
        )
        ..circle(x: 230, y: 82, radius: 23, color: const Color(0xFFA8743F))
        ..rrect(
          rrect: RRect.fromRectAndRadius(
            const Rect.fromLTRB(157, 262, 303, 367),
            const Radius.circular(10),
          ),
          color: const Color(0xFFA8743F),
        )
        ..rect(
          rect: const Rect.fromLTRB(216, 262, 244, 367),
          color: const Color(0xFF865C32),
        ),
    );
    expect(
      tester.getTopLeft(wordmark).dx,
      greaterThan(tester.getTopRight(logo).dx),
    );
    final style = tester.widget<Text>(wordmark).style!;
    expect(style.color, DesignTokens.green);
    expect(style.letterSpacing, style.fontSize! * 0.16);
  });
}
