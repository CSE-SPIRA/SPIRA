import '../contracts.dart' as wire;

String lineLabel(wire.LineState state) => switch (state) {
  wire.LineState.HELD => '시간을 기다리는 중',
  wire.LineState.SCHEDULED => '예정됨',
  wire.LineState.RUNNING => '진행 중',
  wire.LineState.DONE => '완료',
  wire.LineState.PARTIAL => '일부 완료',
  wire.LineState.FAILED => '실패',
  wire.LineState.UNKNOWN => '결과 확인 불가',
  wire.LineState.BLOCKED => '실행하지 못함',
  wire.LineState.USER_CHANGED => '사람이 바꿨어요',
  wire.LineState.OFF => '꺼짐',
  wire.LineState.STOPPED => '중지됨',
  wire.LineState.CANCELLED => '취소됨',
  wire.LineState.DROPPED => '준비하지 않음',
};

String? visibleLineLabel(wire.LineState state) =>
    state == wire.LineState.SCHEDULED ? null : lineLabel(state);

String endLabel(wire.EndState state) => switch (state) {
  wire.EndState.RESTORED => '이전 상태로 돌아갔어요',
  wire.EndState.KEPT_USER_CHANGE => '사람이 바꾼 그대로 두었어요',
  wire.EndState.RESTORE_FAILED => '이전 상태로 돌아가지 못했거나 확인할 수 없어요',
  wire.EndState.WITHHELD => '행사 끝을 확인하지 못해 안전 설정을 그대로 두었어요.',
  wire.EndState.NONE => '되돌릴 설정이 없어요',
};

String eventLabel(wire.TriggerEvent event) => switch (event) {
  wire.TriggerEvent.EVENT_END => '일정 종료',
  wire.TriggerEvent.GUEST_ARRIVED => '손님 도착',
  wire.TriggerEvent.PACKAGE_BROUGHT_IN => '택배를 집 안으로 들이는 때',
};

String deviceLabel(String type) => switch (type) {
  'cleaner' => '로봇청소기',
  'light' => '조명',
  'display' => '화면',
  'oven' => '오븐',
  'cooktop' => '인덕션',
  'fridge' => '냉장고',
  'smart_plug' => '전원 플러그',
  'speaker' => '스피커',
  _ => '기기',
};

String deviceKindLabel(wire.Substrate? substrate) => switch (substrate) {
  wire.Substrate.VIRTUAL => '가상 기기',
  wire.Substrate.PHYSICAL => '실물 기기',
  null => '실물 기기인지 확인하지 못했어요',
};

String commandLabel(String command) => switch (command) {
  'clean' => '청소',
  'color' => '조명 색 바꾸기',
  'color_temp' => '조명을 따뜻한 색이나 차가운 색으로 바꾸기',
  'play_mood' => '분위기에 맞는 화면 켜기',
  'off' => '전원 끄기',
  'child_lock' => '어린이 잠금',
  'set_cook_standby' => '오븐 온도와 시간 맞춰 두기',
  'show_notice' => '화면에 안내 띄우기',
  'clear_notice' => '화면에서 안내 지우기',
  'play' => '음악 틀기',
  'stop' => '음악 끄기',
  'purchase' => '물건 사기',
  'heat' => '불 켜기',
  'start' => '굽기 시작하기',
  _ => '기기 동작',
};

DateTime _seoulTime(String raw) =>
    DateTime.parse(raw).toUtc().add(const Duration(hours: 9));

String seoulDateTime(String raw) {
  final dt = _seoulTime(raw);
  final minute = dt.minute.toString().padLeft(2, '0');
  return '${dt.month}월 ${dt.day}일 ${dt.hour}:$minute';
}

const koreanWeekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'];

String seoulWeekdayTime(String raw, {String? relativeTo}) {
  final dt = _seoulTime(raw);
  final reference = relativeTo == null ? null : _seoulTime(relativeTo);
  final date =
      reference != null &&
          dt.year == reference.year &&
          dt.month == reference.month &&
          dt.day == reference.day
      ? ''
      : '${dt.month}월 ${dt.day}일 ';
  return '$date${koreanWeekdays[dt.weekday - 1]} ${koreanClock(dt.hour, dt.minute)}';
}

String koreanClock(
  int hour,
  int minute, {
  bool showPeriod = true,
  bool showHourUnit = true,
}) {
  final period = showPeriod ? (hour < 12 ? '오전 ' : '오후 ') : '';
  final clockHour = hour % 12 == 0 ? 12 : hour % 12;
  final units = switch (minute) {
    0 => showHourUnit ? '시' : '',
    _ => '시 $minute분',
  };
  return '$period$clockHour$units';
}
