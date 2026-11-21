import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:spira_app/korean_text.dart';

void main() {
  testWidgets('Hangul wraps between words, including across styling', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(
      const Directionality(
        textDirection: TextDirection.ltr,
        child: Center(
          child: SizedBox(
            width: 85,
            child: KoreanText.rich(
              TextSpan(
                text: '가나 다',
                children: [
                  TextSpan(
                    text: '라마-AB)',
                    style: TextStyle(color: Color(0xFF123456)),
                  ),
                ],
              ),
              style: TextStyle(fontSize: 10),
            ),
          ),
        ),
      ),
    );

    final paragraph = tester.renderObject<RenderParagraph>(
      find.byType(RichText),
    );
    final text = paragraph.text.toPlainText();
    double topOf(String character) {
      final start = text.indexOf(character);
      return paragraph
          .getBoxesForSelection(
            TextSelection(baseOffset: start, extentOffset: start + 1),
          )
          .single
          .top;
    }

    expect(topOf('다'), greaterThan(topOf('가')));
    expect(topOf(')'), topOf('다'));
    expect(find.bySemanticsLabel('가나 다라마-AB)'), findsOneWidget);
    semantics.dispose();
  });
}
