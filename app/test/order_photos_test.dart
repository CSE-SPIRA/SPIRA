import 'dart:typed_data';

// ignore: deprecated_member_use
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:spira_app/features/order_extraction.dart';

void main() {
  final images = List.generate(3, (index) => Uint8List.fromList([index]));

  Future<void> pump(WidgetTester tester, List<Uint8List> shown) =>
      tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: OrderPhotos(images: shown)),
          ),
        ),
      );

  testWidgets('three photos show the first large with 1/3 and a row to switch', (
    tester,
  ) async {
    await pump(tester, images);

    expect(find.text('1/3'), findsOneWidget);
    expect(find.bySemanticsLabel('사진 2 보기'), findsOneWidget);

    await tester.tap(find.bySemanticsLabel('사진 2 보기'));
    await tester.pump();

    expect(find.text('2/3'), findsOneWidget);
  });

  testWidgets('one photo shows no position and no row', (tester) async {
    await pump(tester, images.sublist(0, 1));

    expect(find.text('1/1'), findsNothing);
    expect(find.bySemanticsLabel('사진 1 보기'), findsNothing);
  });
}
