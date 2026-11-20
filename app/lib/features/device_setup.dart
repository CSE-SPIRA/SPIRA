// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../platform/home_hub_onboarding.dart';
import 'labels.dart';

const homeHubPending = '이 휴대폰에만 저장돼요. 아직 집에 있는 허브에 전달되지 않았어요.';

String homeSaveLabel(HomeSaveResult result) => switch (result) {
  HomeSaveResult.local => homeHubPending,
  HomeSaveResult.sent => '집 허브에 보냈어요.',
  HomeSaveResult.uploadPending => '집 허브에 저장했어요. 전송을 기다리고 있어요.',
};

String homeDeviceDescription(HomeDevice device) =>
    '${deviceLabel(device.type)} · ${deviceKindLabel(device.substrate)}';

class DeviceDraft {
  DeviceDraft(this.device, {HomeDeviceSettings? saved, Set<String>? delegated})
    : room = TextEditingController(
        text: saved == null ? device.room : saved.room,
      ),
      name = TextEditingController(
        text: saved == null ? defaultName(device) : saved.name,
      ),
      delegated = {...(delegated ?? device.selectableCommands)};

  final HomeDevice device;
  final TextEditingController room;
  final TextEditingController name;
  final Set<String> delegated;

  static String defaultName(HomeDevice device) {
    final label = device.label?.trim();
    return label == null || label.isEmpty ? deviceLabel(device.type) : label;
  }

  static String savedName(HomeDevice device, HomeDeviceSettings? saved) =>
      saved == null
      ? defaultName(device)
      : saved.name ?? deviceLabel(device.type);

  String get roomName => room.text.trim();
  String get displayName =>
      name.text.trim().isEmpty ? deviceLabel(device.type) : name.text.trim();

  HomeDeviceSettings get settings => HomeDeviceSettings(
    room: roomName.isEmpty ? null : roomName,
    name: name.text.trim().isEmpty ? null : name.text.trim(),
    delegated: delegated,
  );

  void dispose() {
    room.dispose();
    name.dispose();
  }
}

class DeviceFields extends StatelessWidget {
  const DeviceFields(
    this.draft, {
    required this.reviewed,
    required this.enabled,
    required this.onChanged,
    super.key,
  });

  final DeviceDraft draft;
  final bool reviewed;
  final bool enabled;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    final device = draft.device;
    final suggestion = device.room?.trim() ?? '';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(homeDeviceDescription(device)),
        const SizedBox(height: 12),
        TextField(
          key: ValueKey('${device.id}/room'),
          controller: draft.room,
          enabled: enabled,
          onChanged: (_) => onChanged(),
          decoration: InputDecoration(
            labelText: '방 이름',
            helperText: draft.roomName.isEmpty
                ? '방을 골라 주세요'
                : !reviewed && suggestion.isNotEmpty
                ? '찾은 방이 맞는지 확인해 주세요.'
                : null,
            helperMaxLines: 3,
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          key: ValueKey('${device.id}/name'),
          controller: draft.name,
          enabled: enabled,
          decoration: const InputDecoration(labelText: '기기 이름'),
        ),
      ],
    );
  }
}

class DelegationChoices extends StatefulWidget {
  const DelegationChoices(this.draft, {required this.enabled, super.key});

  final DeviceDraft draft;
  final bool enabled;

  @override
  State<DelegationChoices> createState() => _DelegationChoicesState();
}

class _DelegationChoicesState extends State<DelegationChoices> {
  @override
  Widget build(BuildContext context) {
    final draft = widget.draft;
    final device = draft.device;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final command in device.selectableCommands)
          CheckboxListTile(
            key: ValueKey('${device.id}/$command'),
            contentPadding: EdgeInsets.zero,
            title: Text(commandLabel(command)),
            value: draft.delegated.contains(command),
            onChanged: widget.enabled
                ? (selected) => setState(() {
                    if (selected == true) {
                      draft.delegated.add(command);
                    } else {
                      draft.delegated.remove(command);
                    }
                  })
                : null,
          ),
        for (final command in device.never.toSet())
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Text('${commandLabel(command)} · 하지 않아요'),
          ),
      ],
    );
  }
}
