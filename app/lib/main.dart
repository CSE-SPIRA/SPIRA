import 'dart:async';

import 'package:flutter/foundation.dart';
// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api/app_api.dart';
import 'app_controller.dart';
import 'contracts.dart' as wire;
import 'features/labels.dart';
import 'features/our_home.dart';
import 'features/preparations.dart';
import 'features/settings.dart';
import 'features/setup.dart';
import 'korean_text.dart';
import 'platform/android_bridge.dart';
import 'platform/google_calendar.dart';
import 'platform/home_hub_onboarding.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  const rawUrl = String.fromEnvironment('SPIRA_BASE_URL');
  final baseUrl = Uri.tryParse(rawUrl);
  if (baseUrl == null ||
      baseUrl.host.isEmpty ||
      (!baseUrl.isScheme('http') && !baseUrl.isScheme('https')) ||
      baseUrl.userInfo.isNotEmpty ||
      baseUrl.hasQuery ||
      baseUrl.hasFragment) {
    runApp(
      const MaterialApp(
        home: Scaffold(
          body: SafeArea(child: Center(child: KoreanText('서버 주소를 설정해 주세요.'))),
        ),
      ),
    );
    return;
  }
  const discovery = String.fromEnvironment('SPIRA_DISCOVERY_JSON');
  const calendarClientId = String.fromEnvironment('SPIRA_GOOGLE_CLIENT_ID');
  const household = String.fromEnvironment('SPIRA_HOUSEHOLD_ID');
  const hubUrl = String.fromEnvironment('SPIRA_HUB_URL');
  const peer = String.fromEnvironment('SPIRA_PEER', defaultValue: 'fixture');
  final api = AppApi(baseUrl);
  final homeHub = hubUrl.isEmpty ? null : HttpHomeHubOnboarding(hubUrl);
  if (kIsWeb && peer == 'fixture') {
    const demoToken = String.fromEnvironment('SPIRA_FIXTURE_APP_TOKEN');
    const demoHomeKey = String.fromEnvironment('SPIRA_FIXTURE_HOME_KEY');
    if (demoToken.isNotEmpty) api.token = demoToken;
    if (demoHomeKey.isNotEmpty) homeHub?.useApiKey(demoHomeKey);
  }
  wire.Devices? discovered;
  if (discovery.isNotEmpty) {
    try {
      discovered = wire.devicesFromJson(discovery);
    } catch (_) {
      // Setup displays device discovery as unavailable.
    }
  }
  final android = !kIsWeb && defaultTargetPlatform == TargetPlatform.android;
  final reader = !android || calendarClientId.isEmpty
      ? null
      : GoogleCalendarReader(calendarClientId).call;
  runApp(
    SpiraApp(
      app: AppController(
        api: api,
        platform: android ? AndroidBridge() : null,
        store: PreferencesAppStore(),
        homeHub: homeHub,
        browserPreview: kIsWeb,
        fixture: peer != 'server',
        discovered: discovered,
        configuredHousehold: household.isEmpty ? null : household,
        readCalendar: reader,
      ),
    ),
  );
}

class SpiraApp extends StatelessWidget {
  const SpiraApp({required this.app, super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SPIRA',
      theme: buildAppTheme(
        reduceMotion: MediaQuery.disableAnimationsOf(context),
      ),
      locale: const Locale('ko'),
      supportedLocales: const [Locale('ko')],
      // ignore: deprecated_member_use
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: _Home(app),
    );
  }
}

class _Home extends StatefulWidget {
  const _Home(this.app);

  final AppController app;

  @override
  State<_Home> createState() => _HomeState();
}

class _HomeState extends State<_Home> with WidgetsBindingObserver {
  AppController get app => widget.app;
  _HomeTab _tab = _HomeTab.preparations;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(app.start());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // On web, a visible window becomes inactive when another window has focus.
    app.setForeground(
      state == AppLifecycleState.resumed || state == AppLifecycleState.inactive,
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    app.dispose();
    super.dispose();
  }

  Future<void> _token({bool hub = false}) async {
    final token = await showDialog<String>(
      context: context,
      animationStyle: MediaQuery.disableAnimationsOf(context)
          ? AnimationStyle.noAnimation
          : null,
      builder: (_) => _TokenDialog(
        title: hub ? '우리 집 접속 키' : '서버 접속 토큰',
        label: hub ? '접속 키' : '접속 토큰',
      ),
    );
    if (token == null || !mounted) return;
    try {
      await (hub ? app.useHomeKey(token) : app.useToken(token));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: KoreanText('접속 정보를 저장하지 못했어요.')));
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) {
      final ready = !app.starting && app.step == SetupStep.ready;
      final surface = ready ? Theme.of(context).colorScheme.surface : null;
      final lastCheck = app.lastServerCheck;
      return Scaffold(
        backgroundColor: surface,
        appBar: AppBar(
          title: const KoreanText('SPIRA'),
          backgroundColor: surface,
          actions: [
            if (!ready && app.needsToken)
              IconButton(
                tooltip: '서버 접속 토큰 입력',
                onPressed: _token,
                icon: const Icon(Icons.key),
              ),
          ],
        ),
        body: SafeArea(
          bottom: !ready,
          child: app.starting
              ? const Center(
                  child: CircularProgressIndicator(semanticsLabel: '앱 시작 중'),
                )
              : ready
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (app.serverUnavailable)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(20, 0, 20, 4),
                        child: Semantics(
                          liveRegion: true,
                          child: KoreanText(
                            lastCheck == null
                                ? '서버에 연결할 수 없어요'
                                : '서버에 연결할 수 없어요 · 마지막 확인 ${seoulClock(lastCheck)}',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ),
                      ),
                    Expanded(
                      child: Stack(
                        fit: StackFit.expand,
                        children: [
                          // Keep the preparation scroll and extraction alive
                          // while another tab is visible.
                          Offstage(
                            offstage: _tab != _HomeTab.preparations,
                            child: ExcludeFocus(
                              excluding: _tab != _HomeTab.preparations,
                              child: Preparations(app),
                            ),
                          ),
                          if (_tab == _HomeTab.ourHome) OurHome(app),
                          if (_tab == _HomeTab.settings)
                            SettingsScreen(
                              app,
                              onServerToken: _token,
                              onHomeKey: () => _token(hub: true),
                            ),
                        ],
                      ),
                    ),
                  ],
                )
              : SetupScreen(app),
        ),
        bottomNavigationBar: ready
            ? _TabBar(
                key: const ValueKey('home-tabs'),
                selected: _tab,
                onSelect: (tab) => setState(() => _tab = tab),
              )
            : null,
      );
    },
  );
}

enum _HomeTab {
  preparations('준비', Icons.checklist_rounded),
  ourHome('우리 집', Icons.home_outlined),
  settings('설정', Icons.settings_outlined);

  const _HomeTab(this.label, this.icon);

  final String label;
  final IconData icon;
}

class _TabBar extends StatelessWidget {
  const _TabBar({super.key, required this.selected, required this.onSelect});

  final _HomeTab selected;
  final ValueChanged<_HomeTab> onSelect;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    return SafeArea(
      minimum: const EdgeInsets.fromLTRB(20, 4, 20, 12),
      child: Align(
        alignment: Alignment.bottomCenter,
        heightFactor: 1,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 380),
          child: Material(
            color: appPaper,
            elevation: 4,
            shadowColor: colors.primary.withValues(alpha: .22),
            shape: StadiumBorder(
              side: BorderSide(color: colors.outlineVariant),
            ),
            child: Padding(
              padding: const EdgeInsets.all(5),
              child: Row(
                children: [
                  for (final tab in _HomeTab.values)
                    Expanded(
                      child: Semantics(
                        selected: tab == selected,
                        child: TextButton(
                          onPressed: () => onSelect(tab),
                          style: TextButton.styleFrom(
                            minimumSize: const Size(0, 48),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 4,
                              vertical: 4,
                            ),
                            backgroundColor: tab == selected
                                ? colors.primaryContainer
                                : null,
                            foregroundColor: tab == selected
                                ? colors.primary
                                : colors.onSurfaceVariant,
                            textStyle: theme.textTheme.bodySmall?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(tab.icon, size: 20),
                              KoreanText(
                                tab.label,
                                textAlign: TextAlign.center,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _TokenDialog extends StatefulWidget {
  const _TokenDialog({required this.title, required this.label});

  final String title;
  final String label;

  @override
  State<_TokenDialog> createState() => _TokenDialogState();
}

class _TokenDialogState extends State<_TokenDialog> {
  final _text = TextEditingController();

  void _submit(String value) {
    final token = value.trim();
    if (token.isNotEmpty) Navigator.pop(context, token);
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: KoreanText(widget.title),
    content: TextField(
      controller: _text,
      obscureText: true,
      autocorrect: false,
      enableSuggestions: false,
      textInputAction: TextInputAction.done,
      onSubmitted: _submit,
      decoration: InputDecoration(labelText: widget.label),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const KoreanText('취소'),
      ),
      FilledButton(
        onPressed: () => _submit(_text.text),
        child: const KoreanText('연결'),
      ),
    ],
  );
}
