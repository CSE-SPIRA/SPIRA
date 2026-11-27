import 'dart:convert';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../design_tokens.g.dart';
import '../design_vocabulary.g.dart';
import '../korean_text.dart';
import 'labels.dart';
import 'status_badge.dart';

typedef _SampleDevice = ({wire.Device device, String? label});

class DeviceDelegationHint extends StatelessWidget {
  const DeviceDelegationHint({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: DesignTokens.space8),
      child: KoreanText(
        '기기별로 맡길지는 집 허브가 연결되면 고를 수 있어요.',
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
    );
  }
}

class SampleDevices extends StatefulWidget {
  const SampleDevices({super.key, required this.showDelegation, this.app});

  // Onboarding passes no controller and has no card controls.
  final AppController? app;
  final bool showDelegation;

  @override
  State<SampleDevices> createState() => _SampleDevicesState();
}

class _SampleDevicesState extends State<SampleDevices> {
  late final _inventory = _readInventory(DefaultAssetBundle.of(context));

  Future<List<_SampleDevice>> _readInventory(AssetBundle bundle) async {
    final json = jsonDecode(
      await bundle.loadString('assets/sample-home.json'),
    ) as List<dynamic>;
    return [
      for (final row in json.cast<Map<String, dynamic>>())
        (device: wire.Device.fromJson(row), label: row['label'] as String?),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return FutureBuilder(
      future: _inventory,
      builder: (context, snapshot) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: DesignTokens.space12,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              KoreanText(
                '예시 집',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
              if (widget.showDelegation && snapshot.hasData)
                KoreanText('맡기기', style: theme.textTheme.bodySmall),
            ],
          ),
          if (snapshot.hasError) const StatusMessage('예시 집을 불러오지 못했어요.'),
          if (snapshot.data case final inventory?)
            for (final room in [
              roomNames['entrance']!,
              roomNames['living_room']!,
              roomNames['kitchen']!,
            ])
              if (inventory.where((entry) => entry.device.room == room)
                  case final devices when devices.isNotEmpty)
                _DeviceRoom(
                  key: ValueKey('device-room-$room'),
                  room: room,
                  devices: devices,
                  showDelegation: widget.showDelegation,
                  app: widget.app,
                ),
        ],
      ),
    );
  }
}

class _DeviceRoom extends StatelessWidget {
  const _DeviceRoom({
    super.key,
    required this.room,
    required this.devices,
    required this.showDelegation,
    required this.app,
  });

  final String room;
  final Iterable<_SampleDevice> devices;
  final bool showDelegation;
  final AppController? app;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Semantics(
          header: true,
          child: KoreanText(room, style: theme.textTheme.titleMedium),
        ),
        const SizedBox(height: DesignTokens.space4),
        DecoratedBox(
          decoration: BoxDecoration(
            color: DesignTokens.paper,
            borderRadius: BorderRadius.circular(DesignTokens.radius12),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              for (final (index, entry) in devices.indexed) ...[
                if (index > 0)
                  const Divider(
                    height: 1,
                    indent: DesignTokens.space12,
                    endIndent: DesignTokens.space12,
                  ),
                _DeviceRow(
                  key: ValueKey('sample-device-${entry.device.id}'),
                  entry: entry,
                  showDelegation: showDelegation,
                  app: app,
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _DeviceRow extends StatelessWidget {
  const _DeviceRow({
    super.key,
    required this.entry,
    required this.showDelegation,
    required this.app,
  });

  final _SampleDevice entry;
  final bool showDelegation;
  final AppController? app;

  @override
  Widget build(BuildContext context) {
    final controller = app;
    final type = entry.device.type;
    final theme = Theme.of(context);
    final name = entry.label ?? deviceNames[type] ?? '기기';
    return Padding(
      padding: EdgeInsets.symmetric(
        horizontal: DesignTokens.space12,
        vertical: showDelegation ? 0 : DesignTokens.space8,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            spacing: DesignTokens.space8,
            children: [
              Icon(
                deviceIcons[type] ?? Icons.devices_other_outlined,
                size: 22,
                color: theme.colorScheme.primary,
              ),
              Expanded(
                child: KoreanText(
                  name,
                  style: theme.textTheme.titleMedium,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (showDelegation)
                Semantics(
                  label: '$name 맡기기',
                  child: const Switch(
                    value: false,
                    onChanged: null,
                    padding: EdgeInsets.zero,
                  ),
                ),
            ],
          ),
          if (controller != null)
            for (final (:card, :line) in controller.linesForDevice(
              entry.device,
            ))
              _DeviceLine(app: controller, card: card, line: line),
        ],
      ),
    );
  }
}

class _DeviceLine extends StatelessWidget {
  const _DeviceLine({
    required this.app,
    required this.card,
    required this.line,
  });

  final AppController app;
  final wire.Card card;
  final wire.LineElement line;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pending = app.linePending(card, line);
    final canTurnOff =
        line.state != wire.LineState.OFF && app.canSwitch(card, line);
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      spacing: DesignTokens.space8,
      children: [
        Expanded(
          child: KoreanText(
            normalizeKelvin(line.text),
            style: theme.textTheme.bodySmall,
            maxLines: 1,
            softWrap: false,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        Flexible(
          child: StatusBadge(
            lineLabel(line.state),
            color: lineStatusColor(context, line.state),
          ),
        ),
        TextButton(
          style: TextButton.styleFrom(
            minimumSize: const Size(DesignTokens.space32, DesignTokens.space32),
            padding: const EdgeInsets.symmetric(
              horizontal: DesignTokens.space4,
            ),
            textStyle: theme.textTheme.bodySmall,
          ),
          onPressed: pending || !canTurnOff
              ? null
              : () => app.switchLine(card, line),
          child: Semantics(
            liveRegion: pending,
            child: KoreanText(pending ? '요청함' : '끄기'),
          ),
        ),
      ],
    );
  }
}
