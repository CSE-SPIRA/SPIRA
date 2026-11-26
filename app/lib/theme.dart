// ignore: deprecated_member_use
import 'package:flutter/material.dart';

import 'design_tokens.g.dart';

const appPaper = DesignTokens.paper;
const appGreen = DesignTokens.green;
const appPinkOnGreen = DesignTokens.pinkOnGreen;
const appEase = DesignTokens.ease;
const appSettle = DesignTokens.settle;
const appCardRadius = DesignTokens.radius16;

ThemeData buildAppTheme({bool reduceMotion = false}) {
  final colors = ColorScheme.fromSeed(
    seedColor: appGreen,
    primary: DesignTokens.greenDeep,
    onPrimary: DesignTokens.surface,
    primaryContainer: DesignTokens.greenSoft,
    onPrimaryContainer: DesignTokens.greenDeep,
    secondary: DesignTokens.pinkInk,
    secondaryContainer: DesignTokens.pinkSoft,
    onSecondaryContainer: DesignTokens.pinkInk,
    surface: DesignTokens.surface,
    onSurface: DesignTokens.ink,
    surfaceContainerHighest: DesignTokens.soft,
    onSurfaceVariant: DesignTokens.muted,
    outline: DesignTokens.greenLine,
    outlineVariant: DesignTokens.line,
  );
  return ThemeData(
    colorScheme: colors,
    pageTransitionsTheme: reduceMotion
        ? PageTransitionsTheme(
            builders: {
              for (final platform in TargetPlatform.values)
                platform: const _NoMotionPageTransitions(),
            },
          )
        : const PageTransitionsTheme(),
    scaffoldBackgroundColor: appPaper,
    appBarTheme: const AppBarThemeData(
      backgroundColor: appPaper,
      foregroundColor: DesignTokens.greenDeep,
      surfaceTintColor: Colors.transparent,
    ),
    cardTheme: const CardThemeData(color: DesignTokens.surface, elevation: 0),
    inputDecorationTheme: const InputDecorationTheme(
      border: OutlineInputBorder(),
    ),
    fontFamily: 'packages/spira_fonts/${DesignTokens.font}',
    fontFamilyFallback: const [
      'Apple SD Gothic Neo',
      'Malgun Gothic',
      'Noto Sans CJK KR',
      'sans-serif',
    ],
    textTheme: const TextTheme(
      headlineMedium: TextStyle(
        fontSize: DesignTokens.size27,
        fontWeight: FontWeight.w700,
        height: 1.12,
      ),
      titleLarge: TextStyle(
        fontSize: DesignTokens.size22,
        fontWeight: FontWeight.w700,
        height: 1.28,
      ),
      titleMedium: TextStyle(
        fontSize: DesignTokens.size16,
        fontWeight: FontWeight.w600,
        height: 1.26,
      ),
      bodyMedium: TextStyle(fontSize: DesignTokens.size15, height: 1.45),
      bodySmall: TextStyle(fontSize: DesignTokens.size13, height: 1.35),
    ),
  );
}

class _NoMotionPageTransitions extends PageTransitionsBuilder {
  const _NoMotionPageTransitions();

  @override
  Duration get transitionDuration => Duration.zero;

  @override
  Duration get reverseTransitionDuration => Duration.zero;

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) => child;
}
