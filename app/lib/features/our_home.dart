// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../design_tokens.g.dart';
import '../korean_text.dart';
import 'sample_devices.dart';
import 'setup.dart';
import 'status_badge.dart';

class OurHome extends StatelessWidget {
  const OurHome(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(
      DesignTokens.space20,
      DesignTokens.space12,
      DesignTokens.space20,
      DesignTokens.space32,
    ),
    children: [
      KoreanText('기기', style: Theme.of(context).textTheme.headlineMedium),
      const SizedBox(height: DesignTokens.space8),
      if (!app.hasDelegationRoute) const DeviceDelegationHint(),
      for (final error in app.controlErrors.values.toSet())
        StatusMessage(error),
      SampleDevices(showDelegation: app.hasDelegationRoute, app: app),
      const Divider(height: DesignTokens.space32),
      HouseholdTypesForm(
        app,
        title: '가구 유형',
        button: '가구 유형 저장',
        onSave: app.updateHousehold,
      ),
      const Divider(height: 36),
      KoreanText('Google 캘린더', style: Theme.of(context).textTheme.titleLarge),
      ListTile(
        contentPadding: EdgeInsets.zero,
        title: KoreanText(app.calendarConnected ? '연결됨' : '연결 안 됨'),
        trailing: TextButton(
          onPressed: app.busy || app.readCalendar == null
              ? null
              : app.calendarConnected
              ? app.disconnectGoogle
              : app.connectGoogle,
          child: KoreanText(
            app.calendarConnected ? 'Google 연결 해제' : 'Google 연결',
          ),
        ),
      ),
      if (app.calendarError case final error?) StatusMessage(error),
    ],
  );
}
