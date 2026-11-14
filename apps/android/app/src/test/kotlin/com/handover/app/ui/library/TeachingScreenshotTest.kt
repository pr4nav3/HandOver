package com.handover.app.ui.library

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onRoot
import com.github.takahirom.roborazzi.captureRoboImage
import com.handover.app.core.HubJson
import com.handover.app.core.Lesson
import com.handover.app.core.UploadSource
import com.handover.app.ui.editor.Cue
import com.handover.app.ui.editor.EditorActions
import com.handover.app.ui.editor.EditorContent
import com.handover.app.ui.editor.EditorFeatures
import com.handover.app.ui.editor.EditorUi
import com.handover.app.ui.editor.EditorUrls
import com.handover.app.ui.editor.SaveState
import com.handover.app.ui.editor.snapPoints
import com.handover.app.ui.editor.startSeconds
import com.handover.app.ui.record.RecordContent
import com.handover.app.ui.record.RecordPhase
import com.handover.app.ui.record.RecordUi
import com.handover.app.ui.teach.RowState
import com.handover.app.ui.teach.Stage
import com.handover.app.ui.teach.StageRow
import com.handover.app.ui.teach.TeachContent
import com.handover.app.ui.teach.TeachPhase
import com.handover.app.ui.teach.TeachUi
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
import kotlin.math.sin

/**
 * Library, Lesson detail, Teach (home, processing, the finished timeline), Record (idle and recording) and the
 * course editor, drawn on the JVM with Robolectric and Roborazzi. Images land in apps/android/screenshots. Run:
 * ./gradlew :app:testDebugUnitTest --tests '*TeachingScreenshotTest*' -Proborazzi.test.record=true
 *
 * The lesson is the repo's own synthetic fortune teller (lessons/synthetic-fortune-teller-v1), with its real
 * titles, times, questions and frames. Video panes and the camera preview show its still frames.
 */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "w412dp-h915dp-xhdpi")
class TeachingScreenshotTest {
    @get:Rule val compose = createComposeRule()

    private val root = File("../../../lessons/synthetic-fortune-teller-v1")
    private val lesson: Lesson = HubJson.decodeFromString(Lesson.serializer(), File(root, "lesson.json").readText()).withDefaults()
    private val demo: Lesson = HubJson.decodeFromString(Lesson.serializer(), File("../../../lessons/demo-v1/lesson.json").readText()).withDefaults()

    private fun image(key: String): ImageBitmap? {
        val file = when {
            key.startsWith("x/frames/") -> File(root, key.removePrefix("x/"))
            key.startsWith("demo/frames/") -> File("../../../lessons/demo-v1", key.removePrefix("demo/"))
            else -> null
        }
        return file?.takeIf { it.exists() }?.let { BitmapFactory.decodeFile(it.path)?.asImageBitmap() }
    }

    private fun shot(name: String, dark: Boolean = false, content: @Composable () -> Unit) {
        compose.mainClock.autoAdvance = false
        compose.setContent {
            HandOverTheme(ThemeCatalog.system, dark, reduceMotion = false) {
                // Inspection mode: clip panes show their still instead of starting a player.
                CompositionLocalProvider(LocalPreviewImages provides { key -> image(key) }, LocalInspectionMode provides true) {
                    HandOverSurface { Box(Modifier.fillMaxSize()) { content() } }
                }
            }
        }
        compose.mainClock.advanceTimeBy(2_000)
        compose.onRoot().captureRoboImage("../screenshots/$name.png")
    }

    // Covers: frames/01.jpg of each lesson (the hub's fallback when there is no produced cover).
    private val fortune = LibraryItem(lesson.id, lesson.title, lesson.steps.size, lesson.durationSeconds(), listOf("x/frames/01.jpg"))
    private val pattern = LibraryItem(demo.id, demo.title, demo.steps.size, demo.durationSeconds(), listOf("demo/frames/01.jpg"), badge = "Draft")
    private val library = LibraryUiState(
        loading = false, signedIn = true, all = listOf(fortune, pattern),
        session = Triple(lesson.id, 3, lesson.steps.size),
    )

    @Test fun libraryPhone() = shot("library-phone") { LibraryContent(library) }

    @Test fun libraryPhoneDark() = shot("library-phone-dark", dark = true) { LibraryContent(library) }

    @Test fun libraryEmpty() = shot("library-empty") { LibraryContent(LibraryUiState(loading = false, legacy = true)) }

    @Test fun libraryNoResults() = shot("library-no-results") { LibraryContent(library.copy(query = "crane")) }

    @Config(qualifiers = "w1280dp-h800dp-xhdpi")
    @Test fun libraryTablet() = shot("library-tablet") { LibraryContent(library) }

    private val detail = LessonDetailUi(
        loading = false, lesson = lesson, covers = listOf("x/frames/01.jpg"), canEdit = true,
        frames = lesson.steps.map { "x/" + it.refFrame },
    )

    @Test fun lessonDetail() = shot("lesson-detail") { LessonDetailContent(detail, currentStep = 3) }

    @Config(qualifiers = "w1280dp-h800dp-xhdpi")
    @Test fun lessonDetailTablet() = shot("lesson-detail-tablet") { LessonDetailContent(detail, currentStep = null) }

    private val video = UploadSource("fortune-teller.mp4", "video/mp4", 214_300_000) { "".byteInputStream() }

    @Test fun teachHome() = shot("teach-home") {
        TeachContent(TeachUi(lessons = listOf(fortune, pattern.copy(badge = "Draft"))))
    }

    @Test fun teachUploading() = shot("teach-uploading") {
        TeachContent(TeachUi(phase = TeachPhase.Uploading, video = video, title = "Fold a fortune teller", sent = 90_000_000, total = 214_300_000, rows = listOf(StageRow(Stage.Upload, RowState.Active))))
    }

    @Test fun teachProcessing() = shot("teach-processing") {
        TeachContent(
            TeachUi(
                phase = TeachPhase.Processing, video = video, title = "Fold a fortune teller", sent = 1, total = 1,
                rows = listOf(
                    StageRow(Stage.Upload, RowState.Done),
                    StageRow(Stage.Normalizing, RowState.Done),
                    StageRow(Stage.Transcribing, RowState.Done),
                    StageRow(Stage.Extracting, RowState.Active, "Sending 40 frames and 42 narration lines to gemini-2.5-flash"),
                ),
            ),
        )
    }

    @Test fun teachReadyTimeline() = shot("teach-timeline") {
        TeachContent(
            TeachUi(
                phase = TeachPhase.Ready, title = lesson.title, lessonId = lesson.id, lesson = lesson,
                rows = listOf(Stage.Upload, Stage.Normalizing, Stage.Transcribing, Stage.Extracting, Stage.Cutting).map { StageRow(it, RowState.Done) },
            ),
            fileUrl = { _, path -> "x/$path" },
        )
    }

    @Composable
    private fun still(n: Int) {
        image("x/frames/%02d.jpg".format(n))?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop) }
    }

    @Test fun recordIdle() = shot("record-idle") { RecordContent(RecordUi(micAsked = true), preview = { still(1) }) }

    @Test fun recordRecording() = shot("record-recording") {
        // A meter shape for the picture only: a soft rise and fall, as a voice makes.
        val levels = List(24) { i -> (0.35f + 0.3f * sin(i / 2.6).toFloat()).coerceIn(0f, 1f) }
        RecordContent(RecordUi(phase = RecordPhase.Recording, elapsedMs = 42_000, levels = levels, micAsked = true, hasRecorded = true), preview = { still(4) })
    }

    @Test fun recordNoCamera() = shot("record-no-camera") { RecordContent(RecordUi(cameraAllowed = false, micAsked = true), preview = {}) }

    private val urls = EditorUrls(clip = { _, _ -> null }, frame = { s, _ -> s.refFrame?.let { "x/$it" } })

    private fun editorUi(selected: Int) = EditorUi(
        loading = false,
        lesson = lesson,
        course = com.handover.app.ui.library.CourseInfo(id = lesson.id, title = lesson.title, status = "draft"),
        features = EditorFeatures(serverEdits = true, captions = true, selfTest = true, voiceover = true, publish = true),
        selected = selected,
        cues = lesson.steps.map { emptyList<Cue>() },
        snaps = snapPoints(lesson.steps.map { it.startSeconds() }, emptyList()),
        save = SaveState.Saved,
        canUndo = true,
    )

    @Config(qualifiers = "w1280dp-h800dp-xhdpi")
    @Test fun editorTablet() = shot("editor-tablet") { EditorContent(editorUi(3), urls, object : EditorActions {}) }

    @Config(qualifiers = "w1280dp-h800dp-xhdpi")
    @Test fun editorTabletDark() = shot("editor-tablet-dark", dark = true) { EditorContent(editorUi(1), urls, object : EditorActions {}) }

    @Test fun editorPhone() = shot("editor-phone") { EditorContent(editorUi(3), urls, object : EditorActions {}) }
}
