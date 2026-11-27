// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:spira_app/design_tokens.g.dart';
import 'package:spira_app/features/brand.dart';

void main() {
  testWidgets('the top bar paints the SPIRA leaf beside the wordmark', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(appBar: SpiraTopBar())),
    );

    final brand = find.descendant(
      of: find.byType(SpiraTopBar),
      matching: find.byType(SpiraMark),
    );
    final leaf = find.descendant(of: brand, matching: find.byType(CustomPaint));
    final wordmark = find.descendant(of: brand, matching: find.text('SPIRA'));

    expect(tester.getSize(leaf), const Size.square(26));
    expect(
      leaf,
      paints
        ..drrect(color: DesignTokens.green)
        ..drrect(color: DesignTokens.green),
    );
    expect(
      tester.getTopLeft(wordmark).dx,
      greaterThan(tester.getCenter(leaf).dx),
    );
    final style = tester.widget<Text>(wordmark).style!;
    expect(style.letterSpacing, style.fontSize! * 0.16);
  });
}
