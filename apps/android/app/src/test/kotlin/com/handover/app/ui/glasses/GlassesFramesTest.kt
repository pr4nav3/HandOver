package com.handover.app.ui.glasses

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.ByteBuffer

class GlassesFramesTest {
    // A 4 x 2 frame: 8 Y bytes, then a 2 x 1 chroma grid (2 U, 2 V).
    private val y = byteArrayOf(1, 2, 3, 4, 5, 6, 7, 8)

    @Test fun i420BecomesNv21WithVFirst() {
        val i420 = y + byteArrayOf(10, 11) + byteArrayOf(20, 21) // U = 10 11, V = 20 21
        assertArrayEquals(y + byteArrayOf(20, 10, 21, 11), GlassesFrames.toNv21(i420, 4, 2, YuvLayout.Planar, swap = false))
    }

    @Test fun swapFlagPutsUFirst() {
        val i420 = y + byteArrayOf(10, 11) + byteArrayOf(20, 21)
        assertArrayEquals(y + byteArrayOf(10, 20, 11, 21), GlassesFrames.toNv21(i420, 4, 2, YuvLayout.Planar, swap = true))
    }

    @Test fun nv12InterleavedIsReordered() {
        val nv12 = y + byteArrayOf(10, 20, 11, 21) // U V U V
        assertArrayEquals(y + byteArrayOf(20, 10, 21, 11), GlassesFrames.toNv21(nv12, 4, 2, YuvLayout.SemiPlanar, swap = false))
        assertArrayEquals(nv12, GlassesFrames.toNv21(nv12, 4, 2, YuvLayout.SemiPlanar, swap = true))
    }

    @Test fun sizesForTheLowGlassesStream() {
        // VideoQuality.LOW is 360 x 640.
        assertEquals(360 * 640 * 3 / 2, GlassesFrames.frameBytes(360, 640))
        assertEquals(YuvLayout.Planar, GlassesFrames.layoutFor(345_600, 360, 640))
        assertNull(GlassesFrames.layoutFor(1_000, 360, 640))
        assertNull(GlassesFrames.layoutFor(345_600, 0, 640))
    }

    @Test fun shortBufferIsRejected() {
        val thrown = runCatching { GlassesFrames.toNv21(ByteArray(10), 4, 2) }.exceptionOrNull()
        assertTrue(thrown is IllegalArgumentException)
    }

    @Test fun bufferCopyLeavesPosition() {
        val b = ByteBuffer.wrap(byteArrayOf(1, 2, 3))
        assertArrayEquals(byteArrayOf(1, 2, 3), GlassesFrames.bytesOf(b))
        assertEquals(0, b.position())
    }

    @Test fun watchdogFallsBackOnlyWithoutAFrame() {
        val w = FrameWatchdog()
        assertFalse("nothing started", w.shouldFallBack(10_000))
        w.started(1_000)
        assertEquals(5_000L, w.waitMs(1_000))
        assertFalse(w.shouldFallBack(5_999))
        assertTrue(w.shouldFallBack(6_000))
        w.frame(6_500)
        assertFalse("a frame arrived", w.shouldFallBack(60_000))
        assertNull(w.waitMs(60_000))
    }

    @Test fun watchdogRestartsWithANewSession() {
        val w = FrameWatchdog(timeoutMs = 5_000)
        w.started(0); w.frame(100)
        w.started(10_000)
        assertFalse(w.shouldFallBack(14_000))
        assertTrue(w.shouldFallBack(15_000))
        w.reset()
        assertFalse(w.shouldFallBack(99_000))
    }
}
