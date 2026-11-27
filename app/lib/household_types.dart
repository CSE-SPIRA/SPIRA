typedef HouseholdAxis = ({bool pickOne, List<String> types});

class HouseholdTypeCatalog {
  HouseholdTypeCatalog.fromJson(Map<String, dynamic> json)
    : axes = (json['axes'] as Map<String, dynamic>).map((name, value) {
        final axis = value as Map<String, dynamic>;
        return MapEntry(name, (
          pickOne: axis['pick'] == 'one',
          types: (axis['types'] as List<dynamic>).cast<String>(),
        ));
      }),
      _childTypes = (json['child_types'] as List<dynamic>).cast<String>(),
      _sizeMax = (json['size_max'] as Map<String, dynamic>)
          .cast<String, int?>();

  static const asset = 'assets/household-types.json';

  final Map<String, HouseholdAxis> axes;
  final List<String> _childTypes;
  final Map<String, int?> _sizeMax;

  String? blockedReason(Set<String> types) {
    final size = axes['size']!.types.where(types.contains).firstOrNull;
    final cap = _sizeMax[size];
    final children = _childTypes.where(types.contains).length;
    final couple = types.contains('부부·커플');
    final adultChild = types.contains('부모 + 성인 자녀');
    final threeGenerations = types.contains('3대 함께');
    final dualIncome = types.contains('맞벌이');
    final minimum = (couple ? 2 : 1) + children + (adultChild ? 1 : 0);
    if (cap != null && (minimum > cap || (threeGenerations && cap < 3))) {
      return '선택한 가구 구성에 맞게 인원을 늘려 주세요.';
    }
    if (types.contains('룸메이트·셰어하우스') &&
        (couple || children > 0 || adultChild || threeGenerations)) {
      return '룸메이트·셰어하우스는 가족 구성과 함께 고를 수 없어요.';
    }
    if (dualIncome && !couple) {
      return '맞벌이는 부부·커플과 함께 골라 주세요.';
    }
    if (types.contains('은퇴·노년') && (dualIncome || types.contains('재택근무'))) {
      return '은퇴·노년은 맞벌이 또는 재택근무와 함께 고를 수 없어요.';
    }
    return null;
  }
}
