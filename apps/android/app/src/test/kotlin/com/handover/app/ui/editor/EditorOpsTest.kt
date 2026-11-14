package com.handover.app.ui.editor

import com.handover.app.core.Answer
import com.handover.app.core.CheckType
import com.handover.app.core.Lesson
import com.handover.app.core.SelfTest
import com.handover.app.core.Step
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EditorOpsTest {
    private val lesson = Lesson(
        id = "fold",
        steps = listOf(
            Step(title = "Lay flat", start = "00:00", end = "00:03", checkType = CheckType.Manual, checkQuestion = ""),
            Step(title = "Triangle", start = "00:03", end = "00:06", checkQuestion = "One triangle?", refTime = "00:05.5", selfTest = SelfTest(Answer.Yes, Answer.No, true)),
            Step(title = "Crease", start = "00:06", end = "00:09.5", checkQuestion = "X crease?"),
        ),
    ).withDefaults()

    @Test fun timestampsMatchTheHub() {
        assertEquals("01:14.5", formatTimestamp(74.5))
        assertEquals("00:03", formatTimestamp(3.0))
        assertEquals("00:03", formatTimestamp(2.96))
        assertEquals("01:14.5", formatEditorTime(74.5))
        assertEquals("00:03.0", formatEditorTime(3.0))
    }

    @Test fun snapReachesWithinPointFourSeconds() {
        val points = listOf(2.0, 4.5, 7.25)
        assertEquals(4.5 to true, snap(4.2, points))
        assertEquals(4.5 to true, snap(4.9, points))
        assertEquals(5.0 to false, snap(4.96, points))
        assertEquals(3.3 to false, snap(3.27, points))
        assertEquals(1.2 to false, snap(1.23, emptyList()))
    }

    @Test fun snapPicksTheNearestEdge() {
        assertEquals(2.0 to true, snap(2.15, listOf(2.0, 2.4)))
        assertEquals(2.4 to true, snap(2.25, listOf(2.0, 2.4)))
    }

    @Test fun snapPointsAreCueEdgesInLessonTime() {
        val cues = listOf(listOf(Cue(0.5, 2.5, "a")), emptyList(), listOf(Cue(0.0, 1.0, "b"), Cue(1.0, 3.0, "c")))
        assertEquals(listOf(0.5, 2.5, 6.0, 7.0, 9.0), snapPoints(listOf(0.0, 3.0, 6.0), cues))
    }

    @Test fun movingABoundaryResizesBothNeighborsAndClearsDerived() {
        val moved = lesson.moveBoundary(0, 4.25)
        assertEquals("00:04.3", moved.steps[0].end)
        assertEquals("00:04.3", moved.steps[1].start)
        assertNull(moved.steps[1].refTime)
        assertNull(moved.steps[1].selfTest)
        assertEquals(lesson.steps[2], moved.steps[2])
    }

    @Test fun boundaryKeepsHalfASecondEachSide() {
        assertEquals("00:05.5", lesson.moveBoundary(0, 99.0).steps[0].end)
        assertEquals("00:00.5", lesson.moveBoundary(0, -3.0).steps[0].end)
        assertEquals(0.5..5.5, lesson.boundaryRange(0))
    }

    @Test fun splitNeedsHalfASecondEachSide() {
        assertFalse(lesson.canSplit(1, 3.4))
        assertTrue(lesson.canSplit(1, 4.5))
        assertNull(lesson.split(1, 5.8))
        val split = lesson.split(1, 4.5)!!
        assertEquals(4, split.steps.size)
        assertEquals(listOf(1, 2, 3, 4), split.steps.map { it.n })
        assertEquals("Triangle (part 2)", split.steps[2].title)
        assertEquals("00:04.5", split.steps[1].end)
        assertEquals("00:04.5", split.steps[2].start)
        assertEquals(CheckType.Camera, split.steps[2].checkType)
        assertEquals("clips/04.mp4", split.steps[3].clip)
        assertNull(split.steps[1].selfTest)
    }

    @Test fun mergeKeepsFirstTitleAndSecondCheck() {
        val merged = lesson.merge(1)!!
        assertEquals(2, merged.steps.size)
        assertEquals("Triangle", merged.steps[1].title)
        assertEquals("00:03", merged.steps[1].start)
        assertEquals("00:09.5", merged.steps[1].end)
        assertEquals("X crease?", merged.steps[1].checkQuestion)
        assertNull(lesson.merge(2))
    }

    @Test fun deleteKeepsAtLeastOneStep() {
        assertEquals(listOf("Lay flat", "Crease"), lesson.deleteStep(1)!!.steps.map { it.title })
        assertNull(Lesson(steps = listOf(Step())).deleteStep(0))
    }

    @Test fun manualStepsCarryNoQuestion() {
        val manual = lesson.editStep(1, checkType = CheckType.Manual)
        assertEquals("", manual.steps[1].checkQuestion)
        assertNull(manual.steps[1].selfTest)
        val camera = manual.editStep(1, checkType = CheckType.Camera)
        assertEquals(DEFAULT_QUESTION, camera.steps[1].checkQuestion)
        assertEquals("Watch the corners", lesson.editStep(2, mistake = "Watch the corners").steps[2].commonMistake)
        assertEquals(lesson.steps[1].selfTest, lesson.editStep(1, title = "Fold to a triangle").steps[1].selfTest)
    }
}
