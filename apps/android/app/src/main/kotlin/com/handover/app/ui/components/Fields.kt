package com.handover.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.unit.dp
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.Hairline

/** A multi-line field (DESIGN.md 3.16): raised fill, lineStrong hairline, accent 1 dp while focused. */
@Composable
fun TextArea(value: String, onChange: (String) -> Unit, placeholder: String, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val source = remember { MutableInteractionSource() }
    val focused by source.collectIsFocusedAsState()
    val shape = RoundedCornerShape(HORadius.control)
    val style = HandOver.type.body.copy(color = c.ink)
    BasicTextField(
        value, onChange, modifier.fillMaxWidth(), textStyle = style, minLines = 3, maxLines = 6,
        cursorBrush = SolidColor(c.accent), interactionSource = source,
        decorationBox = { inner ->
            Box(
                Modifier.fillMaxWidth().heightIn(min = 88.dp).background(c.raised, shape)
                    .border(if (focused) 1.dp else Hairline, if (focused) c.accent else c.lineStrong, shape)
                    .padding(horizontal = HOSpace.m, vertical = HOSpace.s + 2.dp),
            ) {
                if (value.isEmpty()) Text(placeholder, style = style.copy(color = c.ink3))
                inner()
            }
        },
    )
}
