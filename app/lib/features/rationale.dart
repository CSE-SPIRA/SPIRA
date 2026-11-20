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
    appBar: AppBar(title: const Text('준비 이유')),
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
    final unbundled = result.unbundled.where((item) => item.trim().isNotEmpty);
    if (intents.isEmpty) {
      // The stored reason can include private purchase-history comparisons.
      if (result.intents.isEmpty && _hasText(result.noneReason)) {
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            _sectionHeading(context, '이렇게 알아들었어요'),
            if (unbundled.isNotEmpty)
              Text("${unbundled.join(' · ')} 같은 물건을 주문하셨어요."),
            const Text('이번 주문에 맞춰 집에서 따로 준비할 일은 없어요.'),
          ],
        );
      }
      return const Center(child: StatusMessage('저장된 이유를 볼 수 없어요.'));
    }

    final feedback = {
      for (final observation in result.observations)
        for (final task in observation.taskFeedback)
          (observation.cardId, task.taskId): task,
    };
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        for (final intent in intents) ...[
          if (_hasText(intent.intentText)) ...[
            _sectionHeading(context, '이렇게 알아들었어요'),
            Text(intent.intentText),
          ],
          if (_basisSentences(intent, calendar) case final basis
              when basis.isNotEmpty) ...[
            const SizedBox(height: 20),
            _sectionHeading(context, '이렇게 생각했어요'),
            for (final sentence in basis) _bullet(sentence),
          ],
          if (result.tasks
                  .where(
                    (task) =>
                        task.cardId == intent.cardId && _hasText(task.need),
                  )
                  .toList()
              case final tasks when tasks.isNotEmpty) ...[
            const SizedBox(height: 20),
            _sectionHeading(context, '그래서 집이 이렇게 준비해요'),
            for (final task in tasks)
              _bullet(
                _taskSentence(
                  task,
                  feedback[(task.cardId, task.taskId)],
                  app.cards[task.cardId]?.lines
                      .where((line) => line.taskId == task.taskId)
                      .firstOrNull,
                ),
              ),
          ],
        ],
        if (unbundled.isNotEmpty) ...[
          const SizedBox(height: 20),
          _sectionHeading(context, '이번 준비와 상관없는 물건'),
          Text(unbundled.join(' · ')),
        ],
      ],
    );
  }
}

bool _hasText(String? value) => value != null && value.trim().isNotEmpty;

Widget _sectionHeading(BuildContext context, String heading) => Padding(
  padding: const EdgeInsets.only(bottom: 6),
  child: Semantics(
    header: true,
    child: Text(heading, style: Theme.of(context).textTheme.titleMedium),
  ),
);

Widget _bullet(String sentence) => Padding(
  padding: const EdgeInsets.only(bottom: 6),
  child: Row(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const ExcludeSemantics(child: Text('·  ')),
      Expanded(child: Text(sentence)),
    ],
  ),
);

List<String> _basisSentences(
  wire.IntentElement intent,
  Map<String, wire.CalendarElement> calendar,
) {
  final situation = intent.situation;
  final basis = intent.basis;
  final facetsByItem = <String, Set<String>>{};
  // General intent evidence does not identify a situation facet.
  for (final (facet, sources) in [
    (situation.event, basis.event),
    (_guestsSentence(situation.guests), basis.guests),
    (_activitySentence(situation.activity), basis.activity),
    (_themePhrase(situation.theme), basis.theme),
  ]) {
    if (!_hasText(facet)) continue;
    for (final source in sources) {
      if (!_hasText(source) ||
          source == '가구 유형' ||
          source == intent.calendarEventId ||
          calendar.containsKey(source)) {
        continue;
      }
      (facetsByItem[source] ??= {}).add(facet!);
    }
  }
  final itemsByFacets = <String, List<String>>{};
  for (final entry in facetsByItem.entries) {
    (itemsByFacets[entry.value.join(', ')] ??= []).add(entry.key);
  }
  return [
    for (final id in basis.event.toSet())
      if (calendar[id] case final event?) ?_calendarSentence(event),
    for (final entry in itemsByFacets.entries)
      "${entry.value.join(' · ')} → ${entry.key}",
  ];
}

String? _guestsSentence(String? guests) {
  final match = RegExp(r'^(.+) 여러 명$').firstMatch(guests ?? '');
  if (match == null) return guests;
  final subject = match[1]!;
  return '$subject${_hasFinalConsonant(subject) ? '이' : '가'} 여럿 와요';
}

String? _activitySentence(String? activity) {
  final match = RegExp(r'^(.+) 굽고 꾸미기$').firstMatch(activity ?? '');
  if (match == null) return activity;
  final object = match[1]!;
  final particle = object.endsWith('을') || object.endsWith('를')
      ? ''
      : _hasFinalConsonant(object)
      ? '을'
      : '를';
  return '$object$particle 굽고 꾸며요';
}

bool _hasFinalConsonant(String word) {
  final suffix = word.codeUnitAt(word.length - 1) - 0xAC00;
  return suffix >= 0 && suffix < 11172 && suffix % 28 != 0;
}

String? _themePhrase(String? theme) =>
    !_hasText(theme) || theme!.endsWith('테마') ? theme : '$theme 테마';

String? _calendarSentence(wire.CalendarElement event) {
  final day = event.day.trim();
  final tags = event.tags.where(_hasText).join(' · ');
  final start = DateTime.tryParse('2000-01-01T${event.start}Z');
  final end = DateTime.tryParse('2000-01-01T${event.end}Z');
  if (day.isEmpty || tags.isEmpty || start == null || end == null) return null;

  final weekday = koreanWeekdays.where((name) => name[0] == day).firstOrNull;
  final samePeriod = start.hour ~/ 12 == end.hour ~/ 12 && !end.isBefore(start);
  final from = koreanClock(
    start.hour,
    start.minute,
    showHourUnit: !samePeriod || end.minute != 0,
  );
  final to = koreanClock(end.hour, end.minute, showPeriod: !samePeriod);
  return "캘린더에 ${weekday ?? day} $from–$to '$tags' 일정이 있어요";
}

String _taskSentence(
  wire.Task task,
  wire.TaskFeedbackElement? feedback,
  wire.LineElement? current,
) {
  final action = _describeActions(task, feedback?.actions ?? const []);
  final devices = task.devices
      .map((device) {
        final type = deviceLabel(device.type);
        return _hasText(device.room) ? '${device.room} $type' : type;
      })
      .toSet()
      .join(' · ');
  final description = action ?? devices;
  final state = switch (current?.state ?? task.state) {
    wire.LineState.OFF => '꺼 두셨어요',
    wire.LineState.RUNNING => '진행 중이에요',
    wire.LineState.DONE => '준비를 마쳤어요',
    wire.LineState.FAILED => '준비하지 못했어요',
    final state => visibleLineLabel(state),
  };
  final status = [
    ?state,
    if (current?.endState == wire.EndState.WITHHELD)
      endLabel(wire.EndState.WITHHELD),
  ].join(' · ');
  return '${task.need}'
      "${description.isEmpty ? '' : ' — $description'}"
      "${status.isEmpty ? '' : ' ($status)'}";
}

String? _describeActions(wire.Task task, List<List<String>> actions) {
  String? roomFor(String type) {
    final devices = task.devices.where((device) => device.type == type);
    if (devices.length != 1) return null;
    final room = devices.single.room;
    return _hasText(room) ? room : null;
  }

  if (actions
      case [['cooktop', 'child_lock'], [final plug, 'off']] ||
          [[final plug, 'off'], ['cooktop', 'child_lock']]) {
    if (_plugName(plug) case final name?) {
      return '인덕션을 잠그고 $name 전원을 꺼요';
    }
  }
  if (actions
      case [['display', 'play_mood'], ['light', 'color']] ||
          [['light', 'color'], ['display', 'play_mood']]) {
    final room = roomFor('display');
    if (room != null && room == roomFor('light')) {
      return '$room 화면과 조명을 바꿔요';
    }
  }

  final phrases = <String>[];
  for (final action in actions) {
    final phrase = switch (action) {
      ['cleaner', 'clean'] => "${roomFor('cleaner') ?? ''} 로봇청소기가 청소해요".trim(),
      ['cooktop', 'child_lock'] => '인덕션을 잠가요',
      [final plug, 'off'] when _plugName(plug) != null =>
        '${_plugName(plug)} 전원을 꺼요',
      ['display', 'play_mood'] => '화면을 분위기에 맞게 바꿔요',
      ['light', 'color'] => '조명 색을 바꿔요',
      ['oven', 'set_cook_standby'] => '온도를 맞춰 둘게요. 굽기는 직접 시작해 주세요',
      ['fridge', 'show_notice'] => '냉장고 화면에 안내를 띄워요',
      _ => null,
    };
    if (phrase == null) return null;
    phrases.add(phrase);
  }
  return phrases.isEmpty ? null : phrases.join('. ');
}

String? _plugName(String type) {
  const prefix = 'smart_plug:';
  if (type.startsWith(prefix) && _hasText(type.substring(prefix.length))) {
    return type.substring(prefix.length);
  }
  return type == 'smart_plug' ? deviceLabel(type) : null;
}
