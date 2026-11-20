import 'dart:async';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api/app_api.dart';
import 'app_controller.dart';
import 'features/our_home.dart';
import 'features/preparations.dart';
import 'features/settings.dart';
import 'features/setup.dart';
import 'platform/android_bridge.dart';
import 'platform/app_store.dart';
import 'platform/google_calendar.dart';
import 'platform/home_hub_onboarding.dart';

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
          body: SafeArea(
            child: Center(child: Text('연결할 수 없어요. 앱 설정을 확인해 주세요.')),
          ),
        ),
      ),
    );
    return;
  }
  const calendarClientId = String.fromEnvironment('SPIRA_GOOGLE_CLIENT_ID');
  const household = String.fromEnvironment('SPIRA_HOUSEHOLD_ID');
  const hubUrl = String.fromEnvironment('SPIRA_HUB_URL');
  final store = PreferencesAppStore();
  final reader = calendarClientId.isEmpty
      ? null
      : GoogleCalendarReader(calendarClientId).call;
  runApp(
    SpiraApp(
      app: AppController(
        api: AppApi(baseUrl),
        platform: AndroidBridge(),
        store: store,
        homeHub: hubUrl.isEmpty
            ? LocalHomeHubOnboarding(store)
            : HttpHomeHubOnboarding(hubUrl),
        fixture:
            const String.fromEnvironment(
              'SPIRA_PEER',
              defaultValue: 'fixture',
            ) !=
            'server',
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
    final theme = ThemeData(
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF1D634D),
        surface: const Color(0xFFF7F8F3),
      ),
      scaffoldBackgroundColor: const Color(0xFFF7F8F3),
      cardTheme: const CardThemeData(color: Colors.white, elevation: 0),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
      ),
    );
    return MaterialApp(
      title: 'SPIRA',
      theme: theme,
      locale: const Locale('ko'),
      supportedLocales: const [Locale('ko')],
      // ignore: deprecated_member_use
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: ScaffoldMessenger(child: _Home(app)),
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

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: app,
    builder: (context, _) => Scaffold(
      appBar: AppBar(
        title: const Text('SPIRA'),
        actions: [
          if (!app.starting && app.step == SetupStep.ready)
            TextButton(
              onPressed: () => Navigator.push<void>(
                context,
                MaterialPageRoute(builder: (_) => OurHomeScreen(app)),
              ),
              child: const Text('우리 집'),
            ),
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
