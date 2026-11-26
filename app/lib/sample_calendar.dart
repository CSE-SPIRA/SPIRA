import 'contracts.dart' as wire;

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
