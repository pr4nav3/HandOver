package com.handover.app.ui.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SettingsStoreTest {
    @Test fun defaultsMatchTheSpec() {
        val s = SettingsStore(MemoryKeyValue()).current
        assertTrue(s.captions)
        assertEquals(CaptionSize.Medium, s.captionSize)
        assertFalse("Voice Next is off until the learner turns it on", s.voiceNext)
        assertTrue(s.haptics)
        assertTrue(s.keepScreenOn)
        assertTrue(s.stepResults)
    }

    @Test fun everyChangeSurvivesARestart() {
        val kv = MemoryKeyValue()
        SettingsStore(kv).update {
            it.copy(captions = false, captionSize = CaptionSize.ExtraLarge,
                voiceNext = true, speakMistakes = true, stepResults = false, haptics = false, keepScreenOn = false, cameraFacing = CameraFacing.Front)
        }
        val back = SettingsStore(kv).current
        assertFalse(back.captions)
        assertEquals(CaptionSize.ExtraLarge, back.captionSize)
        assertTrue(back.voiceNext)
        assertTrue(back.speakMistakes)
        assertFalse(back.stepResults)
        assertFalse(back.haptics)
        assertFalse(back.keepScreenOn)
        assertEquals(CameraFacing.Front, back.cameraFacing)
    }

    @Test fun flowPublishesChangesAndUnknownValuesFallBack() {
        val kv = MemoryKeyValue().apply { putString("caption_size", "Huge"); putString("camera_facing", "Side") }
        val store = SettingsStore(kv)
        assertEquals(CaptionSize.Medium, store.current.captionSize)
        assertEquals(CameraFacing.Back, store.current.cameraFacing)
        store.update { it.copy(haptics = false) }
        assertFalse(store.settings.value.haptics)
    }

    @Test fun captionScales() {
        assertEquals(listOf(0.85f, 1.0f, 1.25f, 1.5f), CaptionSize.entries.map { it.scale })
    }

    @Test fun voiceCommands() {
        assertEquals(VoiceCommand.Next, VoiceCommand.match("Next"))
        assertEquals(VoiceCommand.Next, VoiceCommand.match("okay next"))
        assertEquals(VoiceCommand.Back, VoiceCommand.match("go back."))
        assertNull(VoiceCommand.match("I think the next part is hard"))
        assertNull(VoiceCommand.match("hello"))
    }
}
