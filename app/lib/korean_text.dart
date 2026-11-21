import 'package:flutter/widgets.dart';

/// Keeps Hangul words together when soft wrapping, like CSS keep-all.
class KoreanText extends Text {
  const KoreanText(
    super.data, {
    super.key,
    super.style,
    super.textAlign,
    super.softWrap,
    super.maxLines,
    super.overflow,
    super.semanticsLabel,
  });

  const KoreanText.rich(
    TextSpan super.textSpan, {
    super.key,
    super.style,
    super.textAlign,
    super.softWrap,
    super.maxLines,
    super.overflow,
    super.semanticsLabel,
  }) : super.rich();

  @override
  Widget build(BuildContext context) {
    if (maxLines == 1 || softWrap == false) return super.build(context);
    final original =
        data ?? textSpan!.toPlainText(includeSemanticsLabels: false);
    final joins = _hangulBoundary
        .allMatches(original)
        .map((boundary) => boundary.end)
        .toSet();
    if (joins.isEmpty) return super.build(context);

    return Text.rich(
      _joinWords(textSpan as TextSpan? ?? TextSpan(text: data), joins),
      style: style,
      textAlign: textAlign,
      softWrap: softWrap,
      maxLines: maxLines,
      overflow: overflow,
      semanticsLabel: semanticsLabel ?? data ?? textSpan!.toPlainText(),
    ).build(context);
  }
}

// Insert a word joiner at Hangul boundaries inside a word. The label spoken
// by assistive technology still uses the original text.
final _hangulBoundary = RegExp(
  r'\p{Script=Hangul}(?=[\p{L}\p{N}])|[\p{L}\p{N}](?=\p{Script=Hangul})',
  unicode: true,
);

TextSpan _joinWords(TextSpan paragraph, Set<int> joins) {
  var offset = 0;
  TextSpan joinSpan(TextSpan span) {
    final source = span.text;
    final text = StringBuffer();
    if (source != null) {
      for (var index = 0; index < source.length; index++) {
        text.writeCharCode(source.codeUnitAt(index));
        if (joins.contains(++offset)) text.writeCharCode(0x2060);
      }
    }
    return TextSpan(
      text: source == null ? null : text.toString(),
      style: span.style,
      children: span.children?.map((child) {
        if (child is TextSpan) return joinSpan(child);
        offset += child.toPlainText().length;
        return child;
      }).toList(),
      recognizer: span.recognizer,
      mouseCursor: span.mouseCursor,
      onEnter: span.onEnter,
      onExit: span.onExit,
      semanticsLabel: span.semanticsLabel,
      locale: span.locale,
      spellOut: span.spellOut,
    );
  }

  return joinSpan(paragraph);
}
