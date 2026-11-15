package com.handover.app.ui.camera

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FramePipelineTest {
    @Test fun landscapeSensorFrameScalesToLongSide640() {
        assertEquals(FrameSize(640, 360), FramePipeline.sentSize(1280, 720, 0))
        assertEquals(FrameSize(640, 480), FramePipeline.sentSize(1920, 1440, 180))
    }

    @Test fun portraitRotationSwapsSidesBeforeScaling() {
        assertEquals(FrameSize(360, 640), FramePipeline.sentSize(1280, 720, 90))
        assertEquals(FrameSize(360, 640), FramePipeline.sentSize(1920, 1080, 270))
    }

    @Test fun smallFramesAreNeverScaledUp() {
        assertEquals(FrameSize(640, 480), FramePipeline.sentSize(640, 480, 0))
        assertEquals(FrameSize(480, 640), FramePipeline.sentSize(640, 480, 90))
        assertEquals(FrameSize(320, 240), FramePipeline.sentSize(320, 240, 0))
    }

    @Test fun oddSizesRoundAndStayPositive() {
        assertEquals(FrameSize(640, 1), FramePipeline.scaled(FrameSize(4000, 1)))
        assertEquals(FrameSize(640, 480), FramePipeline.scaled(FrameSize(4032, 3024 + 3)))
    }

    @Test fun smoothFeedNumbers() {
        assertEquals(640, FramePipeline.MAX_LONG_SIDE)
        assertEquals(50, FramePipeline.JPEG_QUALITY)
        assertEquals(15, FramePipeline.FPS)
        assertEquals(66L, FramePipeline.INTERVAL_MS)
    }

    @Test fun gateLetsAbout15FramesPerSecondThrough() {
        val gate = FrameGate()
        var sent = 0
        // A camera delivering 30 frames a second for 60 seconds.
        for (i in 0 until 1800) {
            val now = i * 1000L / 30
            if (gate.ready(now)) { gate.sent(now); sent++ }
        }
        // Every other camera frame: about 15 a second, never all 30.
        assertTrue("sent $sent", sent in 880..920)
    }

    @Test fun gateWaitsWhenNotMarkedSent() {
        val gate = FrameGate()
        assertTrue(gate.ready(0))
        gate.sent(0)
        assertFalse(gate.ready(30))
        assertTrue(gate.ready(60))
        gate.intervalMs = FramePipeline.SLOW_INTERVAL_MS
        gate.sent(100)
        assertFalse(gate.ready(150))
        assertTrue(gate.ready(232))
    }

    @Test fun senderDropsFramesWhileTheSocketIsBusyAndNeverQueues() {
        var now = 0L
        var busy = false
        var encoded = 0
        val sent = mutableListOf<ByteArray>()
        val sender = FrameSender(FrameGate(), busy = { busy }, send = { sent += it; true }, clock = { now })
        val encode = { encoded++; byteArrayOf(encoded.toByte()) }

        assertTrue(sender.offer(encode))
        assertEquals(1, sent.size)

        // The socket is still sending: the next frames are dropped before they are even encoded.
        busy = true
        repeat(10) { now += 70; assertFalse(sender.offer(encode)) }
        assertEquals(1, encoded)
        assertEquals(1, sent.size)

        // Idle again: only the newest frame goes out, nothing that was dropped is sent later.
        busy = false
        now += 70
        assertTrue(sender.offer(encode))
        assertEquals(listOf(1, 2), sent.map { it[0].toInt() })
    }

    @Test fun senderKeepsTheRateWhenIdleAndRetriesAFailedSend() {
        var now = 0L
        var accept = false
        val sender = FrameSender(FrameGate(), busy = { false }, send = { accept }, clock = { now })
        assertFalse("send refused", sender.offer { byteArrayOf(1) })
        accept = true
        assertTrue("the gate stays open after a refused send", sender.offer { byteArrayOf(1) })
        now += 30
        assertFalse("too soon for 15 a second", sender.offer { byteArrayOf(1) })
        now += 40
        assertTrue(sender.offer { byteArrayOf(1) })
        assertFalse("an encode that throws is dropped", run { now += 70; sender.offer { error("bad frame") } })
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
