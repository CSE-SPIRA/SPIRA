// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../korean_text.dart';
import 'labels.dart';
import 'memory_sheet.dart';
import 'setup.dart';

class PreparationCalendar extends StatelessWidget {
  const PreparationCalendar(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now().toUtc();
    final today = seoulDay(now.toIso8601String());
    final horizon = now.add(const Duration(days: 14));
    final future = <DateTime, List<wire.EventElement>>{};
    final events = [...app.googleCalendar.events]
      ..sort(
        (a, b) => DateTime.parse(a.start).compareTo(DateTime.parse(b.start)),
      );
    for (final event in events) {
      if (!DateTime.parse(event.end).isAfter(now) ||
          !DateTime.parse(event.start).isBefore(horizon)) {
        continue;
      }
      final start = seoulDay(event.start);
      final firstDay = start.isBefore(today) ? today : start;
      final eventEnd = DateTime.parse(event.end);
      final end = eventEnd.isBefore(horizon) ? eventEnd : horizon;
      for (
        var day = firstDay;
        day.subtract(const Duration(hours: 9)).isBefore(end);
        day = day.add(const Duration(days: 1))
      ) {
        (future[day] ??= []).add(event);
      }
    }
    final past = <DateTime, List<MemoryDate>>{};
    for (final memory in app.memoryDates) {
      final day = seoulDay(memory.startsAt);
      if (!day.isAfter(today)) (past[day] ??= []).add(memory);
    }
    final upcomingDays = future.keys.toList()..sort();
    final historyDays =
        past.keys.where((day) => !future.containsKey(day)).toList()
          ..sort((a, b) => b.compareTo(a));
    return RefreshIndicator(
      onRefresh: () => Future.wait([app.resendCalendar(), app.sync()]),
      child: ListView(
        key: const PageStorageKey('calendar'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 14, 20, 28),
        children: [
          if (app.calendarError case final error?) StatusMessage(error),
          if (upcomingDays.isEmpty && historyDays.isEmpty)
            const KoreanText('표시할 일정과 기억이 없어요'),
          for (final day in [...upcomingDays, ...historyDays])
            _CalendarDay(
              day: day,
              events: future[day] ?? const [],
              memories: past[day] ?? const [],
              onMemory: (memory) => _openMemory(context, memory),
            ),
        ],
      ),
    );
  }

  void _openMemory(BuildContext context, MemoryDate memory) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (context) => _CalendarMemory(app, memory),
    );
  }
}

class _CalendarDay extends StatelessWidget {
  const _CalendarDay({
    required this.day,
    required this.events,
    required this.memories,
    required this.onMemory,
  });

  final DateTime day;
  final List<wire.EventElement> events;
  final List<MemoryDate> memories;
  final ValueChanged<MemoryDate> onMemory;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final date = '${day.month}월 ${day.day}일';
    return Padding(
      padding: const EdgeInsets.only(bottom: 15),
      child: Column(
        key: ValueKey(day.toIso8601String().substring(0, 10)),
        crossAxisAlignment: CrossAxisAlignment.start,
        spacing: 8,
        children: [
          KoreanText(date, style: theme.textTheme.titleMedium),
          for (final event in events)
            Align(
              key: ValueKey('event-${event.id}'),
              alignment: Alignment.centerLeft,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(6),
                  color: theme.colorScheme.primaryContainer,
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 7,
                  ),
                  child: KoreanText(
                    '${seoulClock(event.start)}–${seoulClock(event.end)}  ${event.title.isEmpty ? '일정' : event.title}',
                  ),
                ),
              ),
            ),
          if (memories.isNotEmpty)
            Wrap(
              children: [
                for (final memory in memories)
                  IconButton(
                    key: ValueKey('memory-dot-${memory.episodeId}'),
                    icon: const Icon(Icons.circle, size: 10),
                    tooltip: '$date 준비 기억 · ${seoulClock(memory.startsAt)}',
                    onPressed: () => onMemory(memory),
                  ),
              ],
            ),
          const Divider(height: 1),
        ],
      ),
    );
  }
}

class _CalendarMemory extends StatefulWidget {
  const _CalendarMemory(this.app, this.memory);

  final AppController app;
  final MemoryDate memory;

  @override
  State<_CalendarMemory> createState() => _CalendarMemoryState();
}

class _CalendarMemoryState extends State<_CalendarMemory> {
  late var _read = widget.app.readMemory(widget.memory.episodeId);

  @override
  Widget build(BuildContext context) =>
      FutureBuilder<({wire.Episode episode, wire.Rationale rationale})>(
        future: _read,
        builder: (context, snapshot) => SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: switch (snapshot) {
              AsyncSnapshot(:final data?) => MemorySheet(
                rationale: data.rationale,
                episode: data.episode,
                startsAt: widget.memory.startsAt,
                cardIds: data.episode.cardIds,
              ),
              AsyncSnapshot(hasError: true) => Column(
                children: [
                  const StatusMessage('기억을 불러오지 못했어요'),
                  TextButton(
                    onPressed: () => setState(() {
                      _read = widget.app.readMemory(widget.memory.episodeId);
                    }),
                    child: const KoreanText('다시 시도'),
                  ),
                ],
              ),
              _ => const Center(
                child: CircularProgressIndicator(semanticsLabel: '기억 불러오는 중'),
              ),
            },
          ),
        ),
      );
}
