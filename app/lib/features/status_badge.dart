// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../contracts.dart' as wire;
import '../korean_text.dart';

Color lineStatusColor(BuildContext context, wire.LineState state) {
  final colors = Theme.of(context).colorScheme;
  return switch (state) {
    wire.LineState.DONE || wire.LineState.RUNNING => colors.primary,
    wire.LineState.PARTIAL || wire.LineState.USER_CHANGED => colors.tertiary,
    wire.LineState.FAILED || wire.LineState.BLOCKED => colors.error,
    _ => colors.onSurfaceVariant,
  };
}

class StatusBadge extends StatelessWidget {
  const StatusBadge(this.label, {super.key, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    spacing: 5,
    children: [
      ExcludeSemantics(child: Icon(Icons.circle, size: 6, color: color)),
      Flexible(
        child: KoreanText(
          label,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: color),
        ),
      ),
    ],
  );
}

class StatusMessage extends StatelessWidget {
  const StatusMessage(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Semantics(
    container: true,
    label: text,
    liveRegion: true,
    excludeSemantics: true,
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: KoreanText(text),
    ),
  );
}
