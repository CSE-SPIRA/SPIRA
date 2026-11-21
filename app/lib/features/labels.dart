import '../contracts.dart' as wire;
import '../design_vocabulary.g.dart';

const fixturePreviewLabel = '미리보기 · 계약 테스트 서버';

String lineLabel(wire.LineState state) => switch (state) {
  wire.LineState.HELD => '시간을 기다리는 중',
  wire.LineState.SCHEDULED => '예정됨',
  wire.LineState.RUNNING => '진행 중',
  wire.LineState.DONE => '완료',
  wire.LineState.PARTIAL => '일부 완료',
  wire.LineState.FAILED => '실패',
  wire.LineState.UNKNOWN => '결과 확인 불가',
  wire.LineState.BLOCKED => '실행하지 못함',
  wire.LineState.USER_CHANGED => '직접 바꾸셨어요',
  wire.LineState.OFF => stateWords['off']!,
  wire.LineState.STOPPED => '중지됨',
  wire.LineState.CANCELLED => '취소됨',
  wire.LineState.DROPPED => '준비하지 않음',
};

String? visibleLineLabel(wire.LineState state) =>
    state == wire.LineState.SCHEDULED ? null : lineLabel(state);

String? endLabel(wire.EndState? state) => switch (state) {
  wire.EndState.RESTORED => '원래대로 돌렸어요',
  wire.EndState.KEPT_USER_CHANGE => '바꾸신 그대로 두었어요',
  wire.EndState.RESTORE_FAILED => '복원 실패 또는 결과 확인 불가',
  wire.EndState.WITHHELD => '행사 끝을 확인하지 못해 안전 설정을 그대로 두었어요.',
  wire.EndState.NONE || null => null,
};

String? lineNoteLabel(String? note) {
  if (note == null || note.trim().isEmpty) return null;
  return normalizeKelvin(
    note
        .replaceFirstMapped(
          RegExp(r'^사용자가 (.+) 바꿔 현재 상태를 유지했어요'),
          (match) => '${match[1]} 직접 바꾸셨어요. 바꾸신 그대로 두었어요',
        )
        .replaceFirst(RegExp(r'^사용자가 '), '직접 '),
  );
}

String normalizeKelvin(String text) =>
    text.replaceAllMapped(RegExp(r'(\d)\s+K\b'), (match) => '${match[1]}K');

String eventLabel(wire.TriggerEvent event) => switch (event) {
  wire.TriggerEvent.EVENT_END => '일정 종료',
  wire.TriggerEvent.GUEST_ARRIVED => '손님 도착',
  wire.TriggerEvent.PACKAGE_BROUGHT_IN => '택배를 집 안으로 들이는 때',
};

String deviceLabel(String type, {String? unknownLabel}) =>
    appDeviceNames[type] ?? deviceNames[type] ?? unknownLabel ?? '기기';

String? roomLabel(String? room) {
  final name = room?.trim();
  return name == null || name.isEmpty ? null : roomNames[name] ?? name;
}

String substrateLabel(wire.Substrate substrate) =>
    stateWords[wire.substrateValues.reverse[substrate]]!;

String commandLabel(String command) => switch (command) {
  'clean' => '청소',
  'color' => '조명 색상 설정',
  'color_temp' => '조명 색온도 설정',
  'play_mood' => '분위기 화면 재생',
  'off' => '전원 끄기',
  'child_lock' => '어린이 잠금',
  'set_cook_standby' => '조리 대기 설정',
  'show_notice' => '안내 표시',
  'play' => '재생',
  'stop' => '정지',
  'purchase' => '구매',
  'heat' => '가열',
  'start' => '조리 시작',
  _ => command,
};

DateTime _seoulTime(String raw) =>
    DateTime.parse(raw).toUtc().add(const Duration(hours: 9));

String seoulDateTime(String raw, {bool fullDate = false}) {
  final dt = _seoulTime(raw);
  if (!fullDate) return _lineClock(dt);
  return '${dt.month}월 ${dt.day}일 (${_weekday(dt)}) ${_hourMinute(dt)}';
}

String seoulClock(String raw) => _hourMinute(_seoulTime(raw));

String scheduleDayLabel(String raw, String? name) =>
    '${_weekday(_seoulTime(raw))}요일 ${name ?? '일정'}';

const _weekdays = ['월', '화', '수', '목', '금', '토', '일'];

String _weekday(DateTime seoul) => _weekdays[seoul.weekday - 1];

String _hourMinute(DateTime seoul) {
  final hour = seoul.hour.toString().padLeft(2, '0');
  final minute = seoul.minute.toString().padLeft(2, '0');
  return '$hour:$minute';
}

String? triggerLabel(wire.TriggerEvent? event) => switch (event) {
  wire.TriggerEvent.GUEST_ARRIVED => '손님이 오면',
  wire.TriggerEvent.EVENT_END => '일정이 끝나면',
  wire.TriggerEvent.PACKAGE_BROUGHT_IN => '택배가 들어오면',
  null => null,
};

String? lineRelationLabel(wire.LineElement? line, wire.Card card) {
  final time = line?.when?.time;
  if (time == null) return triggerLabel(line?.when?.event);
  final start = card.startsAt;
  if (start == null) return null;
  final event = isPartyPreparation(card) ? '파티' : '일정';
  final relation = DateTime.parse(time).compareTo(DateTime.parse(start));
  return switch (relation) {
    < 0 => '$event 전',
    0 => '$event 시작에 맞춰',
    _ => '$event 시작 후',
  };
}

bool isPartyPreparation(wire.Card card) => switch (card.intentId) {
  'kid_birthday_party' || 'home_party' || 'christmas_party' => true,
  _ => false,
};

String? storyLineTiming(
  wire.LineElement? line, {
  required String? scheduleStart,
  required String scheduleName,
  required String? sharedAt,
  required String? runAt,
}) {
  final trigger = triggerLabel(line?.when?.event);
  final time = line?.when?.time;
  if (time == null) {
    if (runAt == null) return trigger;
    final action = '${seoulDateTime(runAt)}에 실행';
    return trigger == null ? action : '$trigger · $action';
  }

  final task = _seoulTime(time);
  final schedule = scheduleStart == null ? null : _seoulTime(scheduleStart);
  final sameDay =
      schedule != null &&
      schedule.year == task.year &&
      schedule.month == task.month &&
      schedule.day == task.day;
  final name = schedule == null
      ? null
      : '$scheduleName(${sameDay ? _hourMinute(schedule) : _lineClock(schedule)})';
  final minutes = schedule == null
      ? null
      : (schedule.difference(task).inMilliseconds /
                Duration.millisecondsPerMinute)
            .round();
  final relation = switch (minutes) {
    0 => '$name 시작에 맞춰',
    final offset? when offset > 0 => '$name $offset분 전',
    final offset? => '$name 시작 ${offset.abs()}분 뒤',
    null => null,
  };
  final prefix = relation == null ? '' : '$relation, ';
  final upcoming = switch (line?.state) {
    wire.LineState.HELD || wire.LineState.SCHEDULED => true,
    _ => false,
  };
  if (sharedAt != null && task.isBefore(_seoulTime(sharedAt))) {
    final clock = seoulDateTime(runAt ?? sharedAt);
    final plan = upcoming ? ' 예정' : '할 예정이었어요';
    return '$prefix$clock에 바로 실행${runAt == null ? plan : ''}';
  }
  final clock = sameDay ? _hourMinute(task) : _lineClock(task);
  final ranAsPlanned =
      runAt != null &&
      _seoulTime(runAt).difference(task).inMinutes == 0 &&
      seoulDateTime(runAt) == _lineClock(task);
  if (ranAsPlanned) return '$prefix$clock에 실행';
  if (upcoming) return '$prefix$clock 예정';
  return '$prefix$clock에 실행할 예정이었어요';
}

String _lineClock(DateTime seoul) => '${_weekday(seoul)} ${_hourMinute(seoul)}';
