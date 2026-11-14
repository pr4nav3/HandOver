package com.handover.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline

object MistakeCopy {
    /** The hub's text, verbatim, with the contract's fallbacks when it is blank. */
    fun message(m: Mistake): String = m.message.ifBlank {
        if (m.kind == MistakeKind.Ahead) "You're ahead." else "This still looks like step ${m.looksLike + 1}."
    }

    /** "Show Step <looks_like + 1>" (1-based for people). */
    fun showStep(m: Mistake): String = "Show Step ${m.looksLike + 1}"
}

/**
 * The mistake card, DESIGN.md 3.2: caution wash over raised, a caution hairline at 40%, the
 * warning symbol, the hub's message, and two quiet buttons. Behind: Show Step N and I'm Fine.
 * Ahead: OK. [onVideo] draws it as a dark glass panel over the clip (landscape).
 */
@Composable
fun MistakeCard(
    mistake: Mistake,
    onShowStep: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
    radius: Dp = HORadius.control,
    onVideo: Boolean = false,
) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(radius)
    val message = MistakeCopy.message(mistake)
    val ink = if (onVideo) Color.White else c.ink
    val symbol = if (onVideo) Color(0xFFFFC46B) else c.caution
    val body = if (onVideo) {
        modifier.fillMaxWidth().glass(shape)
    } else {
        modifier.fillMaxWidth().clip(shape).background(c.raised, shape).background(c.wash(c.caution), shape)
            .border(Hairline, c.caution.copy(alpha = 0.40f), shape)
    }
    Column(
        body.padding(start = HOSpace.m, end = HOSpace.s, top = HOSpace.m, bottom = HOSpace.xs)
            .semantics { contentDescription = "Mistake. $message"; liveRegion = LiveRegionMode.Assertive },
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Icon(Icons.Rounded.Warning, null, tint = symbol, modifier = Modifier.padding(top = 1.dp).size(20.dp))
            Spacer(Modifier.width(HOSpace.s + 2.dp))
            Text(message, style = HandOver.type.headline, color = ink, maxLines = 3, modifier = Modifier.weight(1f).padding(end = HOSpace.xs))
        }
        Row(Modifier.fillMaxWidth().padding(top = HOSpace.xs), horizontalArrangement = Arrangement.spacedBy(HOSpace.xs, Alignment.End)) {
            val kind = if (onVideo) ButtonKind.Glass else ButtonKind.Quiet
            if (mistake.kind == MistakeKind.Behind) {
                HOButton(MistakeCopy.showStep(mistake), onShowStep, kind = kind, size = ButtonSize.Small)
                HOButton("I'm Fine", onDismiss, kind = kind, size = ButtonSize.Small)
            } else {
                HOButton("OK", onDismiss, kind = kind, size = ButtonSize.Small)
            }
        }
    }
}
