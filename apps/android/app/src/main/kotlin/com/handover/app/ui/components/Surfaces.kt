package com.handover.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline

/** What a dot, badge or message means. One mapping from meaning to color (vibeflux `Tone`). */
enum class Tone { Neutral, Accent, Good, Caution, Bad, Idle }

@Composable
fun toneColor(t: Tone): Color {
    val c = HandOver.colors
    return when (t) {
        Tone.Neutral -> c.ink2
        Tone.Accent -> c.accent
        Tone.Good -> c.good
        Tone.Caution -> c.caution
        Tone.Bad -> c.bad
        Tone.Idle -> c.idle
    }
}

@Composable
fun toneText(t: Tone): Color {
    val c = HandOver.colors
    return when (t) {
        Tone.Neutral, Tone.Idle -> c.ink2
        Tone.Accent -> c.accentInk
        Tone.Good -> c.good
        Tone.Caution -> c.caution
        Tone.Bad -> c.bad
    }
}

@Composable
fun toneWash(t: Tone): Color {
    val c = HandOver.colors
    return when (t) {
        Tone.Neutral, Tone.Idle -> c.well
        Tone.Accent -> c.accentSoft
        else -> c.wash(toneColor(t))
    }
}

/** A raised card: the raised fill with a hairline edge (DESIGN.md 2.6). */
@Composable
fun Modifier.card(radius: Dp = HORadius.card, fill: Color? = null, edge: Color? = null): Modifier {
    val c = HandOver.colors
    val shape = RoundedCornerShape(radius)
    return this.clip(shape).background(fill ?: c.raised, shape).border(Hairline, edge ?: c.line, shape)
}

@Composable
fun HOCard(modifier: Modifier = Modifier, padding: Dp = HOSpace.l, radius: Dp = HORadius.card, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier.card(radius).padding(padding), content = content)
}

/** Something that floats (toasts, the PiP tile): a soft two-layer shadow (DESIGN.md 2.6). */
@Composable
fun Modifier.floating(radius: Dp = HORadius.panel, fill: Color? = null): Modifier {
    val c = HandOver.colors
    val shape = RoundedCornerShape(radius)
    return this
        .shadow(if (c.isDark) 18.dp else 14.dp, shape, ambientColor = Color.Black.copy(alpha = if (c.isDark) 0.30f else 0.06f), spotColor = Color.Black.copy(alpha = if (c.isDark) 0.45f else 0.16f))
        .background(fill ?: c.raised, shape)
        .border(Hairline, c.line, shape)
}

/**
 * Android has no Liquid Glass; controls over video use a dark translucent capsule with a white
 * hairline, forced dark so their content reads on any frame (DESIGN.md 2.6).
 */
fun Modifier.glass(shape: androidx.compose.ui.graphics.Shape = CircleShape): Modifier =
    this.clip(shape).background(Color.Black.copy(alpha = 0.55f), shape).border(Hairline, Color.White.copy(alpha = 0.20f), shape)

/** A plain, still status dot. Nothing pulses (DESIGN.md principle 8). */
@Composable
fun StatusDot(color: Color, modifier: Modifier = Modifier, size: Dp = 8.dp) {
    androidx.compose.foundation.layout.Box(modifier.size(size).background(color, CircleShape))
}

/** A small capsule chip: symbol and words in a tone, on its wash. */
@Composable
fun Pill(text: String, tone: Tone, modifier: Modifier = Modifier, icon: ImageVector? = null) {
    Row(
        modifier.background(toneWash(tone), CircleShape).padding(horizontal = 9.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, null, tint = toneText(tone), modifier = Modifier.size(13.dp))
            Spacer(Modifier.width(4.dp))
        }
        Text(text, style = HandOver.type.badge, color = toneText(tone), maxLines = 1)
    }
}

/** A slim card for an ongoing condition (DESIGN.md 3.12). */
@Composable
fun Banner(text: String, icon: ImageVector, tone: Tone, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Row(
        modifier.fillMaxWidth().card(HORadius.control).padding(horizontal = HOSpace.m, vertical = HOSpace.s + 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, null, tint = toneText(tone), modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(HOSpace.s))
        Text(text, style = HandOver.type.footnote, color = HandOver.colors.ink2, maxLines = 3, modifier = Modifier.weight(1f))
        if (action != null) {
            Spacer(Modifier.width(HOSpace.s))
            action()
        }
    }
}

/** Centered symbol, title, message and actions for empty and error states (DESIGN.md 3.11). */
@Composable
fun EmptyState(
    title: String,
    message: String?,
    modifier: Modifier = Modifier,
    icon: ImageVector? = null,
    tone: Tone? = null,
    loading: Boolean = false,
    actions: @Composable ColumnScope.() -> Unit = {},
) {
    val c = HandOver.colors
    Column(
        modifier.fillMaxWidth().padding(HOSpace.xl),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(HOSpace.m, Alignment.CenterVertically),
    ) {
        if (loading) {
            CircularProgressIndicator(color = c.ink2, strokeWidth = 2.5.dp, modifier = Modifier.size(32.dp))
        } else if (icon != null) {
            Icon(icon, null, tint = tone?.let { toneText(it) } ?: c.ink2, modifier = Modifier.size(44.dp))
        }
        Text(title, style = HandOver.type.title, color = c.ink, textAlign = TextAlign.Center)
        if (message != null) {
            Text(message, style = HandOver.type.callout, color = c.ink2, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 320.dp))
        }
        Column(Modifier.padding(top = HOSpace.s), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s), content = actions)
    }
}
