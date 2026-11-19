// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import 'labels.dart';
import 'setup.dart';

class SettingsScreen extends StatelessWidget {
  const SettingsScreen(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) => Scaffold(
      appBar: AppBar(title: const Text('설정')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          PeerLabel(app.fixture),
          const SizedBox(height: 16),
          Text('자동 준비', style: Theme.of(context).textTheme.titleLarge),
          const Text(
            '일시정지하면 시작 전 준비를 취소하고, 진행 중인 준비는 그대로 이어가요. '
            '일시정지 중 공유한 주문은 보관해요. 재개하면 이후 주문부터 새로 준비해요.',
          ),
          StatusMessage(
            app.pausePending
                ? '자동 준비 상태 변경을 확인하는 중…'
                : switch (app.paused) {
                    true => '자동 준비 일시정지됨',
                    false => '자동 준비 켜짐',
                    null => '자동 준비 상태 미확인',
                  },
          ),
          if (app.controlErrors['pause'] case final error?)
            StatusMessage(error),
          Wrap(
            spacing: 8,
            children: [
              if (app.paused != true)
                OutlinedButton(
                  onPressed: app.pausePending
                      ? null
                      : () => app.setPaused(true),
                  child: const Text('자동 준비 일시정지'),
                ),
              if (app.paused != false)
                OutlinedButton(
                  onPressed: app.pausePending
                      ? null
                      : () => app.setPaused(false),
                  child: const Text('자동 준비 재개'),
                ),
            ],
          ),
          const SizedBox(height: 24),
          const Divider(),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('우리 집 기억'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push<void>(
              context,
              MaterialPageRoute(builder: (_) => _MemoryScreen(app)),
            ),
          ),
          if (app.discovered?.devices case final devices?
              when devices.isNotEmpty) ...[
            const Divider(),
            Text('기기 동작 선택', style: Theme.of(context).textTheme.titleLarge),
            const Text('이 앱에 저장된 선택이에요.'),
            for (final device in devices) ...[
              const SizedBox(height: 12),
              Text(
                '${device.label ?? deviceLabel(device.type)} · ${device.room ?? '공간 미확인'} · '
                '${device.substrate == wire.Substrate.VIRTUAL ? '가상 기기' : '실물 기기'}',
              ),
              for (final entry in (app.deviceChoices[device.id] ?? {}).entries)
                Text(
                  '${commandLabel(entry.key)} · ${entry.value == DeviceChoice.delegated ? '맡기기로 선택' : '맡기지 않기로 선택'}',
                ),
            ],
          ],
        ],
      ),
    ),
  );
}

class PeerLabel extends StatelessWidget {
  const PeerLabel(this.fixture, {super.key});

  final bool fixture;

  @override
  Widget build(BuildContext context) => Align(
    alignment: Alignment.centerLeft,
    child: DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
        child: Text(
          fixture ? '계약 테스트 서버' : '실제 서버 프로필',
          style: Theme.of(context).textTheme.labelMedium,
        ),
      ),
    ),
  );
}

class _MemoryScreen extends StatefulWidget {
  const _MemoryScreen(this.app);
  final AppController app;

  @override
  State<_MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends State<_MemoryScreen> {
  wire.Memory? _memory;
  bool _busy = true;
  String? _message;
  String? _awaitingDeletion;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final memory = await widget.app.memory();
      if (!mounted) return;
      setState(() {
        _memory = memory;
        _busy = false;
        final target = _awaitingDeletion;
        if (target != null &&
            !memory.intents.any(
              (intent) =>
                  intent.episodes.any((episode) => episode.caseId == target) ||
                  intent.offLines.any((line) => line.caseId == target) ||
                  intent.changed.any((change) => change.caseId == target),
            )) {
          _message = '선택한 기억을 삭제했어요.';
          _awaitingDeletion = null;
        } else if (target != null) {
          _message = '선택한 기억의 삭제를 확인하는 중이에요.';
        } else {
          _message = null;
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _message = _awaitingDeletion == null
              ? '우리 집 기억을 불러오지 못했어요.'
              : '서버에서 삭제 결과를 확인하지 못했어요.';
          _busy = false;
        });
      }
    }
  }

  Future<void> _delete(String caseId) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('선택한 기억을 삭제할까요?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('삭제'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted || _busy) return;
    setState(() {
      _busy = true;
      _message = '삭제 결과 확인 중…';
    });
    try {
      await widget.app.deleteCase(caseId);
      _awaitingDeletion = caseId;
      await _refresh();
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _message = '선택한 기억을 삭제하지 못했어요.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('우리 집 기억')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        PeerLabel(widget.app.fixture),
        if (_message case final message?) StatusMessage(message),
        if (_busy)
          const LinearProgressIndicator(semanticsLabel: '우리 집 기억 확인 중'),
        if (!_busy && (_memory == null || _awaitingDeletion != null))
          OutlinedButton(
            onPressed: () {
              setState(() => _busy = true);
              _refresh();
            },
            child: const Text('새로고침'),
          ),
        if (_memory?.intents.isEmpty ?? false) const Text('저장된 기억이 없어요.'),
        for (final intent in _memory?.intents ?? const <wire.Intent>[]) ...[
          const SizedBox(height: 16),
          Text(intent.name, style: Theme.of(context).textTheme.titleLarge),
          if (intent.calendarTags.isNotEmpty)
            Text(intent.calendarTags.join(' · ')),
          if (intent.habitTime case final time?)
            Text('${time.weekday}요일 ${time.time}'),
          for (final episode in intent.episodes) ...[
            const Divider(),
            Text(
              '${episode.date} · ${switch (episode.verdict) {
                wire.Verdict.MATCH => '상황 일치',
                wire.Verdict.STOPPED => '중지됨',
                wire.Verdict.UNCONFIRMED => '확인되지 않음',
              }}',
            ),
            for (final line in intent.offLines.where(
              (line) => line.caseId == episode.caseId,
            ))
              Text('${line.line} · ${line.until}까지 꺼짐'),
            for (final change in intent.changed.where(
              (change) => change.caseId == episode.caseId,
            ))
              Text('${deviceLabel(change.deviceType)} · ${change.change}'),
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton(
                onPressed: _busy || _awaitingDeletion != null
                    ? null
                    : () => _delete(episode.caseId),
                child: Text(
                  '이 기억 삭제',
                  semanticsLabel: '${intent.name} ${episode.date} 기억 삭제',
                ),
              ),
            ),
          ],
        ],
      ],
    ),
  );
}
