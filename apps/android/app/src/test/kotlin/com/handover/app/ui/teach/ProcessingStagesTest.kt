package com.handover.app.ui.teach

import com.handover.app.ui.library.RawJob
import org.junit.Assert.assertEquals
import org.junit.Test

class ProcessingStagesTest {
    private fun run(vararg jobs: RawJob) = jobs.fold(listOf(StageRow(Stage.Upload, RowState.Done))) { rows, j -> rows.observe(j) }

    @Test fun onlyReportedStagesShow() {
        val rows = run(RawJob("queued", ""), RawJob("normalizing", "Converting video to 1080p 30 fps"), RawJob("cutting", "step 1 of 3"))
        assertEquals(listOf(Stage.Upload, Stage.Queued, Stage.Normalizing, Stage.Cutting), rows.map { it.stage })
        assertEquals(listOf(RowState.Done, RowState.Done, RowState.Done, RowState.Active), rows.map { it.state })
        assertEquals("step 1 of 3", rows.last().message)
        assertEquals("", rows[2].message)
    }

    @Test fun transcriptionInsideExtractingIsItsOwnRow() {
        val rows = run(
            RawJob("extracting", "Downloading speech model base once"),
            RawJob("extracting", "Transcribing narration"),
            RawJob("extracting", "Transcribed 42 narration segments in 3.1 s"),
            RawJob("extracting", "Sending 40 frames and 42 narration lines to gemini"),
        )
        assertEquals(listOf(Stage.Upload, Stage.Transcribing, Stage.Extracting), rows.map { it.stage })
        assertEquals("Narration transcribed", rows[1].text())
        assertEquals("Finding steps", rows[2].text())
    }

    @Test fun sameStageUpdatesMessageOnly() {
        val rows = run(RawJob("cutting", "step 1 of 8"), RawJob("cutting", "step 2 of 8"))
        assertEquals(2, rows.size)
        assertEquals("step 2 of 8", rows.last().message)
    }

    @Test fun doneClosesEverythingAndCountsSteps() {
        val rows = run(RawJob("extracting", "x"), RawJob("cutting", "y"), RawJob("done", "ready"))
        assertEquals(RowState.Done, rows.last().state)
        assertEquals("8 steps found", rows.first { it.stage == Stage.Extracting }.text(8))
        assertEquals("1 step found", rows.first { it.stage == Stage.Extracting }.text(1))
    }

    @Test fun errorFailsTheOpenRowWithHubText() {
        val rows = run(RawJob("normalizing", ""), RawJob("error", "ffmpeg: invalid data"))
        assertEquals(RowState.Failed, rows.last().state)
        assertEquals("ffmpeg: invalid data", rows.last().message)
    }

    @Test fun unknownStatusShowsItsOwnWord() {
        val rows = run(RawJob("rendering", "course video"), RawJob("final_pass", ""))
        assertEquals("Course video made", rows[1].text())
        assertEquals("Final pass", rows.last().text())
    }

    @Test fun progressOnlyWhenReported() {
        val rows = run(RawJob("cutting", "", progress = 0.4), RawJob("cutting", "", progress = 1.7))
        assertEquals(1.0, rows.last().progress!!, 0.0)
        assertEquals(null, run(RawJob("cutting", "")).last().progress)
    }
}
