import 'dart:async';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api/app_api.dart';
import 'app_controller.dart';
import 'contracts.dart' as wire;
import 'features/preparations.dart';
import 'features/settings.dart';
import 'features/setup.dart';
import 'platform/android_bridge.dart';
import 'platform/google_calendar.dart';
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
          body: SafeArea(child: Center(child: Text('서버 주소를 설정해 주세요.'))),
        ),
      ),
    );
    return;
  }
  const discovery = String.fromEnvironment('SPIRA_DISCOVERY_JSON');
  const calendarClientId = String.fromEnvironment('SPIRA_GOOGLE_CLIENT_ID');
  const household = String.fromEnvironment('SPIRA_HOUSEHOLD_ID');
  wire.Devices? discovered;
  if (discovery.isNotEmpty) {
    try {
      discovered = wire.devicesFromJson(discovery);
    } catch (_) {
      // Setup displays device discovery as unavailable.
    }
  }
  final reader = calendarClientId.isEmpty
      ? null
      : GoogleCalendarReader(calendarClientId).call;
  runApp(
    SpiraApp(
      app: AppController(
        api: AppApi(baseUrl),
        platform: AndroidBridge(),
        store: PreferencesAppStore(),
        fixture:
            const String.fromEnvironment(
              'SPIRA_PEER',
              defaultValue: 'fixture',
            ) !=
            'server',
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
      theme: buildAppTheme(),
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(app.start());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    app.setForeground(state == AppLifecycleState.resumed);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    app.dispose();
    super.dispose();
  }

  Future<void> _token() async {
    final token = await showDialog<String>(
      context: context,
      builder: (_) => const _TokenDialog(),
    );
    if (token != null && mounted) app.useToken(token);
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const Text('SPIRA'),
        actions: [
          if (app.needsToken)
            IconButton(
              tooltip: '서버 접속 토큰 입력',
              onPressed: _token,
              icon: const Icon(Icons.key),
            ),
          if (app.step == SetupStep.ready)
            IconButton(
              tooltip: '설정',
              icon: const Icon(Icons.settings_outlined),
              onPressed: () => Navigator.push<void>(
                context,
                MaterialPageRoute(builder: (_) => SettingsScreen(app)),
              ),
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: PeerLabel(app.fixture),
            ),
            Expanded(
              child: app.starting
                  ? const Center(
                      child: CircularProgressIndicator(
                        semanticsLabel: '앱 시작 중',
                      ),
                    )
                  : app.step == SetupStep.ready
                  ? Preparations(app)
                  : SetupScreen(app),
            ),
          ],
        ),
      ),
    ),
  );
}

class _TokenDialog extends StatefulWidget {
  const _TokenDialog();

  @override
  State<_TokenDialog> createState() => _TokenDialogState();
}

class _TokenDialogState extends State<_TokenDialog> {
  final _text = TextEditingController();

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('서버 접속 토큰'),
    content: TextField(
      controller: _text,
      obscureText: true,
      autocorrect: false,
      enableSuggestions: false,
      decoration: const InputDecoration(labelText: '접속 토큰'),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('취소'),
      ),
      FilledButton(
        onPressed: () {
          final token = _text.text.trim();
          if (token.isNotEmpty) Navigator.pop(context, token);
        },
        child: const Text('연결'),
      ),
    ],
  );
}
