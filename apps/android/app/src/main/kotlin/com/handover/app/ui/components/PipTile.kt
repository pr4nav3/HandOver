package com.handover.app.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.VectorConverter
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline
import kotlinx.coroutines.launch
import kotlin.math.max
import kotlin.math.roundToInt

/** Room the floating tile takes at the bottom of the large pane, so captions sit above it. */
val LocalPipClearance = androidx.compose.runtime.compositionLocalOf { 0.dp }

enum class Corner(val words: String) { TopLeft("Top Left"), TopRight("Top Right"), BottomLeft("Bottom Left"), BottomRight("Bottom Right") }

object PipMath {
    /**
     * The corner a tile thrown from [center] with [velocity] (px per second) lands in, inside a
     * container of [w] x [h]. Velocity carries it: the release point is projected 0.15 s ahead.
     */
    fun corner(center: Offset, velocity: Offset, w: Float, h: Float): Corner {
        val x = center.x + velocity.x * 0.15f
        val y = center.y + velocity.y * 0.15f
        val left = x < w / 2
        val top = y < h / 2
        return when {
            top && left -> Corner.TopLeft
            top -> Corner.TopRight
            left -> Corner.BottomLeft
            else -> Corner.BottomRight
        }
    }
}

/**
 * The floating preview tile over the large video (DESIGN.md 3.6): 30% of the width (at least
 * 112 dp), the aspect of its content, pip radius, floating shadow and a white 20% hairline. Tap
 * swaps; drag follows the finger and snaps to the nearest corner on release, inset `l`.
 */
@Composable
fun PipHost(
    large: @Composable (Modifier) -> Unit,
    small: @Composable (Modifier) -> Unit,
    smallAspect: Float,
    corner: Corner,
    onCorner: (Corner) -> Unit,
    onSwap: () -> Unit,
    smallLabel: String,
    modifier: Modifier = Modifier,
) {
    val reduce = HandOver.reduceMotion
    val haptics = rememberHaptics()
    BoxWithConstraints(modifier) {
        val density = LocalDensity.current
        val tileW = max(maxWidth.value * HOSize.PIP_FRACTION, HOSize.pipMinWidth.value).dp
        val tileH = tileW / smallAspect.coerceIn(0.4f, 2.5f)
        val bottom = corner == Corner.BottomLeft || corner == Corner.BottomRight
        androidx.compose.runtime.CompositionLocalProvider(LocalPipClearance provides if (bottom) tileH + HOSpace.s else 0.dp) {
            large(Modifier.fillMaxSize())
        }
        val inset = with(density) { HOSpace.s.toPx() }
        val wPx = with(density) { maxWidth.toPx() }
        val hPx = with(density) { maxHeight.toPx() }
        val tw = with(density) { tileW.toPx() }
        val th = with(density) { tileH.toPx() }
        fun target(c: Corner) = Offset(
            if (c == Corner.TopLeft || c == Corner.BottomLeft) inset else wPx - tw - inset,
            if (c == Corner.TopLeft || c == Corner.TopRight) inset else hPx - th - inset,
        )
        val pos = remember { Animatable(target(corner), Offset.VectorConverter) }
        val scope = rememberCoroutineScope()
        LaunchedEffect(corner, wPx, hPx, tw, th) { pos.animateTo(target(corner), HOMotion.layout(reduce)) }
        val shape = RoundedCornerShape(HORadius.pip)
        Box(
            Modifier
                .offset { IntOffset(pos.value.x.roundToInt(), pos.value.y.roundToInt()) }
                .size(tileW, tileH)
                .shadow(14.dp, shape, ambientColor = Color.Black.copy(alpha = 0.3f), spotColor = Color.Black.copy(alpha = 0.45f))
                .clip(shape)
                .border(Hairline, Color.White.copy(alpha = 0.20f), shape)
                .pointerInput(wPx, hPx, tw, th) {
                    val tracker = VelocityTracker()
                    detectDragGestures(
                        onDragStart = { tracker.resetTracking() },
                        onDragEnd = {
                            val v = tracker.calculateVelocity()
                            val c = PipMath.corner(pos.value + Offset(tw / 2, th / 2), Offset(v.x, v.y), wPx, hPx)
                            scope.launch { pos.animateTo(target(c), HOMotion.layout(reduce)); haptics.play(HOHaptic.Tap) }
                            onCorner(c)
                        },
                        onDragCancel = { scope.launch { pos.animateTo(target(corner), HOMotion.layout(reduce)) } },
                    ) { change, drag ->
                        change.consume()
                        tracker.addPosition(change.uptimeMillis, change.position)
                        scope.launch {
                            pos.snapTo(Offset((pos.value.x + drag.x).coerceIn(0f, wPx - tw), (pos.value.y + drag.y).coerceIn(0f, hPx - th)))
                        }
                    }
                }
                .clickable(remember { MutableInteractionSource() }, indication = null) { haptics.play(HOHaptic.Tap); onSwap() }
                .semantics {
                    role = Role.Button
                    contentDescription = "$smallLabel, small. Double tap to swap."
                    customActions = listOf(CustomAccessibilityAction("Swap") { onSwap(); true }) +
                        Corner.entries.map { c -> CustomAccessibilityAction("Move to ${c.words}") { onCorner(c); true } }
                },
        ) { small(Modifier.fillMaxSize()) }
    }
}
