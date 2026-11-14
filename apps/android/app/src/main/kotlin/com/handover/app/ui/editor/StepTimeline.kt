package com.handover.app.ui.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.setProgress
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.handover.app.core.Lesson
import com.handover.app.ui.library.HubImage
import com.handover.app.ui.library.clock
import com.handover.app.ui.library.rememberHaptics
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import kotlin.math.roundToInt

/** DESIGN.md 3.18 step hues: deep enough to reach 3:1 as marks on `well` in light themes. */
val StepHues = listOf(
    Color(0xFF4F78A8), Color(0xFF5E8B62), Color(0xFFA87A3E), Color(0xFF7E62A0),
    Color(0xFFA85E57), Color(0xFF3F8A86), Color(0xFF8C7E2E), Color(0xFF6268A8),
)

private val TrackHeight = 44.dp
private val GripHit = 32.dp

/**
 * The timeline (DESIGN.md 3.18): one colored segment per step on a `well` track, the step number in a small
 * `raised` pill, the selected segment outlined in `ink`. With [editable], each boundary has a grip that drags,
 * snapping to [snaps] (caption cue edges) within 0.4 s with a tick each time it lands on a new edge.
 * [thumbnails] (one URL per step) draws a strip of clip frames under the track.
 */
@Composable
fun StepTimeline(
    lesson: Lesson,
    selected: Int?,
    modifier: Modifier = Modifier,
    editable: Boolean = false,
    snaps: List<Double> = emptyList(),
    thumbnails: List<String>? = null,
    playhead: Double? = null,
    onSelect: (Int) -> Unit = {},
    onDrag: (k: Int, t: Double) -> Unit = { _, _ -> },
    onDragEnd: (k: Int, t: Double) -> Unit = { _, _ -> },
) {
    val c = HandOver.colors
    val mono = HandOver.isMono
    val total = lesson.totalSeconds().takeIf { it > 0 } ?: return
    val haptics = rememberHaptics()
    val density = LocalDensity.current
    var dragLabel by remember { mutableStateOf<Pair<Float, String>?>(null) }
    val currentLesson by rememberUpdatedState(lesson)
    val currentSnaps by rememberUpdatedState(snaps)

    Column(modifier) {
        BoxWithConstraints(Modifier.fillMaxWidth().height(TrackHeight + if (editable) 20.dp else 0.dp)) {
            val widthPx = with(density) { maxWidth.toPx() }
            fun xOf(t: Double): Dp = maxWidth * (t / total).toFloat()
            // Floating time label while dragging.
            dragLabel?.let { (x, text) ->
                Text(
                    text,
                    style = HandOver.type.caption,
                    color = c.onAccent,
                    modifier = Modifier.offset { IntOffset((x - with(density) { 28.dp.toPx() }).roundToInt().coerceIn(0, (widthPx - with(density) { 56.dp.toPx() }).roundToInt().coerceAtLeast(0)), 0) }
                        .clip(CircleShape).background(c.accent).padding(horizontal = 6.dp, vertical = 1.dp),
                )
            }
            Box(
                Modifier.align(Alignment.BottomStart).fillMaxWidth().height(TrackHeight)
                    .clip(RoundedCornerShape(HORadius.small)).background(c.well),
            ) {
                lesson.steps.forEachIndexed { i, step ->
                    val a = step.startSeconds()
                    val b = step.endSeconds()
                    val w = xOf(b - a)
                    val hue = if (mono) c.ink2.copy(alpha = if (i % 2 == 0) 0.35f else 0.22f) else StepHues[i % StepHues.size]
                    val isSelected = i == selected
                    Box(
                        Modifier.offset(x = xOf(a)).width(w).fillMaxHeight().padding(end = 1.dp)
                            .background(hue)
                            .then(if (isSelected) Modifier.border(2.dp, c.ink) else Modifier)
                            .clickable { haptics.tap(); onSelect(i) }
                            .semantics { contentDescription = "Step ${i + 1}, ${step.title}, ${clock(a)} to ${clock(b)}" + if (isSelected) ", selected" else "" },
                    ) {
                        if (w >= 26.dp) {
                            Text(
                                "${i + 1}",
                                style = HandOver.type.badge,
                                color = c.ink,
                                maxLines = 1,
                                modifier = Modifier.padding(4.dp).height(16.dp).clip(RoundedCornerShape(8.dp)).background(c.raised).padding(horizontal = 5.dp),
                            )
                        }
                    }
                }
                playhead?.let { p ->
                    Box(Modifier.offset(x = xOf(p) - 1.dp).width(2.dp).fillMaxHeight().background(c.ink))
                }
            }
            playhead?.let { p ->
                Box(Modifier.align(Alignment.BottomStart).offset(x = xOf(p) - 5.dp, y = -(TrackHeight - 2.dp)).size(10.dp).clip(CircleShape).background(c.ink))
            }
            if (editable) {
                lesson.boundaries().forEachIndexed { k, t ->
                    var lastSnap by remember(k) { mutableStateOf<Double?>(null) }
                    var dragX by remember(k) { mutableStateOf(0f) }
                    Box(
                        Modifier.align(Alignment.BottomStart).offset(x = xOf(t) - GripHit / 2).width(GripHit).height(TrackHeight)
                            .semantics {
                                contentDescription = "Boundary between step ${k + 1} and step ${k + 2}, ${formatEditorTime(t)}"
                                progressBarRangeInfo = ProgressBarRangeInfo(t.toFloat(), 0f..total.toFloat())
                                setProgress { v -> onDragEnd(k, v.toDouble()); true }
                            }
                            .pointerInput(k, total, widthPx) {
                                detectHorizontalDragGestures(
                                    onDragStart = {
                                        dragX = (currentLesson.boundaries().getOrNull(k) ?: 0.0).toFloat() / total.toFloat() * widthPx
                                        lastSnap = null
                                    },
                                    onDragEnd = {
                                        val raw = dragX / widthPx * total
                                        val (snapped, _) = snap(raw, currentSnaps)
                                        dragLabel = null
                                        onDragEnd(k, snapped.coerceIn(currentLesson.boundaryRange(k)))
                                    },
                                    onDragCancel = { dragLabel = null; onDragEnd(k, currentLesson.boundaries().getOrNull(k) ?: t) },
                                ) { change, amount ->
                                    change.consume()
                                    dragX = (dragX + amount).coerceIn(0f, widthPx)
                                    val (snapped, didSnap) = snap(dragX / widthPx * total, currentSnaps)
                                    val clamped = snapped.coerceIn(currentLesson.boundaryRange(k))
                                    if (didSnap && snapped != lastSnap) haptics.snap()
                                    lastSnap = if (didSnap) snapped else null
                                    dragLabel = (clamped / total * widthPx).toFloat() to formatEditorTime(clamped)
                                    onDrag(k, clamped)
                                }
                            },
                        contentAlignment = Alignment.Center,
                    ) {
                        Box(Modifier.width(4.dp).height(24.dp).clip(RoundedCornerShape(2.dp)).background(c.raised).border(0.6.dp, c.lineStrong, RoundedCornerShape(2.dp)))
                    }
                }
            }
        }
        if (thumbnails != null) {
            Spacer(Modifier.height(HOSpace.xs))
            BoxWithConstraints(Modifier.fillMaxWidth().height(40.dp)) {
                lesson.steps.forEachIndexed { i, step ->
                    val a = step.startSeconds()
                    val w = maxWidth * ((step.endSeconds() - a) / total).toFloat()
                    if (w >= 24.dp) {
                        HubImage(
                            listOfNotNull(thumbnails.getOrNull(i)),
                            Modifier.offset(x = maxWidth * (a / total).toFloat()).width(w).fillMaxHeight().padding(end = 1.dp).clip(RoundedCornerShape(4.dp))
                                .clickable { onSelect(i) },
                        )
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = HOSpace.xs)) {
            Text("00:00", style = HandOver.type.caption, color = c.ink2, modifier = Modifier.weight(1f))
            Text(clock(total).padStart(5, '0'), style = HandOver.type.caption, color = c.ink2)
        }
    }
}
