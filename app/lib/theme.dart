// ignore: deprecated_member_use
import 'package:flutter/material.dart';

ThemeData buildAppTheme() {
  const paper = Color(0xFFF6F5EE);
  const surface = Color(0xFFFFFEFA);
  const ink = Color(0xFF192E28);
  const green = Color(0xFF265446);
  const deepGreen = Color(0xFF1E4036);
  const greenSoft = Color(0xFFE4EDE3);
  const pinkInk = Color(0xFF783C5A);
  const pinkSoft = Color(0xFFF5E2EB);
  final colors = ColorScheme.fromSeed(
    seedColor: green,
    primary: deepGreen,
    onPrimary: surface,
    primaryContainer: greenSoft,
    onPrimaryContainer: deepGreen,
    secondary: pinkInk,
    secondaryContainer: pinkSoft,
    onSecondaryContainer: pinkInk,
    surface: surface,
    onSurface: ink,
    surfaceContainerHighest: const Color(0xFFEDEEE5),
    onSurfaceVariant: const Color(0xFF51665C),
    outline: const Color(0xFF8BAA99),
    outlineVariant: const Color(0xFFD4DBCF),
  );
  return ThemeData(
    colorScheme: colors,
    scaffoldBackgroundColor: paper,
    appBarTheme: const AppBarThemeData(
      backgroundColor: paper,
      foregroundColor: deepGreen,
    ),
    cardTheme: const CardThemeData(color: surface, elevation: 0),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
    fontFamily: 'IBM Plex Sans KR',
    fontFamilyFallback: const [
      'Apple SD Gothic Neo',
      'Malgun Gothic',
      'Noto Sans CJK KR',
      'sans-serif',
    ],
    textTheme: const TextTheme(
      titleLarge: TextStyle(
        fontSize: 21,
        fontWeight: FontWeight.w700,
        height: 1.3,
      ),
      titleMedium: TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.w600,
        height: 1.35,
      ),
      bodyMedium: TextStyle(fontSize: 14, height: 1.5),
      bodySmall: TextStyle(fontSize: 13, height: 1.4),
    ),
  );
}
