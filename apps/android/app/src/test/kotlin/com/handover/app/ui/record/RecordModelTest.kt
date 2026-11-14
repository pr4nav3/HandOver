package com.handover.app.ui.record

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordModelTest {
    @Test fun timer() {
        assertEquals("00:42", timerText(42_900))
        assertEquals("12:05", timerText(725_000))
        assertEquals("1:02:05", timerText(3_725_000))
        assertEquals("Recording, 40 seconds", timerSpoken(42_900))
        assertEquals("Recording, 2 minutes 10 seconds", timerSpoken(131_000))
    }

    @Test fun levelCurve() {
        assertEquals(0f, LevelMeter.toLevel(0.0))
        assertEquals(1f, LevelMeter.toLevel(1.0))
        assertEquals(0.6f, LevelMeter.toLevel(0.1), 0.01f)
        assertTrue(LevelMeter.toLevel(0.01) < LevelMeter.toLevel(0.1))
    }

    @Test fun meterRisesFastFallsSlowAndNoticesSilence() {
        val m = LevelMeter()
        assertFalse(m.add(0.3, 0))
        val high = m.bars.last()
        m.add(0.0, 100)
        assertTrue("falls gradually", m.bars.last() in 0.01f..high)
        assertEquals(LevelMeter.BARS, m.bars.size)
        assertFalse(m.add(0.0, 2_000))
        assertTrue(m.add(0.0, 3_200))
        assertFalse("sound resets the silence", m.add(0.5, 3_300))
    }
}
