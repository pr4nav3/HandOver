package com.handover.app.ui.theme

import androidx.compose.ui.graphics.Color
import kotlin.math.pow

/**
 * WCAG 2.x contrast rules for a theme look, ported from vibeflux `Contrast.problems` (DESIGN.md 5):
 * text 4.5:1, marks and placeholders 3:1, on every surface, wash and grain extreme it appears on.
 * Empty when the look passes.
 */
object Contrast {
    private fun lin(c: Float): Double = if (c <= 0.04045f) c / 12.92 else ((c + 0.055) / 1.055).pow(2.4)
    fun luminance(c: Color): Double = 0.2126 * lin(c.red) + 0.7152 * lin(c.green) + 0.0722 * lin(c.blue)

    /** [fg] drawn over an opaque [bg], in sRGB, as `DeckRGB.over` does. */
    fun over(fg: Color, bg: Color): Color = Color(
        red = fg.red * fg.alpha + bg.red * (1 - fg.alpha),
        green = fg.green * fg.alpha + bg.green * (1 - fg.alpha),
        blue = fg.blue * fg.alpha + bg.blue * (1 - fg.alpha),
    )

    fun ratio(fg: Color, bg: Color): Double {
        val a = luminance(over(fg, bg))
        val b = luminance(bg)
        return (maxOf(a, b) + 0.05) / (minOf(a, b) + 0.05)
    }

    private fun lifted(c: Color, amount: Float) =
        Color((c.red + amount).coerceIn(0f, 1f), (c.green + amount).coerceIn(0f, 1f), (c.blue + amount).coerceIn(0f, 1f), c.alpha)

    fun problems(t: ColorRoles): List<String> {
        val out = ArrayList<String>()
        fun check(name: String, fg: Color, bgName: String, bgs: List<Color>, need: Double) {
            for (bg in bgs) {
                val r = ratio(fg, bg)
                if (r < need) out += "$name on $bgName: ${"%.2f".format(r)} < $need"
            }
        }
        val paperSamples = t.grain?.let { listOf(lifted(t.paper, -it), t.paper, lifted(t.paper, it)) } ?: listOf(t.paper)
        val surfaces = listOf("paper" to paperSamples, "raised" to listOf(t.raised), "well" to listOf(t.well))
        val tinted = listOf("accentInk" to t.accentInk, "good" to t.good, "caution" to t.caution, "bad" to t.bad)
        for ((bgName, bgs) in surfaces) {
            for ((name, fg) in listOf("ink" to t.ink, "ink2" to t.ink2) + tinted) check(name, fg, bgName, bgs, 4.5)
            check("idle", t.idle, bgName, bgs, 3.0)
            check("accent fill", t.accent, bgName, bgs, 3.0)
            if (bgName != "well") check("ink3", t.ink3, bgName, bgs, 3.0)
        }
        for ((name, tone) in tinted) {
            check(name, tone, "its wash", listOf(over(t.wash(tone), t.raised)) + paperSamples.map { over(t.wash(tone), it) }, 4.5)
        }
        for ((name, fg) in listOf("ink" to t.ink, "ink2" to t.ink2)) check(name, fg, "accent wash", listOf(over(t.accentSoft, t.raised)), 4.5)
        check("onAccent", t.onAccent, "accent", listOf(t.accent), 4.5)
        check("captionInk", t.captionInk, "caption bar over white", listOf(over(t.captionFill, Color.White)), 4.5)
        return out
    }
}
