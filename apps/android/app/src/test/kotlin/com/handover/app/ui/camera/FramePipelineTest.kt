package com.handover.app.ui.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FramePipelineTest {
    @Test fun landscapeSensorFrameScalesToLongSide960() {
        assertEquals(FrameSize(960, 540), FramePipeline.sentSize(1280, 720, 0))
        assertEquals(FrameSize(960, 720), FramePipeline.sentSize(1920, 1440, 180))
    }

    @Test fun portraitRotationSwapsSidesBeforeScaling() {
        assertEquals(FrameSize(540, 960), FramePipeline.sentSize(1280, 720, 90))
        assertEquals(FrameSize(540, 960), FramePipeline.sentSize(1920, 1080, 270))
    }

    @Test fun smallFramesAreNeverScaledUp() {
        assertEquals(FrameSize(640, 480), FramePipeline.sentSize(640, 480, 0))
        assertEquals(FrameSize(480, 640), FramePipeline.sentSize(640, 480, 90))
    }

    @Test fun oddSizesRoundAndStayPositive() {
        assertEquals(FrameSize(960, 1), FramePipeline.scaled(FrameSize(4000, 1)))
        assertEquals(FrameSize(960, 721), FramePipeline.scaled(FrameSize(4032, 3024 + 3)))
    }

    @Test fun contractNumbers() {
        assertEquals(960, FramePipeline.MAX_LONG_SIDE)
        assertEquals(70, FramePipeline.JPEG_QUALITY)
        assertEquals(1_000L, FramePipeline.INTERVAL_MS)
    }

    @Test fun gateLetsAboutOneFramePerSecondThrough() {
        val gate = FrameGate()
        var sent = 0
        // A camera delivering 30 frames a second for 60 seconds.
        for (i in 0 until 1800) {
            val now = i * 1000L / 30
            if (gate.ready(now)) { gate.sent(now); sent++ }
        }
        // 0 s, then about once a second up to 59.97 s: 60 or 61 frames, never the 1.2 fps an early-slack gate gives.
        assertTrue("sent \$sent", sent in 60..61)
    }

    @Test fun gateWaitsWhenNotMarkedSent() {
        val gate = FrameGate()
        assertTrue(gate.ready(0))
        gate.sent(0)
        assertFalse(gate.ready(500))
        assertTrue(gate.ready(960))
        gate.intervalMs = FramePipeline.SLOW_INTERVAL_MS
        gate.sent(1_000)
        assertFalse(gate.ready(2_500))
        assertTrue(gate.ready(3_000))
    }

    @Test fun fpsMeterCountsOnlyTheWindow() {
        val m = FpsMeter()
        assertEquals(0.0, m.fps(0), 0.0)
        for (t in 0L..9_000L step 1_000L) m.record(t)
        assertEquals(1.0, m.fps(9_500), 0.01)
        // Frames stop: the rate falls as old frames leave the window.
        assertEquals(0.4, m.fps(12_500), 0.01)
        assertEquals("0.4 fps", FpsMeter.label(m.fps(12_500)))
        assertEquals(0.0, m.fps(20_000), 0.0)
    }

    @Test fun fpsMeterEarlyReadingUsesTimeCovered() {
        val m = FpsMeter()
        m.record(0); m.record(500); m.record(1_000); m.record(1_500)
        assertEquals(2.0, m.fps(2_000), 0.01)
    }
}
