package com.handover.app.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

/** The from-guard on next and back (CONTRACT.md section 5), and the reconnect backoff. */
class NavTest {
    private fun at(step: Int, total: Int = 4, done: Boolean = false, lesson: String? = "x") =
        HubState(lessonId = lesson, step = step, total = total, status = if (done) StepStatus.Done else StepStatus.Watching)

    @Test fun nextCarriesTheShownStep() {
        assertEquals(NextCommand(from = 0), Nav.next(at(0)))
        assertEquals(NextCommand(from = 3), Nav.next(at(3)))
        assertEquals(NextCommand(from = 2, reason = "voice"), Nav.next(at(2), "voice"))
        assertEquals("anything else counts as button", "button", Nav.next(at(2), "wave")?.reason)
    }

    @Test fun backCarriesTheShownStep() {
        assertEquals(BackCommand(from = 2), Nav.back(at(2)))
        // On the done screen the client shows position total; back returns to the last step.
        assertEquals(BackCommand(from = 4), Nav.back(at(3, done = true)))
    }

    @Test fun noOpsAreNotSent() {
        assertNull(Nav.next(null))
        assertNull(Nav.next(at(0, lesson = null)))
        assertNull(Nav.next(at(0, total = 0)))
        assertNull("next on the done screen", Nav.next(at(3, done = true)))
        assertNull("back on the first step", Nav.back(at(0)))
        assertNull(Nav.back(null))
        assertNull(Nav.goto(at(1), 1))
        assertNull(Nav.goto(at(1), 4))
        assertNull(Nav.goto(at(1), -1))
        assertEquals(GotoCommand(3), Nav.goto(at(1), 3))
        assertEquals("goto from done to the last step", GotoCommand(3), Nav.goto(at(3, done = true), 3))
    }

    @Test fun aDoubleTapIsIgnoredByTheHub() {
        val shown = at(1)
        val first = Nav.next(shown)!!
        assertTrue(Nav.hubAccepts(first.from, shown))
        // The hub applied the first tap and moved to step 2; the second tap still says from 1.
        val second = Nav.next(shown)!!
        assertFalse(Nav.hubAccepts(second.from, at(2)))
    }

    @Test fun tapRacingACameraAdvanceIsIgnored() {
        val back = Nav.back(at(2))!!
        assertFalse("the camera already moved the hub to step 3", Nav.hubAccepts(back.from, at(3)))
    }

    @Test fun hubRuleOnTheDoneScreen() {
        val done = at(3, done = true)
        assertTrue(Nav.hubAccepts(3, done))
        assertTrue(Nav.hubAccepts(4, done))
        assertFalse(Nav.hubAccepts(2, done))
        assertTrue("from absent is always applied", Nav.hubAccepts(null, at(1)))
    }

    @Test fun backoffDoublesCapsAndStops() {
        val b = Backoff(baseMs = 500, maxMs = 10_000, jitter = 0.0)
        assertEquals(listOf(500L, 1000L, 2000L, 4000L, 8000L, 10_000L, 10_000L), (0..6).map { b.delayFor(it, null) })
        assertNull("4000 replaced never reconnects", b.delayFor(0, CloseCodes.REPLACED))
        assertEquals("1011 retries at once the first time", 0L, b.delayFor(0, CloseCodes.STALLED))
        assertEquals(1000L, b.delayFor(1, CloseCodes.STALLED))
        assertEquals(2000L, b.delayFor(2, CloseCodes.TRY_LATER))
        assertEquals("huge attempt counts do not overflow", 10_000L, b.delayFor(500, null))
    }

    @Test fun backoffJitterOnlyShortens() {
        val b = Backoff(baseMs = 1000, maxMs = 10_000, jitter = 0.2, random = Random(7))
        repeat(50) { assertTrue(b.delayFor(0, null)!! in 800L..1000L) }
    }
}
