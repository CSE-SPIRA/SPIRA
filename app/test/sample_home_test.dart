import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('the sample home mirrors the Hub installation inventory', () {
    final installation = jsonDecode(
      File('../hub/installation.example.json').readAsStringSync(),
    ) as Map<String, dynamic>;
    final inventory = installation['devices'] as Map<String, dynamic>;
    final devices = (inventory['devices'] as List<dynamic>)
        .cast<Map<String, dynamic>>();
    final bundled = jsonDecode(
      File('assets/sample-home.json').readAsStringSync(),
    );
    expect(bundled, [
      for (final device in devices)
        {
          for (final field in ['id', 'type', 'room', 'label'])
            if (device.containsKey(field)) field: device[field],
        },
    ]);
  });
}
