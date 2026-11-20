// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import 'device_setup.dart';

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
  final _drafts = <String, DeviceDraft>{};
  bool _choosingActions = false;

  @override
  void dispose() {
    for (final draft in _drafts.values) {
      draft.dispose();
    }
    super.dispose();
  }

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
      key: ValueKey((app.step, _choosingActions)),
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 28),
      children: [
        if (app.setupError case final error?) StatusMessage(error),
        switch (app.step) {
          SetupStep.start => _start(context),
          SetupStep.household => _household(context),
          SetupStep.calendar => _calendar(context),
          SetupStep.devices => _devices(context),
          SetupStep.ready => const SizedBox.shrink(),
        },
      ],
    );
  }

  Widget _start(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text('SPIRA와 함께 시작해요', style: Theme.of(context).textTheme.headlineMedium),
      const SizedBox(height: 12),
      const Text('공유한 주문과 캘린더 일정을 보고 집을 미리 준비해요.'),
      const SizedBox(height: 8),
      const Text('맡기기로 한 기기와 동작만 사용해요. 준비는 언제든 멈출 수 있어요.'),
      const SizedBox(height: 20),
      FilledButton(onPressed: widget.app.beginSetup, child: const Text('시작하기')),
    ],
  );

  Widget _household(BuildContext context) {
    final app = widget.app;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('우리 집 설정', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        const Text('우리 집에 해당하는 항목을 골라 주세요.'),
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
        if (!_validTypes) const StatusMessage('함께 고를 수 없는 항목이 있어요.'),
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
        const Text('Google 캘린더를 연결하면 앞으로 14일 동안의 일정을 보고 준비해요.'),
        if (app.readCalendar == null)
          const StatusMessage('지금은 Google 캘린더를 연결할 수 없어요.'),
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
    final drafts = [
      for (final device in app.home.devices)
        _drafts.putIfAbsent(
          device.id,
          () => DeviceDraft(
            device,
            saved: app.home.settings[device.id],
            delegated: app.savedDelegation(device),
          ),
        ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          _choosingActions ? 'SPIRA에게 맡길 일' : '기기가 있는 방과 이름',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const StatusMessage(homeHubPending),
        if (drafts.isEmpty)
          const Text('찾은 기기가 없어요.')
        else
          Text(
            _choosingActions
                ? '맡기고 싶지 않은 일만 선택을 풀어 주세요.'
                : '찾은 방과 기기 이름이 맞으면 그대로 두고, 다르면 바꿔 주세요.',
          ),
        for (final draft in drafts)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: _choosingActions
                  ? Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          draft.displayName,
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        Text(
                          draft.roomName.isEmpty ? '방을 골라 주세요' : draft.roomName,
                        ),
                        DelegationChoices(draft, enabled: !app.busy),
                      ],
                    )
                  : DeviceFields(
                      draft,
                      reviewed: app.home.settings.containsKey(draft.device.id),
                      enabled: !app.busy,
                      onChanged: () => setState(() {}),
                    ),
            ),
          ),
        const SizedBox(height: 18),
        if (_choosingActions) ...[
          FilledButton(
            onPressed: app.busy ? null : () => _finishDevices(drafts),
            child: Text(app.busy ? '저장 중…' : '설정 완료'),
          ),
          TextButton(
            onPressed: app.busy
                ? null
                : () => setState(() => _choosingActions = false),
            child: const Text('방과 이름 다시 보기'),
          ),
        ] else
          FilledButton(
            onPressed: () => setState(() => _choosingActions = true),
            child: const Text('맡길 일 고르기'),
          ),
      ],
    );
  }

  Future<void> _finishDevices(List<DeviceDraft> drafts) async {
    final app = widget.app;
    final messenger = ScaffoldMessenger.of(context);
    await app.finishDevices({
      for (final draft in drafts) draft.device.id: draft.settings,
    });
    if (app.step == SetupStep.ready && messenger.mounted) {
      messenger.showSnackBar(
        const SnackBar(content: Text('설정을 마쳤어요. $homeHubPending')),
      );
    }
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
