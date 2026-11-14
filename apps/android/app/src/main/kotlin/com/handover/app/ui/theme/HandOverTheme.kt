package com.handover.app.ui.theme

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode

/** The active roles and spec, for anything Material's ColorScheme does not cover. */
@Immutable
data class HandOverPalette(val roles: ColorRoles, val spec: ThemeSpec, val isDark: Boolean)

val LocalHandOverPalette = staticCompositionLocalOf { HandOverPalette(ThemeCatalog.system.light, ThemeCatalog.system, false) }
val LocalHOType = staticCompositionLocalOf { HOType.Default }

/** True when the system's animator duration scale is 0 (Reduce Motion on Android). */
val LocalReduceMotion = staticCompositionLocalOf { false }

/** Settings, Learn, Haptics. Screens that own that setting provide it; on by default. */
val LocalHapticsEnabled = staticCompositionLocalOf { true }

/** Shorthand: `HandOver.colors.accent`, `HandOver.type.body`. */
object HandOver {
    val colors: ColorRoles @Composable get() = LocalHandOverPalette.current.roles
    val type: HOType @Composable get() = LocalHOType.current
    val spec: ThemeSpec @Composable get() = LocalHandOverPalette.current.spec
    val grain: Boolean @Composable get() = LocalHandOverPalette.current.roles.grain != null
    val isMono: Boolean @Composable get() = ThemeCatalog.isMono(LocalHandOverPalette.current.spec)
    val reduceMotion: Boolean @Composable get() = LocalReduceMotion.current
}

/**
 * Draws [content] in [spec]. [dark] picks the look for themes with two (themes with one look keep
 * it whatever is passed). Dynamic color is off on purpose: the themes are the design.
 */
@Composable
fun HandOverTheme(
    spec: ThemeSpec = ThemeSpec.Default,
    dark: Boolean = isSystemInDarkTheme(),
    reduceMotion: Boolean = rememberReduceMotion(),
    content: @Composable () -> Unit,
) {
    val isDark = spec.isDark(systemDark = dark, appearance = if (dark) Appearance.Dark else Appearance.Light)
    val roles = spec.roles(isDark)
    CompositionLocalProvider(
        LocalHandOverPalette provides HandOverPalette(roles, spec, isDark),
        LocalHOType provides HOType.Default,
        LocalReduceMotion provides reduceMotion,
    ) {
        MaterialTheme(colorScheme = roles.material(), typography = HOType.Default.material(), shapes = HOShapes, content = content)
    }
}

/** The theme the person chose (persisted), in their Appearance setting. The app root uses this. */
@Composable
fun HandOverAppTheme(content: @Composable () -> Unit) {
    val store = rememberThemeStore()
    val choice by store.choice
    val systemDark = isSystemInDarkTheme()
    HandOverTheme(choice.spec, dark = choice.spec.isDark(systemDark, choice.appearance), content = content)
}

/** Watches Settings.Global.ANIMATOR_DURATION_SCALE; 0 means the person turned animations off. */
@Composable
fun rememberReduceMotion(): Boolean {
    if (LocalInspectionMode.current) return false
    val context = LocalContext.current
    val resolver = context.contentResolver
    fun read() = runCatching { Settings.Global.getFloat(resolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false)
    var reduce by remember { mutableStateOf(read()) }
    DisposableEffect(resolver) {
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { reduce = read() }
        }
        runCatching { resolver.registerContentObserver(Settings.Global.getUriFor(Settings.Global.ANIMATOR_DURATION_SCALE), false, observer) }
        onDispose { runCatching { resolver.unregisterContentObserver(observer) } }
    }
    return reduce
}

private val HOShapes = Shapes(
    extraSmall = RoundedCornerShape(HORadius.small),
    small = RoundedCornerShape(HORadius.small),
    medium = RoundedCornerShape(HORadius.control),
    large = RoundedCornerShape(HORadius.card),
    extraLarge = RoundedCornerShape(HORadius.panel),
)

/** Material 3 roles from HandOver roles: DESIGN.md 6.4, copied from vibeflux `DeckColors.material()`. */
fun ColorRoles.material(): ColorScheme {
    val base = if (isDark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = accent, onPrimary = onAccent, primaryContainer = accentSoft, onPrimaryContainer = accentInk,
        secondary = ink2, onSecondary = paper, tertiary = accent,
        background = paper, onBackground = ink, surface = raised, onSurface = ink, surfaceVariant = well,
        onSurfaceVariant = ink2, surfaceContainerLowest = raised, surfaceContainerLow = raised, surfaceContainer = raised,
        surfaceContainerHigh = raised, surfaceContainerHighest = well, surfaceBright = raised, surfaceDim = well,
        outline = lineStrong, outlineVariant = line, error = bad, onError = Color.White, scrim = Color.Black.copy(alpha = 0.32f),
        inverseSurface = ink, inverseOnSurface = paper,
        secondaryContainer = accentSoft, onSecondaryContainer = ink,
    )
}

/** Material type roles from the HandOver scale, so stock components use the same sizes. */
fun HOType.material(): Typography = Typography(
    displayLarge = largeTitle, displayMedium = largeTitle, displaySmall = display,
    headlineLarge = display, headlineMedium = stepTitle, headlineSmall = title,
    titleLarge = title, titleMedium = headline, titleSmall = section,
    bodyLarge = body, bodyMedium = callout, bodySmall = footnote,
    labelLarge = callout.copy(fontWeight = headline.fontWeight), labelMedium = badge, labelSmall = caption,
)
