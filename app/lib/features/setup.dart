// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../app_controller.dart';
import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'sample_devices.dart';
import 'status_badge.dart';

class SetupScreen extends StatelessWidget {
  const SetupScreen(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) {
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
          ),
          SetupStep.connection => _connection(context),
          _ => const SizedBox.shrink(),
        },
      ],
    );
  }

  Widget _calendar(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    spacing: 12,
    children: [
      KoreanText(
        'Google 캘린더',
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      const KoreanText('앞으로 14일의 일정을 참고해 준비할게요.'),
      FilledButton(
        onPressed: app.busy || app.readCalendar == null
            ? null
            : () => app.finishCalendar(connect: true),
        child: const KoreanText('Google 캘린더 연결'),
      ),
      TextButton(
        onPressed: app.busy ? null : () => app.finishCalendar(connect: false),
        child: const KoreanText('건너뛰기'),
      ),
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
            KoreanText(
              '집 기기 확인',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: DesignTokens.space8),
            const SampleDevices(),
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
  });

  final AppController app;
  final String title;
  final String button;
  final Future<void> Function(Set<String>) onSave;

  @override
  State<HouseholdTypesForm> createState() => _HouseholdTypesFormState();
}

class _HouseholdTypesFormState extends State<HouseholdTypesForm> {
  static const _groups = {
    '인원': ['1인', '2인', '3~4인', '5인 이상'],
    '구성': [
      '부부·커플',
      '영유아 자녀',
      '초등 자녀',
      '중학생 자녀',
      '고등학생 자녀',
      '부모 + 성인 자녀',
      '3대 함께',
      '룸메이트·셰어하우스',
    ],
    '생활 단계': ['대학생', '직장인', '은퇴·노년'],
    '근무 형태': ['맞벌이', '재택근무'],
    '반려동물': ['반려견', '반려묘', '그 밖의 반려동물'],
  };
  static const _singleChoice = {'인원', '생활 단계'};

  late final Set<String> _types = {...widget.app.householdTypes};
  String? _error;

  @override
  Widget build(BuildContext context) {
    final app = widget.app;
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        KoreanText(widget.title, style: theme.textTheme.headlineMedium),
        for (final group in _groups.entries) ...[
          const SizedBox(height: 14),
          KoreanText(group.key, style: theme.textTheme.titleMedium),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              for (final type in group.value)
                FilterChip(
                  label: KoreanText(type),
                  selected: _types.contains(type),
                  onSelected: app.busy
                      ? null
                      : (selected) => setState(() {
                          _error = null;
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
        const SizedBox(height: 10),
        if (_error case final error?) StatusMessage(error),
        FilledButton(
          onPressed: app.busy || _types.isEmpty
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
