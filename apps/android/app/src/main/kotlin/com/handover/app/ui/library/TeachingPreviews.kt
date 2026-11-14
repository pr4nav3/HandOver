package com.handover.app.ui.library

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.tooling.preview.Preview
import com.handover.app.core.CheckType
import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.core.UploadSource
import com.handover.app.ui.editor.EditorActions
import com.handover.app.ui.editor.EditorContent
import com.handover.app.ui.editor.EditorFeatures
import com.handover.app.ui.editor.EditorUi
import com.handover.app.ui.editor.EditorUrls
import com.handover.app.ui.editor.SaveState
import com.handover.app.ui.record.RecordContent
import com.handover.app.ui.record.RecordPhase
import com.handover.app.ui.record.RecordUi
import com.handover.app.ui.teach.RowState
import com.handover.app.ui.teach.Stage
import com.handover.app.ui.teach.StageRow
import com.handover.app.ui.teach.TeachContent
import com.handover.app.ui.teach.TeachPhase
import com.handover.app.ui.teach.TeachUi
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog

// Compose previews for every state of Library, Lesson detail, Teach, Record and the editor. The lesson is the
// repo's synthetic fortune teller (titles and times from lessons/synthetic-fortune-teller-v1). Pictures are
// black panes here; the screenshot tests draw the real frames.

private val previewLesson = Lesson(
    id = "synthetic-fortune-teller-v1",
    title = "Fold a fortune teller (synthetic renders)",
    steps = listOf(
        Step(title = "Lay the square sheet flat", start = "00:00", end = "00:03", checkType = CheckType.Manual, checkQuestion = ""),
        Step(title = "Fold corner to corner into triangle", start = "00:03", end = "00:06", checkQuestion = "Is the paper folded into a single triangle with three corners?"),
        Step(title = "Crease both diagonals, then unfold flat", start = "00:06", end = "00:09", checkType = CheckType.Manual, checkQuestion = ""),
        Step(title = "Fold all four corners to center", start = "00:09", end = "00:12", checkQuestion = "Is the paper a smaller square with four triangular flaps whose points meet at the center?", commonMistake = "Bring every corner to the exact center."),
    ),
).withDefaults()

private val item = LibraryItem(previewLesson.id, previewLesson.title, 8, 24.0, emptyList())
private val library = LibraryUiState(loading = false, signedIn = true, all = listOf(item, item.copy(id = "demo", title = "Test pattern (not a real lesson)", steps = 5, duration = 40.0, badge = "Draft")))

@Composable
private fun P(dark: Boolean = false, content: @Composable () -> Unit) =
    HandOverTheme(ThemeCatalog.system, dark, reduceMotion = false) { Box(Modifier.fillMaxSize()) { content() } }

@Preview(name = "Library", widthDp = 412, heightDp = 915) @Composable private fun LibraryPreview() = P { LibraryContent(library.copy(session = Triple(item.id, 3, 8))) }
@Preview(name = "Library dark", widthDp = 412, heightDp = 915) @Composable private fun LibraryDarkPreview() = P(dark = true) { LibraryContent(library) }
@Preview(name = "Library tablet", widthDp = 1280, heightDp = 800) @Composable private fun LibraryTabletPreview() = P { LibraryContent(library) }
@Preview(name = "Library loading", widthDp = 412, heightDp = 600) @Composable private fun LibraryLoadingPreview() = P { LibraryContent(LibraryUiState()) }
@Preview(name = "Library empty", widthDp = 412, heightDp = 600) @Composable private fun LibraryEmptyPreview() = P { LibraryContent(LibraryUiState(loading = false, legacy = true)) }
@Preview(name = "Library no results", widthDp = 412, heightDp = 600) @Composable private fun LibraryNoResultsPreview() = P { LibraryContent(library.copy(query = "crane")) }
@Preview(name = "Library unreachable", widthDp = 412, heightDp = 600) @Composable private fun LibraryErrorPreview() = P {
    LibraryContent(LibraryUiState(loading = false, error = "Could not reach the hub. Check that it is running and on the same Wi-Fi."))
}

private val detail = LessonDetailUi(loading = false, lesson = previewLesson, canEdit = true, frames = previewLesson.steps.map { "" })
@Preview(name = "Lesson detail", widthDp = 412, heightDp = 915) @Composable private fun DetailPreview() = P { LessonDetailContent(detail, currentStep = null) }
@Preview(name = "Lesson detail, mid run", widthDp = 412, heightDp = 915) @Composable private fun DetailContinuePreview() = P { LessonDetailContent(detail, currentStep = 2) }
@Preview(name = "Lesson detail, rated", widthDp = 412, heightDp = 915) @Composable private fun DetailRatedPreview() = P { LessonDetailContent(detail.copy(ratings = RatingSummary(4.5, 2)), currentStep = null) }
@Preview(name = "Lesson detail tablet", widthDp = 1280, heightDp = 800) @Composable private fun DetailTabletPreview() = P { LessonDetailContent(detail, currentStep = null) }
@Preview(name = "Lesson not found", widthDp = 412, heightDp = 600) @Composable private fun DetailNotFoundPreview() = P { LessonDetailContent(LessonDetailUi(loading = false, notFound = true), null) }

private val video = UploadSource("fortune-teller.mp4", "video/mp4", 214_300_000) { "".byteInputStream() }
@Preview(name = "Teach home", widthDp = 412, heightDp = 915) @Composable private fun TeachHomePreview() = P { TeachContent(TeachUi(lessons = library.all)) }
@Preview(name = "Teach home, no lessons", widthDp = 412, heightDp = 915) @Composable private fun TeachEmptyPreview() = P { TeachContent(TeachUi(lessons = emptyList())) }
@Preview(name = "Teach naming", widthDp = 412, heightDp = 915) @Composable private fun TeachNamingPreview() = P { TeachContent(TeachUi(phase = TeachPhase.Naming, video = video, title = "Fortune teller")) }
@Preview(name = "Teach uploading", widthDp = 412, heightDp = 915) @Composable private fun TeachUploadPreview() = P {
    TeachContent(TeachUi(phase = TeachPhase.Uploading, video = video, title = "Fold a fortune teller", sent = 90_000_000, total = 214_300_000, rows = listOf(StageRow(Stage.Upload, RowState.Active))))
}
@Preview(name = "Teach processing", widthDp = 412, heightDp = 915) @Composable private fun TeachProcessingPreview() = P {
    TeachContent(TeachUi(phase = TeachPhase.Processing, title = "Fold a fortune teller", rows = listOf(StageRow(Stage.Upload, RowState.Done), StageRow(Stage.Normalizing, RowState.Done), StageRow(Stage.Extracting, RowState.Active, "Transcribing narration"))))
}
@Preview(name = "Teach failed", widthDp = 412, heightDp = 915) @Composable private fun TeachFailedPreview() = P {
    TeachContent(TeachUi(phase = TeachPhase.Failed, title = "Fold a fortune teller", error = "The hub restarted and lost this job. Upload the video again.", rows = listOf(StageRow(Stage.Upload, RowState.Done), StageRow(Stage.Normalizing, RowState.Failed, "The hub restarted and lost this job. Upload the video again."))))
}
@Preview(name = "Teach ready", widthDp = 412, heightDp = 915) @Composable private fun TeachReadyPreview() = P {
    TeachContent(TeachUi(phase = TeachPhase.Ready, title = previewLesson.title, lessonId = previewLesson.id, lesson = previewLesson, rows = listOf(StageRow(Stage.Upload, RowState.Done), StageRow(Stage.Extracting, RowState.Done))))
}

@Composable private fun StillPreview() = Box(Modifier.fillMaxSize().background(Color(0xFF202124)))
@Preview(name = "Record idle", widthDp = 412, heightDp = 915) @Composable private fun RecordIdlePreview() = RecordP { RecordContent(RecordUi(micAsked = true), { StillPreview() }) }
@Preview(name = "Record recording", widthDp = 412, heightDp = 915) @Composable private fun RecordingPreview() = RecordP {
    RecordContent(RecordUi(phase = RecordPhase.Recording, elapsedMs = 42_000, levels = List(24) { (it % 6) / 6f }, micAsked = true), { StillPreview() })
}
@Preview(name = "Record silent mic", widthDp = 412, heightDp = 915) @Composable private fun RecordSilentPreview() = RecordP {
    RecordContent(RecordUi(phase = RecordPhase.Recording, elapsedMs = 8_000, silent = true, micAsked = true), { StillPreview() })
}
@Preview(name = "Record finishing", widthDp = 412, heightDp = 915) @Composable private fun RecordFinishingPreview() = RecordP { RecordContent(RecordUi(phase = RecordPhase.Finishing, elapsedMs = 61_000), { StillPreview() }) }
@Preview(name = "Record review", widthDp = 412, heightDp = 915) @Composable private fun RecordReviewPreview() = RecordP { RecordContent(RecordUi(phase = RecordPhase.Review, elapsedMs = 61_000, takePath = "take.mp4"), { StillPreview() }) }
@Preview(name = "Record no camera", widthDp = 412, heightDp = 915) @Composable private fun RecordNoCameraPreview() = RecordP { RecordContent(RecordUi(cameraAllowed = false, micAsked = true), {}) }

@Composable private fun RecordP(content: @Composable () -> Unit) = P(dark = true, content)

private val urls = EditorUrls({ _, _ -> null }, { _, _ -> null })
private fun editorUi(features: EditorFeatures = EditorFeatures(true, true, true, true, true), save: SaveState = SaveState.Saved) = EditorUi(
    loading = false, lesson = previewLesson, course = CourseInfo(id = previewLesson.id, status = "draft"), features = features,
    selected = 3, cues = previewLesson.steps.map { emptyList() }, save = save, canUndo = true,
)
@Preview(name = "Editor tablet", widthDp = 1280, heightDp = 800) @Composable private fun EditorTabletPreview() = P { EditorContent(editorUi(), urls, object : EditorActions {}) }
@Preview(name = "Editor phone", widthDp = 412, heightDp = 915) @Composable private fun EditorPhonePreview() = P { EditorContent(editorUi(), urls, object : EditorActions {}) }
@Preview(name = "Editor legacy hub", widthDp = 1280, heightDp = 800) @Composable private fun EditorLegacyPreview() = P { EditorContent(editorUi(EditorFeatures(), SaveState.Saving), urls, object : EditorActions {}) }
@Preview(name = "Editor updating clips", widthDp = 1280, heightDp = 800) @Composable private fun EditorBusyPreview() = P { EditorContent(editorUi(save = SaveState.UpdatingClips), urls, object : EditorActions {}) }
@Preview(name = "Editor save failed", widthDp = 412, heightDp = 915) @Composable private fun EditorFailedPreview() = P {
    EditorContent(editorUi(save = SaveState.Failed("step 3: bad timestamp: '01:7x'")).copy(banner = "step 3: bad timestamp: '01:7x'"), urls, object : EditorActions {})
}
