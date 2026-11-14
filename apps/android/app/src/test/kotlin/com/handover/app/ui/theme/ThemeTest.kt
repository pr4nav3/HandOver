package com.handover.app.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ThemeTest {
    private fun hex(c: Color) = "%06X".format(c.toArgb() and 0xFFFFFF)

    @Test fun catalogHasTheFourteenThemesInPickerOrder() {
        assertEquals(
            listOf("system", "night", "highContrast", "ivory", "dim", "grain", "newsprint", "chalkboard", "harbor", "sage", "clay", "nocturne", "mono", "matte"),
            ThemeCatalog.all.map { it.id },
        )
        assertEquals(14, ThemeCatalog.all.map { it.id }.toSet().size)
    }

    @Test fun groupsAndLooksMatchThemesMd() {
        val groups = ThemeCatalog.all.groupBy { it.group }.mapValues { (_, v) -> v.map { it.id } }
        assertEquals(listOf("system", "night", "highContrast", "ivory", "dim"), groups[ThemeGroup.Classic])
        assertEquals(listOf("grain", "newsprint", "chalkboard"), groups[ThemeGroup.Grain])
        assertEquals(listOf("harbor", "sage", "clay", "nocturne"), groups[ThemeGroup.Color])
        assertEquals(listOf("mono", "matte"), groups[ThemeGroup.Mono])
        val dark = ThemeCatalog.all.filter { it.looks == ThemeLooks.AlwaysDark }.map { it.id }
        val light = ThemeCatalog.all.filter { it.looks == ThemeLooks.AlwaysLight }.map { it.id }
        assertEquals(listOf("night", "dim", "chalkboard", "nocturne"), dark)
        assertEquals(listOf("newsprint", "matte"), light)
    }

    @Test fun spotValuesAreExact() {
        val d = ThemeCatalog.system
        assertEquals("F0F1F2", hex(d.light.paper))
        assertEquals("131416", hex(d.dark.paper))
        assertEquals("3249B8", hex(d.light.accentInk))
        assertEquals("8AA8FF", hex(d.dark.accentInk))
        assertEquals("186629", hex(d.light.good))
        assertEquals("FF6961", hex(d.dark.bad))
        assertEquals(0.70f, d.light.ink2.alpha, 0.003f)
        assertEquals(0.46f, d.dark.ink3.alpha, 0.003f)
        assertEquals("961E1A", hex(ThemeCatalog.newsprint.light.accentInk))
        assertEquals("F0E19A", hex(ThemeCatalog.chalkboard.dark.accent))
        assertEquals("FF7A70", hex(ThemeCatalog.ivory.dark.bad))
        assertEquals("FF8A82", hex(ThemeCatalog.dim.dark.bad))
        assertEquals("555555", hex(ThemeCatalog.mono.light.caution))
        assertEquals("F1F0EC", hex(ThemeCatalog.matte.light.onAccent))
        assertEquals(0.42f, ThemeCatalog.highContrast.light.line.alpha, 0.003f)
        assertEquals(0.45f, ThemeCatalog.highContrast.dark.line.alpha, 0.003f)
    }

    @Test fun sharedVideoRolesAreFixed() {
        for (t in ThemeCatalog.all) for (r in listOf(t.light, t.dark)) {
            assertEquals(Color.Black, r.stage)
            assertEquals("D70015", hex(r.record))
            assertEquals(Color.White, r.captionInk)
            assertEquals(0.72f, r.captionFill.alpha, 0.003f)
        }
    }

    @Test fun grainOnlyOnGrainThemesWithSpecAmounts() {
        assertEquals(0.030f, ThemeCatalog.grain.light.grain)
        assertEquals(0.025f, ThemeCatalog.grain.dark.grain)
        assertEquals(0.035f, ThemeCatalog.newsprint.light.grain)
        assertEquals(0.030f, ThemeCatalog.chalkboard.dark.grain)
        assertEquals(listOf("grain", "newsprint", "chalkboard"), ThemeCatalog.all.filter { it.grain }.map { it.id })
    }

    @Test fun washesRoundDownTo8BitAlpha() {
        assertEquals(30 / 255f, ThemeCatalog.system.light.accentSoft.alpha, 0.002f)
        assertEquals(40 / 255f, ThemeCatalog.system.dark.accentSoft.alpha, 0.002f)
    }

    @Test fun appearanceAppliesOnlyToThemesWithTwoLooks() {
        assertTrue(ThemeCatalog.system.isDark(systemDark = false, appearance = Appearance.Dark))
        assertFalse(ThemeCatalog.system.isDark(systemDark = true, appearance = Appearance.Light))
        assertTrue(ThemeCatalog.system.isDark(systemDark = true, appearance = Appearance.System))
        assertTrue(ThemeCatalog.night.isDark(systemDark = false, appearance = Appearance.Light))
        assertFalse(ThemeCatalog.matte.isDark(systemDark = true, appearance = Appearance.Dark))
    }

    @Test fun everyLookPassesTheContrastMatrix() {
        val problems = ThemeCatalog.all.flatMap { t ->
            listOf(t.light, t.dark).distinct().flatMap { r -> Contrast.problems(r).map { "${t.id} ${if (r.isDark) "dark" else "light"}: $it" } }
        }
        assertTrue(problems.joinToString("\n"), problems.isEmpty())
    }

    @Test fun highContrastTextReachesSevenToOne() {
        for (r in listOf(ThemeCatalog.highContrast.light, ThemeCatalog.highContrast.dark)) {
            for (fg in listOf(r.ink, r.ink2, r.accentInk, r.good, r.caution, r.bad)) assertTrue(Contrast.ratio(fg, r.paper) >= 7.0)
        }
    }

    @Test fun measuredRatiosMatchThemesMd() {
        // THEMES.md rounds down to one decimal; Compose keeps alpha at 8 bits (0.70 is 179/255), so allow 0.15.
        val d = ThemeCatalog.system.light
        assertEquals(15.2, Contrast.ratio(d.ink, d.paper), 0.15)
        assertEquals(5.9, Contrast.ratio(d.ink2, d.paper), 0.15)
        assertEquals(5.4, Contrast.ratio(d.onAccent, d.accent), 0.15)
    }

    @Test fun persistedChoiceRoundTrips() {
        val prefs = MemoryThemePrefs()
        val store = ThemeStore(prefs)
        assertEquals("system", store.choice.value.spec.id)
        store.select(ThemeCatalog.harbor)
        store.setAppearance(Appearance.Dark)
        val again = ThemeStore(prefs)
        assertEquals("harbor", again.choice.value.spec.id)
        assertEquals(Appearance.Dark, again.choice.value.appearance)
        assertEquals("system", ThemeSpec.from("not-a-theme").id)
    }

    @Test fun grainTileIsDeterministicAndBounded() {
        val a = HOGrain.pixels(0.03f)
        val b = HOGrain.pixels(0.03f)
        assertTrue(a.contentEquals(b))
        assertEquals(128 * 128, a.size)
        val maxAlpha = a.maxOf { it ushr 24 }
        // |n| <= 0.5, so alpha <= amount * 2.2 = 0.066 of 255.
        assertTrue("max alpha $maxAlpha", maxAlpha in 1..17)
        assertTrue(a.any { it and 0xFFFFFF == 0xFFFFFF && it ushr 24 > 0 })
        assertTrue(a.any { it and 0xFFFFFF == 0 && it ushr 24 > 0 })
    }
}
