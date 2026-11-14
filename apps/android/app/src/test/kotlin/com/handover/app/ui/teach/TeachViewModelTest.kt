package com.handover.app.ui.teach

import com.handover.app.core.HubException
import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.core.UploadResponse
import com.handover.app.core.UploadSource
import com.handover.app.ui.library.FakeBackend
import com.handover.app.ui.library.MainDispatcherRule
import com.handover.app.ui.library.RawJob
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.IOException

class TeachViewModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val video = UploadSource("fold_fortune-teller.mp4", "video/mp4", 1_000) { "x".byteInputStream() }

    @Test fun titleComesFromFileName() {
        assertEquals("Fold fortune teller", TeachViewModel.titleFromFileName("fold_fortune-teller.mp4"))
        assertEquals("Untitled lesson", TeachViewModel.titleFromFileName(".mp4"))
    }

    @Test fun uploadThenStagesThenReady() = runTest(main.dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val b = FakeBackend().apply {
            uploadBlock = { v, _, progress ->
                progress(400, v.length)
                gate.await()
                progress(v.length, v.length)
                UploadResponse("job1", "fold")
            }
            jobs = ArrayDeque(listOf({ RawJob("normalizing", "") }, { RawJob("extracting", "Transcribing narration") }, { RawJob("cutting", "") }, { RawJob("done", "ready") }))
            lessonResult = { Lesson(id = it, steps = listOf(Step(title = "a", start = "00:00", end = "00:03"), Step(title = "b", start = "00:03", end = "00:06"))).withDefaults() }
        }
        val vm = TeachViewModel(b, pollMs = 10)
        vm.pick(video)
        assertEquals(TeachPhase.Naming, vm.state.value.phase)
        assertEquals("Fold fortune teller", vm.state.value.title)
        vm.setTitle("Fold a fortune teller")
        vm.makeCourse()
        runCurrent()
        assertEquals(TeachPhase.Uploading, vm.state.value.phase)
        assertEquals(40, vm.state.value.percent)
        gate.complete(Unit)
        advanceUntilIdle()
        val s = vm.state.value
        assertEquals(TeachPhase.Ready, s.phase)
        assertEquals("fold", s.lessonId)
        assertEquals(2, s.lesson?.steps?.size)
        assertEquals(listOf(Stage.Upload, Stage.Normalizing, Stage.Transcribing, Stage.Cutting), s.rows.map { it.stage })
        assertTrue(s.rows.all { it.state == RowState.Done })
        assertTrue("upload:Fold a fortune teller" in b.calls)
    }

    @Test fun hubErrorIsShownVerbatim() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { jobs = ArrayDeque(listOf({ RawJob("normalizing", "") }, { RawJob("error", "ffmpeg failed: no video stream") })) }
        val vm = TeachViewModel(b, pollMs = 10)
        vm.pick(video); vm.makeCourse(); advanceUntilIdle()
        assertEquals(TeachPhase.Failed, vm.state.value.phase)
        assertEquals("ffmpeg failed: no video stream", vm.state.value.error)
        assertEquals(RowState.Failed, vm.state.value.rows.last().state)
    }

    @Test fun uploadRefusalUsesPlainWords() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { uploadBlock = { _, _, _ -> throw HubException(429, "too many jobs") } }
        val vm = TeachViewModel(b, pollMs = 10)
        vm.pick(video); vm.makeCourse(); advanceUntilIdle()
        assertEquals("The hub is busy with other lessons. Try again when one finishes.", vm.state.value.error)
        assertEquals(RowState.Failed, vm.state.value.rows.single().state)
    }

    @Test fun lostJobAfterHubRestart() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { jobs = ArrayDeque(listOf({ throw HubException(404, "job not found") })) }
        val vm = TeachViewModel(b, pollMs = 10)
        vm.pick(video); vm.makeCourse(); advanceUntilIdle()
        assertEquals("The hub restarted and lost this job. Upload the video again.", vm.state.value.error)
    }

    @Test fun givesUpAfterThirtyMissedPolls() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { jobs = ArrayDeque(List(40) { { throw IOException("down") } }) }
        val vm = TeachViewModel(b, pollMs = 10)
        vm.pick(video); vm.makeCourse(); advanceUntilIdle()
        assertEquals("Lost contact with the hub. Check that it is running, then upload again.", vm.state.value.error)
        assertEquals(30, b.calls.count { it.startsWith("job:") })
    }

    @Test fun cancelGoesBackToNaming() = runTest(main.dispatcher) {
        val b = FakeBackend().apply { uploadBlock = { _, _, _ -> CompletableDeferred<Unit>().await(); error("never") } }
        val vm = TeachViewModel(b, pollMs = 10)
        vm.pick(video); vm.makeCourse(); runCurrent()
        vm.cancelUpload(); advanceUntilIdle()
        assertEquals(TeachPhase.Naming, vm.state.value.phase)
        vm.finish()
        assertEquals(TeachPhase.Home, vm.state.value.phase)
    }
}
