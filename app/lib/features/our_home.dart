// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import '../app_controller.dart';
import '../korean_text.dart';
import 'setup.dart';

class OurHome extends StatelessWidget {
  const OurHome(this.app, {super.key});

  final AppController app;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.fromLTRB(20, 14, 20, 28),
    children: [
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
      const Divider(height: 36),
      KoreanText('기기', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 5),
      const KoreanText(devicesConnectionText),
    ],
  );
}
