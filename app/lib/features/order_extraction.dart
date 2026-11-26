import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../contracts.dart' as wire;
import '../korean_text.dart';
import 'labels.dart';
import 'status_badge.dart';

class OrderExtraction extends StatelessWidget {
  const OrderExtraction({
    super.key,
    required this.episode,
    required this.images,
    required this.received,
  });

  final wire.Episode? episode;
  final List<Uint8List> images;
  final bool received;

  @override
  Widget build(BuildContext context) {
    final order = episode;
    final status = order?.status;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 8,
      children: [
        if (images.isNotEmpty)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final (index, image) in images.indexed)
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.memory(
                    image,
                    width: 68,
                    height: 88,
                    fit: BoxFit.cover,
                    cacheWidth: 220,
                    semanticLabel: '보낸 사진 ${index + 1}',
                    errorBuilder: (_, _, _) => const SizedBox(
                      width: 68,
                      height: 88,
                      child: Icon(Icons.image_not_supported_outlined),
                    ),
                  ),
                ),
            ],
          ),
        if (received || status == wire.EpisodeStatus.RECEIVED)
          const KoreanText('받았어요'),
        if (status == wire.EpisodeStatus.READING)
          const _OrderSkeleton()
        else if (status == wire.EpisodeStatus.READ_FAILED)
          const KoreanText('읽지 못했어요. 다시 보내 주세요')
        else if (order != null && status != wire.EpisodeStatus.RECEIVED)
          OrderItems(episode: order, showGuidance: true),
      ],
    );
  }
}

class OrderItems extends StatelessWidget {
  const OrderItems({
    super.key,
    required this.episode,
    this.showGuidance = false,
  });

  final wire.Episode episode;
  final bool showGuidance;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tasks = showGuidance
        ? episode.itemTasks
        : const <wire.ItemTaskElement>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: 8,
      children: [
        if (showGuidance)
          KoreanText(
            '읽은 품목 ${episode.itemCount}개',
            style: theme.textTheme.titleSmall,
          ),
        for (final item in episode.items)
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            spacing: 4,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 8,
                children: [
                  Expanded(child: KoreanText(item.name)),
                  if (item.qty case final quantity?) KoreanText('$quantity개'),
                ],
              ),
              for (final task in tasks.where((task) => task.item == item.type))
                StatusBadge(
                  lineLabel(task.state),
                  color: lineStatusColor(context, task.state),
                ),
            ],
          ),
        if (episode.maskedCount > 0)
          KoreanText('가린 품목 ${episode.maskedCount}개'),
      ],
    );
  }
}

class _OrderSkeleton extends StatelessWidget {
  const _OrderSkeleton();

  @override
  Widget build(BuildContext context) => Column(
    key: const ValueKey('order-reading'),
    crossAxisAlignment: CrossAxisAlignment.start,
    spacing: 9,
    children: [
      const KoreanText('주문을 읽고 있어요'),
      ExcludeSemantics(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          spacing: 9,
          children: [
            for (final width in [0.80, 0.58, 0.70])
              FractionallySizedBox(
                widthFactor: width,
                child: Container(
                  height: 12,
                  decoration: BoxDecoration(
                    color: Theme.of(context)
                        .colorScheme
                        .surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(6),
                  ),
                ),
              ),
          ],
        ),
      ),
    ],
  );
}
