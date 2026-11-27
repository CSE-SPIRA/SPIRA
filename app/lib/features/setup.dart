import 'dart:convert';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_controller.dart';
import '../design_tokens.g.dart';
import '../household_types.dart';
import '../korean_text.dart';
import 'brand.dart';
import 'sample_devices.dart';
import 'status_badge.dart';

class SetupScreen extends StatelessWidget {
  const SetupScreen(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) {
    if (app.step == SetupStep.welcome) return _welcome(context);
    if (app.step == SetupStep.devices) return _devices(context);
    return ListView(
      key: ValueKey(app.step),
      padding: const EdgeInsets.fromLTRB(
        DesignTokens.space20,
        DesignTokens.space16,
        DesignTokens.space20,
        DesignTokens.space32,
      ),
      children: [
        _progress(context),
        const SizedBox(height: DesignTokens.space12),
        if (app.setupError case final error?
            when app.step != SetupStep.household)
          StatusMessage(error),
        switch (app.step) {
          SetupStep.calendar => _calendar(context),
          SetupStep.household => HouseholdTypesForm(
            app,
            title: '가구 유형',
            button: '우리 집 만들기',
            onSave: app.submitHousehold,
            validateCombinations: true,
          ),
          SetupStep.connection => _connection(context),
          _ => const SizedBox.shrink(),
        },
      ],
    );
  }

  Widget _welcome(BuildContext context) => CustomScrollView(
    slivers: [
      SliverPadding(
        padding: const EdgeInsets.all(DesignTokens.space20),
        sliver: SliverFillRemaining(
          hasScrollBody: false,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            spacing: DesignTokens.space24,
            children: [
              const Center(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: SpiraMark(large: true),
                ),
              ),
              KoreanText(
                '온라인 주문을 보고, 그날에 맞춰 집을 미리 준비해요.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleLarge,
              ),
              if (app.setupError case final error?) StatusMessage(error),
              FilledButton(
                onPressed: app.busy ? null : app.startSetup,
                child: const KoreanText('시작하기'),
              ),
            ],
          ),
        ),
      ),
    ],
  );

  Widget _progress(BuildContext context) {
    final current = app.step.index;
    final total = SetupStep.devices.index;
    return KoreanText(
      '$current / $total',
      semanticsLabel: '전체 $total단계 중 $current단계',
      style: Theme.of(context).textTheme.bodySmall
          ?.copyWith(color: DesignTokens.green),
    );
  }

  Widget _calendar(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    spacing: DesignTokens.space12,
    children: [
      KoreanText(
        app.readCalendar == null ? 'Google 캘린더' : 'Google 계정으로 시작',
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      if (app.readCalendar != null) ...[
        const KoreanText('앞으로 14일의 일정을 참고해 준비할게요.'),
        if (app.calendarError case final error?) StatusMessage(error),
        FilledButton(
          onPressed: app.busy ? null : () => app.finishCalendar(connect: true),
          child: const KoreanText('Google로 계속'),
        ),
        TextButton(
          onPressed: app.busy ? null : () => app.finishCalendar(connect: false),
          child: const KoreanText('건너뛰기'),
        ),
      ] else ...[
        const KoreanText('Google 연결 없이 시작할 수 있어요.'),
        FilledButton(
          onPressed: app.busy ? null : () => app.finishCalendar(connect: false),
          child: const KoreanText('건너뛰기'),
        ),
      ],
    ],
  );

  Widget _connection(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    spacing: 12,
    children: [
      KoreanText(
        '집 허브 연결 코드',
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      const KoreanText('이 코드를 집 허브에 입력하세요'),
      if (app.connectionCode case final code?) ...[
        DecoratedBox(
          decoration: BoxDecoration(
            color: DesignTokens.greenSoft,
            borderRadius: BorderRadius.circular(DesignTokens.radius12),
          ),
          child: Padding(
            padding: const EdgeInsets.all(DesignTokens.space16),
            child: SelectableText(
              code,
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
        ),
        OutlinedButton.icon(
          icon: const Icon(Icons.copy_rounded),
          label: const KoreanText('연결 코드 복사'),
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: code));
            if (!context.mounted) return;
            ScaffoldMessenger.of(
              context,
            ).showSnackBar(const SnackBar(content: KoreanText('연결 코드를 복사했어요')));
          },
        ),
      ],
      FilledButton(
        onPressed: app.busy ? null : app.completeConnection,
        child: const KoreanText('다음'),
      ),
    ],
  );

  Widget _devices(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Expanded(
        child: ListView(
          padding: const EdgeInsets.all(DesignTokens.space20),
          children: [
            _progress(context),
            const SizedBox(height: DesignTokens.space12),
            KoreanText(
              '집 기기 확인',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: DesignTokens.space8),
            if (!app.hasDelegationRoute) const DeviceDelegationHint(),
            SampleDevices(showDelegation: app.hasDelegationRoute),
            if (app.setupError case final error?) StatusMessage(error),
          ],
        ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(
          DesignTokens.space20,
          DesignTokens.space8,
          DesignTokens.space20,
          DesignTokens.space16,
        ),
        child: FilledButton(
          onPressed: app.busy ? null : app.finishDevices,
          child: const KoreanText('저장'),
        ),
      ),
    ],
  );
}

class HouseholdTypesForm extends StatefulWidget {
  const HouseholdTypesForm(
    this.app, {
    super.key,
    required this.title,
    required this.button,
    required this.onSave,
    this.validateCombinations = false,
  });

  final AppController app;
  final String title;
  final String button;
  final Future<void> Function(Set<String>) onSave;
  final bool validateCombinations;

  @override
  State<HouseholdTypesForm> createState() => _HouseholdTypesFormState();
}

class _HouseholdTypesFormState extends State<HouseholdTypesForm> {
  static const _axisLabels = {
    'size': '인원',
    'composition': '구성',
    'life_stage': '생활 단계',
    'work_style': '근무 형태',
    'pets': '반려동물',
  };

  late final _catalog = _readCatalog(DefaultAssetBundle.of(context));
  late final Set<String> _types = {...widget.app.householdTypes};
  String? _error;

  Future<HouseholdTypeCatalog> _readCatalog(AssetBundle bundle) async =>
      HouseholdTypeCatalog.fromJson(
        jsonDecode(await bundle.loadString(HouseholdTypeCatalog.asset))
            as Map<String, dynamic>,
      );

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      KoreanText(
        widget.title,
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      FutureBuilder(
        future: _catalog,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return const StatusMessage('가구 유형을 불러오지 못했어요.');
          }
          if (snapshot.data case final catalog?) return _form(context, catalog);
          return const Center(child: CircularProgressIndicator());
        },
      ),
    ],
  );

  Widget _form(BuildContext context, HouseholdTypeCatalog catalog) {
    final app = widget.app;
    final theme = Theme.of(context);
    final blockedReason = widget.validateCombinations
        ? catalog.blockedReason(_types)
        : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final axis in catalog.axes.entries) ...[
          const SizedBox(height: 14),
          KoreanText(
            _axisLabels[axis.key]!,
            style: theme.textTheme.titleMedium,
          ),
          Wrap(
            spacing: DesignTokens.space8,
            runSpacing: DesignTokens.space4,
            children: [
              for (final type in axis.value.types)
                FilterChip(
                  label: KoreanText(type),
                  selected: _types.contains(type),
                  showCheckmark: false,
                  selectedColor: DesignTokens.greenSoft,
                  side: _types.contains(type)
                      ? const BorderSide(color: DesignTokens.greenLine)
                      : null,
                  labelStyle: _types.contains(type)
                      ? const TextStyle(color: DesignTokens.greenDeep)
                      : null,
                  onSelected: app.busy
                      ? null
                      : (selected) => setState(() {
                          _error = null;
                          if (selected) {
                            if (axis.value.pickOne) {
                              _types.removeAll(axis.value.types);
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
        const SizedBox(height: 10),
        if (blockedReason ?? _error case final error?) StatusMessage(error),
        FilledButton(
          onPressed: app.busy || _types.isEmpty || blockedReason != null
              ? null
              : () async {
                  await widget.onSave({..._types});
                  if (mounted) setState(() => _error = app.setupError);
                },
          child: KoreanText(widget.button),
        ),
      ],
    );
  }
}
