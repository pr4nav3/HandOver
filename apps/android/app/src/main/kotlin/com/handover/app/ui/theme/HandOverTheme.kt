package com.handover.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

// STUB for the design builder. The shape is fixed so screens can be written against it now:
// a ThemeSpec holds the color roles (light and dark), the type scale and the grain flag, and
// HandOverTheme maps it onto Material 3 so stock components match. The values below are neutral
// placeholders; replace them, add more specs, but keep the HandOverTheme(spec) signature.

/** The color roles HandOver screens use. Material's roles are derived from these in [toColorScheme]. */
@Immutable
data class ColorRoles(
    val background: Color,
    val surface: Color,
    val surfaceRaised: Color,
    val ink: Color,
    val inkSecondary: Color,
    val line: Color,
    val accent: Color,
    val onAccent: Color,
    /** A check passed, a step verified. */
    val good: Color,
    /** Checks off, a mistake to look at. */
    val caution: Color,
    val bad: Color,
)

@Immutable
data class ThemeSpec(
    val name: String,
    val light: ColorRoles,
    val dark: ColorRoles,
    val typography: Typography = Typography(),
    /** Draw a fine paper grain over the background. The design builder implements the texture. */
    val grain: Boolean = false,
) {
    companion object {
        /** The placeholder theme until the design builder adds the real ones. */
        val Default = ThemeSpec(
            name = "Default",
            light = ColorRoles(
                background = Color(0xFFFAFAF8),
                surface = Color(0xFFFFFFFF),
                surfaceRaised = Color(0xFFF2F1EC),
                ink = Color(0xFF1C1B1F),
                inkSecondary = Color(0xFF5E5D63),
                line = Color(0x1F1C1B1F),
                accent = Color(0xFF3E5FD9),
                onAccent = Color(0xFFFFFFFF),
                good = Color(0xFF2E7D4F),
                caution = Color(0xFFA15C00),
                bad = Color(0xFFB3261E),
            ),
            dark = ColorRoles(
                background = Color(0xFF141416),
                surface = Color(0xFF1C1C1F),
                surfaceRaised = Color(0xFF26262A),
                ink = Color(0xFFEDECEF),
                inkSecondary = Color(0xFFA9A8AE),
                line = Color(0x29EDECEF),
                accent = Color(0xFF8EA6FF),
                onAccent = Color(0xFF0F1A45),
                good = Color(0xFF7CD39C),
                caution = Color(0xFFF2B866),
                bad = Color(0xFFFFB4AB),
            ),
        )
    }
}

/** The active roles and spec, for anything Material's ColorScheme does not cover. */
@Immutable
data class HandOverPalette(val roles: ColorRoles, val spec: ThemeSpec, val isDark: Boolean)

val LocalHandOverPalette = staticCompositionLocalOf { HandOverPalette(ThemeSpec.Default.light, ThemeSpec.Default, false) }

/** Shorthand: `HandOver.colors.accent`. */
object HandOver {
    val colors: ColorRoles @Composable get() = LocalHandOverPalette.current.roles
    val grain: Boolean @Composable get() = LocalHandOverPalette.current.spec.grain
}

@Composable
fun HandOverTheme(
    spec: ThemeSpec = ThemeSpec.Default,
    dark: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val roles = if (dark) spec.dark else spec.light
    CompositionLocalProvider(LocalHandOverPalette provides HandOverPalette(roles, spec, dark)) {
        MaterialTheme(colorScheme = roles.toColorScheme(dark), typography = spec.typography, content = content)
    }
}

private fun ColorRoles.toColorScheme(dark: Boolean): ColorScheme {
    val base = if (dark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = accent,
        onPrimary = onAccent,
        secondaryContainer = accent.copy(alpha = if (dark) 0.24f else 0.14f),
        onSecondaryContainer = ink,
        background = background,
        onBackground = ink,
        surface = background,
        onSurface = ink,
        surfaceVariant = surfaceRaised,
        onSurfaceVariant = inkSecondary,
        surfaceContainer = surface,
        surfaceContainerLow = surface,
        surfaceContainerHigh = surfaceRaised,
        outline = inkSecondary,
        outlineVariant = line,
        error = bad,
    )
}
