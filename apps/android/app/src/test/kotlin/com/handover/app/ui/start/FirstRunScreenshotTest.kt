package com.handover.app.ui.start

import android.graphics.BitmapFactory
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import com.handover.app.core.HubJson
import com.handover.app.core.HubUrl
import com.handover.app.core.Lesson
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ClipPlayer
import com.handover.app.ui.components.Corner
import com.handover.app.ui.components.LiveSource
import com.handover.app.ui.components.LiveState
import com.handover.app.ui.components.LiveView
import com.handover.app.ui.components.Progress
import com.handover.app.ui.glasses.GlassesPhase
import com.handover.app.ui.glasses.GlassesState
import com.handover.app.ui.learn.LearnActions
import com.handover.app.ui.learn.LearnContent
import com.handover.app.ui.learn.LearnUi
import com.handover.app.ui.library.HomeUi
import com.handover.app.ui.library.LibraryContent
import com.handover.app.ui.library.LibraryItem
import com.handover.app.ui.library.LibraryUiState
import com.handover.app.ui.library.LocalPreviewImages
import com.handover.app.ui.library.durationSeconds
import com.handover.app.ui.shell.AppShellFrame
import com.handover.app.ui.shell.Destination
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.HandOverSurface
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

/**
 * What a first-time person sees: Home with How it works, the camera sheet's three options, Learn with
 * End, and the empty Learn tab. Drawn from the repo's synthetic fortune teller lesson. Run:
 * ./gradlew :app:testDebugUnitTest --tests '*FirstRunScreenshotTest*' -Proborazzi.test.record=true
 *
 * The sheet shots draw the sheet's content in a sheet-shaped panel over a dimmed Home, because
 * Robolectric does not capture the sheet's own window. The video panes are still frames.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w412dp-h915dp-xhdpi")
class FirstRunScreenshotTest {
    @get:Rule val compose = createComposeRule()

    private val root = File("../../../lessons/synthetic-fortune-teller-v1")
    private val lesson: Lesson = HubJson.decodeFromString(Lesson.serializer(), File(root, "lesson.json").readText()).withDefaults()
    private val item = LibraryItem(lesson.id, lesson.title, lesson.steps.size, lesson.durationSeconds(), listOf("x/frames/01.jpg"))
    private val library = LibraryUiState(loading = false, signedIn = true, all = listOf(item))
    private val hub = HubUrl.parse("192.168.1.20:8000")!!
    private val all = Destination.entries.toList()

    private fun frame(n: Int): ImageBitmap? =
        File(root, "frames/%02d.jpg".format(n)).takeIf { it.exists() }?.let { BitmapFactory.decodeFile(it.path)?.asImageBitmap() }

    private fun shot(name: String, dark: Boolean = false, content: @Composable () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            HandOverTheme(ThemeCatalog.system, dark, reduceMotion = false) {
                val images: (String) -> ImageBitmap? = { key ->
                    File(root, key.removePrefix("x/")).takeIf { key.startsWith("x/") && it.exists() }?.let { BitmapFactory.decodeFile(it.path)?.asImageBitmap() }
                }
                CompositionLocalProvider(LocalPreviewImages provides images, LocalInspectionMode provides true) {
                    HandOverSurface { Box(Modifier.fillMaxSize()) { content() } }
                }
            }
        }
        compose.mainClock.advanceTimeBy(2_000)
        compose.onRoot().captureRoboImage("../screenshots/$name.png")
    }

    @Composable
    private fun Home(ui: LibraryUiState = library, home: HomeUi = HomeUi(), tabs: List<Destination> = all) =
        AppShellFrame(tabs, Destination.Home, {}) { LibraryContent(ui, home = home, onTeach = if (Destination.Teach in tabs) ({}) else null) }

    @Test fun homeFirstRun() = shot("home-first-run") { Home() }

    @Test fun homeFirstRunDark() = shot("home-first-run-dark", dark = true) { Home() }

    /** Guide dismissed, a lesson in progress: Continue sits under the two actions. */
    @Test fun homeReturning() = shot("home-returning") {
        Home(library.copy(session = Triple(lesson.id, 3, lesson.steps.size)), HomeUi(guide = false, running = lesson.title))
    }

    /** A learner on a 360 dp phone: no Teach, and "Orgs" fits under its icon. */
    @Config(qualifiers = "w360dp-h780dp-xhdpi")
    @Test fun homeSmallLearner() = shot("home-small-learner") { Home(tabs = all - Destination.Teach) }

    @Config(qualifiers = "w1280dp-h800dp-xhdpi")
    @Test fun homeTablet() = shot("home-tablet") { Home() }

    @Composable
    private fun Sheet(content: @Composable () -> Unit) {
        Box(Modifier.fillMaxSize()) {
            Home(home = HomeUi(guide = false))
            Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.32f)))
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                    .background(HandOver.colors.raised, RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(Modifier.padding(vertical = 22.dp).size(32.dp, 4.dp).background(HandOver.colors.ink3.copy(alpha = 0.4f), RoundedCornerShape(2.dp)))
                content()
            }
        }
    }

    @Test fun startSheetPhone() = shot("start-sheet") {
        Sheet { CameraChoiceBody(CameraChoice.ThisPhone, {}, hub, null, {}, "Start Lesson", {}) }
    }

    @Test fun startSheetGlassesSetup() = shot("start-sheet-glasses") {
        Sheet { CameraChoiceBody(CameraChoice.Glasses, {}, hub, GlassesState(GlassesPhase.NotRegistered), {}, "Start Lesson", {}) }
    }

    @Test fun startSheetOtherDevice() = shot("start-sheet-other-device", dark = true) {
        Sheet { CameraChoiceBody(CameraChoice.OtherDevice, {}, hub, null, {}, "Start Lesson", {}) }
    }

    @Test fun lessonPicker() = shot("lesson-picker") {
        Sheet { LessonPickerBody(listOf(com.handover.app.core.LessonSummary(lesson.id, lesson.title, lesson.steps.size), com.handover.app.core.LessonSummary("crane", "Fold a paper crane", 12)), false, {}) }
    }

    private fun learnUi(step: Int = 3) = LearnUi(
        hasLesson = true, lessonTitle = lesson.title, stepIndex = step, total = lesson.steps.size, stepTitle = lesson.steps[step].title,
        segments = Progress.segments(lesson.steps.size, step, false), badge = BadgeState.Watching, meta = "Last check 0.9 s",
        canBack = true, canNext = true, corner = Corner.BottomRight, usingThisPhone = true, camera = CameraChoice.ThisPhone,
    )

    @Composable
    private fun Learn(ui: LearnUi, notice: (@Composable () -> Unit)? = null) = Box(Modifier.statusBarsPadding()) {
        LearnContent(
            ui, object : LearnActions {},
            clip = { m, compact, inPane -> ClipPlayer(null, null, null, ui.stepIndex + 1, m, compact = compact, captionsInPane = inPane, still = frame(ui.stepIndex + 1)) },
            live = { m, compact -> LiveView(frame(maxOf(1, ui.stepIndex)), LiveState.Live, LiveSource("This phone", Icons.Outlined.PhoneAndroid), m, compact = compact) },
            notice = notice,
        )
    }

    @Test fun learnWithEnd() = shot("learn-end") { Learn(learnUi()) }

    @Test fun learnCameraOff() = shot("learn-camera-off") {
        Learn(learnUi(1)) {
            com.handover.app.ui.components.Banner("Camera is off, so steps are not checked.", Icons.Outlined.PhoneAndroid, com.handover.app.ui.components.Tone.Caution) {
                com.handover.app.ui.components.QuietButton("Allow", {})
            }
        }
    }

    @Test fun learnEmpty() = shot("learn-empty") {
        AppShellFrame(all, Destination.Learn, {}) { LearnContent(LearnUi(hasLesson = false, camera = CameraChoice.ThisPhone), object : LearnActions {}, { _, _, _ -> }, { _, _ -> }) }
    }

    @Test fun learnNotConnected() = shot("learn-not-connected") {
        AppShellFrame(all, Destination.Learn, {}) { LearnContent(LearnUi(hasLesson = false, hasHub = false), object : LearnActions {}, { _, _, _ -> }, { _, _ -> }) }
    }
}
