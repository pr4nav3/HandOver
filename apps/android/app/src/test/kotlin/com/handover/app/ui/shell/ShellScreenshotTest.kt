package com.handover.app.ui.shell

import android.graphics.BitmapFactory
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.github.takahirom.roborazzi.captureRoboImage
import com.handover.app.core.HubJson
import com.handover.app.core.Lesson
import com.handover.app.ui.library.LibraryContent
import com.handover.app.ui.library.LibraryItem
import com.handover.app.ui.library.LibraryUiState
import com.handover.app.ui.library.LocalPreviewImages
import com.handover.app.ui.library.durationSeconds
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
 * The app frame: bottom bar on a phone, rail on a tablet, with Home (the library) inside, drawn from the
 * repo's own synthetic fortune teller lesson. Run:
 * ./gradlew :app:testDebugUnitTest --tests '*ShellScreenshotTest*' -Proborazzi.test.record=true
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w412dp-h915dp-xhdpi")
class ShellScreenshotTest {
    @get:Rule val compose = createComposeRule()

    private val root = File("../../../lessons/synthetic-fortune-teller-v1")
    private val lesson: Lesson = HubJson.decodeFromString(Lesson.serializer(), File(root, "lesson.json").readText()).withDefaults()
    private val item = LibraryItem(lesson.id, lesson.title, lesson.steps.size, lesson.durationSeconds(), listOf("x/frames/01.jpg"))
    private val library = LibraryUiState(loading = false, signedIn = true, all = listOf(item), session = Triple(lesson.id, 3, lesson.steps.size))

    private fun shot(name: String, tabs: List<Destination>, current: Destination = Destination.Home, dark: Boolean = false, content: @Composable () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            HandOverTheme(ThemeCatalog.system, dark, reduceMotion = false) {
                val images: (String) -> androidx.compose.ui.graphics.ImageBitmap? = { key ->
                    File(root, key.removePrefix("x/")).takeIf { key.startsWith("x/") && it.exists() }?.let { BitmapFactory.decodeFile(it.path)?.asImageBitmap() }
                }
                CompositionLocalProvider(LocalPreviewImages provides images, LocalInspectionMode provides true) {
                    HandOverSurface { Box(Modifier.fillMaxSize()) { AppShellFrame(tabs, current, {}) { content() } } }
                }
            }
        }
        compose.mainClock.advanceTimeBy(2_000)
        compose.onRoot().captureRoboImage("../screenshots/$name.png")
    }

    private val all = Destination.entries.toList()

    @Test fun shellPhone() = shot("shell-phone", all) { LibraryContent(library) }

    @Test fun shellPhoneDark() = shot("shell-phone-dark", all, dark = true) { LibraryContent(library) }

    /** A learner on a hub with accounts: no Teach tab (SCREENS.md 24). */
    @Test fun shellPhoneLearner() = shot("shell-phone-learner", all - Destination.Teach) { LibraryContent(library) }

    /** A narrow 360 dp phone, where the five labels are tightest. */
    @Config(qualifiers = "w360dp-h780dp-xhdpi")
    @Test fun shellPhoneSmall() = shot("shell-phone-small", all) { LibraryContent(library) }

    @Config(qualifiers = "w1280dp-h800dp-xhdpi")
    @Test fun shellTablet() = shot("shell-tablet", all) { LibraryContent(library) }
}
