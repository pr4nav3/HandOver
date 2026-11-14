package com.handover.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.HandOverSurface
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog
import com.handover.app.ui.theme.ThemeSpec

@Composable
private fun Sheet(spec: ThemeSpec = ThemeCatalog.system, dark: Boolean = false, content: @Composable () -> Unit) =
    HandOverTheme(spec, dark, reduceMotion = false) { HandOverSurface { Column(Modifier.padding(HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.m)) { content() } } }

@Preview(name = "Badges, light", widthDp = 360, heightDp = 420) @Composable
private fun BadgesLight() = Sheet { BadgeState.entries.forEach { StatusBadge(it) } }

@Preview(name = "Badges, dark", widthDp = 360, heightDp = 420) @Composable
private fun BadgesDark() = Sheet(dark = true) { BadgeState.entries.forEach { StatusBadge(it) } }

@Preview(name = "Badges, mono", widthDp = 360, heightDp = 420) @Composable
private fun BadgesMono() = Sheet(ThemeCatalog.mono) { BadgeState.entries.forEach { StatusBadge(it) } }

@Preview(name = "Mistake cards", widthDp = 412, heightDp = 520) @Composable
private fun Mistakes() = Sheet {
    MistakeCard(Mistake(4, MistakeKind.Behind, 3, "Flip it over first."), {}, {})
    MistakeCard(Mistake(4, MistakeKind.Ahead, 5, "You're ahead."), {}, {})
    Box(Modifier.fillMaxWidth().height(160.dp).background(HandOver.colors.stage).padding(HOSpace.s)) {
        MistakeCard(Mistake(4, MistakeKind.Behind, 3, "Flip it over first."), {}, {}, onVideo = true, modifier = Modifier.align(Alignment.BottomCenter))
    }
}

@Preview(name = "Progress, buttons, rings, bars", widthDp = 412, heightDp = 760) @Composable
private fun Parts() = Sheet {
    StepProgressBar(Progress.segments(8, 3, false))
    StepProgressBar(Progress.segments(8, 3, true))
    StepProgressBar(Progress.segments(30, 12, false))
    StepProgressBar(emptyList())
    Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        PrimaryButton("Next", {})
        SecondaryButton("Back", {}, size = ButtonSize.Large)
        QuietButton("I'm Fine", {})
    }
    Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.l)) { ScoreRing(91, ScoreLabel.of(91)); ScoreRing(55, ScoreLabel.of(55)); }
    ScoreRing(null, null)
    TimeBar(9.0, 21.0, 30.0)
    TimeBar(null, 21.0, 30.0)
    StarRating(3, {})
    Toast("Lesson saved")
}

@Preview(name = "Live view states", widthDp = 412, heightDp = 700) @Composable
private fun LiveStates() = Sheet {
    LiveState.entries.forEach { s -> LiveView(null, s, LiveSource("Recording", Icons.Outlined.Movie, recording = true), Modifier.fillMaxWidth().height(150.dp)) }
}

@Preview(name = "Clip, error and caption", widthDp = 412, heightDp = 260) @Composable
private fun Clip() = Sheet(dark = true) {
    ClipPlayer(null, null, null, 4, Modifier.fillMaxWidth().height(220.dp), stillCaption = "Fold the top corner down to meet the center.")
}
