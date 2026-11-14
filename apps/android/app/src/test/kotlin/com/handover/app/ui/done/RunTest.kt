package com.handover.app.ui.done

import com.handover.app.core.Advance
import com.handover.app.core.AdvanceReason
import com.handover.app.core.CheckType
import com.handover.app.core.HubState
import com.handover.app.core.Lesson
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.core.Step
import com.handover.app.core.StepStatus
import com.handover.app.ui.components.ScoreLabel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RunTest {
    private var now = 1_000_000L
    private val rec = RunRecorder { now }

    private val lesson = Lesson(
        id = "ft", title = "Fold a fortune teller",
        steps = listOf(
            Step(1, "Lay the sheet flat", "00:00", "00:10", checkType = CheckType.Manual),
            Step(2, "Fold corner to corner", "00:10", "00:30"),
            Step(3, "Fold four corners in", "00:30", "00:50", commonMistake = "Bring every corner to the exact center."),
            Step(4, "Flip it over", "00:50", "01:00"),
        ),
    )

    private fun state(step: Int, done: Boolean = false, offline: Boolean = false) =
        HubState(lessonId = "ft", rev = 7, step = step, total = 4, status = if (done) StepStatus.Done else StepStatus.Watching, checkOffline = offline)

    private fun advance(from: Int, to: Int, reason: AdvanceReason): Forward? {
        val f = rec.onAdvance(Advance(from, to, reason))
        rec.onState(state(minOf(to, 3), done = to >= 4))
        return f
    }

    private fun wait(s: Double) { now += (s * 1000).toLong() }

    @Test fun recordsTimesCompletionsAndMistakes() {
        rec.onState(state(0))
        wait(8.0)
        val f0 = advance(0, 1, AdvanceReason.Button)
        assertEquals(Forward(0, 8.0, false, 0), f0)
        wait(15.0)
        assertEquals(15.0, advance(1, 2, AdvanceReason.Camera)!!.seconds!!, 0.001)
        wait(5.0)
        rec.onMistake(Mistake(step = 2, kind = MistakeKind.Behind, looksLike = 1))
        wait(40.0)
        val f2 = advance(2, 3, AdvanceReason.Camera)!!
        assertEquals(1, f2.mistakesFixed)
        wait(9.0)
        assertNull("last step: Done takes over", advance(3, 4, AdvanceReason.Camera))
        val d = rec.data
        assertTrue(d.finished)
        assertEquals(77_000L, d.runMs)
        assertEquals(listOf(Completion.Hand, Completion.Camera, Completion.Camera, Completion.Camera), d.steps.map { it.completion })
        assertEquals(listOf(8_000L, 15_000L, 45_000L, 9_000L), d.steps.map { it.ms })
        assertEquals(1, d.steps[2].mistakes)

        val m = RunScore.model(lesson, d)
        assertEquals("1:17", com.handover.app.ui.components.Format.clock(m.runSeconds!!))
        assertEquals(60.0, m.expertSeconds!!, 0.001)
        assertEquals(3, m.checkedByCamera)
        assertEquals(3, m.cameraSteps)
        assertEquals(1, m.markedDone)
        assertEquals(1, m.mistakes)
        assertEquals(0, m.skipped)
        // Checked 3/3; pace mean(min(1,10/8)=1, 20/15=1, 20/45, 10/9=1) = 0.861; clean 1 - 1/4 = 0.75.
        assertEquals(Math.round(100 * (0.5 * 1.0 + 0.3 * ((1 + 1 + 20.0 / 45 + 1) / 4) + 0.2 * 0.75)).toInt(), m.score)
        assertEquals(ScoreLabel.of(m.score!!), m.label)
        assertEquals(2, m.weakest!!.index)
        assertEquals("1 mistake, 0:45 against 0:20.", m.weakest!!.reason)
        assertEquals(1, m.best!!.index)
        assertEquals("Checked by camera in 15 s.", m.best!!.reason)
        assertEquals("On step 3, watch for this: Bring every corner to the exact center.", m.tip)
        assertEquals("3 of 3 camera steps checked by camera.", m.parts!!.checked)
    }

    @Test fun underOneSecondShowsNoTime() {
        rec.onState(state(0))
        wait(0.4)
        assertNull(advance(0, 1, AdvanceReason.Button)!!.seconds)
    }

    @Test fun aheadJumpByCameraCountsBothStepsAndButtonJumpSkips() {
        rec.onState(state(0)); wait(5.0)
        advance(0, 1, AdvanceReason.Button); wait(5.0)
        advance(1, 3, AdvanceReason.Camera)
        assertEquals(Completion.Camera, rec.data.steps[2].completion)
        rec.onState(state(3))
        rec.willGoto(0)
        assertFalse(rec.data.steps.any { it.completion == Completion.Skipped })
    }

    @Test fun localGotoForwardSkips() {
        rec.onState(state(0)); wait(5.0)
        rec.willGoto(2)
        assertNull(advance(0, 2, AdvanceReason.Button))
        assertEquals(listOf(Completion.Skipped, Completion.Skipped, null, null), rec.data.steps.map { it.completion })
        val m = RunScore.model(lesson, rec.data)
        assertEquals("You skipped step 1. Try it once so the camera can check it.", RunScore.tip(m.steps, null))
    }

    @Test fun longDisconnectInterruptsAndHidesScoreAndTime() {
        rec.onState(state(0)); wait(5.0)
        rec.onState(null); wait(12.0)
        rec.onState(state(0)); wait(3.0)
        advance(0, 1, AdvanceReason.Button); wait(5.0)
        advance(1, 2, AdvanceReason.Button); wait(5.0)
        advance(2, 3, AdvanceReason.Button); wait(5.0)
        advance(3, 4, AdvanceReason.Button)
        val d = rec.data
        assertTrue(d.interrupted)
        assertEquals(8_000L, d.steps[0].ms)
        val m = RunScore.model(lesson, d)
        assertNull(m.score)
        assertNull(m.label)
        assertNull(m.runSeconds)
        assertNull("step 1's timer was cut", m.steps[0].seconds)
    }

    @Test fun notEnoughDataWhenUnderHalfTheStepsHaveATime() {
        rec.onState(state(2)) // joined mid lesson: no run time, earlier steps unseen
        wait(5.0)
        advance(2, 3, AdvanceReason.Camera); wait(5.0)
        advance(3, 4, AdvanceReason.Camera)
        val m = RunScore.model(lesson, rec.data)
        assertNull(m.runSeconds)
        assertNotNull(m.steps[2].seconds)
        // 2 of 4 timed is half: score allowed.
        assertNotNull(m.score)
        val rec2 = RunRecorder { now }
        rec2.onState(state(3)); now += 5_000
        rec2.onAdvance(Advance(3, 4, AdvanceReason.Camera))
        assertNull(RunScore.model(lesson, rec2.data).score)
        assertNull(RunScore.model(lesson, rec2.data).weakest)
    }

    @Test fun checksOffStepsLeaveTheCheckedPartAndTipSaysSo() {
        rec.onState(state(0)); wait(10.0)
        advance(0, 1, AdvanceReason.Button)
        rec.onState(state(1, offline = true)); wait(20.0)
        advance(1, 2, AdvanceReason.Button); wait(20.0)
        advance(2, 3, AdvanceReason.Button); wait(10.0)
        advance(3, 4, AdvanceReason.Button)
        val m = RunScore.model(lesson, rec.data)
        // Camera steps with checks on the whole time: steps 3 and 4, neither verified: Checked = 0.
        assertEquals("0 of 2 camera steps checked by camera.", m.parts!!.checked)
        assertEquals(Math.round(100 * (0.5 * 0 + 0.3 * 1.0 + 0.2 * 1.0)).toInt(), m.score)
    }

    @Test fun startOverBeginsAFreshRunAtStepOne() {
        rec.onState(state(0)); wait(5.0)
        advance(0, 1, AdvanceReason.Button)
        rec.restart()
        rec.onState(state(1))
        assertEquals(Completion.Hand, rec.data.steps[0].completion)
        rec.onState(state(0))
        assertNull(rec.data.steps[0].completion)
    }

    @Test fun hubScoreOverridesScoreLabelAndTip() {
        rec.onState(state(0)); wait(5.0)
        advance(0, 1, AdvanceReason.Button)
        val local = RunScore.model(lesson, rec.data)
        val m = local.withHub(HubRunScore(score = 91, label = "Excellent", tip = "Step 2: hold it still.", weakestStep = HubStepRef(2, 40)))
        assertEquals(91, m.score)
        assertEquals(ScoreLabel.Excellent, m.label)
        assertEquals("Step 2: hold it still.", m.tip)
        assertEquals(1, m.weakest!!.index)
        assertEquals(ScoreSource.Hub, m.source)
        assertEquals(local, local.withHub(HubRunScore(score = null)))
    }
}
