import 'dart:async';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../theme.dart';
import 'labels.dart';
import 'settings.dart';
import 'setup.dart';

void openOurHome(BuildContext context, AppController app, wire.Card card) {
  final home = (
    app
        .rationale(card.episodeId)
        .then<wire.Rationale?>((result) => result, onError: (Object _) => null),
    app.homeHub?.fetchDevices(app.household!) ?? Future<wire.Devices?>.value(),
  ).wait;
  Navigator.push<void>(
    context,
    MaterialPageRoute(
      builder: (_) => _OurHome(app: app, card: card, home: home),
    ),
  );
}

class _OurHome extends StatelessWidget {
  const _OurHome({required this.app, required this.card, required this.home});

  final AppController app;
  final wire.Card card;
  final Future<(wire.Rationale?, wire.Devices?)> home;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('우리 집')),
    body: SafeArea(
      top: false,
      child: FutureBuilder<(wire.Rationale?, wire.Devices?)>(
        future: home,
        builder: (context, snapshot) {
          final (result, inventory) = snapshot.data ?? (null, null);
          final selected = <String, wire.Device>{
            for (final task in result?.tasks ?? const <wire.Task>[])
              if (task.cardId == card.cardId)
                for (final device in task.devices) device.id: device,
          };
          final itemDeviceIds = <String>{};
          final executions = result?.executions ?? const <wire.Execution>[];
          for (final task
              in result?.itemTasks ?? const <wire.ItemTaskElement>[]) {
            final itemExecutions = executions.where(
              (execution) => execution.taskId == task.taskId,
            );
            // The current item notice kinds (prep and storage) use the fridge.
            if (itemExecutions.isEmpty && task.kind != null) {
              final fridge = inventory?.devices
                  .where((device) => device.type == 'fridge')
                  .singleOrNull;
              if (fridge != null) itemDeviceIds.add(fridge.id);
            }
            for (final execution in itemExecutions) {
              itemDeviceIds.add(execution.device);
              if (inventory == null && task.kind != null) {
                selected.putIfAbsent(
                  execution.device,
                  () => wire.Device(
                    id: execution.device,
                    type: 'fridge',
                    room: null,
                  ),
                );
              }
            }
          }
          final devices = [
            if (inventory == null)
              for (final device in selected.values)
                (
                  id: device.id,
                  type: device.type,
                  room: device.room,
                  label: null,
                )
            else
              for (final device in inventory.devices)
                (
                  id: device.id,
                  type: device.type,
                  room: device.room,
                  label: device.label,
                ),
          ];

          final rooms = <String, List<Widget>>{};
          for (final (:id, :type, :room, :label) in devices) {
            final roomName = room?.trim();
            final name = label?.trim();
            rooms
                .putIfAbsent(
                  roomName == null || roomName.isEmpty ? '방 미확인' : roomName,
                  () => [],
                )
                .add(
                  _HomeDevice(
                    name: name == null || name.isEmpty
                        ? _homeDeviceLabel(type)
                        : name,
                    type: type,
                    selected: result == null
                        ? null
                        : selected.containsKey(id) ||
                              itemDeviceIds.contains(id),
                  ),
                );
          }
          final roomNames = {
            '현관',
            '거실',
            '주방',
            ...rooms.keys,
          }.where(rooms.containsKey).toList();
          final theme = Theme.of(context);
          final intent = result?.intents
              .where((intent) => intent.cardId == card.cardId)
              .firstOrNull;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: PeerLabel(app.fixture),
              ),
              const SizedBox(height: 12),
              Text.rich(
                highlightTheme(
                  card.text,
                  intent?.situation.theme,
                  theme.colorScheme.onSecondaryContainer,
                ),
                style: theme.textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              if (snapshot.connectionState != ConnectionState.done)
                const LinearProgressIndicator(semanticsLabel: '준비 기기 확인 중')
              else if (result == null)
                const StatusMessage('이번 준비에 선택된 기기를 확인할 수 없어요.')
              else if (inventory == null && devices.isNotEmpty)
                const StatusMessage('집 기기 목록을 받지 못해 이번 준비에 선택된 기기만 보여 드려요.'),
              if (devices.isNotEmpty) ...[
                Text('확인한 기기 ${devices.length}대'),
                const SizedBox(height: 12),
                _RoomMap(roomNames: roomNames, rooms: rooms),
              ] else if (inventory != null)
                const Text('집에 등록된 기기가 없어요.')
              else if (result != null)
                const Text('이번 준비에 선택된 기기가 없어요.'),
            ],
          );
        },
      ),
    ),
  );
}

String _homeDeviceLabel(String type) => switch (type) {
  'display' => 'TV',
  'purifier' => '공기청정기',
  'styler' => '스타일러',
  _ => deviceLabel(type, unknownLabel: '기기'),
};

class _RoomMap extends StatelessWidget {
  const _RoomMap({required this.roomNames, required this.rooms});

  final List<String> roomNames;
  final Map<String, List<Widget>> rooms;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    const wall = 5.0;
    return ClipRRect(
      borderRadius: BorderRadius.circular(13),
      child: ColoredBox(
        color: colors.primary,
        child: Padding(
          padding: const EdgeInsets.all(wall),
          child: LayoutBuilder(
            builder: (context, constraints) {
              final narrow =
                  constraints.maxWidth < 300 ||
                  MediaQuery.textScalerOf(context).scale(13) > 18;
              final columns = narrow || roomNames.length == 1
                  ? 1
                  : constraints.maxWidth >= 520 && roomNames.length >= 3
                  ? 3
                  : 2;
              return Column(
                spacing: wall,
                children: [
                  for (
                    var start = 0;
                    start < roomNames.length;
                    start += columns
                  )
                    IntrinsicHeight(
                      child: Row(
                        spacing: wall,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          for (final name
                              in roomNames.skip(start).take(columns))
                            Expanded(
                              child: ColoredBox(
                                color: name == '거실'
                                    ? colors.primaryContainer
                                    : colors.surfaceContainerHighest,
                                child: Padding(
                                  padding: const EdgeInsets.all(8),
                                  child: Column(
                                    spacing: 7,
                                    crossAxisAlignment:
                                        CrossAxisAlignment.stretch,
                                    children: [
                                      Semantics(
                                        header: true,
                                        child: Text(
                                          name,
                                          style: theme.textTheme.titleMedium,
                                        ),
                                      ),
                                      ...rooms[name]!,
                                    ],
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _HomeDevice extends StatelessWidget {
  const _HomeDevice({
    required this.name,
    required this.type,
    required this.selected,
  });

  final String name;
  final String type;
  final bool? selected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final icon = switch (type) {
      'cleaner' => Icons.circle_outlined,
      'light' => Icons.lightbulb_outline,
      'display' => Icons.tv,
      'cooktop' => Icons.grid_view,
      'oven' => Icons.countertops_outlined,
      'fridge' => Icons.kitchen_outlined,
      'smart_plug' => Icons.power_outlined,
      _ => Icons.devices_other,
    };
    final foreground = selected == true
        ? colors.primary
        : colors.onSurfaceVariant;
    return MergeSemantics(
      child: Container(
        constraints: const BoxConstraints(minHeight: 39),
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 5),
        decoration: BoxDecoration(
          color: selected == false
              ? colors.surfaceContainerHighest
              : colors.surface,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
            color: selected == true ? colors.outline : colors.outlineVariant,
          ),
        ),
        child: Row(
          children: [
            Icon(icon, size: 18, color: foreground),
            const SizedBox(width: 5),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: foreground,
                      fontWeight: selected == true ? FontWeight.w600 : null,
                    ),
                  ),
                  if (selected != null)
                    Text(
                      selected! ? '준비에 선택됨' : '쉬는 중',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: foreground,
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
