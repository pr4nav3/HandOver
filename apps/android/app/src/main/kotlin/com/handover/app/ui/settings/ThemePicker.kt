package com.handover.app.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageShader
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.ShaderBrush
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.theme.Appearance
import com.handover.app.ui.theme.ColorRoles
import com.handover.app.ui.theme.HOGrain
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline
import com.handover.app.ui.theme.ThemeCatalog
import com.handover.app.ui.theme.ThemeGroup
import com.handover.app.ui.theme.ThemeLooks
import com.handover.app.ui.theme.ThemeSpec

/** Whether [spec] matches the picker search (THEMES.md, Theme picker): name, one line, group and keywords. */
fun ThemeSpec.matches(query: String): Boolean {
    val q = query.trim().lowercase()
    if (q.isEmpty()) return true
    return listOf(name, blurb, group.title, keywords, looks.words).any { q in it.lowercase() }
}

/**
 * The theme picker (THEMES.md, Theme picker): Appearance, a search field, then the 14 themes in
 * Classic, Grain, Color and Mono, two cards per row (four on wide screens). Each card is a
 * miniature drawn in that theme's own colors, light and dark side by side for themes with two looks.
 */
@Composable
fun ThemePicker(selected: ThemeSpec, appearance: Appearance, onSelect: (ThemeSpec) -> Unit, onAppearance: (Appearance) -> Unit, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    var query by remember { mutableStateOf("") }
    val shown = ThemeCatalog.all.filter { it.matches(query) }
    BoxWithConstraints(modifier) {
        val columns = if (maxWidth >= 600.dp) 4 else 2
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
            FormSection("Appearance", footer = "Themes with one look keep it.") {
                Segmented(Appearance.entries, appearance, { it.title }, onAppearance)
            }
            HOField(query, { query = it }, "Search ${ThemeCatalog.all.size} themes", leading = Icons.Outlined.Search, label = "Search themes")
            if (shown.isEmpty()) Text("No themes match.", style = HandOver.type.body, color = c.ink2, modifier = Modifier.padding(horizontal = HOSpace.xs))
            ThemeGroup.entries.forEach { group ->
                val items = shown.filter { it.group == group }
                if (items.isNotEmpty()) FormSection(group.title) {
                    Column(verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
                        items.chunked(columns).forEach { row ->
                            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                                row.forEach { t -> ThemeCard(t, t.id == selected.id, Modifier.weight(1f)) { onSelect(t) } }
                                repeat(columns - row.size) { Spacer(Modifier.weight(1f)) }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** One picker card: the miniature, the name and the one line. Selected: a 2 dp accent ring and a check. */
@Composable
fun ThemeCard(theme: ThemeSpec, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val c = HandOver.colors
    val spoken = "${theme.name}, ${theme.blurb.lowercase()}, ${theme.looks.words}." + if (selected) " Selected." else ""
    Column(
        modifier.clip(RoundedCornerShape(HORadius.card + 4.dp)).pressRow(haptic = HOHaptic.Selection, onClick = onClick)
            .clearAndSetSemantics { contentDescription = spoken; role = Role.RadioButton; this.selected = selected },
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box {
            val shape = RoundedCornerShape(HORadius.card)
            Box(
                Modifier.fillMaxWidth()
                    .border(2.dp, if (selected) c.accent else Color.Transparent, RoundedCornerShape(HORadius.card + 3.dp)).padding(3.dp)
                    .aspectRatio(1.45f).clip(shape).border(Hairline, c.line, shape),
            ) { ThemeMiniature(theme) }
            if (selected) {
                Icon(
                    Icons.Rounded.CheckCircle, null, tint = c.accent,
                    modifier = Modifier.align(Alignment.BottomEnd).offset(4.dp, 4.dp).size(24.dp).background(c.paper, CircleShape),
                )
            }
        }
        Column(Modifier.padding(horizontal = 4.dp).padding(bottom = 4.dp)) {
            Text(theme.name, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1)
            Text(theme.blurb, style = HandOver.type.caption, color = c.ink2, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Light on the left half and dark on the right for themes with two looks; one look fills the card. */
@Composable
fun ThemeMiniature(theme: ThemeSpec, modifier: Modifier = Modifier) {
    if (theme.looks == ThemeLooks.FollowsSystem) {
        Box(modifier.fillMaxSize()) {
            Miniature(theme.light, Modifier.fillMaxSize())
            Box(Modifier.fillMaxSize().clip(RightHalf)) { Miniature(theme.dark, Modifier.fillMaxSize()) }
        }
    } else Miniature(if (theme.looks == ThemeLooks.AlwaysDark) theme.dark else theme.light, modifier.fillMaxSize())
}

private object RightHalf : Shape {
    override fun createOutline(size: androidx.compose.ui.geometry.Size, layoutDirection: LayoutDirection, density: Density) =
        Outline.Rectangle(Rect(size.width / 2, 0f, size.width, size.height))
}

/** Paper (with grain if the look has it), a raised card with a line of ink and ink2, and an accent pill. */
@Composable
private fun Miniature(r: ColorRoles, modifier: Modifier) {
    val grain = remember(r.grain) { r.grain?.let { ShaderBrush(ImageShader(HOGrain.tile(it), TileMode.Repeated, TileMode.Repeated)) } }
    Box(modifier.background(r.paper).then(if (grain != null) Modifier.background(grain) else Modifier).padding(10.dp)) {
        Column(
            Modifier.fillMaxWidth().fillMaxHeight(0.78f).clip(RoundedCornerShape(8.dp)).background(r.raised).border(Hairline, r.line, RoundedCornerShape(8.dp)).padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            Box(Modifier.fillMaxWidth(0.72f).height(6.dp).background(r.ink, CircleShape))
            Box(Modifier.fillMaxWidth(0.5f).height(5.dp).background(r.ink2, CircleShape))
            Spacer(Modifier.weight(1f))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.width(30.dp).height(11.dp).background(r.accent, CircleShape))
                Spacer(Modifier.width(5.dp))
                Box(Modifier.size(7.dp).background(r.good, CircleShape))
            }
        }
    }
}
