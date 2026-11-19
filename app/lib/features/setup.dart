// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import 'labels.dart';

class SetupScreen extends StatefulWidget {
  const SetupScreen(this.app, {super.key});

  final AppController app;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  static const _groups = {
    '인원': ['1인', '2인', '3~4인', '5인 이상'],
    '구성': ['부부·커플', ..._children, '부모 + 성인 자녀', '3대 함께', '룸메이트·셰어하우스'],
    '생활 단계': ['대학생', '직장인', '은퇴·노년'],
    '근무 형태': ['맞벌이', '재택근무'],
    '반려동물': ['반려견', '반려묘', '그 밖의 반려동물'],
  };
  static const _children = ['영유아 자녀', '초등 자녀', '중학생 자녀', '고등학생 자녀'];
  static const _singleChoice = {'인원', '생활 단계'};

  late final Set<String> _types = {...widget.app.householdTypes};
  final _choices = <String, Map<String, DeviceChoice>>{};

  bool get _validTypes {
    final hasCouple = _types.contains('부부·커플');
    final hasParents = _types.contains('부모 + 성인 자녀');
    final hasGenerations = _types.contains('3대 함께');
    final childCount = _children.where(_types.contains).length;
    final minPeople = (hasCouple ? 2 : 1) + childCount + (hasParents ? 1 : 0);
    final maxSize = const {
      '1인': 1,
      '2인': 2,
      '3~4인': 4,
    }.entries.where((e) => _types.contains(e.key)).firstOrNull?.value;
    return (maxSize == null ||
            (maxSize >= minPeople && (!hasGenerations || maxSize >= 3))) &&
        !(_types.contains('룸메이트·셰어하우스') &&
            (hasCouple || childCount > 0 || hasParents || hasGenerations)) &&
        !(_types.contains('맞벌이') && !hasCouple) &&
        !(_types.contains('은퇴·노년') &&
            (_types.contains('맞벌이') || _types.contains('재택근무')));
  }

  @override
  Widget build(BuildContext context) {
    final app = widget.app;
    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 28),
      children: [
        if (app.setupError case final error?) StatusMessage(error),
        switch (app.step) {
          SetupStep.household => _household(context),
          SetupStep.calendar => _calendar(context),
          SetupStep.devices => _devices(context),
          SetupStep.ready => const SizedBox.shrink(),
        },
      ],
    );
  }

  Widget _household(BuildContext context) {
    final app = widget.app;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('우리 집 설정', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        const Text('해당하는 가구 유형을 선택해 주세요.'),
        for (final group in _groups.entries) ...[
          const SizedBox(height: 18),
          Text(group.key, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 5),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              for (final type in group.value)
                FilterChip(
                  label: Text(type),
                  selected: _types.contains(type),
                  onSelected: app.busy
                      ? null
                      : (selected) => setState(() {
                          if (selected) {
                            if (_singleChoice.contains(group.key)) {
                              _types.removeAll(group.value);
                            }
                            _types.add(type);
                          } else {
                            _types.remove(type);
                          }
                        }),
                ),
            ],
          ),
        ],
        if (!_validTypes) const StatusMessage('선택한 가구 유형을 함께 사용할 수 없어요.'),
        const SizedBox(height: 24),
        FilledButton(
          onPressed: app.busy || _types.isEmpty || !_validTypes
              ? null
              : () => app.submitHousehold(_types),
          child: Text(app.busy ? '저장 중…' : '우리 집 만들기'),
        ),
      ],
    );
  }

  Widget _calendar(BuildContext context) {
    final app = widget.app;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('일정 연결', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        const Text('Google 캘린더를 연결하면 향후 14일의 일정을 준비에 참고해요.'),
        if (app.readCalendar == null)
          const StatusMessage('이 환경에서 Google 캘린더 연결을 사용할 수 없어요.'),
        const SizedBox(height: 20),
        FilledButton(
          onPressed: app.busy || app.readCalendar == null
              ? null
              : () => app.finishCalendar(connect: true),
          child: Text(app.busy ? '연결 중…' : 'Google 캘린더 연결'),
        ),
        TextButton(
          onPressed: app.busy ? null : () => app.finishCalendar(connect: false),
          child: const Text('건너뛰기'),
        ),
      ],
    );
  }

  Widget _devices(BuildContext context) {
    final app = widget.app;
    final devices = app.discovered?.devices ?? const <wire.DeviceElement>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('기기와 맡길 동작', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        Text(
          devices.isEmpty
              ? '기기 검색 정보를 사용할 수 없어요.'
              : '발견 목록에서 동작을 선택할 수 있어요. 이 선택은 이 앱에 저장돼요.',
        ),
        for (final device in devices)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    device.label ?? deviceLabel(device.type),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    '${device.room ?? '공간 미확인'} · ${deviceLabel(device.type)} · '
                    '${device.substrate == wire.Substrate.VIRTUAL ? '가상 기기' : '실물 기기'}',
                  ),
                  for (final command in device.commands)
                    if (!device.never.contains(command.cmd)) ...[
                      const SizedBox(height: 8),
                      DropdownButtonFormField<DeviceChoice>(
                        key: ValueKey('${device.id}/${command.cmd}'),
                        initialValue:
                            _choices[device.id]?[command.cmd] ??
                            DeviceChoice.undecided,
                        decoration: InputDecoration(
                          labelText: commandLabel(command.cmd),
                        ),
                        isExpanded: true,
                        items: const [
                          DropdownMenuItem(
                            value: DeviceChoice.undecided,
                            child: Text('미선택'),
                          ),
                          DropdownMenuItem(
                            value: DeviceChoice.delegated,
                            child: Text('맡기기'),
                          ),
                          DropdownMenuItem(
                            value: DeviceChoice.never,
                            child: Text('맡기지 않기'),
                          ),
                        ],
                        onChanged: app.busy
                            ? null
                            : (choice) {
                                if (choice == null) return;
                                final selected = _choices.putIfAbsent(
                                  device.id,
                                  () => {},
                                );
                                if (choice == DeviceChoice.undecided) {
                                  selected.remove(command.cmd);
                                } else {
                                  selected[command.cmd] = choice;
                                }
                              },
                      ),
                    ],
                  for (final command in device.never)
                    Text('${commandLabel(command)} · 위임 유보'),
                ],
              ),
            ),
          ),
        const SizedBox(height: 18),
        FilledButton(
          onPressed: app.busy ? null : () => app.finishDevices(_choices),
          child: Text(app.busy ? '저장 중…' : '설정 완료'),
        ),
      ],
    );
  }
}

class StatusMessage extends StatelessWidget {
  const StatusMessage(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Semantics(
    container: true,
    label: text,
    liveRegion: true,
    excludeSemantics: true,
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Text(text),
    ),
  );
}
