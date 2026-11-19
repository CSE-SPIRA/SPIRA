// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import 'labels.dart';
import 'setup.dart';

void openRationale(
  BuildContext context,
  AppController app,
  String episode, {
  String? cardId,
}) {
  Navigator.push<void>(
    context,
    MaterialPageRoute(
      builder: (_) => _RationaleScreen(
        app: app,
        rationale: app.rationale(episode),
        cardId: cardId,
      ),
    ),
  );
}

class _RationaleScreen extends StatelessWidget {
  const _RationaleScreen({
    required this.app,
    required this.rationale,
    required this.cardId,
  });

  final AppController app;
  final Future<wire.Rationale> rationale;
  final String? cardId;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('WHY · 준비 이유')),
    body: FutureBuilder<wire.Rationale>(
      future: rationale,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(
            child: CircularProgressIndicator(semanticsLabel: '준비 이유 불러오는 중'),
          );
        }
        final result = snapshot.data;
        if (result == null) {
          return const Center(child: StatusMessage('저장된 이유를 볼 수 없어요.'));
        }
        return ListenableBuilder(
          listenable: app,
          builder: (context, _) =>
              _RationaleContent(result: result, app: app, cardId: cardId),
        );
      },
    ),
  );
}

class _RationaleContent extends StatelessWidget {
  const _RationaleContent({
    required this.result,
    required this.app,
    required this.cardId,
  });

  final wire.Rationale result;
  final AppController app;
  final String? cardId;

  @override
  Widget build(BuildContext context) {
    final calendar = {
      for (final event in result.evidence.calendar) event.id: event,
    };
    final intents = result.intents.where(
      (intent) => cardId == null || intent.cardId == cardId,
    );
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        if (intents.isEmpty)
          Text(
            result.intents.isEmpty && result.noneReason != null
                ? result.noneReason!
                : '저장된 이유를 볼 수 없어요.',
          ),
        for (final intent in intents) ...[
          Text(
            intent.intentText,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 12),
          for (final (label, value, sources) in [
            ('의도 근거', null, intent.basis.intent),
            ('상황', intent.situation.event, intent.basis.event),
            ('손님', intent.situation.guests, intent.basis.guests),
            ('활동', intent.situation.activity, intent.basis.activity),
            ('테마', intent.situation.theme, intent.basis.theme),
          ])
            if (value != null || sources.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      value == null ? label : '$label · $value',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    if (sources.isNotEmpty)
                      Text(
                        sources
                            .map((source) {
                              final match = calendar[source];
                              if (match == null) return source;
                              final tags = match.tags.isEmpty
                                  ? ''
                                  : ' ${match.tags.join(' · ')}';
                              return '캘린더$tags (${match.day} ${match.start}–${match.end})';
                            })
                            .join(' · '),
                      ),
                  ],
                ),
              ),
        ],
        if (result.unbundled.isNotEmpty) ...[
          Text(
            '준비에 포함하지 않은 품목',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          Text(result.unbundled.join(' · ')),
          const SizedBox(height: 18),
        ],
        for (final task in result.tasks)
          if (cardId == null || task.cardId == cardId) ...[
            const Divider(),
            Text(task.need, style: Theme.of(context).textTheme.titleMedium),
            for (final device in task.devices)
              Text('${device.room ?? '공간 미확인'} · ${deviceLabel(device.type)}'),
            Text(
              lineLabel(
                app.cards[task.cardId]?.lines
                        .where((line) => line.taskId == task.taskId)
                        .firstOrNull
                        ?.state ??
                    task.state,
              ),
            ),
          ],
      ],
    );
  }
}
