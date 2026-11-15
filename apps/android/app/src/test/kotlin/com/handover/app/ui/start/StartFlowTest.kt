package com.handover.app.ui.start

import com.handover.app.core.AppState
import com.handover.app.core.EndedRun
import com.handover.app.core.HubState
import com.handover.app.core.HubUrl
import com.handover.app.ui.shell.Destination
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StartFlowTest {
    @Test fun captureLinkUsesTheHubsSecurePort() {
        // Phone browsers only open the camera on a secure page, so plain 8000 becomes https 8443.
        assertEquals("https://192.168.1.20:8443/capture", StartFlow.captureLink(HubUrl.parse("192.168.1.20:8000")!!))
        assertEquals("https://mac.local:8443/capture", StartFlow.captureLink(HubUrl.parse("mac.local")!!))
        // A tunnel already on https keeps its own address.
        assertEquals("https://hub.example.com/capture", StartFlow.captureLink(HubUrl.parse("https://hub.example.com")!!))
    }

    @Test fun startAsksOnlyBeforeTheFirstChoice() {
        assertTrue(StartFlow.mustAsk(null))
        CameraChoice.entries.forEach { assertFalse(StartFlow.mustAsk(it)) }
    }

    @Test fun cameraRowWords() {
        assertEquals("Camera: This phone", StartFlow.cameraRow(CameraChoice.ThisPhone))
        assertEquals("Camera: Meta glasses", StartFlow.cameraRow(CameraChoice.Glasses))
        assertEquals("Camera: Another device", StartFlow.cameraRow(CameraChoice.OtherDevice))
    }

    @Test fun savedChoiceParsesAndUnknownIsNull() {
        CameraChoice.entries.forEach { assertEquals(it, CameraChoice.parse(it.name)) }
        assertNull(CameraChoice.parse("Webcam"))
        assertNull(CameraChoice.parse(null))
    }

    @Test fun copyHasNoDashes() {
        CameraChoice.entries.forEach { c ->
            listOf(c.title, c.line).forEach { assertFalse(it, it.contains('—') || it.contains('–')) }
        }
    }

    @Test fun endedRunHidesTheLessonUntilANewRun() {
        val running = AppState(session = HubState(lessonId = "ft", runId = "r1", total = 8))
        assertTrue(running.lessonRunning)
        val ended = running.copy(ended = EndedRun("ft", "r1"))
        assertFalse(ended.lessonRunning)
        // Someone starts the lesson again (a new run) or picks another one: it shows again.
        assertTrue(ended.copy(session = HubState(lessonId = "ft", runId = "r2", total = 8)).lessonRunning)
        assertTrue(ended.copy(session = HubState(lessonId = "crane", runId = "r1", total = 4)).lessonRunning)
        // A hub without run ids: hidden until this phone starts a lesson (which clears the mark).
        val old = AppState(session = HubState(lessonId = "ft", total = 8), ended = EndedRun("ft", null))
        assertFalse(old.lessonRunning)
        assertFalse(AppState().lessonRunning)
        assertFalse(AppState(session = HubState(lessonId = null)).lessonRunning)
    }

    @Test fun orgsTabLabelFitsNarrowPhones() {
        assertEquals("Orgs", Destination.Organizations.short)
        assertEquals("Organizations", Destination.Organizations.label)
        Destination.entries.forEach { assertTrue(it.short, it.short.length <= 8) }
    }
}
