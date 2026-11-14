package com.handover.app.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.handover.app.core.CameraIdentity
import com.handover.app.core.CameraSource
import com.handover.app.core.CheckType
import com.handover.app.core.Lesson
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.core.Step
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.ClipPlayer
import com.handover.app.ui.components.Corner
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.LiveSource
import com.handover.app.ui.components.LiveState
import com.handover.app.ui.components.LiveView
import com.handover.app.ui.components.MistakeCard
import com.handover.app.ui.components.Progress
import com.handover.app.ui.components.ScoreLabel
import com.handover.app.ui.components.ScoreRing
import com.handover.app.ui.components.StarRating
import com.handover.app.ui.components.StatusBlock
import com.handover.app.ui.components.StepProgressBar
import com.handover.app.ui.components.StepResultCopy
import com.handover.app.ui.components.TimeBar
import com.handover.app.ui.components.Toast
import com.handover.app.ui.done.Completion
import com.handover.app.ui.done.DoneScreen
import com.handover.app.ui.done.RunData
import com.handover.app.ui.done.RunScore
import com.handover.app.ui.done.StepRun
import com.handover.app.ui.learn.LearnActions
import com.handover.app.ui.learn.LearnContent
import com.handover.app.ui.learn.LearnUi
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.HandOverSurface
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog
import com.handover.app.ui.theme.ThemeSpec
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * Learn, Done, every badge state, the mistake card and a component sheet, drawn on the JVM with
 * Robolectric and Roborazzi (vibeflux's setup). Images land in apps/android/screenshots. Run:
 * ./gradlew :app:testDebugUnitTest --tests '*ui.ScreenshotTest*' -Proborazzi.test.record=true
 *
 * The video panes show still frames from the repo's synthetic fortune teller lesson in place of
 * playing video, so the layout can be judged; nothing here is passed off as a real run.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w412dp-h915dp-xhdpi")
class ScreenshotTest {
    @get:Rule val compose = createComposeRule()

    private fun frame(n: Int): ImageBitmap? {
        val f = File("../../../lessons/synthetic-fortune-teller-v1/frames/%02d.jpg".format(n)).takeIf { it.exists() }
            ?: File("../../../lessons/demo-v1/frames/%02d.jpg".format(n.coerceIn(1, 5))).takeIf { it.exists() }
        return f?.let { BitmapFactory.decodeFile(it.path)?.asImageBitmap() }
    }

    private fun shot(name: String, spec: ThemeSpec, dark: Boolean, content: @Composable () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            HandOverTheme(spec, dark, reduceMotion = false) {
                HandOverSurface { Box(Modifier.fillMaxSize().statusBarsPadding()) { content() } }
            }
        }
        compose.mainClock.advanceTimeBy(2_000)
        compose.onRoot().captureRoboImage("../screenshots/$name.png")
    }

    private val lesson = Lesson(
        "ft", "Fold a fortune teller",
        steps = listOf(
            Step(1, "Lay the square sheet flat", "00:00", "00:03", checkType = CheckType.Manual),
            Step(2, "Fold corner to corner into triangle", "00:03", "00:06"),
            Step(3, "Crease both diagonals, then unfold flat", "00:06", "00:09", checkType = CheckType.Manual),
            Step(4, "Fold all four corners to center", "00:09", "00:12", commonMistake = "Bring every corner to the exact center."),
            Step(5, "Flip the paper over", "00:12", "00:15"),
            Step(6, "Fold four corners to center again", "00:15", "00:18"),
            Step(7, "Crease in half both ways, unfold", "00:18", "00:21", checkType = CheckType.Manual),
            Step(8, "Flip, then push into four pockets", "00:21", "00:24"),
        ),
    )

    private fun learnUi(step: Int = 3, badge: BadgeState = BadgeState.Watching, mistake: Mistake? = null, swapped: Boolean = false) = LearnUi(
        hasLesson = true, lessonTitle = lesson.title, stepIndex = step, total = 8, stepTitle = lesson.steps[step].title,
        segments = Progress.segments(8, step, mistake?.kind == MistakeKind.Behind), badge = badge,
        meta = if (badge == BadgeState.Watching || badge == BadgeState.Checking) "Last check 0.9 s" else null,
        reason = if (badge == BadgeState.Watching) "corners not yet at the center" else null,
        mistake = mistake, canBack = true, canNext = true, swapped = swapped, corner = Corner.BottomRight,
        caption = "Fold the top corner down to meet the center.",
    )

    @Composable
    private fun Learn(ui: LearnUi, live: LiveState = LiveState.Live, source: LiveSource? = LiveSource("Pixel camera", Icons.Outlined.Videocam)) {
        val clipStill = frame(ui.stepIndex + 1)
        val liveStill = frame(maxOf(1, ui.stepIndex))
        LearnContent(
            ui, object : LearnActions {},
            clip = { m, compact, inPane ->
                ClipPlayer(null, null, null, ui.stepIndex + 1, m, compact = compact, captionsInPane = inPane, still = clipStill, stillCaption = ui.caption)
            },
            live = { m, compact -> LiveView(liveStill, live, source, m, compact = compact) },
        )
    }

    private val behind = Mistake(step = 4, kind = MistakeKind.Behind, looksLike = 3, message = "Flip it over first.")

    @Test fun learnPortrait() = shot("learn-portrait", ThemeCatalog.system, false) { Learn(learnUi()) }

    @Test fun learnPortraitGlassesAudio() = shot("learn-portrait-glasses-audio", ThemeCatalog.system, false) {
        Learn(learnUi(step = 2, badge = BadgeState.Manual).copy(audioRoute = "Ray-Ban Meta", speaking = true, spokenGuidance = true, meta = null, reason = null))
    }

    @Test fun learnPortraitMistake() = shot("learn-portrait-mistake", ThemeCatalog.system, true) {
        Learn(learnUi(step = 4, mistake = behind))
    }

    @Test fun learnPortraitSwappedRecording() = shot("learn-portrait-swapped-recording", ThemeCatalog.ivory, false) {
        Learn(learnUi(step = 1, badge = BadgeState.Checking, swapped = true), source = LiveSource.of(CameraIdentity("Replay: take.mp4", "replay", CameraSource.File), false))
    }

    @Test fun learnLandscape() {
        RuntimeEnvironment.setQualifiers("w891dp-h411dp-xhdpi")
        shot("learn-landscape", ThemeCatalog.system, true) {
            Learn(learnUi(step = 1, badge = BadgeState.Verified).copy(moment = StepResultCopy.moment(4.0, 3.0, true, 0)))
        }
    }

    @Test fun learnLandscapeMistake() {
        RuntimeEnvironment.setQualifiers("w891dp-h411dp-xhdpi")
        shot("learn-landscape-mistake", ThemeCatalog.sage, false) { Learn(learnUi(step = 4, mistake = behind)) }
    }

    @Test fun learnTablet() {
        RuntimeEnvironment.setQualifiers("w1280dp-h800dp-mdpi")
        shot("learn-tablet", ThemeCatalog.harbor, false) {
            Learn(learnUi(step = 3, badge = BadgeState.Simulated).copy(mockChecks = true, meta = "Test mode. Steps pass on a timer.", reason = null))
        }
    }

    @Test fun learnWaitingChecksOff() = shot("learn-waiting-checks-off", ThemeCatalog.night, true) {
        Learn(learnUi(step = 1, badge = BadgeState.ChecksOff).copy(checksOffPill = "Checks off: no key", meta = "No check key on the hub.", reason = null), live = LiveState.Waiting, source = null)
    }

    @Test fun learnReconnecting() = shot("learn-reconnecting", ThemeCatalog.system, false) {
        Learn(learnUi().copy(reconnecting = true, canNext = false, canBack = false), live = LiveState.Reconnecting)
    }

    @Test fun learnNoLesson() = shot("learn-no-lesson", ThemeCatalog.system, false) {
        LearnContent(LearnUi(hasLesson = false), object : LearnActions {}, { _, _, _ -> }, { _, _ -> })
    }

    // Three themes on the same Learn state.
    @Test fun themeGrain() = shot("theme-grain-learn", ThemeCatalog.grain, false) { Learn(learnUi(step = 4, mistake = behind)) }
    @Test fun themeChalkboard() = shot("theme-chalkboard-learn", ThemeCatalog.chalkboard, true) { Learn(learnUi(step = 4, mistake = behind)) }
    @Test fun themeMono() = shot("theme-mono-learn", ThemeCatalog.mono, true) { Learn(learnUi(step = 4, mistake = behind)) }

    @Composable
    private fun Badges() {
        Column(Modifier.padding(HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
            Text("Status badge, every state", style = HandOver.type.section, color = HandOver.colors.ink2)
            BadgeState.entries.forEach { b ->
                val meta = com.handover.app.ui.components.Badge.meta(b, com.handover.app.core.HubState("ft", lastCheck = com.handover.app.core.LastCheck(latencyMs = 910), cameraConnected = true))
                StatusBlock(b, meta, null)
            }
        }
    }

    @Test fun badgesLight() = shot("badges-light", ThemeCatalog.system, false) { Badges() }
    @Test fun badgesDark() = shot("badges-dark", ThemeCatalog.system, true) { Badges() }
    @Test fun badgesMono() = shot("badges-mono", ThemeCatalog.mono, false) { Badges() }

    @Test fun mistakeCards() = shot("mistake-card", ThemeCatalog.system, false) {
        Column(Modifier.padding(HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
            MistakeCard(behind, {}, {})
            MistakeCard(Mistake(step = 4, kind = MistakeKind.Behind, looksLike = 3, message = ""), {}, {})
            MistakeCard(Mistake(step = 4, kind = MistakeKind.Ahead, looksLike = 5, message = "You're ahead."), {}, {})
            Box(Modifier.fillMaxWidth().height(180.dp).background(HandOver.colors.stage).padding(HOSpace.s)) {
                MistakeCard(behind, {}, {}, onVideo = true, modifier = Modifier.align(androidx.compose.ui.Alignment.BottomCenter))
            }
        }
    }

    @Test fun components() = shot("components", ThemeCatalog.system, false) {
        Column(Modifier.padding(HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
            StepProgressBar(Progress.segments(8, 3, false))
            StepProgressBar(Progress.segments(8, 3, true))
            StepProgressBar(Progress.segments(30, 12, false))
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                HOButton("Next", {}, kind = ButtonKind.Primary, size = ButtonSize.Large)
                HOButton("Try Again", {}, kind = ButtonKind.Secondary)
                HOButton("I'm Fine", {}, kind = ButtonKind.Quiet, size = ButtonSize.Small)
                HOButton("Next", {}, kind = ButtonKind.Primary, enabled = false)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.l)) {
                ScoreRing(82, ScoreLabel.of(82))
                ScoreRing(null, null)
            }
            TimeBar(14.0, 21.0, 40.0)
            TimeBar(null, 21.0, 40.0)
            StarRating(4, {})
            Toast("Thanks. Rating sent.")
            Box(Modifier.fillMaxWidth().height(80.dp).background(HandOver.colors.stage), contentAlignment = androidx.compose.ui.Alignment.Center) {
                com.handover.app.ui.components.StepResultToast(StepResultCopy.moment(8.0, 12.0, true, 0), {}, hold = true)
            }
        }
    }

    private fun run(): RunData = RunData(
        lessonId = "ft", rev = 1, runMs = 98_000, finished = true,
        steps = listOf(
            StepRun(4_000, Completion.Hand), StepRun(5_000, Completion.Camera), StepRun(4_000, Completion.Hand),
            StepRun(19_000, Completion.Camera, mistakes = 2), StepRun(3_000, Completion.Camera), StepRun(6_000, Completion.Camera),
            StepRun(5_000, Completion.Hand), StepRun(0, Completion.Skipped),
        ),
    )

    @Test fun done() = shot("done", ThemeCatalog.system, false) { DoneScreen(RunScore.model(lesson, run()), true, {}, {}, {}) }

    @Test fun doneFullPage() {
        RuntimeEnvironment.setQualifiers("w412dp-h2000dp-xhdpi")
        shot("done-full", ThemeCatalog.system, false) { DoneScreen(RunScore.model(lesson, run()), true, {}, {}, {}) }
    }

    @Test fun doneNotEnoughData() {
        RuntimeEnvironment.setQualifiers("w412dp-h1400dp-xhdpi")
        val sparse = RunData("ft", 1, steps = List(8) { if (it == 7) StepRun(5_000, Completion.Camera) else StepRun() }, runMs = null, finished = true)
        shot("done-not-enough-data", ThemeCatalog.chalkboard, true) { DoneScreen(RunScore.model(lesson, sparse), false, {}, {}, {}) }
    }

    @Test fun doneTablet() {
        RuntimeEnvironment.setQualifiers("w1280dp-h800dp-mdpi")
        shot("done-tablet", ThemeCatalog.clay, true) { DoneScreen(RunScore.model(lesson, run()), true, {}, {}, {}) }
    }

    @Test fun rating() = shot("rating", ThemeCatalog.system, false) {
        Column(Modifier.fillMaxSize()) {
            Spacer(Modifier.weight(1f))
            Box(Modifier.fillMaxWidth().background(HandOver.colors.raised).padding(top = HOSpace.l)) {
                com.handover.app.ui.done.RatingBody({ _, _ -> }, {})
            }
        }
    }
}
