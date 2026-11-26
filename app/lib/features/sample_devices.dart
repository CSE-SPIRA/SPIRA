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

class SampleDevices extends StatefulWidget {
  const SampleDevices({super.key, this.app});

  // Onboarding passes no controller and has no card controls.
  final AppController? app;

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
              if (snapshot.hasData)
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
    required this.app,
  });

  final String room;
  final Iterable<_SampleDevice> devices;
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
  const _DeviceRow({super.key, required this.entry, required this.app});

  final _SampleDevice entry;
  final AppController? app;

  @override
  Widget build(BuildContext context) {
    final controller = app;
    final type = entry.device.type;
    final theme = Theme.of(context);
    final name = entry.label ?? deviceNames[type] ?? '기기';
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: DesignTokens.space12),
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
                child: KoreanText(name, style: theme.textTheme.titleMedium),
              ),
              Flexible(
                child: KoreanText(
                  '집 연결 후',
                  textAlign: TextAlign.end,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
              Semantics(
                label: '$name 맡기기 · 집 연결 후',
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
    final pending = app.linePending(card, line);
    final canTurnOff =
        line.state != wire.LineState.OFF && app.canSwitch(card, line);
    return Row(
      spacing: DesignTokens.space8,
      children: [
        Expanded(
          child: KoreanText(
            '지금: ${normalizeKelvin(line.text)} · ${lineLabel(line.state)}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
        TextButton(
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
