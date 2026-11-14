package com.handover.app.ui.components

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline

/** DESIGN.md 3.7. Primary is the accent fill, one per screen. */
enum class ButtonKind { Primary, Secondary, Quiet, Destructive, Glass }
enum class ButtonSize { Small, Regular, Large }

/**
 * A HandOver button. Pressed: scale 0.98 (off with Reduce Motion) and the primary fill at 82%.
 * Disabled: `well` fill and `ink3` text (quiet stays clear). Plays the tap haptic.
 */
@Composable
fun HOButton(
    text: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    kind: ButtonKind = ButtonKind.Secondary,
    size: ButtonSize = ButtonSize.Regular,
    enabled: Boolean = true,
    icon: ImageVector? = null,
    /** Spoken label when [text] is null (icon only). */
    label: String? = null,
    haptic: HOHaptic? = HOHaptic.Tap,
) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val reduce = HandOver.reduceMotion
    val shape = RoundedCornerShape(if (size == ButtonSize.Large) HORadius.buttonLarge else HORadius.control)
    val fill = when {
        !enabled -> if (kind == ButtonKind.Quiet) Color.Transparent else if (kind == ButtonKind.Glass) Color.Black.copy(alpha = 0.35f) else c.well
        kind == ButtonKind.Primary -> c.accent.copy(alpha = if (pressed) 0.82f else 1f)
        kind == ButtonKind.Quiet -> if (pressed) c.pressed else Color.Transparent
        kind == ButtonKind.Glass -> Color.Black.copy(alpha = if (pressed) 0.70f else 0.55f)
        else -> if (pressed) c.well else c.raised
    }
    val fg = when {
        kind == ButtonKind.Glass -> Color.White.copy(alpha = if (enabled) 1f else 0.45f)
        !enabled -> c.ink3
        kind == ButtonKind.Primary -> c.onAccent
        kind == ButtonKind.Destructive -> c.bad
        else -> c.ink
    }
    val edge = when (kind) {
        ButtonKind.Secondary, ButtonKind.Destructive -> c.line
        ButtonKind.Glass -> Color.White.copy(alpha = 0.20f)
        else -> null
    }
    val height = when (size) {
        ButtonSize.Small -> HOSize.controlSmall
        ButtonSize.Regular -> HOSize.control
        ButtonSize.Large -> HOSize.controlLarge
    }
    val hp = if (text == null) HOSpace.s else when (size) {
        ButtonSize.Small -> HOSpace.m
        ButtonSize.Regular -> HOSpace.l
        ButtonSize.Large -> HOSpace.xl
    }
    val scale by animateFloatAsState(if (pressed && !reduce) 0.98f else 1f, HOMotion.press(), label = "press")
    Row(
        modifier
            .scale(scale)
            .heightIn(min = height)
            .then(if (text == null) Modifier.sizeIn(minWidth = height) else Modifier)
            .background(fill, shape)
            .then(if (edge != null) Modifier.border(Hairline, edge, shape) else Modifier)
            .clickable(source, indication = null, enabled = enabled, role = Role.Button, onClickLabel = label) {
                haptic?.let(haptics::play)
                onClick()
            }
            .then(if (text == null && label != null) Modifier.semantics { contentDescription = label } else Modifier)
            .padding(horizontal = hp, vertical = HOSpace.xs),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, null, tint = fg, modifier = Modifier.size(if (size == ButtonSize.Small) 16.dp else 20.dp))
            if (text != null) Spacer(Modifier.width(HOSpace.s))
        }
        if (text != null) {
            Text(
                text,
                style = (if (size == ButtonSize.Small) HandOver.type.callout else HandOver.type.body).copy(fontWeight = FontWeight.SemiBold),
                color = fg,
                maxLines = if (size == ButtonSize.Small) 1 else 2,
                textAlign = TextAlign.Center,
            )
        }
    }
}

@Composable
fun PrimaryButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, size: ButtonSize = ButtonSize.Large, enabled: Boolean = true, fullWidth: Boolean = false, haptic: HOHaptic? = HOHaptic.Tap) =
    HOButton(text, onClick, if (fullWidth) modifier.fillMaxWidth() else modifier, ButtonKind.Primary, size, enabled, haptic = haptic)

@Composable
fun SecondaryButton(text: String?, onClick: () -> Unit, modifier: Modifier = Modifier, size: ButtonSize = ButtonSize.Regular, enabled: Boolean = true, icon: ImageVector? = null, label: String? = null, haptic: HOHaptic? = HOHaptic.Tap) =
    HOButton(text, onClick, modifier, ButtonKind.Secondary, size, enabled, icon, label, haptic)

@Composable
fun QuietButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, size: ButtonSize = ButtonSize.Small, enabled: Boolean = true) =
    HOButton(text, onClick, modifier, ButtonKind.Quiet, size, enabled)

/** A round symbol-only button, 36 visible inside a 48 dp target. Glass when it sits on video. */
@Composable
fun IconCircleButton(icon: ImageVector, label: String, onClick: () -> Unit, modifier: Modifier = Modifier, onVideo: Boolean = false, diameter: Dp = HOSize.iconButton) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    Box(
        modifier.sizeIn(minWidth = HOSize.touch, minHeight = HOSize.touch)
            .clickable(source, indication = null, onClickLabel = label, role = Role.Button) { haptics.play(HOHaptic.Tap); onClick() },
        contentAlignment = Alignment.Center,
    ) {
        val inner = Modifier.size(diameter)
        Box(
            if (onVideo) inner.glass() else inner.background(if (pressed) c.well else c.raised, CircleShape).border(Hairline, c.line, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, label, tint = if (onVideo) Color.White else c.ink, modifier = Modifier.size(diameter * 0.52f))
        }
    }
}
