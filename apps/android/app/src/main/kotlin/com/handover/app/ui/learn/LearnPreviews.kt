package com.handover.app.ui.learn

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ClipPlayer
import com.handover.app.ui.components.LiveSource
import com.handover.app.ui.components.LiveState
import com.handover.app.ui.components.LiveView
import com.handover.app.ui.components.Progress
import com.handover.app.ui.components.StepResultCopy
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog
import com.handover.app.ui.theme.ThemeSpec

// Previews for every Learn state. The panes are black stand-ins; screenshots use lesson frames.

private fun sample(step: Int = 3, badge: BadgeState = BadgeState.Watching, mistake: Mistake? = null) = LearnUi(
    hasLesson = true, lessonTitle = "Fold a fortune teller", stepIndex = step, total = 8, stepTitle = "Fold all four corners to center",
    segments = Progress.segments(8, step, mistake?.kind == MistakeKind.Behind), badge = badge,
    meta = if (badge == BadgeState.Watching) "Last check 0.9 s" else null, mistake = mistake, canBack = true, canNext = true,
    caption = "Fold the top corner down to meet the center.",
)

private val behind = Mistake(step = 3, kind = MistakeKind.Behind, looksLike = 2, message = "Flip it over first.")

@Composable
private fun Frame(ui: LearnUi, spec: ThemeSpec = ThemeCatalog.system, dark: Boolean = false, live: LiveState = LiveState.Live) {
    HandOverTheme(spec, dark, reduceMotion = false) {
        LearnContent(
            ui, object : LearnActions {},
            clip = { m, compact, inPane -> ClipPlayer(null, null, null, ui.stepIndex + 1, m, compact = compact, captionsInPane = inPane, stillCaption = ui.caption) },
            live = { m, compact -> LiveView(null, live, LiveSource("Pixel camera", Icons.Outlined.Videocam), m, compact = compact) },
        )
    }
}

@Preview(name = "Portrait", widthDp = 412, heightDp = 915) @Composable private fun PortraitPreview() = Frame(sample())
@Preview(name = "Portrait, mistake", widthDp = 412, heightDp = 915) @Composable private fun MistakePreview() = Frame(sample(mistake = behind), dark = true)
@Preview(name = "Portrait, verified with result", widthDp = 412, heightDp = 915) @Composable private fun VerifiedPreview() =
    Frame(sample(badge = BadgeState.Verified).copy(moment = StepResultCopy.moment(8.0, 12.0, true, 0)))
@Preview(name = "Portrait, checks off", widthDp = 412, heightDp = 915) @Composable private fun ChecksOffPreview() =
    Frame(sample(badge = BadgeState.ChecksOff).copy(checksOffPill = "Checks off: no key", meta = "No check key on the hub."))
@Preview(name = "Portrait, mock checks", widthDp = 412, heightDp = 915) @Composable private fun MockPreview() =
    Frame(sample(badge = BadgeState.Simulated).copy(mockChecks = true, meta = "Test mode. Steps pass on a timer."))
@Preview(name = "Portrait, waiting for camera", widthDp = 412, heightDp = 915) @Composable private fun WaitingPreview() =
    Frame(sample(badge = BadgeState.NoCamera), live = LiveState.Waiting)
@Preview(name = "Portrait, reconnecting", widthDp = 412, heightDp = 915) @Composable private fun ReconnectingPreview() =
    Frame(sample().copy(reconnecting = true, canNext = false, canBack = false), live = LiveState.Reconnecting)
@Preview(name = "Portrait, swapped", widthDp = 412, heightDp = 915) @Composable private fun SwappedPreview() = Frame(sample().copy(swapped = true))
@Preview(name = "No lesson", widthDp = 412, heightDp = 915) @Composable private fun EmptyPreview() = Frame(LearnUi(hasLesson = false))
@Preview(name = "Landscape", widthDp = 891, heightDp = 411) @Composable private fun LandscapePreview() = Frame(sample(mistake = behind), dark = true)
@Preview(name = "Tablet", widthDp = 1280, heightDp = 800) @Composable private fun TabletPreview() = Frame(sample(), ThemeCatalog.harbor)
