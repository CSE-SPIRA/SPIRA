// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'labels.dart';
import 'memory_sheet.dart';
import 'status_badge.dart';

class PreparationCalendar extends StatefulWidget {
  const PreparationCalendar(this.app, {super.key});

  final AppController app;

  @override
  State<PreparationCalendar> createState() => _PreparationCalendarState();
}

class _PreparationCalendarState extends State<PreparationCalendar> {
  AppController get app => widget.app;
  DateTime get _today => seoulDay(DateTime.now().toIso8601String());
  DateTime? _chosenDay;

  void _showMonth(DateTime month, int offset) => setState(() {
    final next = DateTime.utc(month.year, month.month + offset);
    final today = _today;
    _chosenDay = today.year == next.year && today.month == next.month
        ? today
        : next;
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final today = _today;
    final calendar = app.displayCalendar;
    final birthday = app.showsSampleCalendar
        ? calendar.events.firstOrNull
        : null;
    final selected =
        _chosenDay ?? (birthday == null ? today : seoulDay(birthday.start));
    final month = DateTime.utc(selected.year, selected.month);
    final firstColumn = month.weekday % 7;
    final days = DateTime.utc(month.year, month.month + 1, 0).day;
    final rows = (firstColumn + days + 6) ~/ 7;
    final events = [...calendar.events]
      ..sort(
        (a, b) => DateTime.parse(a.start).compareTo(DateTime.parse(b.start)),
      );
    final dayEvents = <DateTime, List<wire.EventElement>>{};
    for (var number = 1; number <= days; number++) {
      final day = DateTime.utc(month.year, month.month, number);
      final midnight = day.subtract(const Duration(hours: 9));
      final tomorrow = midnight.add(const Duration(days: 1));
      dayEvents[day] = events
          .where(
            (event) =>
                DateTime.parse(event.start).isBefore(tomorrow) &&
                DateTime.parse(event.end).isAfter(midnight),
          )
          .toList();
    }
    final memories = <DateTime, List<MemoryDate>>{};
    for (final memory in app.memoryDates) {
      final day = seoulDay(memory.startsAt);
      (memories[day] ??= []).add(memory);
    }
    return RefreshIndicator(
      onRefresh: () => Future.wait([app.resendCalendar(), app.sync()]),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(
          DesignTokens.space12,
          DesignTokens.space12,
          DesignTokens.space12,
          DesignTokens.space24,
        ),
        children: [
          Row(
            children: [
              Expanded(
                child: KoreanText(
                  '${month.year}년 ${month.month}월',
                  style: theme.textTheme.headlineMedium,
                ),
              ),
              TextButton(
                onPressed: () => setState(() => _chosenDay = today),
                child: const KoreanText('오늘'),
              ),
              IconButton(
                tooltip: '이전 달',
                onPressed: () => _showMonth(month, -1),
                icon: const Icon(Icons.chevron_left),
              ),
              IconButton(
                tooltip: '다음 달',
                onPressed: () => _showMonth(month, 1),
                icon: const Icon(Icons.chevron_right),
              ),
            ],
          ),
          if (app.showsSampleCalendar)
            Padding(
              padding: const EdgeInsets.only(bottom: DesignTokens.space8),
              child: KoreanText('예시 일정', style: theme.textTheme.bodySmall),
            ),
          if (app.calendarError case final error?) StatusMessage(error),
          Row(
            children: [
              for (final name in ['일', '월', '화', '수', '목', '금', '토'])
                Expanded(
                  child: KoreanText(
                    name,
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
            ],
          ),
          const SizedBox(height: DesignTokens.space8),
          for (var row = 0; row < rows; row++)
            Row(
              children: [
                for (var col = 0; col < 7; col++)
                  Expanded(
                    child: _gridCell(
                      row * 7 + col - firstColumn + 1,
                      days,
                      today,
                      selected,
                      dayEvents,
                      memories,
                    ),
                  ),
              ],
            ),
          const SizedBox(height: DesignTokens.space20),
          _DayAgenda(
            day: selected,
            events: dayEvents[selected] ?? const [],
            memories: memories[selected] ?? const [],
            onMemory: (memory) => showModalBottomSheet<void>(
              context: context,
              isScrollControlled: true,
              useSafeArea: true,
              showDragHandle: true,
              builder: (context) => MemoryDetailSheet(app, memory),
            ),
          ),
        ],
      ),
    );
  }

  Widget _gridCell(
    int number,
    int days,
    DateTime today,
    DateTime selected,
    Map<DateTime, List<wire.EventElement>> events,
    Map<DateTime, List<MemoryDate>> memories,
  ) {
    if (number < 1 || number > days) return const SizedBox.shrink();
    final day = DateTime.utc(selected.year, selected.month, number);
    return _MonthDay(
      key: ValueKey(day.toIso8601String().substring(0, 10)),
      day: day,
      today: day == today,
      selected: day == selected,
      events: events[day] ?? const [],
      memories: memories[day] ?? const [],
      onTap: () => setState(() => _chosenDay = day),
    );
  }
}

String _eventTitle(wire.EventElement event) =>
    event.title.isEmpty ? '일정' : event.title;

String _eventLabel(wire.EventElement event) {
  final start = seoulClock(event.start);
  final end = seoulClock(event.end);
  return start == '00:00' && end == '00:00'
      ? '${_eventTitle(event)} · 종일'
      : '${_eventTitle(event)} $start–$end';
}

class _MonthDay extends StatelessWidget {
  const _MonthDay({
    super.key,
    required this.day,
    required this.today,
    required this.selected,
    required this.events,
    required this.memories,
    required this.onTap,
  });

  final DateTime day;
  final bool today;
  final bool selected;
  final List<wire.EventElement> events;
  final List<MemoryDate> memories;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    const labelHeight = 1.25;
    final labelStyle = theme.textTheme.bodySmall?.copyWith(
      fontSize: DesignTokens.size12,
      height: labelHeight,
    );
    final scaledLabelHeight =
        MediaQuery.textScalerOf(context).scale(DesignTokens.size12) *
        labelHeight;
    final date = '${day.month}월 ${day.day}일';
    return Semantics(
      selected: selected,
      button: true,
      label:
          '${today ? '오늘, ' : ''}$date · 일정 ${events.length}개 · 기억 ${memories.length}개',
      child: Material(
        color: selected ? DesignTokens.soft : Colors.transparent,
        shape: Border(top: BorderSide(color: colors.outlineVariant)),
        child: InkWell(
          onTap: onTap,
          child: SizedBox(
            // Reserve lines for the date, event and count, plus room for dots.
            height: 3 * scaledLabelHeight + DesignTokens.space20,
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(3),
                  child: DecoratedBox(
                    key: today ? const ValueKey('calendar-today') : null,
                    decoration: BoxDecoration(
                      color: today ? colors.primary : Colors.transparent,
                      borderRadius: BorderRadius.circular(
                        DesignTokens.radiusPill,
                      ),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 5),
                      child: KoreanText(
                        '${day.day}',
                        maxLines: 1,
                        overflow: TextOverflow.clip,
                        style: labelStyle?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: today ? colors.onPrimary : colors.onSurface,
                        ),
                      ),
                    ),
                  ),
                ),
                if (events.firstOrNull case final event?)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 2),
                    child: Tooltip(
                      message: _eventLabel(event),
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final compact = constraints.maxWidth < 115;
                          return Container(
                            key: ValueKey('event-${event.id}'),
                            width: double.infinity,
                            padding: const EdgeInsets.symmetric(
                              horizontal: 2,
                              vertical: 1,
                            ),
                            decoration: BoxDecoration(
                              color: colors.primaryContainer,
                              borderRadius: BorderRadius.circular(
                                DesignTokens.radius6,
                              ),
                            ),
                            child: KoreanText(
                              compact ? _eventTitle(event) : _eventLabel(event),
                              maxLines: 1,
                              softWrap: false,
                              overflow: TextOverflow.ellipsis,
                              style: labelStyle?.copyWith(
                                color: colors.onPrimaryContainer,
                              ),
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                if (events.length > 1)
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    child: KoreanText(
                      '+${events.length - 1}',
                      maxLines: 1,
                      style: labelStyle?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ),
                if (memories.isNotEmpty)
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      for (final memory in memories.take(3))
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 1,
                            vertical: 2,
                          ),
                          child: Icon(
                            Icons.circle,
                            key: ValueKey('memory-dot-${memory.episodeId}'),
                            size: 5,
                            color: colors.secondary,
                          ),
                        ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _DayAgenda extends StatelessWidget {
  const _DayAgenda({
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
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.space8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: DesignTokens.space8,
        children: [
          KoreanText(
            '${day.month}월 ${day.day}일',
            style: theme.textTheme.titleLarge,
          ),
          if (events.isEmpty && memories.isEmpty)
            const KoreanText('이날의 일정과 기억이 없어요.'),
          for (final event in events)
            DecoratedBox(
              decoration: BoxDecoration(
                color: theme.colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(DesignTokens.radius8),
              ),
              child: Padding(
                padding: const EdgeInsets.all(DesignTokens.space8),
                child: KoreanText(_eventLabel(event)),
              ),
            ),
          for (final memory in memories)
            ListTile(
              key: ValueKey('calendar-memory-${memory.episodeId}'),
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                Icons.circle,
                size: 8,
                color: theme.colorScheme.secondary,
              ),
              title: const KoreanText('준비 기억'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => onMemory(memory),
            ),
        ],
      ),
    );
  }
}

class MemoryDetailSheet extends StatefulWidget {
  const MemoryDetailSheet(this.app, this.memory, {super.key});

  final AppController app;
  final MemoryDate memory;

  @override
  State<MemoryDetailSheet> createState() => _MemoryDetailSheetState();
}

class _MemoryDetailSheetState extends State<MemoryDetailSheet> {
  late var _read = widget.app.readMemory(widget.memory.episodeId);

  @override
  Widget build(BuildContext context) =>
      FutureBuilder(
        future: _read,
        builder: (context, snapshot) => SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: switch (snapshot) {
              AsyncSnapshot(:final data?) => MemorySheet(
                rationale: data.rationale,
                episode: data.episode,
                startsAt: widget.app.memoryStart(
                  data.episode.episodeId,
                  data.cardIds,
                ),
                cardIds: data.cardIds,
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
