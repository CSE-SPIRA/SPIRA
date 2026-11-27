import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:spira_app/household_types.dart';

void main() {
  final asset = File(HouseholdTypeCatalog.asset).readAsStringSync();
  final catalog = HouseholdTypeCatalog.fromJson(
    jsonDecode(asset) as Map<String, dynamic>,
  );

  test('the bundled catalog is identical to the contract', () {
    expect(
      asset,
      File('../contracts/kb/household_types.json').readAsStringSync(),
    );
  });

  test(
    'minimum size counts couples, children, adult children and generations',
    () {
      const reason = '선택한 가구 구성에 맞게 인원을 늘려 주세요.';
      for (final types in [
        {'1인', '부부·커플'},
        {'1인', '부모 + 성인 자녀'},
        {'2인', '3대 함께'},
        {'2인', '부부·커플', '초등 자녀'},
        {'3~4인', '부부·커플', '영유아 자녀', '중학생 자녀', '고등학생 자녀'},
      ]) {
        expect(catalog.blockedReason(types), reason, reason: '$types');
      }
      expect(catalog.blockedReason({'3~4인', '3대 함께'}), isNull);
      expect(
        catalog.blockedReason({
          '5인 이상',
          '부부·커플',
          '초등 자녀',
          '중학생 자녀',
          '고등학생 자녀',
          '부모 + 성인 자녀',
        }),
        isNull,
      );
    },
  );

  test('roommates cannot be combined with any family composition', () {
    for (final family in catalog.axes['composition']!.types) {
      if (family == '룸메이트·셰어하우스') continue;
      expect(
        catalog.blockedReason({'룸메이트·셰어하우스', family}),
        '룸메이트·셰어하우스는 가족 구성과 함께 고를 수 없어요.',
        reason: family,
      );
    }
    expect(catalog.blockedReason({'2인', '룸메이트·셰어하우스'}), isNull);
  });

  test('dual income requires a couple', () {
    expect(catalog.blockedReason({'맞벌이', '초등 자녀'}), '맞벌이는 부부·커플과 함께 골라 주세요.');
    expect(catalog.blockedReason({'맞벌이', '부부·커플'}), isNull);
  });

  test('retirement blocks dual income and remote work', () {
    for (final work in ['맞벌이', '재택근무']) {
      expect(
        catalog.blockedReason({'은퇴·노년', '부부·커플', work}),
        '은퇴·노년은 맞벌이 또는 재택근무와 함께 고를 수 없어요.',
        reason: work,
      );
    }
    expect(catalog.blockedReason({'은퇴·노년', '맞벌이'}), '맞벌이는 부부·커플과 함께 골라 주세요.');
  });

  test('rare combinations and the demo household are allowed', () {
    final demo = jsonDecode(
      File('../contracts/fixtures/ep_9031/household.create.json')
          .readAsStringSync(),
    ) as Map<String, dynamic>;
    for (final types in [
      (demo['household_types'] as List<dynamic>).cast<String>().toSet(),
      {'대학생', '재택근무'},
      {'은퇴·노년', '영유아 자녀'},
      {'5인 이상', '반려견'},
      {'2인', '재택근무'},
    ]) {
      expect(catalog.blockedReason(types), isNull, reason: '$types');
    }
  });
}
