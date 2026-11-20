// ignore: deprecated_member_use
import 'package:flutter/material.dart';

const appPaper = Color(0xFFF6F5EE);
const appGreen = Color(0xFF265446);
const appPinkOnGreen = Color(0xFFF3CADF);
const appEase = Cubic(.22, .73, .23, 1);
const appSettle = Duration(milliseconds: 560);
const appCardRadius = 16.0;

TextSpan highlightTheme(String text, String? phrase, Color color) {
  if (phrase == null || phrase.trim().isEmpty) return TextSpan(text: text);
  final start = text.indexOf(phrase);
  if (start < 0) return TextSpan(text: text);
  final end = start + phrase.length;
  return TextSpan(
    children: [
      TextSpan(text: text.substring(0, start)),
      TextSpan(
        text: phrase,
        style: TextStyle(color: color),
      ),
      TextSpan(text: text.substring(end)),
    ],
  );
}

ThemeData buildAppTheme() {
  const surface = Color(0xFFFFFEFA);
  const ink = Color(0xFF192E28);
  const deepGreen = Color(0xFF1E4036);
  const greenSoft = Color(0xFFE4EDE3);
  const pinkInk = Color(0xFF783C5A);
  const pinkSoft = Color(0xFFF5E2EB);
  final colors = ColorScheme.fromSeed(
    seedColor: appGreen,
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
    scaffoldBackgroundColor: appPaper,
    appBarTheme: const AppBarThemeData(
      backgroundColor: appPaper,
      foregroundColor: deepGreen,
      surfaceTintColor: Colors.transparent,
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
      headlineMedium: TextStyle(
        fontSize: 27,
        fontWeight: FontWeight.w700,
        height: 1.12,
      ),
      titleLarge: TextStyle(
        fontSize: 22,
        fontWeight: FontWeight.w700,
        height: 1.28,
      ),
      titleMedium: TextStyle(
        fontSize: 16,
        fontWeight: FontWeight.w600,
        height: 1.26,
      ),
      bodyMedium: TextStyle(fontSize: 15, height: 1.45),
      bodySmall: TextStyle(fontSize: 13, height: 1.35),
    ),
  );
}
