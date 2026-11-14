package com.handover.app.ui.done

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.core.content.edit
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.StarRating
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver

/** Offered once per lesson on this device (SCREENS.md 9): shown, sent or skipped, never asked again. */
class RatingPrompts(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("handover", Context.MODE_PRIVATE)
    fun asked(lessonId: String): Boolean = prefs.getBoolean("rating_asked:$lessonId", false)
    fun markAsked(lessonId: String) = prefs.edit { putBoolean("rating_asked:$lessonId", true) }
}

/** "Rate this lesson": stars, an optional comment, Send and Not Now. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RatingSheet(onSend: (stars: Int, comment: String?) -> Unit, onNotNow: () -> Unit, accounts: Boolean = false) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onNotNow, sheetState = state, containerColor = HandOver.colors.raised) {
        RatingBody(onSend, onNotNow, accounts)
    }
}

@Composable
fun RatingBody(onSend: (Int, String?) -> Unit, onNotNow: () -> Unit, accounts: Boolean = false) {
    val c = HandOver.colors
    var stars by remember { mutableIntStateOf(0) }
    var comment by remember { mutableStateOf("") }
    Column(
        Modifier.fillMaxWidth().padding(horizontal = HOSpace.l).padding(bottom = HOSpace.l).navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(HOSpace.m),
    ) {
        Text("Rate this lesson", style = HandOver.type.title, color = c.ink)
        StarRating(stars, { stars = it })
        com.handover.app.ui.components.TextArea(comment, { if (it.length <= 500) comment = it }, "What helped or got in the way? (optional)")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
            HOButton("Not Now", onNotNow, Modifier.weight(1f), ButtonKind.Quiet, ButtonSize.Large)
            HOButton("Send", { onSend(stars, comment.ifBlank { null }) }, Modifier.weight(1f), ButtonKind.Primary, ButtonSize.Large, enabled = stars > 0, haptic = null)
        }
        Text(
            if (accounts) "The lesson's owner sees your rating and comment with your name." else "The lesson's owner sees your rating and comment with no name.",
            style = HandOver.type.footnote, color = c.ink2, textAlign = TextAlign.Center,
        )
    }
}
