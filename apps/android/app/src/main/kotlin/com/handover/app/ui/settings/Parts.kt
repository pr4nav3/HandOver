package com.handover.app.ui.settings

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.Tone
import com.handover.app.ui.components.card
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.components.toneText
import com.handover.app.ui.components.toneWash
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline

// Small building blocks shared by Settings, pairing, account and onboarding: grouped rows, a
// field, a switch, a segmented control and a pushed page bar. Same shapes as vibeflux's
// DeckGroup, DeckField, DeckSwitch and DeckSegmented. Move to ui/components if others need them.

/** A section: optional header, content, optional footer (SCREENS.md 17). */
@Composable
fun FormSection(title: String?, modifier: Modifier = Modifier, footer: String? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        if (title != null) {
            Text(
                title, style = HandOver.type.section, color = HandOver.colors.ink2,
                modifier = Modifier.padding(horizontal = HOSpace.l).semantics { heading() },
            )
        }
        content()
        if (footer != null) Text(footer, style = HandOver.type.footnote, color = HandOver.colors.ink2, modifier = Modifier.padding(horizontal = HOSpace.l))
    }
}

/** Rows in one raised card, split by inset hairlines. */
@Composable
fun FormGroup(modifier: Modifier = Modifier, rows: GroupScope.() -> Unit) {
    val scope = GroupScope().apply(rows)
    Column(modifier.fillMaxWidth().card(HORadius.card)) {
        scope.items.forEachIndexed { i, row ->
            if (i > 0) HorizontalDivider(Modifier.padding(start = HOSpace.l), thickness = Hairline, color = HandOver.colors.line)
            row()
        }
    }
}

class GroupScope {
    internal val items = mutableListOf<@Composable () -> Unit>()
    fun row(content: @Composable () -> Unit) { items += content }
}

/** A rounded square holding a symbol (vibeflux DeckSymbolTile). Accent tone for the "do this" row. */
@Composable
fun SymbolTile(icon: ImageVector, modifier: Modifier = Modifier, size: Dp = 32.dp, tone: Tone? = null) {
    val c = HandOver.colors
    Box(
        modifier.size(size).background(if (tone != null) toneWash(tone) else c.well, RoundedCornerShape(size * 0.28f)),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, null, tint = if (tone != null) toneText(tone) else c.ink2, modifier = Modifier.size(size * 0.56f)) }
}

/** Pressed wash for rows. */
@Composable
fun Modifier.pressRow(label: String? = null, haptic: HOHaptic? = HOHaptic.Tap, onClick: () -> Unit): Modifier {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val haptics = rememberHaptics()
    return this
        .background(if (pressed) HandOver.colors.pressed else Color.Transparent)
        .clickable(source, indication = null, role = Role.Button, onClickLabel = label) { haptic?.let(haptics::play); onClick() }
}

/** Symbol tile, title, optional value, optional chevron. */
@Composable
fun SettingsRow(
    title: String,
    icon: ImageVector?,
    modifier: Modifier = Modifier,
    value: String? = null,
    subtitle: String? = null,
    accent: Boolean = false,
    destructive: Boolean = false,
    chevron: Boolean = false,
    trailing: (@Composable RowScope.() -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    val c = HandOver.colors
    Row(
        modifier.fillMaxWidth().heightIn(min = 56.dp)
            .then(if (onClick != null) Modifier.pressRow(onClick = onClick) else Modifier)
            .padding(horizontal = HOSpace.l, vertical = HOSpace.s),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            SymbolTile(icon, tone = when { accent -> Tone.Accent; destructive -> Tone.Bad; else -> null })
            Spacer(Modifier.width(HOSpace.m))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = HandOver.type.body, color = when { destructive -> c.bad; accent -> c.accentInk; else -> c.ink })
            if (subtitle != null) Text(subtitle, style = HandOver.type.footnote, color = c.ink2)
        }
        if (value != null) {
            Spacer(Modifier.width(HOSpace.s))
            Text(value, style = HandOver.type.body, color = c.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        trailing?.invoke(this)
        if (chevron) {
            Spacer(Modifier.width(HOSpace.xs))
            Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, null, tint = c.ink3, modifier = Modifier.size(20.dp))
        }
    }
}

/** A row with a switch. The whole row toggles. */
@Composable
fun ToggleRow(title: String, icon: ImageVector?, on: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true) {
    val c = HandOver.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .then(if (enabled) Modifier.pressRow(haptic = HOHaptic.Selection) { onChange(!on) } else Modifier)
            .semantics(mergeDescendants = true) { stateDescription = if (on) "On" else "Off" }
            .padding(start = HOSpace.l, end = HOSpace.m, top = HOSpace.s, bottom = HOSpace.s),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            SymbolTile(icon)
            Spacer(Modifier.width(HOSpace.m))
        }
        Text(title, style = HandOver.type.body, color = if (enabled) c.ink else c.ink3, modifier = Modifier.weight(1f))
        HOSwitch(on, enabled)
    }
}

/** A switch drawn in theme roles: accent track when on (DESIGN.md 2.1). Visual only; the row handles taps. */
@Composable
fun HOSwitch(on: Boolean, enabled: Boolean = true) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    val track by animateColorAsState(if (on) c.accent else c.well, HOMotion.snappy(reduce), label = "track")
    val x by animateDpAsState(if (on) 20.dp else 0.dp, HOMotion.layout(reduce), label = "knob")
    Box(
        Modifier.size(51.dp, 31.dp).clip(CircleShape).background(if (enabled) track else c.well)
            .border(Hairline, if (on) Color.Transparent else c.lineStrong, CircleShape).padding(2.dp),
    ) {
        Box(Modifier.offset(x = x).size(27.dp).background(if (on && !enabled) c.ink3 else Color.White, CircleShape).border(Hairline, Color.Black.copy(alpha = 0.06f), CircleShape))
    }
}

/** A text field: raised fill, lineStrong edge turning accent while focused (DESIGN.md 3.16). */
@Composable
fun HOField(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    leading: ImageVector? = null,
    trailing: (@Composable () -> Unit)? = null,
    style: TextStyle = HandOver.type.body,
    keyboard: KeyboardOptions = KeyboardOptions.Default,
    actions: KeyboardActions = KeyboardActions.Default,
    visual: VisualTransformation = VisualTransformation.None,
    error: Boolean = false,
    label: String = placeholder,
) {
    val c = HandOver.colors
    val source = remember { MutableInteractionSource() }
    val focused by source.collectIsFocusedAsState()
    val edge = when { error -> c.bad; focused -> c.accent; else -> c.lineStrong }
    val shape = RoundedCornerShape(HORadius.control)
    BasicTextField(
        value = value, onValueChange = onChange, singleLine = true, interactionSource = source,
        textStyle = style.copy(color = c.ink), cursorBrush = SolidColor(c.accent),
        keyboardOptions = keyboard, keyboardActions = actions, visualTransformation = visual,
        modifier = modifier.fillMaxWidth().semantics { contentDescription = label },
        decorationBox = { inner ->
            Row(
                Modifier.heightIn(min = HOSize.touch).background(c.raised, shape).border(if (focused || error) 1.dp else Hairline, edge, shape).padding(horizontal = HOSpace.m),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (leading != null) {
                    Icon(leading, null, tint = c.ink3, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(HOSpace.s))
                }
                Box(Modifier.weight(1f).padding(vertical = HOSpace.s)) {
                    if (value.isEmpty()) Text(placeholder, style = style, color = c.ink3, maxLines = 1)
                    inner()
                }
                trailing?.invoke()
            }
        },
    )
}

/** Sunken track, raised selected segment with a hairline (DESIGN.md 3.15). */
@Composable
fun <T> Segmented(options: List<T>, selected: T, title: (T) -> String, onSelect: (T) -> Unit, modifier: Modifier = Modifier, dark: Boolean = false) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    val reduce = HandOver.reduceMotion
    val index = options.indexOf(selected).coerceAtLeast(0)
    val trackColor = if (dark) Color.White.copy(alpha = 0.14f) else c.well
    val segColor = if (dark) Color.White.copy(alpha = 0.28f) else c.raised
    BoxWithConstraints(modifier.fillMaxWidth().height(36.dp).background(trackColor, RoundedCornerShape(HORadius.control)).padding(2.dp)) {
        val w = maxWidth / options.size
        val x by animateDpAsState(w * index, HOMotion.layout(reduce), label = "segment")
        Box(Modifier.offset(x = x).width(w).fillMaxHeight().background(segColor, RoundedCornerShape(HORadius.control - 2.dp)).then(if (dark) Modifier else Modifier.border(Hairline, c.lineStrong, RoundedCornerShape(HORadius.control - 2.dp))))
        Row(Modifier.fillMaxWidth().fillMaxHeight()) {
            options.forEach { o ->
                val on = o == selected
                Box(
                    Modifier.weight(1f).fillMaxHeight().clip(RoundedCornerShape(HORadius.control - 2.dp))
                        .clickable(role = Role.Tab) { if (!on) { haptics.play(HOHaptic.Selection); onSelect(o) } }
                        .semantics { stateDescription = if (on) "Selected" else "" },
                    contentAlignment = Alignment.Center,
                ) {
                    Text(title(o), style = HandOver.type.callout.copy(fontWeight = if (on) androidx.compose.ui.text.font.FontWeight.SemiBold else null),
                        color = if (dark) Color.White else if (on) c.ink else c.ink2, maxLines = 1)
                }
            }
        }
    }
}

/** The bar on a pushed page: back arrow and an inline title, plus an optional trailing action. */
@Composable
fun PushedBar(title: String, onBack: (() -> Unit)?, modifier: Modifier = Modifier, trailing: (@Composable RowScope.() -> Unit)? = null) {
    val c = HandOver.colors
    Row(modifier.fillMaxWidth().statusBarsPadding().height(56.dp).padding(horizontal = HOSpace.xs), verticalAlignment = Alignment.CenterVertically) {
        if (onBack != null) {
            Box(Modifier.size(HOSize.touch).clip(CircleShape).clickable(role = Role.Button, onClickLabel = "Back", onClick = onBack), contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Rounded.ArrowBack, "Back", tint = c.ink)
            }
        } else Spacer(Modifier.width(HOSpace.m))
        Text(title, style = HandOver.type.headline, color = c.ink, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(horizontal = HOSpace.xs).semantics { heading() })
        trailing?.invoke(this)
    }
}

/** A large title for a top-level page (DESIGN.md 2.2 largeTitle). */
@Composable
fun LargeTitle(text: String, modifier: Modifier = Modifier) {
    Text(text, style = HandOver.type.largeTitle, color = HandOver.colors.ink, modifier = modifier.padding(horizontal = HOSpace.l + HOSpace.xs, vertical = HOSpace.m).semantics { heading() })
}
