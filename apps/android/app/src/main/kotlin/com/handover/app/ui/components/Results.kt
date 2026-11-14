package com.handover.app.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.Star
import androidx.compose.material.icons.rounded.StarOutline
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import kotlin.math.roundToInt

// ---------------------------------------------------------------- score ring (DESIGN.md 3.21)

/** The Done score label and its ring tone (SCREENS.md 8). */
enum class ScoreLabel(val words: String, val tone: Tone) {
    Excellent("Excellent", Tone.Good), Good("Good", Tone.Accent), KeepPracticing("Keep practicing", Tone.Caution);

    companion object {
        /** 85 to 100 Excellent, 60 to 84 Good, below Keep practicing. */
        fun of(score: Int): ScoreLabel = when {
            score >= 85 -> Excellent
            score >= 60 -> Good
            else -> KeepPracticing
        }

        /** A label the hub sent, by its words; unknown words fall back to the local rule. */
        fun of(words: String?, score: Int): ScoreLabel = entries.firstOrNull { it.words.equals(words, ignoreCase = true) } ?: of(score)
    }
}

/**
 * 120 dp ring, 10 dp stroke, filled in the label's tone, the score in the middle. With [score]
 * null: track only and "Not enough data", no number. Fills once from 0 over 0.6 s; with Reduce
 * Motion it appears filled.
 */
@Composable
fun ScoreRing(score: Int?, label: ScoreLabel?, modifier: Modifier = Modifier, size: Dp = 120.dp) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    val fill = remember { Animatable(if (reduce) 1f else 0f) }
    LaunchedEffect(score) { if (score != null && !reduce) fill.animateTo(1f, tween(600, easing = FastOutSlowInEasing)) }
    val tone = label?.let { toneColor(it.tone) } ?: c.accent
    val spoken = if (score == null || label == null) "Score, not enough data" else "Score $score of 100, ${label.words.lowercase()}"
    Box(modifier.size(size).clearAndSetSemantics { contentDescription = spoken }, contentAlignment = Alignment.Center) {
        Canvas(Modifier.size(size)) {
            val w = 10.dp.toPx()
            val arc = Size(this.size.width - w, this.size.height - w)
            val tl = Offset(w / 2, w / 2)
            drawArc(c.well, 0f, 360f, false, tl, arc, style = Stroke(w))
            if (score != null) drawArc(tone, -90f, 360f * (score / 100f) * fill.value, false, tl, arc, style = Stroke(w, cap = StrokeCap.Round))
        }
        if (score == null || label == null) {
            Text("Not enough data", style = HandOver.type.callout, color = c.ink2, textAlign = TextAlign.Center, modifier = Modifier.width(size * 0.62f))
        } else {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("$score", style = HandOver.type.numeral.copy(fontSize = 34.sp, lineHeight = 38.sp), color = c.ink)
                Text(label.words, style = HandOver.type.footnote, color = c.ink2, textAlign = TextAlign.Center)
            }
        }
    }
}

// ---------------------------------------------------------------- time bar (DESIGN.md 3.22)

/**
 * You against the expert: two 6 dp bars, Expert in `ink3`, You in `accent` (or `good` when
 * faster), both scaled to [scale] (the longest time in the lesson). Missing time: no You bar
 * and the words "No time".
 */
@Composable
fun TimeBar(yours: Double?, expert: Double?, scale: Double, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val faster = yours != null && expert != null && yours < expert
    Column(modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
        BarRow(expert, scale, c.ink3, if (expert != null) "Expert ${Format.clock(expert)}" else "Expert, no time")
        if (yours != null) BarRow(yours, scale, if (faster) c.good else c.accent, "You ${Format.clock(yours)}")
        else Text("No time", style = HandOver.type.caption, color = c.ink2)
    }
}

@Composable
private fun BarRow(value: Double?, scale: Double, color: Color, text: String) {
    val track = HandOver.colors.well
    Row(verticalAlignment = Alignment.CenterVertically) {
        Canvas(Modifier.weight(1f).height(6.dp)) {
            val r = androidx.compose.ui.geometry.CornerRadius(3.dp.toPx())
            drawRoundRect(track, cornerRadius = r)
            if (value != null && scale > 0) {
                val w = (size.width * (value / scale).toFloat().coerceIn(0f, 1f)).coerceAtLeast(6.dp.toPx())
                drawRoundRect(color, size = Size(w, size.height), cornerRadius = r)
            }
        }
        Spacer(Modifier.width(HOSpace.s))
        Text(text, style = HandOver.type.caption, color = HandOver.colors.ink2, maxLines = 1, modifier = Modifier.widthIn(min = 76.dp))
    }
}

// ---------------------------------------------------------------- step result moment (DESIGN.md 3.19)

data class StepResultMoment(val text: String, val icon: ImageVector, val key: Long = System.nanoTime())

object StepResultCopy {
    /**
     * The copy rules of SCREENS.md 7.10. [seconds] is the client's time on the step, or null when
     * the step was entered under 1 s ago or the timer was interrupted. [expert] is end minus start.
     */
    fun moment(seconds: Double?, expert: Double?, byCamera: Boolean, mistakesFixed: Int): StepResultMoment = when {
        mistakesFixed > 0 -> StepResultMoment("Done. ${Format.count(mistakesFixed, "mistake")} fixed.", Icons.Rounded.Check)
        seconds != null && expert != null && expert > 0 && seconds < expert * 0.9 ->
            StepResultMoment("Nice. ${Format.secs(seconds)}, faster than the expert.", Icons.Rounded.Speed)
        seconds != null && expert != null && expert > 0 && seconds <= expert * 1.1 ->
            StepResultMoment("Done. ${Format.secs(seconds)}, about the expert's time.", Icons.Rounded.Check)
        seconds != null -> StepResultMoment("Done in ${Format.secs(seconds)}.", Icons.Rounded.Check)
        byCamera -> StepResultMoment("Verified.", Icons.Outlined.CheckCircle)
        else -> StepResultMoment("Done.", Icons.Rounded.Check)
    }
}

/** A glass capsule at the top of the clip pane, 1.5 s on screen, never stacked, never blocking. */
@Composable
fun StepResultToast(moment: StepResultMoment?, onGone: () -> Unit, modifier: Modifier = Modifier, hold: Boolean = false) {
    val reduce = HandOver.reduceMotion
    LaunchedEffect(moment?.key) {
        if (moment != null && !hold) {
            kotlinx.coroutines.delay(1_500)
            onGone()
        }
    }
    AnimatedVisibility(
        moment != null,
        modifier,
        enter = if (reduce) fadeIn(tween(150)) else fadeIn(tween(250)) + scaleIn(tween(250), initialScale = 0.96f),
        exit = fadeOut(tween(if (reduce) 150 else 250)),
    ) {
        val m = moment ?: return@AnimatedVisibility
        Row(
            Modifier.glass().padding(horizontal = HOSpace.m, vertical = 6.dp).semantics(mergeDescendants = true) {
                contentDescription = m.text
                liveRegion = LiveRegionMode.Polite
            },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(m.icon, null, tint = Color.White, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(m.text, style = HandOver.type.callout.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold), color = Color.White, maxLines = 2)
        }
    }
}

// ---------------------------------------------------------------- star rating (DESIGN.md 3.23)

/**
 * Five stars, 32 dp each in a 48 dp target, accent when filled and ink3 empty (ink in Mono
 * themes). Tap sets; dragging across scrubs with a tap haptic per star. One adjustable element.
 */
@Composable
fun StarRating(value: Int, onChange: (Int) -> Unit, modifier: Modifier = Modifier, starSize: Dp = 32.dp) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    val filled = if (HandOver.isMono) c.ink else c.accent
    val empty = if (HandOver.isMono) c.ink else c.ink3
    fun set(v: Int) {
        val n = v.coerceIn(1, 5)
        if (n != value) { haptics.play(HOHaptic.Tap); onChange(n) }
    }
    val cell = 48.dp
    Row(
        modifier
            .clearAndSetSemantics {
                contentDescription = "Rating, $value of 5 stars"
                progressBarRangeInfo = ProgressBarRangeInfo(value.toFloat(), 0f..5f, steps = 4)
                setProgress { set(it.roundToInt()); true }
            }
            .pointerInput(value) {
                detectTapGestures { o -> set((o.x / cell.toPx()).toInt() + 1) }
            }
            .pointerInput(value) {
                detectHorizontalDragGestures { change, _ -> set((change.position.x / cell.toPx()).toInt() + 1) }
            },
    ) {
        for (i in 1..5) {
            Box(Modifier.size(cell), contentAlignment = Alignment.Center) {
                Icon(if (i <= value) Icons.Rounded.Star else Icons.Rounded.StarOutline, null, tint = if (i <= value) filled else empty, modifier = Modifier.size(starSize))
            }
        }
    }
}

/** A thin wrapper for the Done stat cells: value in numeral, label in caption. */
@Composable
fun Stat(value: String, label: String, modifier: Modifier = Modifier, valueIsWords: Boolean = false) {
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        // Words ("Not enough data") sit in the same height as a number, so labels stay on one line across the row.
        Box(Modifier.heightIn(min = 28.dp), contentAlignment = Alignment.Center) {
            Text(
                value,
                style = if (valueIsWords) HandOver.type.footnote else HandOver.type.numeral.copy(fontSize = 22.sp, lineHeight = 28.sp),
                color = if (valueIsWords) HandOver.colors.ink2 else HandOver.colors.ink,
                textAlign = TextAlign.Center, maxLines = 2,
            )
        }
        Text(label, style = HandOver.type.caption, color = HandOver.colors.ink2, textAlign = TextAlign.Center, maxLines = 2)
    }
}

/** The floating capsule toast (DESIGN.md 3.13): one line, raised, floating shadow, height 52. */
@Composable
fun Toast(text: String, modifier: Modifier = Modifier, icon: ImageVector? = null, tone: Tone = Tone.Neutral) {
    Row(
        modifier.height(52.dp).floating(26.dp).padding(horizontal = HOSpace.l).semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, null, tint = toneText(tone), modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(HOSpace.s))
        }
        Text(text, style = HandOver.type.bodyMedium, color = HandOver.colors.ink, maxLines = 1)
    }
}
