// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'labels.dart';
import 'order_extraction.dart';

class MemorySheet extends StatelessWidget {
  const MemorySheet({
    super.key,
    required this.rationale,
    required this.cardIds,
    this.episode,
    this.startsAt,
    this.onAcknowledge,
  });

  final wire.Rationale? rationale;
  final List<String> cardIds;
  final wire.Episode? episode;
  final String? startsAt;
  final VoidCallback? onAcknowledge;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: DesignTokens.paper,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(DesignTokens.radius16),
        side: BorderSide(color: theme.colorScheme.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.space16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          spacing: 12,
          children: [
            KoreanText('이렇게 기억할게요', style: theme.textTheme.headlineMedium),
            if (episode case final order?) OrderItems(episode: order),
            if (startsAt case final start?)
              KoreanText(seoulDateTime(start, fullDate: true)),
            if (rationale case final result?)
              for (final cardId in cardIds) _MemoryRecord(result, cardId)
            else
              const KoreanText('아직 판정 전'),
            if (onAcknowledge case final acknowledge?)
              FilledButton(
                onPressed: acknowledge,
                child: const KoreanText('확인'),
              ),
          ],
        ),
      ),
    );
  }
}

class _MemoryRecord extends StatelessWidget {
  const _MemoryRecord(this.rationale, this.cardId);

  final wire.Rationale rationale;
  final String cardId;

  @override
  Widget build(BuildContext context) {
    final intent = rationale.intents
        .where((intent) => intent.cardId == cardId)
        .firstOrNull;
    final observation = rationale.observations
        .where((observation) => observation.cardId == cardId)
        .firstOrNull;
    final feedback = {
      for (final entry
          in observation?.taskFeedback ?? const <wire.TaskFeedbackElement>[])
        entry.taskId: entry.user,
    };
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 8,
      children: [
        if (intent != null)
          KoreanText(intent.intentText, style: theme.textTheme.titleMedium),
        KoreanText(switch (observation?.verdict) {
          wire.Verdict.MATCH => '예상대로 쓰였어요',
          wire.Verdict.STOPPED => '멈추셨어요',
          wire.Verdict.UNCONFIRMED => '확인하지 못했어요',
          null => '아직 판정 전',
        }, style: theme.textTheme.titleSmall),
        for (final line in rationale.tasks.where(
          (line) => line.cardId == cardId,
        ))
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 10,
            children: [
              Expanded(child: KoreanText(line.line)),
              KoreanText(lineLabel(line.state)),
              if (feedback[line.taskId] case final result?)
                KoreanText(switch (result) {
                  wire.TaskFeedback.OFF => '끔',
                  wire.TaskFeedback.CHANGED => '바꿈',
                  wire.TaskFeedback.KEPT => '그대로',
                }),
            ],
          ),
      ],
    );
  }
}
