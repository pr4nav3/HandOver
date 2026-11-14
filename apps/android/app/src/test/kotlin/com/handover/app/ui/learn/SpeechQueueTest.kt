package com.handover.app.ui.learn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpeechQueueTest {
    private var now = 0L
    private val q = SpeechQueue({ now })

    @Test fun neverTwoAtOnce() {
        assertTrue(q.offer("Fold corner to corner", SpeechKind.StepTitle))
        assertTrue(q.offer("Nice", SpeechKind.Result))
        val first = q.next()!!
        assertNull("busy while the first line plays", q.next())
        q.done(first.id)
        val second = q.next()!!
        assertNull(q.next())
        q.done(second.id)
        assertNull(q.next())
    }

    @Test fun noRepeatWithinThreeSeconds() {
        assertTrue(q.offer("Flip it over first.", SpeechKind.Mistake))
        q.done(q.next()!!.id)
        now += 2_999
        assertFalse(q.offer("Flip it over first.", SpeechKind.Mistake))
        assertFalse("case and spaces do not make a new line", q.offer("  flip it over FIRST. ", SpeechKind.Mistake))
        now += 1
        assertTrue(q.offer("Flip it over first.", SpeechKind.Mistake))
    }

    @Test fun noRepeatOfWhatIsPlayingOrWaiting() {
        q.offer("Nice", SpeechKind.Result)
        q.next()
        now += 10_000
        assertFalse(q.offer("Nice", SpeechKind.Result))
        q.offer("Lesson complete", SpeechKind.Complete)
        now += 10_000
        assertFalse(q.offer("Lesson complete", SpeechKind.Complete))
    }

    @Test fun priorityThenArrival() {
        q.offer("Step title", SpeechKind.StepTitle)
        q.offer("Nice", SpeechKind.Result)
        q.offer("Flip it over first.", SpeechKind.Mistake)
        assertEquals("Flip it over first.", q.next()!!.text.also { q.done(q.current!!.id) })
        assertEquals("Nice", q.next()!!.text.also { q.done(q.current!!.id) })
        assertEquals("Step title", q.next()!!.text)
    }

    @Test fun aNewStepTitleReplacesAWaitingOne() {
        q.offer("Busy line", SpeechKind.Mistake)
        q.next()
        q.offer("Step 2 title", SpeechKind.StepTitle)
        q.offer("Step 3 title", SpeechKind.StepTitle)
        assertEquals(listOf("Step 3 title"), q.pending.map { it.text })
    }

    @Test fun capacityDropsOldestLowestPriority() {
        q.offer("Playing", SpeechKind.Mistake)
        q.next()
        q.offer("Title", SpeechKind.StepTitle)
        q.offer("Nice", SpeechKind.Result)
        q.offer("Mistake one", SpeechKind.Mistake)
        q.offer("Lesson complete", SpeechKind.Complete)
        assertEquals(listOf("Nice", "Mistake one", "Lesson complete"), q.pending.map { it.text })
    }

    @Test fun blankIsIgnoredAndStaleDoneIsHarmless() {
        assertFalse(q.offer("  ", SpeechKind.StepTitle))
        q.offer("One", SpeechKind.Result)
        val u = q.next()!!
        q.done(u.id + 99)
        assertEquals(u, q.current)
    }

    @Test fun verbosityAndDefault() {
        assertFalse(Verbosity.Brief.allows(SpeechKind.StepTitle))
        assertFalse(Verbosity.Brief.allows(SpeechKind.Result))
        assertTrue(Verbosity.Brief.allows(SpeechKind.Mistake))
        assertTrue(Verbosity.Brief.allows(SpeechKind.Complete))
        assertTrue(Verbosity.Standard.allows(SpeechKind.StepTitle))
        assertEquals(Verbosity.Standard, Verbosity.from(null))
        // Spoken guidance: on with Bluetooth audio unless the person chose.
        assertTrue(SpeechPrefs.effective(null, bluetooth = true))
        assertFalse(SpeechPrefs.effective(null, bluetooth = false))
        assertFalse(SpeechPrefs.effective(false, bluetooth = true))
        assertTrue(SpeechPrefs.effective(true, bluetooth = false))
    }
}
