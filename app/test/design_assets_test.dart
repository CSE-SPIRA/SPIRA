import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('App design assets are current', () async {
    final result = await Process.run('python3', [
      '../design/build.py',
      '--check',
      '--part',
      'app',
    ]);
    expect(result.exitCode, 0, reason: '${result.stdout}${result.stderr}');
  });
}
