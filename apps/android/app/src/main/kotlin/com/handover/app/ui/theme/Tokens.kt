package com.handover.app.ui.theme

import androidx.compose.animation.core.FiniteAnimationSpec
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Immutable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.PI
import kotlin.math.pow

// DESIGN.md section 2 on Android, in dp and sp. Same names on every platform.

/** Spacing, DESIGN.md 2.3. */
object HOSpace {
    val xxs = 2.dp
    val xs = 4.dp
    val s = 8.dp
    val m = 12.dp
    val l = 16.dp
    val xl = 24.dp
    val xxl = 32.dp
    val xxxl = 48.dp
}

/** Sizes, DESIGN.md 2.4. Android touch targets are 48 dp. */
object HOSize {
    val touch = 48.dp
    val controlSmall = 32.dp
    val control = 44.dp
    val controlLarge = 52.dp
    val iconButton = 36.dp
    val badge = 22.dp
    val dot = 9.dp
    val tile = 32.dp
    val pipMinWidth = 112.dp
    const val PIP_FRACTION = 0.30f
}

/** Corner radii, DESIGN.md 2.5. */
object HORadius {
    val small = 8.dp
    val control = 12.dp
    val card = 18.dp
    val panel = 24.dp
    val pip = 16.dp
    val buttonLarge = 16.dp
}

/** A hairline: 0.5 pt on iOS, 0.6 dp on Android (DESIGN.md 2.6). */
val Hairline = 0.6.dp

/** The type scale, DESIGN.md 2.2. System font; Android has no SF Rounded, so numerals use tabular figures. */
@Immutable
data class HOType(
    val largeTitle: TextStyle,
    val display: TextStyle,
    val stepTitle: TextStyle,
    val title: TextStyle,
    val headline: TextStyle,
    val body: TextStyle,
    val bodyMedium: TextStyle,
    val callout: TextStyle,
    val section: TextStyle,
    val footnote: TextStyle,
    val caption: TextStyle,
    val badge: TextStyle,
    val captionText: TextStyle,
    val numeral: TextStyle,
    val timer: TextStyle,
    val code: TextStyle,
) {
    companion object {
        private val sans = FontFamily.Default
        private const val TABULAR = "tnum"
        val Default = HOType(
            largeTitle = TextStyle(fontFamily = sans, fontSize = 34.sp, lineHeight = 41.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
            display = TextStyle(fontFamily = sans, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.3).sp),
            stepTitle = TextStyle(fontFamily = sans, fontSize = 22.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.2).sp),
            title = TextStyle(fontFamily = sans, fontSize = 20.sp, lineHeight = 25.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.3).sp),
            headline = TextStyle(fontFamily = sans, fontSize = 17.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold),
            body = TextStyle(fontFamily = sans, fontSize = 17.sp, lineHeight = 22.sp),
            bodyMedium = TextStyle(fontFamily = sans, fontSize = 17.sp, lineHeight = 22.sp, fontWeight = FontWeight.Medium),
            callout = TextStyle(fontFamily = sans, fontSize = 15.sp, lineHeight = 20.sp),
            section = TextStyle(fontFamily = sans, fontSize = 13.sp, lineHeight = 18.sp, fontWeight = FontWeight.SemiBold),
            footnote = TextStyle(fontFamily = sans, fontSize = 13.sp, lineHeight = 18.sp),
            caption = TextStyle(fontFamily = sans, fontSize = 12.sp, lineHeight = 16.sp, fontFeatureSettings = TABULAR),
            badge = TextStyle(fontFamily = sans, fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium),
            captionText = TextStyle(fontFamily = sans, fontSize = 17.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.Center),
            numeral = TextStyle(fontFamily = sans, fontSize = 28.sp, lineHeight = 34.sp, fontWeight = FontWeight.SemiBold, fontFeatureSettings = TABULAR),
            timer = TextStyle(fontFamily = sans, fontSize = 17.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold, fontFeatureSettings = TABULAR),
            code = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.sp, lineHeight = 18.sp),
        )
    }
}

/**
 * Motion, DESIGN.md 2.8. iOS springs are given as response and damping; Compose takes damping
 * ratio and stiffness, where stiffness = (2 pi / response)^2.
 */
object HOMotion {
    private fun stiffness(response: Double): Float = (2 * PI / response).pow(2).toFloat()

    fun <T> panel(reduce: Boolean): FiniteAnimationSpec<T> = if (reduce) tween(150) else spring(0.82f, stiffness(0.38))
    fun <T> layout(reduce: Boolean): FiniteAnimationSpec<T> = if (reduce) tween(150) else spring(0.86f, stiffness(0.34))
    fun <T> snappy(reduce: Boolean): FiniteAnimationSpec<T> = tween(if (reduce) 150 else 250, easing = FastOutSlowInEasing)
    fun <T> press(): FiniteAnimationSpec<T> = tween(120, easing = LinearOutSlowInEasing)
    fun <T> clip(reduce: Boolean): FiniteAnimationSpec<T> = tween(if (reduce) 0 else 200, easing = FastOutSlowInEasing)
    fun <T> reduced(): FiniteAnimationSpec<T> = tween(150, easing = FastOutSlowInEasing)
}
