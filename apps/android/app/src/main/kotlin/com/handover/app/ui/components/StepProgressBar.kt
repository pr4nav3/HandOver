package com.handover.app.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.dp
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HandOver

enum class Segment { Done, Current, CurrentMistake, Upcoming }

object Progress {
    /** One segment per step (DESIGN.md 3.3). Done screen: every segment done. No lesson: no segments. */
    fun segments(total: Int, position: Int, behindMistake: Boolean): List<Segment> = List(total.coerceAtLeast(0)) { i ->
        when {
            i < position -> Segment.Done
            i == position -> if (behindMistake) Segment.CurrentMistake else Segment.Current
            else -> Segment.Upcoming
        }
    }
}

/**
 * The step progress bar: equal segments, 4 dp tall, 3 dp gaps. Over 20 steps it becomes one bar
 * with the done part filled and a tick at the current step. With no lesson, one well segment.
 */
@Composable
fun StepProgressBar(segments: List<Segment>, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    val current = segments.indexOfFirst { it == Segment.Current || it == Segment.CurrentMistake }
    val doneCount = segments.count { it == Segment.Done }
    val spoken = if (segments.isEmpty()) "Progress, no lesson" else if (current >= 0) "Progress, step ${current + 1} of ${segments.size}" else "Progress, all ${segments.size} steps done"
    val bar = modifier.fillMaxWidth().height(4.dp).clearAndSetSemantics { contentDescription = spoken }
    val shape = RoundedCornerShape(2.dp)
    when {
        segments.isEmpty() -> Box(bar.background(c.well, shape))
        segments.size > 20 -> {
            val fraction by animateFloatAsState(doneCount / segments.size.toFloat(), HOMotion.layout(reduce), label = "fill")
            val tickColor = if (segments.getOrNull(current) == Segment.CurrentMistake) c.caution else c.accent
            Canvas(bar) {
                val r = CornerRadius(size.height / 2)
                drawRoundRect(c.well, cornerRadius = r)
                drawRoundRect(c.good, size = Size(size.width * fraction, size.height), cornerRadius = r)
                if (current >= 0) {
                    val w = size.width / segments.size
                    drawRoundRect(tickColor, topLeft = Offset(w * current, 0f), size = Size(maxOf(w, 3.dp.toPx()), size.height), cornerRadius = r)
                }
            }
        }
        else -> Row(bar, horizontalArrangement = Arrangement.spacedBy(3.dp)) {
            segments.forEach { s ->
                val target = when (s) {
                    Segment.Done -> c.good
                    Segment.Current -> c.accent
                    Segment.CurrentMistake -> c.caution
                    Segment.Upcoming -> c.well
                }
                val color by animateColorAsState(target, HOMotion.layout(reduce), label = "segment")
                Box(Modifier.weight(1f).fillMaxHeight().background(color, shape))
            }
        }
    }
}
