package com.handover.app.ui.theme

import android.graphics.Bitmap
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.ImageShader
import androidx.compose.ui.graphics.ShaderBrush
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.asImageBitmap
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * The paper grain, DESIGN.md 2.7, from vibeflux `DeckGrain`: a 128 x 128 px tile from SplitMix64
 * seeded with 0x6465636B67726169. Per pixel n = (r1 + r2 + r3) / 3 - 0.5, white (lift) when n > 0 and
 * black (dip) otherwise, at alpha |n| x 2 x amount x 2.2. Drawn once per amount, tiled one tile pixel
 * per device pixel, never animated, and only on paper (never on raised, video or sheets).
 */
object HOGrain {
    const val SIDE = 128
    const val SEED = 0x6465636B67726169UL
    private val cache = HashMap<Float, ImageBitmap>()

    fun tile(amount: Float): ImageBitmap = synchronized(cache) {
        cache.getOrPut(amount) { Bitmap.createBitmap(pixels(amount), SIDE, SIDE, Bitmap.Config.ARGB_8888).asImageBitmap() }
    }

    /** The tile as ARGB pixels, row by row. Pure, so a JVM test checks it. */
    fun pixels(amount: Float): IntArray {
        val out = IntArray(SIDE * SIDE)
        var state = SEED
        fun next(): Double {
            state += 0x9E3779B97F4A7C15UL
            var z = state
            z = (z xor (z shr 30)) * 0xBF58476D1CE4E5B9UL
            z = (z xor (z shr 27)) * 0x94D049BB133111EBUL
            z = z xor (z shr 31)
            return (z shr 11).toDouble() / (1UL shl 53).toDouble()
        }
        for (i in out.indices) {
            val n = (next() + next() + next()) / 3 - 0.5
            val a = ((abs(n) * 2 * amount * 2.2).coerceIn(0.0, 1.0) * 255).roundToInt()
            out[i] = (a shl 24) or (if (n > 0) 0xFFFFFF else 0x000000)
        }
        return out
    }
}

/** Paints `paper` and, in grain themes, the grain tile over it. */
@Composable
fun Modifier.paper(): Modifier {
    val c = HandOver.colors
    val amount = c.grain
    val brush = remember(amount) { amount?.let { ShaderBrush(ImageShader(HOGrain.tile(it), TileMode.Repeated, TileMode.Repeated)) } }
    return this.background(c.paper).then(if (brush != null) Modifier.background(brush) else Modifier)
}

/** The paper surface behind a screen, with the theme's grain. */
@Composable
fun HandOverSurface(modifier: Modifier = Modifier, content: @Composable BoxScope.() -> Unit) {
    Box(modifier.fillMaxSize().paper(), content = content)
}
