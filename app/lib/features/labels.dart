import '../contracts.dart' as wire;
import '../design_vocabulary.g.dart';

const fixturePreviewLabel = '미리보기 · 계약 테스트 서버';

String lineLabel(wire.LineState state) => switch (state) {
  wire.LineState.HELD => lineWords['held']!,
  wire.LineState.SCHEDULED => lineWords['scheduled']!,
  wire.LineState.RUNNING => lineWords['running']!,
  wire.LineState.DONE => lineWords['done']!,
  wire.LineState.PARTIAL => lineWords['partial']!,
  wire.LineState.FAILED => lineWords['failed']!,
  wire.LineState.UNKNOWN => lineWords['unknown']!,
  wire.LineState.BLOCKED => lineWords['blocked']!,
  wire.LineState.USER_CHANGED => '사람이 바꿈',
  wire.LineState.OFF => lineWords['off']!,
  wire.LineState.STOPPED => lineWords['stopped']!,
  wire.LineState.CANCELLED => lineWords['cancelled']!,
  wire.LineState.DROPPED => lineWords['dropped']!,
};

String? endLabel(wire.EndState? state) => switch (state) {
  wire.EndState.RESTORED => endWords['restored']!,
  wire.EndState.KEPT_USER_CHANGE => endWords['kept_user_change']!,
  wire.EndState.RESTORE_FAILED => '되돌리지 못했어요',
  wire.EndState.WITHHELD => endWords['withheld']!,
  wire.EndState.NONE || null => null,
};

String normalizeKelvin(String text) =>
    text.replaceAllMapped(RegExp(r'(\d)\s+K\b'), (match) => '${match[1]}K');

String eventLabel(wire.TriggerEvent event) => switch (event) {
  wire.TriggerEvent.EVENT_END => '일정 종료',
  wire.TriggerEvent.GUEST_ARRIVED => '손님 도착',
  wire.TriggerEvent.PACKAGE_BROUGHT_IN => '택배를 집 안으로 들이는 때',
};

DateTime _seoulTime(String raw) =>
    DateTime.parse(raw).toUtc().add(const Duration(hours: 9));

DateTime seoulDay(String raw) {
  final time = _seoulTime(raw);
  return DateTime.utc(time.year, time.month, time.day);
}

String seoulDateTime(String raw, {bool fullDate = false}) {
  final dt = _seoulTime(raw);
  if (!fullDate) return _lineClock(dt);
  return '${dt.month}월 ${dt.day}일 (${_weekday(dt)}) ${_hourMinute(dt)}';
}

String seoulClock(String raw) => _hourMinute(_seoulTime(raw));

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

String _lineClock(DateTime seoul) => '${_weekday(seoul)} ${_hourMinute(seoul)}';
