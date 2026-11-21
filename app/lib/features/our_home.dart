// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../design_vocabulary.g.dart';
import '../theme.dart';
import '../korean_text.dart';
import 'labels.dart';
import 'setup.dart';

class OurHome extends StatefulWidget {
  const OurHome(this.app, {super.key});

  final AppController app;

  @override
  State<OurHome> createState() => _OurHomeState();
}

class _OurHomeState extends State<OurHome> {
  AppController get app => widget.app;

  Future<wire.Devices?>? _inventory;
  wire.Episode? _order;
  Future<wire.Rationale>? _rationale;

  @override
  void initState() {
    super.initState();
    _inventory = _fetchInventory();
    _updateOrder();
  }

  @override
  void didUpdateWidget(OurHome oldWidget) {
    super.didUpdateWidget(oldWidget);
    _updateOrder();
  }

  Future<wire.Devices?>? _fetchInventory() =>
      app.homeHub?.fetchDevices(app.household!);

  void _updateOrder({bool retry = false}) {
    final latest = app.orderedEpisodes.firstOrNull;
    final order =
        app.currentPreparationOrder ??
        (latest?.status != wire.EpisodeStatus.CLOSED &&
                (latest?.itemTasks.isNotEmpty ?? false)
            ? latest
            : null);
    if (order == null) {
      _order = null;
      _rationale = null;
      return;
    }
    final cached = app.requestedRationale(order.episodeId);
    if (cached != null) {
      _rationale = cached;
    } else if (retry ||
        order.episodeId != _order?.episodeId ||
        order.status != _order?.status) {
      _rationale = app.rationale(order.episodeId);
    }
    _order = order;
  }

  Future<void> _refresh() async {
    final inventory = _fetchInventory();
    setState(() {
      _inventory = inventory;
      _updateOrder(retry: true);
    });
    await Future.wait([app.sync(), ?inventory]);
  }

  Map<String, ({wire.Device device, Set<String> times})> _selectedDevices(
    wire.Devices? inventory,
    wire.Rationale? rationale,
  ) {
    final selected = <String, ({wire.Device device, Set<String> times})>{};
    final order = _order;
    if (order == null) return selected;

    final cards = {for (final card in app.cardsFor(order)) card.cardId: card};
    for (final task in rationale?.tasks ?? const <wire.Task>[]) {
      final card = cards[task.cardId];
      if (card == null) continue;
      final line = card.lines
          .where((line) => line.taskId == task.taskId)
          .firstOrNull;
      final time = lineTimeLabel(line);
      for (final device in task.devices) {
        final entry = selected.putIfAbsent(
          device.id,
          () => (device: device, times: {}),
        );
        if (time != null) entry.times.add(time);
      }
    }

    final fridge = inventory?.devices
        .where((device) => device.type == 'fridge')
        .singleOrNull;
    for (final task in order.itemTasks) {
      final executions =
          rationale?.executions.where(
            (execution) => execution.taskId == task.taskId,
          ) ??
          const <wire.Execution>[];
      final ids = {for (final execution in executions) execution.device};
      // Item notices have no device ID before execution. Fridge notices
      // can only be associated with an unambiguous inventory match.
      if (ids.isEmpty && task.kind != null && fridge != null) {
        ids.add(fridge.id);
      }
      for (final id in ids) {
        if (inventory == null && task.kind == null) continue;
        selected.putIfAbsent(
          id,
          () => (
            device: wire.Device(id: id, type: 'fridge', room: null),
            times: {},
          ),
        );
      }
    }
    return selected;
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<wire.Devices?>(
    future: _inventory,
    builder: (context, inventory) => FutureBuilder<wire.Rationale>(
      future: _rationale,
      builder: (context, rationale) {
        final loading =
            inventory.connectionState == ConnectionState.waiting ||
            rationale.connectionState == ConnectionState.waiting;
        // A new rationale must never highlight devices from the previous order.
        final result = rationale.data?.episodeId == _order?.episodeId
            ? rationale.data
            : null;
        final selected = _selectedDevices(inventory.data, result);
        final devices = [
          if (inventory.data case final manifest?)
            for (final device in manifest.devices)
              (
                id: device.id,
                type: device.type,
                room: device.room,
                label: device.label,
              )
          else
            for (final entry in selected.values)
              (
                id: entry.device.id,
                type: entry.device.type,
                room: entry.device.room,
                label: null,
              ),
        ];
        final rooms = <String, List<Widget>>{};
        final selectionKnown = _order == null || result != null;
        final usedForPreparation = stateWords['used_for_preparation']!;
        for (final (:id, :type, :room, :label) in devices) {
          final roomName = roomLabel(room);
          final name = label?.trim();
          final times = selected[id]?.times;
          rooms
              .putIfAbsent(roomName ?? '방 미확인', () => [])
              .add(
                _HomeDevice(
                  key: ValueKey(id),
                  name: name == null || name.isEmpty
                      ? deviceNames[type] ?? '기기'
                      : name,
                  type: type,
                  selected: times != null,
                  status: switch (times) {
                    final times? when times.isNotEmpty =>
                      '$usedForPreparation · ${times.join(' · ')}',
                    _ when times != null && type == 'fridge' =>
                      '$usedForPreparation · ${stateWords['guidance']}',
                    _ when times != null => usedForPreparation,
                    _ when selectionKnown => stateWords['resting']!,
                    _ => '준비 미확인',
                  },
                ),
              );
        }

        final theme = Theme.of(context);
        return RefreshIndicator(
          onRefresh: _refresh,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(
              DesignTokens.space20,
              DesignTokens.space12,
              DesignTokens.space20,
              DesignTokens.space24,
            ),
            children: [
              KoreanText('우리 집', style: theme.textTheme.headlineMedium),
              if (devices.isNotEmpty)
                KoreanText(
                  '확인한 기기 ${devices.length}대',
                  style: theme.textTheme.bodySmall,
                ),
              if (loading)
                const LinearProgressIndicator(semanticsLabel: '우리 집 기기 확인 중')
              else ...[
                if (!selectionKnown)
                  const StatusMessage('이번 준비에 선택된 기기를 확인할 수 없어요.'),
                if (inventory.data == null)
                  StatusMessage(
                    devices.isEmpty
                        ? '집 기기 목록을 받지 못했어요.'
                        : '집 기기 목록을 받지 못해 이번 준비에 선택된 기기만 보여 드려요.',
                  )
                else if (devices.isEmpty)
                  const StatusMessage('집에 등록된 기기가 없어요.'),
              ],
              for (final room in {...roomNames.values, ...rooms.keys})
                if (rooms[room] case final cards?)
                  _RoomGrid(name: room, cards: cards),
            ],
          ),
        );
      },
    ),
  );
}

class _RoomGrid extends StatelessWidget {
  const _RoomGrid({required this.name, required this.cards});

  final String name;
  final List<Widget> cards;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 18),
    child: Column(
      spacing: DesignTokens.space8,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: KoreanText(
            name,
            style: Theme.of(context).textTheme.titleMedium,
          ),
        ),
        LayoutBuilder(
          builder: (context, constraints) {
            const gap = DesignTokens.space8;
            final minWidth = MediaQuery.textScalerOf(context).scale(144);
            final columns = ((constraints.maxWidth + gap) / (minWidth + gap))
                .floor()
                .clamp(1, 4);
            final width =
                (constraints.maxWidth - gap * (columns - 1)) / columns;
            return Wrap(
              spacing: gap,
              runSpacing: gap,
              children: [
                for (final card in cards) SizedBox(width: width, child: card),
              ],
            );
          },
        ),
      ],
    ),
  );
}

class _HomeDevice extends StatelessWidget {
  const _HomeDevice({
    required this.name,
    required this.type,
    required this.selected,
    required this.status,
    super.key,
  });

  final String name;
  final String type;
  final bool selected;
  final String status;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final icon = deviceIcons[type] ?? Icons.devices_other;
    final foreground = selected ? colors.primary : colors.onSurfaceVariant;
    return MergeSemantics(
      child: Container(
        constraints: const BoxConstraints(minHeight: 66),
        decoration: BoxDecoration(
          color: selected ? colors.primaryContainer : appPaper,
          borderRadius: BorderRadius.circular(DesignTokens.radius12),
          border: Border.all(color: colors.outlineVariant),
        ),
        clipBehavior: Clip.antiAlias,
        child: Stack(
          children: [
            if (selected)
              PositionedDirectional(
                start: 0,
                top: 0,
                bottom: 0,
                width: 3,
                child: ColoredBox(color: colors.primary),
              ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
              child: Row(
                children: [
                  Icon(icon, size: 20, color: foreground),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        KoreanText(
                          name,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: foreground,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        KoreanText(
                          status,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: foreground,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        ),
                      ],
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
