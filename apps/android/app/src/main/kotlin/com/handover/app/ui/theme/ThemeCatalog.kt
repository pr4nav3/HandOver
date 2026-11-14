package com.handover.app.ui.theme

import androidx.compose.runtime.Immutable
import androidx.compose.ui.graphics.Color

// The 14 HandOver themes, value for value from apps/design/THEMES.md (which takes them from
// vibeflux's DeckThemeCatalog, so their contrast is already proven). Stored ids never change.

/**
 * Every color role from DESIGN.md 2.1 for one look of one theme. `ink2` and `ink3` are `ink` at an
 * alpha, as the spec writes them; [com.handover.app.ui.theme.Contrast] composites them before measuring.
 */
@Immutable
data class ColorRoles(
    val isDark: Boolean,
    val paper: Color,
    val raised: Color,
    val well: Color,
    val ink: Color,
    val ink2: Color,
    val ink3: Color,
    val line: Color,
    val lineStrong: Color,
    val accent: Color,
    val onAccent: Color,
    val accentInk: Color,
    val good: Color,
    val caution: Color,
    val bad: Color,
    val idle: Color,
    /** How far the worst grain pixel moves brightness (0 to 1), or null for flat paper. */
    val grain: Float? = null,
) {
    // Roles shared by every theme (THEMES.md, Rules).
    val stage: Color get() = Color.Black
    val captionFill: Color get() = Color.Black.copy(alpha = 0.72f)
    val captionInk: Color get() = Color.White
    val record: Color get() = Color(0xFFD70015)

    /** The one wash strength, 12% light and 16% dark, rounded down to 8 bit alpha as vibeflux does (30/255, 40/255). */
    val washAlpha: Float get() = if (isDark) 40 / 255f else 30 / 255f
    fun wash(c: Color): Color = c.copy(alpha = washAlpha)
    val accentSoft: Color get() = wash(accent)
    val hover: Color get() = (if (isDark) Color.White else ink).copy(alpha = if (isDark) 0.06f else 0.05f)
    val pressed: Color get() = (if (isDark) Color.White else ink).copy(alpha = if (isDark) 0.10f else 0.09f)

    // Names from the first theme stub, kept so screens written against it still compile.
    val background: Color get() = paper
    val surface: Color get() = raised
    val surfaceRaised: Color get() = well
    val inkSecondary: Color get() = ink2
}

enum class ThemeGroup(val title: String) { Classic("Classic"), Grain("Grain"), Color("Color"), Mono("Mono") }

/** Whether a theme follows the system light or dark setting, or keeps one look always. */
enum class ThemeLooks(val words: String) { FollowsSystem("follows system"), AlwaysDark("always dark"), AlwaysLight("always light") }

/** The Appearance setting (System, Light, Dark). Applies only to themes with two looks. */
enum class Appearance(val id: String, val title: String) {
    System("system", "System"), Light("light", "Light"), Dark("dark", "Dark");

    companion object {
        fun from(id: String?): Appearance = entries.firstOrNull { it.id == id } ?: System
    }
}

@Immutable
data class ThemeSpec(
    /** Stored id. Never changes. */
    val id: String,
    val name: String,
    val group: ThemeGroup,
    val looks: ThemeLooks,
    /** The one line for the picker. */
    val blurb: String,
    val light: ColorRoles,
    val dark: ColorRoles,
    /** Extra search words for the picker. */
    val keywords: String = "",
) {
    /** True when the paper carries grain in either look. */
    val grain: Boolean get() = light.grain != null || dark.grain != null

    /** Whether this theme draws dark, given the system setting and the Appearance choice. */
    fun isDark(systemDark: Boolean, appearance: Appearance = Appearance.System): Boolean = when (looks) {
        ThemeLooks.AlwaysDark -> true
        ThemeLooks.AlwaysLight -> false
        ThemeLooks.FollowsSystem -> when (appearance) {
            Appearance.System -> systemDark
            Appearance.Light -> false
            Appearance.Dark -> true
        }
    }

    fun roles(dark: Boolean): ColorRoles = if (dark) this.dark else light

    companion object {
        val Default: ThemeSpec get() = ThemeCatalog.system
        val all: List<ThemeSpec> get() = ThemeCatalog.all
        fun from(id: String?): ThemeSpec = ThemeCatalog.all.firstOrNull { it.id == id } ?: ThemeCatalog.system
    }
}

private fun hex(v: Long): Color = Color(0xFF000000 or v)

private val LightGood = hex(0x186629)
private val LightCaution = hex(0x934000)
private val LightBad = hex(0xB80011)
private val LightIdle = hex(0x6E6E73)
private val DarkGood = hex(0x30D158)
private val DarkCaution = hex(0xFF9F0A)
private val DarkBad = hex(0xFF6961)
private val DarkIdle = hex(0x8E8E93)

private fun light(
    paper: Long, raised: Long, well: Long, ink: Long, ink2: Float, ink3: Float,
    accent: Long, onAccent: Long, accentInk: Long = accent,
    good: Color = LightGood, caution: Color = LightCaution, bad: Color = LightBad, idle: Color = LightIdle,
    line: Float = 0.09f, lineStrong: Float = 0.16f, grain: Float? = null,
): ColorRoles {
    val i = hex(ink)
    return ColorRoles(
        isDark = false, paper = hex(paper), raised = hex(raised), well = hex(well), ink = i,
        ink2 = i.copy(alpha = ink2), ink3 = i.copy(alpha = ink3), line = i.copy(alpha = line), lineStrong = i.copy(alpha = lineStrong),
        accent = hex(accent), onAccent = hex(onAccent), accentInk = hex(accentInk),
        good = good, caution = caution, bad = bad, idle = idle, grain = grain,
    )
}

private fun dark(
    paper: Long, raised: Long, well: Long, ink: Long, ink2: Float, ink3: Float,
    accent: Long, onAccent: Long, accentInk: Long = accent,
    good: Color = DarkGood, caution: Color = DarkCaution, bad: Color = DarkBad, idle: Color = DarkIdle,
    line: Float = 0.10f, lineStrong: Float = 0.17f, grain: Float? = null,
): ColorRoles {
    val i = hex(ink)
    return ColorRoles(
        isDark = true, paper = hex(paper), raised = hex(raised), well = hex(well), ink = i,
        ink2 = i.copy(alpha = ink2), ink3 = i.copy(alpha = ink3),
        line = Color.White.copy(alpha = line), lineStrong = Color.White.copy(alpha = lineStrong),
        accent = hex(accent), onAccent = hex(onAccent), accentInk = hex(accentInk),
        good = good, caution = caution, bad = bad, idle = idle, grain = grain,
    )
}

object ThemeCatalog {
    // ---------------------------------------------------------------- Classic

    val system = ThemeSpec(
        "system", "Default", ThemeGroup.Classic, ThemeLooks.FollowsSystem, "Cool gray, HandOver blue",
        light = light(0xF0F1F2, 0xFBFBFC, 0xE4E5E8, 0x1A1B1E, 0.70f, 0.50f, 0x3E5FD9, 0xFFFFFF, 0x3249B8),
        dark = dark(0x131416, 0x1D1E21, 0x26272B, 0xEDEEF0, 0.68f, 0.46f, 0x8AA8FF, 0x0E1630),
        keywords = "auto automatic",
    )

    private val nightRoles = dark(0x000000, 0x0F0F11, 0x1C1C1F, 0xF2F2F4, 0.66f, 0.44f, 0x8AA8FF, 0x0E1630, line = 0.12f, lineStrong = 0.20f)
    val night = ThemeSpec(
        "night", "Night", ThemeGroup.Classic, ThemeLooks.AlwaysDark, "True black for OLED",
        light = nightRoles, dark = nightRoles, keywords = "black oled amoled",
    )

    val highContrast = ThemeSpec(
        "highContrast", "High Contrast", ThemeGroup.Classic, ThemeLooks.FollowsSystem, "Firmer text and edges",
        light = light(
            0xFFFFFF, 0xF2F2F4, 0xE3E3E8, 0x000000, 0.84f, 0.66f, 0x0030C0, 0xFFFFFF,
            good = hex(0x0B5E25), caution = hex(0x7A3300), bad = hex(0xA3000E), idle = hex(0x5E5E62), line = 0.42f, lineStrong = 0.66f,
        ),
        dark = dark(
            0x000000, 0x1A1A1C, 0x2A2A2E, 0xFFFFFF, 0.86f, 0.66f, 0xADC4FF, 0x00102E,
            good = hex(0x6CF294), caution = hex(0xFFC46B), bad = hex(0xFF8A80), idle = hex(0xB4B4B8), line = 0.45f, lineStrong = 0.70f,
        ),
        keywords = "accessibility contrast bold",
    )

    val ivory = ThemeSpec(
        "ivory", "Ivory", ThemeGroup.Classic, ThemeLooks.FollowsSystem, "Cream and ink blue",
        light = light(0xF4F1EA, 0xFCFBF7, 0xE9E5DB, 0x221E18, 0.70f, 0.50f, 0x255EA8, 0xFFFFFF, 0x1F4F8E),
        dark = dark(0x1A1815, 0x24211D, 0x2E2A25, 0xEFEAE0, 0.68f, 0.46f, 0x95B7EE, 0x0E1A30, bad = hex(0xFF7A70)),
    )

    private val dimRoles = dark(0x1F2227, 0x272A30, 0x30343A, 0xE1E4E8, 0.72f, 0.50f, 0x93ACF2, 0x101830, bad = hex(0xFF8A82), idle = hex(0x9696A0))
    val dim = ThemeSpec("dim", "Dim", ThemeGroup.Classic, ThemeLooks.AlwaysDark, "Gentle dark slate", light = dimRoles, dark = dimRoles)

    // ---------------------------------------------------------------- Grain

    val grain = ThemeSpec(
        "grain", "Grain", ThemeGroup.Grain, ThemeLooks.FollowsSystem, "Paper with a fine grain",
        light = light(0xEEEDE9, 0xFAFAF8, 0xE3E2DD, 0x1C1B19, 0.72f, 0.52f, 0x34519F, 0xFFFFFF, bad = hex(0xA8000F), grain = 0.030f),
        dark = dark(0x171716, 0x21211F, 0x2B2B29, 0xEEEDEA, 0.70f, 0.48f, 0x9DB1F2, 0x111A33, grain = 0.025f),
    )

    private val newsprintRoles = light(
        0xE8E6E1, 0xF5F4F0, 0xDCDAD4, 0x141414, 0.74f, 0.54f, 0xA3221E, 0xFFFFFF, 0x961E1A,
        good = hex(0x155C25), caution = hex(0x843900), bad = hex(0x9E000F), idle = hex(0x626266), grain = 0.035f,
    )
    val newsprint = ThemeSpec(
        "newsprint", "Newsprint", ThemeGroup.Grain, ThemeLooks.AlwaysLight, "Gray stock, red ink",
        light = newsprintRoles, dark = newsprintRoles,
    )

    private val chalkboardRoles = dark(
        0x1D2A25, 0x24332D, 0x2C3C36, 0xEEF2EC, 0.74f, 0.52f, 0xF0E19A, 0x2A2600,
        good = hex(0x7CF0A0), caution = hex(0xFFC071), bad = hex(0xFF9C93), idle = hex(0xA3B0AA), line = 0.12f, lineStrong = 0.20f, grain = 0.030f,
    )
    val chalkboard = ThemeSpec(
        "chalkboard", "Chalkboard", ThemeGroup.Grain, ThemeLooks.AlwaysDark, "Chalk on green",
        light = chalkboardRoles, dark = chalkboardRoles,
    )

    // ---------------------------------------------------------------- Color

    val harbor = ThemeSpec(
        "harbor", "Harbor", ThemeGroup.Color, ThemeLooks.FollowsSystem, "Cool teal",
        light = light(0xECF0F1, 0xF9FBFB, 0xDEE5E7, 0x15202A, 0.72f, 0.50f, 0x0F6680, 0xFFFFFF, 0x0B5A71),
        dark = dark(0x0F1619, 0x172024, 0x202B30, 0xE6EEF1, 0.70f, 0.46f, 0x6CC4DB, 0x06222B),
    )

    val sage = ThemeSpec(
        "sage", "Sage", ThemeGroup.Color, ThemeLooks.FollowsSystem, "Muted green",
        light = light(0xEEF1EC, 0xFAFBF8, 0xE1E6DE, 0x1A211B, 0.72f, 0.50f, 0x3E6B48, 0xFFFFFF, 0x345C3D),
        dark = dark(0x141814, 0x1C221C, 0x252C25, 0xE7EEE6, 0.70f, 0.46f, 0x9CCB9F, 0x10241A),
    )

    val clay = ThemeSpec(
        "clay", "Clay", ThemeGroup.Color, ThemeLooks.FollowsSystem, "Terracotta",
        light = light(0xF3EEEA, 0xFCFAF8, 0xE8E0D9, 0x241B17, 0.72f, 0.50f, 0xA8452A, 0xFFFFFF, 0x963C22),
        dark = dark(0x1B1513, 0x251D1A, 0x2F2622, 0xF2E9E4, 0.70f, 0.46f, 0xF0A07E, 0x2E1208),
    )

    private val nocturneRoles = dark(0x0E1221, 0x151A2D, 0x1D2339, 0xE6E9F5, 0.70f, 0.46f, 0x9AAEFF, 0x101640)
    val nocturne = ThemeSpec(
        "nocturne", "Nocturne", ThemeGroup.Color, ThemeLooks.AlwaysDark, "Navy, always dark",
        light = nocturneRoles, dark = nocturneRoles,
    )

    // ---------------------------------------------------------------- Mono

    val mono = ThemeSpec(
        "mono", "Mono", ThemeGroup.Mono, ThemeLooks.FollowsSystem, "Black and white",
        light = light(
            0xFFFFFF, 0xF6F6F6, 0xEBEBEB, 0x000000, 0.66f, 0.46f, 0x000000, 0xFFFFFF,
            good = hex(0x000000), caution = hex(0x555555), bad = hex(0x000000), idle = hex(0x777777), line = 0.12f, lineStrong = 0.20f,
        ),
        dark = dark(
            0x000000, 0x121212, 0x222222, 0xFFFFFF, 0.68f, 0.46f, 0xFFFFFF, 0x000000,
            good = hex(0xFFFFFF), caution = hex(0xAAAAAA), bad = hex(0xFFFFFF), idle = hex(0x888888), line = 0.14f, lineStrong = 0.22f,
        ),
        keywords = "black white grayscale",
    )

    private val matteRoles = light(
        0xE7E6E2, 0xF1F0EC, 0xDBDAD5, 0x1E1E1E, 0.74f, 0.54f, 0x2E2E2E, 0xF1F0EC,
        good = hex(0x1E1E1E), caution = hex(0x4F4F4F), bad = hex(0x1E1E1E), idle = hex(0x6A6A6A), line = 0.12f, lineStrong = 0.20f,
    )
    val matte = ThemeSpec(
        "matte", "Matte", ThemeGroup.Mono, ThemeLooks.AlwaysLight, "Gray, low glare",
        light = matteRoles, dark = matteRoles, keywords = "eink e-ink grayscale reader",
    )

    /** Picker order: Classic, Grain, Color, Mono. */
    val all: List<ThemeSpec> = listOf(system, night, highContrast, ivory, dim, grain, newsprint, chalkboard, harbor, sage, clay, nocturne, mono, matte)

    /** True for themes with no hue, where status keeps its meaning through words and symbols. */
    fun isMono(spec: ThemeSpec): Boolean = spec.group == ThemeGroup.Mono
}
