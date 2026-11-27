import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

/// The Grafikomat look in the app: the same colours and sizes as the website (`frontend/src/styles/tokens.css`,
/// accepted by Piotr on 12.11.2026). Text uses the phone's own font, as native apps do. Availability states are told
/// apart by colour, icon AND pattern, never by colour alone.
abstract final class AppColors {
  static const paper = Color(0xFFF3F5F1);
  static const surface = Color(0xFFFFFFFF);
  static const ink = Color(0xFF17212F);
  static const inkMuted = Color(0xFF4A5566);
  static const line = Color(0xFFCDD3DA);
  static const grid = Color(0xFFE1E6EA);
  static const accent = Color(0xFF1E44B8);
  static const accentStrong = Color(0xFF163590);
  static const accentInk = Color(0xFFFFFFFF);
  static const accentSoft = Color(0xFFE5EBFA);
  static const cannot = Color(0xFFB3261E);
  static const cannotSoft = Color(0xFFFCE9E7);
  static const preferNot = Color(0xFF7A5300);
  static const preferNotSoft = Color(0xFFFFF1CC);
  static const prefer = Color(0xFF12663F);
  static const preferSoft = Color(0xFFDFF2E6);
  static const preferFill = Color(0xFFB4E0C4);
  static const can = Color(0xFF2F7D55);
  static const canLine = Color(0xFF9FCFB3);
  static const canSoft = Color(0xFFEDF8F0);
}

/// Every control is at least [touch] tall, the main action of a screen [touchMain].
const double touch = 44;
const double touchMain = 48;

/// Side margin of every screen.
const double gutter = 16;

abstract final class AppRadius {
  static const sm = 8.0;
  static const md = 10.0;
  static const lg = 14.0;
}

ThemeData appTheme() {
  const scheme = ColorScheme(
    brightness: Brightness.light,
    primary: AppColors.accent,
    onPrimary: AppColors.accentInk,
    primaryContainer: AppColors.accentSoft,
    onPrimaryContainer: AppColors.accentStrong,
    secondary: AppColors.accent,
    onSecondary: AppColors.accentInk,
    secondaryContainer: AppColors.accentSoft,
    onSecondaryContainer: AppColors.ink,
    error: AppColors.cannot,
    onError: AppColors.accentInk,
    errorContainer: AppColors.cannotSoft,
    onErrorContainer: AppColors.cannot,
    surface: AppColors.surface,
    onSurface: AppColors.ink,
    onSurfaceVariant: AppColors.inkMuted,
    surfaceContainerLowest: AppColors.surface,
    surfaceContainerLow: AppColors.paper,
    surfaceContainer: AppColors.paper,
    surfaceContainerHigh: AppColors.grid,
    outline: AppColors.line,
    outlineVariant: AppColors.grid,
  );
  final base = ThemeData(colorScheme: scheme, useMaterial3: true);
  final text = base.textTheme
      .apply(bodyColor: AppColors.ink, displayColor: AppColors.ink)
      .copyWith(
        headlineSmall: base.textTheme.headlineSmall?.copyWith(fontSize: 26, height: 1.1, fontWeight: FontWeight.w800),
        titleLarge: base.textTheme.titleLarge?.copyWith(fontSize: 21, height: 1.2, fontWeight: FontWeight.w800),
        titleMedium: base.textTheme.titleMedium?.copyWith(fontSize: 18, height: 1.35, fontWeight: FontWeight.w800),
        bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 16, height: 1.45, color: AppColors.ink),
        bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 16, height: 1.45, color: AppColors.ink),
        bodySmall: base.textTheme.bodySmall?.copyWith(fontSize: 14, height: 1.4, color: AppColors.inkMuted),
        labelLarge: base.textTheme.labelLarge?.copyWith(fontSize: 16, fontWeight: FontWeight.w600),
      );
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppRadius.md));
  const buttonSize = Size(64, touchMain);
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.paper,
    textTheme: text,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.paper,
      foregroundColor: AppColors.ink,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 1,
      systemOverlayStyle: SystemUiOverlayStyle.dark,
      titleTextStyle: TextStyle(fontSize: 21, fontWeight: FontWeight.w800, color: AppColors.ink),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: buttonSize,
        shape: shape,
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: buttonSize,
        shape: shape,
        foregroundColor: AppColors.accent,
        backgroundColor: AppColors.surface,
        side: const BorderSide(color: AppColors.accent, width: 2),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize: const Size(48, touch),
        shape: shape,
        foregroundColor: AppColors.accent,
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, decoration: TextDecoration.underline),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        borderSide: const BorderSide(color: AppColors.line),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        borderSide: const BorderSide(color: AppColors.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.sm),
        borderSide: const BorderSide(color: AppColors.accent, width: 2),
      ),
      hintStyle: const TextStyle(color: AppColors.inkMuted),
      helperMaxLines: 3,
      errorMaxLines: 3,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AppColors.surface,
      indicatorColor: AppColors.accentSoft,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w600,
          color: states.contains(WidgetState.selected) ? AppColors.accent : AppColors.inkMuted,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 26,
          color: states.contains(WidgetState.selected) ? AppColors.accent : AppColors.inkMuted,
        ),
      ),
    ),
    dividerTheme: const DividerThemeData(color: AppColors.line, space: 1),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: AppColors.accent),
  );
}
