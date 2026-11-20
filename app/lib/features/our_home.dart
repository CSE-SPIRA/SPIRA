// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../contracts.dart' as wire;
import '../platform/home_hub_onboarding.dart';
import 'device_setup.dart';
import 'labels.dart';
import 'settings.dart';
import 'setup.dart';

class OurHomeScreen extends StatefulWidget {
  const OurHomeScreen(this.app, {super.key});

  final AppController app;

  @override
  State<OurHomeScreen> createState() => _OurHomeScreenState();
}

class _OurHomeScreenState extends State<OurHomeScreen> {
  AppController get app => widget.app;

  @override
  void initState() {
    super.initState();
    app.openHome();
  }

  @override
  void dispose() {
    app.closeHome();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) {
      final rooms = <String?, List<HomeDevice>>{};
      for (final device in app.home.devices) {
        final saved = app.home.settings[device.id];
        final room = (saved == null ? device.room : saved.room)?.trim();
        rooms
            .putIfAbsent(room == null || room.isEmpty ? null : room, () => [])
            .add(device);
      }
      final preparations = app.devicePreparations;
      return Scaffold(
        appBar: AppBar(title: const Text('우리 집')),
        body: RefreshIndicator(
          onRefresh: () async {
            await Future.wait([
              app.sync(),
              if (app.hasHomeHub) app.refreshHome(),
            ]);
          },
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(20),
            children: [
              PeerLabel(app.fixture),
              HomeDiscoveryStatus(app),
              if (app.stale) const StatusMessage('마지막으로 확인한 준비 상태예요.'),
              if (rooms.isEmpty &&
                  !app.homeLoading &&
                  app.homeReadError == null)
                const Text('찾은 기기가 없어요.'),
              for (final entry in rooms.entries) ...[
                const SizedBox(height: 14),
                Text(
                  entry.key ?? '방을 골라 주세요',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                for (final device in entry.value)
                  _DeviceCard(
                    app: app,
                    device: device,
                    preparations: preparations[device.id] ?? const [],
                  ),
              ],
            ],
          ),
        ),
      );
    },
  );
}

class _DeviceCard extends StatelessWidget {
  const _DeviceCard({
    required this.app,
    required this.device,
    required this.preparations,
  });

  final AppController app;
  final HomeDevice device;
  final List<DevicePreparation> preparations;

  @override
  Widget build(BuildContext context) {
    final saved = app.home.settings[device.id];
    final delegated = app.savedDelegation(device);
    final available = device.selectableCommands;
    final holdings = [
      for (final preparation in preparations)
        if (_holdingLabel(preparation.line) case final status?)
          (preparation, status),
    ];
    return Card(
      child: InkWell(
        onTap: app.homeLoading || app.homeReadError != null
            ? null
            : () async {
                final result = await Navigator.push<HomeSaveResult>(
                  context,
                  MaterialPageRoute(
                    builder: (_) => _HomeDeviceEditor(app, device),
                  ),
                );
                if (result != null && app.hasHomeHub && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text(homeSaveLabel(result))),
                  );
                }
              },
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      DeviceDraft.savedName(device, saved),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                  const Icon(Icons.chevron_right),
                ],
              ),
              Text(homeDeviceDescription(device)),
              if (saved?.roomConfirmed != true &&
                  (device.room?.trim().isNotEmpty ?? false))
                const Text('찾은 방이에요. 맞는지 확인해 주세요.'),
              if (delegated == null)
                const Text('아직 맡길 일을 고르지 않았어요.')
              else ...[
                Text(_actionSummary('맡긴 일', delegated)),
                Text(
                  _actionSummary('맡기지 않은 일', available.difference(delegated)),
                ),
              ],
              for (final command in device.never.toSet())
                Text('${commandLabel(command)} · 하지 않아요'),
              const SizedBox(height: 8),
              Text('지금 준비 상태', style: Theme.of(context).textTheme.titleSmall),
              if (holdings.any((holding) => holding.$1.sharedLine))
                const Text('여러 기기가 함께 쓰인 준비는 전체 준비 상태를 보여 드려요.'),
              if (holdings.isEmpty)
                const Text('지금 확인된 준비 상태가 없어요.')
              else
                for (final (preparation, status) in holdings) ...[
                  Text('$status · ${preparation.line.text}'),
                  Text(preparation.card.text),
                ],
            ],
          ),
        ),
      ),
    );
  }
}

String _actionSummary(String title, Set<String> commands) =>
    "$title · ${commands.isEmpty ? '없어요' : commands.map(commandLabel).join(', ')}";

String? _holdingLabel(wire.LineElement line) => switch (line.endState) {
  wire.EndState.WITHHELD => '안전 설정을 그대로 두었어요',
  wire.EndState.KEPT_USER_CHANGE => '사람이 바꿈 · 그대로 둬요',
  wire.EndState.RESTORE_FAILED => '이전 상태로 돌아갔는지 확인하지 못했어요',
  wire.EndState.RESTORED || wire.EndState.NONE => null,
  null => switch (line.state) {
    wire.LineState.RUNNING ||
    wire.LineState.DONE ||
    wire.LineState.PARTIAL => lineLabel(line.state),
    wire.LineState.USER_CHANGED => '사람이 바꿈 · 그대로 둬요',
    _ => null,
  },
};

class _HomeDeviceEditor extends StatefulWidget {
  const _HomeDeviceEditor(this.app, this.device);

  final AppController app;
  final HomeDevice device;

  @override
  State<_HomeDeviceEditor> createState() => _HomeDeviceEditorState();
}

class _HomeDeviceEditorState extends State<_HomeDeviceEditor> {
  AppController get app => widget.app;
  HomeDevice get device => widget.device;
  late final _draft = DeviceDraft(
    device,
    saved: app.home.settings[device.id],
    delegated: app.savedDelegation(device),
  );
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _draft.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final result = await app.editHomeDevice(device.id, _draft.settings);
      if (mounted) Navigator.pop(context, result);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = app.homeSettingsError(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) {
      final preparations = app.devicePreparations[device.id] ?? const [];
      return PopScope(
        canPop: !_saving,
        child: Scaffold(
          appBar: AppBar(
            title: Text(
              DeviceDraft.savedName(device, app.home.settings[device.id]),
            ),
          ),
          body: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              PeerLabel(app.fixture),
              if (!app.hasHomeHub) const StatusMessage(homeHubPending),
              DeviceFields(
                _draft,
                reviewed: app.home.settings[device.id]?.roomConfirmed ?? false,
                enabled: !_saving,
                onChanged: () => setState(() {}),
              ),
              const SizedBox(height: 18),
              Text(
                'SPIRA에게 맡길 일',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              DelegationChoices(_draft, enabled: !_saving),
              if (_error case final error?) StatusMessage(error),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? '저장 중…' : '변경사항 저장'),
              ),
              const SizedBox(height: 20),
              Text(
                '이 기기와 관련된 준비',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              if (app.stale) const StatusMessage('마지막으로 확인한 준비 상태예요.'),
              if (preparations.isEmpty)
                const Text('이 기기와 관련된 준비를 아직 확인하지 못했어요.'),
              if (preparations.any((preparation) => preparation.sharedLine))
                const Text('여러 기기가 함께 쓰인 준비는 전체 준비 상태를 보여 드려요.'),
              for (final preparation in preparations)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(preparation.line.text),
                  subtitle: Text(
                    [
                      preparation.card.text,
                      lineLabel(preparation.line.state),
                      if (preparation.line.endState case final end?)
                        endLabel(end),
                      if (preparation.line.note case final note?) note,
                    ].join('\n'),
                  ),
                ),
            ],
          ),
        ),
      );
    },
  );
}
