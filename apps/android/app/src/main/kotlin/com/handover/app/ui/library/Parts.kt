package com.handover.app.ui.library

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.Hairline
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.LocalHapticsEnabled
import kotlinx.coroutines.delay
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.Pill

// Small pieces the Library, Teach, Record and Editor screens share. Buttons, cards, badges, empty states and
// haptics come from ui/components (the shared design system); these adapters keep the call sites short.

typealias Tone = com.handover.app.ui.components.Tone

/** DESIGN.md section 4 haptics through ui/components, named for what these screens do. */
class Haptics(private val inner: com.handover.app.ui.components.Haptics) {
    fun tap() = inner.play(HOHaptic.Tap)
    fun segment() = inner.play(HOHaptic.Selection)
    fun snap() = inner.play(HOHaptic.Snap)
    fun success() = inner.play(HOHaptic.Success)
    fun error() = inner.play(HOHaptic.Error)
    fun recordStart() = inner.play(HOHaptic.Heavy)
    fun recordStop() = inner.play(HOHaptic.StepChange)
}

@Composable
fun rememberHaptics(): Haptics {
    val inner = com.handover.app.ui.components.rememberHaptics()
    return remember(inner) { Haptics(inner) }
}

/** DESIGN.md 3.1 badge: a capsule in the tone's wash. */
@Composable
fun Badge(text: String, tone: Tone = Tone.Neutral, modifier: Modifier = Modifier) = Pill(text, tone, modifier)

/** A `raised` card with a hairline (DESIGN.md 2.6). */
@Composable
fun HOCard(modifier: Modifier = Modifier, radius: Dp = HORadius.card, padding: Dp = HOSpace.l, content: @Composable ColumnScope.() -> Unit) =
    com.handover.app.ui.components.HOCard(modifier, padding, radius, content)

@Composable
fun SectionHeader(text: String, modifier: Modifier = Modifier, trailing: @Composable (() -> Unit)? = null) {
    Row(modifier.fillMaxWidth().padding(top = HOSpace.xl, bottom = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = HandOver.type.section, color = HandOver.colors.ink2, modifier = Modifier.weight(1f))
        trailing?.invoke()
    }
}

/** DESIGN.md 3.11, centered. The loading variant shows only after 0.5 s, so a fast load never flashes a spinner. */
@Composable
fun EmptyState(
    icon: ImageVector?,
    title: String,
    message: String? = null,
    modifier: Modifier = Modifier,
    tone: Tone = Tone.Neutral,
    loading: Boolean = false,
    actions: @Composable () -> Unit = {},
) {
    var show by remember { mutableStateOf(!loading) }
    if (loading) LaunchedEffect(Unit) { delay(500); show = true }
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (show) com.handover.app.ui.components.EmptyState(
            title, message, icon = icon, tone = tone.takeIf { it != Tone.Neutral }, loading = loading, actions = { actions() },
        )
    }
}

/** The one filled button per screen (DESIGN.md 3.7). */
@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, large: Boolean = true, icon: ImageVector? = null) =
    HOButton(text, onClick, modifier, ButtonKind.Primary, if (large) ButtonSize.Large else ButtonSize.Regular, enabled, icon)

@Composable
fun SecondaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, large: Boolean = false, icon: ImageVector? = null, destructive: Boolean = false) =
    HOButton(text, onClick, modifier, if (destructive) ButtonKind.Destructive else ButtonKind.Secondary, if (large) ButtonSize.Large else ButtonSize.Regular, enabled, icon)

@Composable
fun QuietButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true, icon: ImageVector? = null, color: Color? = null) {
    if (color == null) HOButton(text, onClick, modifier, ButtonKind.Quiet, ButtonSize.Regular, enabled, icon)
    else {
        // On video: plain white words, no fill.
        val haptics = rememberHaptics()
        TextButton(onClick = { haptics.tap(); onClick() }, enabled = enabled, modifier = modifier.heightIn(min = HOSize.touch)) {
            Text(text, style = HandOver.type.bodyMedium, color = color)
        }
    }
}

/** DESIGN.md 3.21: track in `well`, fill in `accent` (or `good` when complete), round caps. */
@Composable
fun ProgressRing(fraction: Float, modifier: Modifier = Modifier, size: Dp = 28.dp, stroke: Dp = 4.dp, complete: Boolean = false) {
    val c = HandOver.colors
    Canvas(modifier.size(size)) {
        val s = Stroke(stroke.toPx(), cap = StrokeCap.Round)
        val inset = stroke.toPx() / 2
        val arcSize = androidx.compose.ui.geometry.Size(this.size.width - inset * 2, this.size.height - inset * 2)
        val topLeft = androidx.compose.ui.geometry.Offset(inset, inset)
        drawArc(c.well, 0f, 360f, false, topLeft, arcSize, style = s)
        drawArc(if (complete) c.good else c.accent, -90f, 360f * fraction.coerceIn(0f, 1f), false, topLeft, arcSize, style = s)
    }
}

/**
 * DESIGN.md 3.15 as a scrolling chip row: sunken track, the selected segment raised with a hairline.
 * A chip row instead of fixed segments because org names make the count open-ended (SCREENS.md section 5).
 */
@Composable
fun <T> SegmentedRow(options: List<T>, selected: T, label: (T) -> String, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    Row(
        modifier.clip(RoundedCornerShape(HORadius.control)).background(c.well).horizontalScroll(rememberScrollState()).padding(3.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        options.forEach { option ->
            val on = option == selected
            val shape = RoundedCornerShape(HORadius.control - 3.dp)
            Box(
                Modifier
                    .heightIn(min = 36.dp)
                    .clip(shape)
                    .then(if (on) Modifier.background(c.raised).border(Hairline, c.lineStrong, shape) else Modifier)
                    .clickable(role = Role.Tab) { if (!on) { haptics.segment(); onSelect(option) } }
                    .semantics { contentDescription = label(option) + if (on) ", selected" else "" }
                    .padding(horizontal = HOSpace.m, vertical = HOSpace.s),
                contentAlignment = Alignment.Center,
            ) {
                Text(label(option), style = HandOver.type.badge.copy(fontSize = HandOver.type.callout.fontSize), color = if (on) c.ink else c.ink2, maxLines = 1)
            }
        }
    }
}
