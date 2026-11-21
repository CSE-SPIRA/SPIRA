import '../contracts.dart' as wire;
import '../design_vocabulary.g.dart';

String lineLabel(wire.LineState state) => switch (state) {
  wire.LineState.HELD => '시간을 기다리는 중',
  wire.LineState.SCHEDULED => '예정됨',
  wire.LineState.RUNNING => '진행 중',
  wire.LineState.DONE => '완료',
  wire.LineState.PARTIAL => '일부 완료',
  wire.LineState.FAILED => '실패',
  wire.LineState.UNKNOWN => '결과 확인 불가',
  wire.LineState.BLOCKED => '실행하지 못함',
  wire.LineState.USER_CHANGED => '사용자가 변경함',
  wire.LineState.OFF => stateWords['off']!,
  wire.LineState.STOPPED => '중지됨',
  wire.LineState.CANCELLED => '취소됨',
  wire.LineState.DROPPED => '준비하지 않음',
};

String? visibleLineLabel(wire.LineState state) =>
    state == wire.LineState.SCHEDULED ? null : lineLabel(state);

String endLabel(wire.EndState state) => switch (state) {
  wire.EndState.RESTORED => '이전 상태로 복원됨',
  wire.EndState.KEPT_USER_CHANGE => '사용자가 바꾼 상태를 유지함',
  wire.EndState.RESTORE_FAILED => '복원 실패 또는 결과 확인 불가',
  wire.EndState.WITHHELD => '행사 끝을 확인하지 못해 안전 설정을 그대로 두었어요.',
  wire.EndState.NONE => '복원 대상 없음',
};

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

String? lineTimeLabel(wire.LineElement? line) =>
    switch ((line?.when?.time, line?.when?.event)) {
      (final time?, _) => _lineClock(_seoulTime(time)),
      (_, wire.TriggerEvent.GUEST_ARRIVED) => '손님이 오면',
      (_, wire.TriggerEvent.EVENT_END) => '일정이 끝나면',
      (_, wire.TriggerEvent.PACKAGE_BROUGHT_IN) => '택배를 집 안으로 들이면',
      _ => null,
    };

String? lineRelationLabel(wire.LineElement? line, wire.Card card) {
  final time = line?.when?.time;
  if (time == null) return lineTimeLabel(line);
  final start = card.startsAt;
  if (start == null) return null;
  final event = switch (card.intentId) {
    'kid_birthday_party' || 'home_party' || 'christmas_party' => '파티',
    _ => '일정',
  };
  final relation = DateTime.parse(time).compareTo(DateTime.parse(start));
  return switch (relation) {
    < 0 => '$event 전',
    0 => '$event 시작에 맞춰',
    _ => '$event 시작 후',
  };
}

String? lineTimeDerivation(wire.LineElement? line, String? scheduleStart) {
  final time = line?.when?.time;
  if (time == null || scheduleStart == null) return null;
  final task = _seoulTime(time);
  final event = _seoulTime(scheduleStart);
  final minutes =
      (event.difference(task).inMilliseconds / Duration.millisecondsPerMinute)
          .round();
  final relative = switch (minutes) {
    0 => '같은 시각',
    > 0 => '$minutes분 전',
    _ => '${minutes.abs()}분 후',
  };
  return '${_lineClock(event)} 일정 → $relative → ${_lineClock(task)}';
}

String _lineClock(DateTime seoul) => '${_weekday(seoul)} ${_hourMinute(seoul)}';
