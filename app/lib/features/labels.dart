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
  wire.LineState.USER_CHANGED => '사용자가 변경함',
  wire.LineState.OFF => '꺼짐',
  wire.LineState.STOPPED => '중지됨',
  wire.LineState.CANCELLED => '취소됨',
  wire.LineState.DROPPED => '준비하지 않음',
};

String endLabel(wire.EndState state) => switch (state) {
  wire.EndState.RESTORED => '이전 상태로 복원됨',
  wire.EndState.KEPT_USER_CHANGE => '사용자가 바꾼 상태를 유지함',
  wire.EndState.RESTORE_FAILED => '복원 실패 또는 결과 확인 불가',
  wire.EndState.NONE => '복원 대상 없음',
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
  'smart_plug' => '스마트 플러그',
  'speaker' => '스피커',
  _ => type,
};

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

String seoulDateTime(String raw) {
  final dt = DateTime.parse(raw).toUtc().add(const Duration(hours: 9));
  final minute = dt.minute.toString().padLeft(2, '0');
  return '${dt.month}월 ${dt.day}일 ${dt.hour}:$minute';
}
