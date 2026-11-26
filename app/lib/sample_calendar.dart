import 'contracts.dart' as wire;

const sampleBirthdayOffset = Duration(minutes: 20);
const sampleBirthdayDuration = Duration(hours: 1);
const sampleBirthdayRenewalWindow = Duration(minutes: 10);
const _seoulOffset = Duration(hours: 9);

// The birthday uses the h_042 replay's Saturday, with the preview's four-hour window.
final sampleCalendar = wire.Calendar(
  events: [
    wire.EventElement(
      id: 'c1',
      title: '생일 파티',
      start: '2026-10-17T14:00:00+09:00',
      end: '2026-10-17T18:00:00+09:00',
    ),
    wire.EventElement(
      id: 'c4',
      title: '예방접종',
      start: '2026-10-20T09:30:00+09:00',
      end: '2026-10-20T10:00:00+09:00',
    ),
    wire.EventElement(
      id: 'c2',
      title: '가족 저녁',
      start: '2026-10-23T19:00:00+09:00',
      end: '2026-10-23T21:00:00+09:00',
    ),
  ],
);

wire.Calendar serverSampleCalendar(DateTime serverTime) {
  final birthday = sampleCalendar.events.first;
  final start = serverTime.toUtc().add(sampleBirthdayOffset);
  final shift = _seoulDay(start)
      .difference(_seoulDay(DateTime.parse(birthday.start)));
  return wire.Calendar(
    events: [
      wire.EventElement(
        id: birthday.id,
        title: birthday.title,
        start: start.toIso8601String(),
        end: start.add(sampleBirthdayDuration).toIso8601String(),
      ),
      for (final event in sampleCalendar.events.skip(1))
        wire.EventElement(
          id: event.id,
          title: event.title,
          start: DateTime.parse(event.start).add(shift).toIso8601String(),
          end: DateTime.parse(event.end).add(shift).toIso8601String(),
        ),
    ],
  );
}

DateTime _seoulDay(DateTime utcTime) {
  final day = utcTime.add(_seoulOffset);
  return DateTime.utc(day.year, day.month, day.day);
}
