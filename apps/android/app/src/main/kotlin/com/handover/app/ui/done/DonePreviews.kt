package com.handover.app.ui.done

import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import com.handover.app.core.CheckType
import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeCatalog

private val previewLesson = Lesson(
    "ft", "Fold a fortune teller",
    steps = listOf(
        Step(1, "Lay the square sheet flat", "00:00", "00:03", checkType = CheckType.Manual),
        Step(2, "Fold corner to corner", "00:03", "00:06"),
        Step(3, "Fold all four corners to center", "00:06", "00:09", commonMistake = "Bring every corner to the exact center."),
        Step(4, "Flip the paper over", "00:09", "00:12"),
    ),
)

private val fullRun = RunData(
    "ft", 1, finished = true, runMs = 31_000,
    steps = listOf(StepRun(4_000, Completion.Hand), StepRun(5_000, Completion.Camera), StepRun(14_000, Completion.Camera, mistakes = 1), StepRun(3_000, Completion.Camera)),
)

private val sparseRun = RunData("ft", 1, finished = true, steps = listOf(StepRun(), StepRun(), StepRun(), StepRun(3_000, Completion.Camera)))

@Preview(name = "Done", widthDp = 412, heightDp = 1400) @Composable
private fun DonePreview() = HandOverTheme(ThemeCatalog.system, false) { DoneScreen(RunScore.model(previewLesson, fullRun), true, {}, {}, {}) }

@Preview(name = "Done, not enough data", widthDp = 412, heightDp = 1200) @Composable
private fun DoneSparsePreview() = HandOverTheme(ThemeCatalog.system, true) { DoneScreen(RunScore.model(previewLesson, sparseRun), true, {}, {}, {}) }

@Preview(name = "Done, offline", widthDp = 412, heightDp = 1400) @Composable
private fun DoneOfflinePreview() = HandOverTheme(ThemeCatalog.grain, false) { DoneScreen(RunScore.model(previewLesson, fullRun), false, {}, {}, {}) }

@Preview(name = "Done, tablet", widthDp = 1280, heightDp = 800) @Composable
private fun DoneTabletPreview() = HandOverTheme(ThemeCatalog.harbor, false) { DoneScreen(RunScore.model(previewLesson, fullRun), true, {}, {}, {}) }

@Preview(name = "Rating", widthDp = 412) @Composable
private fun RatingPreview() = HandOverTheme(ThemeCatalog.system, false) { RatingBody({ _, _ -> }, {}) }
