package com.handover.app.ui.learn

import com.handover.app.core.AppState
import com.handover.app.core.CheckType
import com.handover.app.core.HubState
import com.handover.app.core.Lesson
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.core.SocketPhase
import com.handover.app.core.SocketStatus
import com.handover.app.core.Step
import com.handover.app.core.StepStatus
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.LiveState
import com.handover.app.ui.components.Segment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

class LearnModelTest {
    private val lesson = Lesson(
        "ft", "Fold a fortune teller",
        steps = listOf(Step(1, "Lay it flat", "00:00", "00:03", checkType = CheckType.Manual), Step(2, "Fold", "00:03", "00:06"), Step(3, "Flip", "00:06", "00:09")),
    )
    private val open = SocketStatus(SocketPhase.Open)

    private fun app(s: HubState?, connected: Boolean = true) = AppState(connection = if (connected) open else SocketStatus(), session = s, lesson = lesson, lessonRev = 1)

    @Test fun noLessonIsAnEmptyState() {
        val ui = LearnModel.ui(AppState(connection = open), false, null, LearnPrefs(), false)
        assertFalse(ui.hasLesson)
        assertFalse(ui.loading)
    }

    @Test fun mapsStepBadgePillsAndButtons() {
        val s = HubState("ft", 1, step = 1, total = 3, status = StepStatus.Watching, cameraConnected = true, checkMode = "mock", checkOffline = true)
        val ui = LearnModel.ui(app(s), false, null, LearnPrefs(), false)
        assertTrue(ui.hasLesson)
        assertEquals("Fold", ui.stepTitle)
        assertEquals(BadgeState.ChecksOff, ui.badge)
        assertTrue(ui.mockChecks)
        assertEquals("Checks off", ui.checksOffPill)
        assertTrue(ui.canBack)
        assertTrue(ui.canNext)
        assertFalse(ui.isLastStep)
        assertEquals(listOf(Segment.Done, Segment.Current, Segment.Upcoming), ui.segments)
    }

    @Test fun manualStepAndLastStep() {
        val first = LearnModel.ui(app(HubState("ft", 1, step = 0, total = 3)), false, null, LearnPrefs(), false)
        assertEquals(BadgeState.Manual, first.badge)
        assertFalse(first.canBack)
        val last = LearnModel.ui(app(HubState("ft", 1, step = 2, total = 3, cameraConnected = true)), false, null, LearnPrefs(), false)
        assertTrue(last.isLastStep)
    }

    @Test fun behindMistakeTurnsTheSegmentCaution() {
        val m = Mistake(step = 1, kind = MistakeKind.Behind, looksLike = 0, message = "Flip it over first.")
        val ui = LearnModel.ui(app(HubState("ft", 1, step = 1, total = 3, cameraConnected = true, mistake = m)), false, null, LearnPrefs(), false)
        assertEquals(m, ui.mistake)
        assertEquals(Segment.CurrentMistake, ui.segments[1])
    }

    @Test fun disconnectedDisablesNavigation() {
        val ui = LearnModel.ui(app(HubState("ft", 1, step = 1, total = 3), connected = false), false, null, LearnPrefs(), false)
        assertTrue(ui.reconnecting)
        assertFalse(ui.canNext)
        assertFalse(ui.canBack)
    }

    @Test fun liveStates() {
        val s = HubState("ft", 1, cameraConnected = true)
        assertEquals(LiveState.Reconnecting, LearnModel.liveState(false, s, true, false))
        assertEquals(LiveState.Live, LearnModel.liveState(true, s, true, false))
        assertEquals(LiveState.Lost, LearnModel.liveState(true, s.copy(cameraConnected = false), true, false))
        assertEquals(LiveState.Waiting, LearnModel.liveState(true, s.copy(cameraConnected = false), false, false))
        assertEquals(LiveState.Live, LearnModel.liveState(true, s.copy(cameraConnected = false), false, true))
        assertNull(LearnModel.ui(app(s), false, null, LearnPrefs(), false).mistake)
    }

    @Test fun chimeIsShortAndSoft() {
        val pcm = Chime.samples()
        assertTrue(pcm.size in 10_000..30_000)
        val peak = pcm.maxOf { abs(it.toInt()) }
        assertTrue("peak $peak", peak in 3_000..Short.MAX_VALUE * 6 / 10)
        assertEquals(0, pcm.first().toInt())
    }
}
