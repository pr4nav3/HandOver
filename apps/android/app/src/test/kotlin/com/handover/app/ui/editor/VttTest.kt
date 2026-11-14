package com.handover.app.ui.editor

import org.junit.Assert.assertEquals
import org.junit.Test

class VttTest {
    @Test fun parsesCuesAndSkipsHeaders() {
        val text = "WEBVTT\n\nNOTE made by teach\n\n1\n00:00:00.500 --> 00:00:03.500 align:center\nFold the top\ncorner down.\n\n00:04.000 --> 00:07.500\nThen the other.\n\n00:09.000 --> 00:08.000\nbackwards, dropped\n"
        val cues = parseVtt(text)
        assertEquals(listOf(Cue(0.5, 3.5, "Fold the top\ncorner down."), Cue(4.0, 7.5, "Then the other.")), cues)
    }

    @Test fun formatsLikeTheHub() {
        assertEquals("00:00:01.500", formatVtt(1.5))
        assertEquals("01:01:01.001", formatVtt(3661.001))
        assertEquals("00:00:03.500", Cue(3.5, 4.0, " hi ").toEdit().start)
        assertEquals("hi", Cue(3.5, 4.0, " hi ").toEdit().text)
    }
}
