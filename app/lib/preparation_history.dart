import 'contracts.dart' as wire;

class PreparationChange {
  const PreparationChange(
    this.revision, {
    required this.switchedOff,
    required this.switchedOn,
    required this.timingChanged,
    required this.tasksChanged,
  });

  final String revision;
  final List<wire.LineElement> switchedOff;
  final List<wire.LineElement> switchedOn;
  final bool timingChanged;
  final bool tasksChanged;

  static PreparationChange? between(wire.Card previous, wire.Card current) {
    final oldLines = {for (final line in previous.lines) line.taskId: line};
    final currentIds = current.lines.map((line) => line.taskId).toSet();
    final switchedOff = <wire.LineElement>[];
    final switchedOn = <wire.LineElement>[];
    var timingChanged = previous.startsAt != current.startsAt;
    for (final line in current.lines) {
      final old = oldLines[line.taskId];
      if (old == null) {
        // Re-enabled tasks receive a new ID. Pair only an unambiguous
        // removed line with the same task name and displayed text.
        final replaced = previous.lines
            .where(
              (candidate) =>
                  !currentIds.contains(candidate.taskId) &&
                  candidate.taskId.split('#').first ==
                      line.taskId.split('#').first &&
                  candidate.text == line.text,
            )
            .singleOrNull;
        if (line.checked && replaced?.state == wire.LineState.OFF) {
          switchedOn.add(line);
        }
        continue;
      }
      if (line.state == wire.LineState.OFF && old.state != wire.LineState.OFF) {
        switchedOff.add(line);
      }
      timingChanged |=
          old.when?.event != line.when?.event ||
          old.when?.time != line.when?.time;
    }
    final tasksChanged =
        currentIds.length != oldLines.length ||
        !currentIds.every(oldLines.containsKey);
    if (!timingChanged &&
        !tasksChanged &&
        switchedOff.isEmpty &&
        switchedOn.isEmpty) {
      return null;
    }
    return PreparationChange(
      current.updatedAt,
      switchedOff: switchedOff,
      switchedOn: switchedOn,
      timingChanged: timingChanged,
      tasksChanged: tasksChanged,
    );
  }
}
