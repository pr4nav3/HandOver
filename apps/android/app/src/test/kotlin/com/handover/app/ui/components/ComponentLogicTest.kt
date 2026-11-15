package com.handover.app.ui.components

import android.view.HapticFeedbackConstants
import androidx.compose.ui.geometry.Offset
import com.handover.app.core.Answer
import com.handover.app.core.CameraIdentity
import com.handover.app.core.CameraSource
import com.handover.app.core.HubState
import com.handover.app.core.LastCheck
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind
import com.handover.app.core.OfflineReason
import com.handover.app.core.StepStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ComponentLogicTest {
    private fun st(
        status: StepStatus = StepStatus.Watching, offline: Boolean = false, mode: String? = null, camera: Boolean = true,
        reason: OfflineReason? = null, lastCheck: LastCheck? = null,
    ) = HubState(lessonId = "l", step = 1, total = 4, status = status, checkOffline = offline, checkMode = mode, cameraConnected = camera, checkOfflineReason = reason, lastCheck = lastCheck)

    @Test fun badgePrecedence() {
        assertEquals(BadgeState.Done, Badge.state(st(StepStatus.Done, offline = true, mode = "mock"), manualStep = true, verifiedFlash = true))
        assertEquals(BadgeState.Verified, Badge.state(st(StepStatus.Verified), manualStep = false))
        assertEquals(BadgeState.Verified, Badge.state(st(StepStatus.Watching, offline = true), manualStep = true, verifiedFlash = true))
        assertEquals(BadgeState.Manual, Badge.state(st(offline = true, mode = "mock"), manualStep = true))
        assertEquals(BadgeState.Manual, Badge.state(st(StepStatus.Manual), manualStep = false))
        assertEquals(BadgeState.ChecksOff, Badge.state(st(StepStatus.Checking, offline = true, mode = "mock", camera = false), manualStep = false))
        assertEquals(BadgeState.Simulated, Badge.state(st(StepStatus.Checking, mode = "mock", camera = false), manualStep = false))
        assertEquals(BadgeState.NoCamera, Badge.state(st(StepStatus.Checking, mode = "gemini", camera = false), manualStep = false))
        assertEquals(BadgeState.Checking, Badge.state(st(StepStatus.Checking), manualStep = false))
        assertEquals(BadgeState.Watching, Badge.state(st(), manualStep = false))
        assertEquals(BadgeState.Watching, Badge.state(null, manualStep = false))
    }

    @Test fun simulatedNeedsTheHubToSaySo() {
        assertEquals(BadgeState.Watching, Badge.state(st(mode = null), manualStep = false))
        assertEquals(BadgeState.Watching, Badge.state(st(mode = "claude"), manualStep = false))
    }

    @Test fun metaAndReasonCopy() {
        val check = LastCheck(Answer.No, 0.82, 910, "seams still facing up")
        assertEquals("Last check 0.9 s", Badge.meta(BadgeState.Watching, st(lastCheck = check)))
        assertEquals("seams still facing up", Badge.reason(BadgeState.Watching, st(lastCheck = check)))
        assertNull(Badge.reason(BadgeState.Watching, st(lastCheck = check.copy(confidence = 0.6))))
        assertNull(Badge.reason(BadgeState.Watching, st(lastCheck = check.copy(done = Answer.Yes))))
        assertNull(Badge.meta(BadgeState.Watching, st(camera = false, lastCheck = check)))
        assertEquals("No check key on the hub.", Badge.meta(BadgeState.ChecksOff, st(reason = OfflineReason.NoKey)))
        assertEquals("Too many checks. Trying again soon.", Badge.meta(BadgeState.ChecksOff, st(reason = OfflineReason.RateLimited)))
        assertEquals("Checks failed. Trying again soon.", Badge.meta(BadgeState.ChecksOff, st(reason = OfflineReason.Errors)))
        assertEquals("Checks are off. Use Next to move on.", Badge.meta(BadgeState.ChecksOff, st(reason = null)))
        assertEquals("Test mode. Steps pass on a timer.", Badge.meta(BadgeState.Simulated, st()))
        assertEquals("Connect a camera to check steps.", Badge.meta(BadgeState.NoCamera, st()))
        assertNull(Badge.meta(BadgeState.Verified, st()))
        assertEquals("Checks off: no key", Badge.offlinePill(OfflineReason.NoKey))
    }

    @Test fun mistakeCopy() {
        val behind = Mistake(step = 4, kind = MistakeKind.Behind, looksLike = 3, message = "Flip it over first.")
        assertEquals("Flip it over first.", MistakeCopy.message(behind))
        assertEquals("Show Step 4", MistakeCopy.showStep(behind))
        assertEquals("This still looks like step 4.", MistakeCopy.message(behind.copy(message = "")))
        assertEquals("You're ahead.", MistakeCopy.message(Mistake(kind = MistakeKind.Ahead, message = "")))
    }

    @Test fun progressSegments() {
        assertEquals(listOf(Segment.Done, Segment.Done, Segment.Current, Segment.Upcoming), Progress.segments(4, 2, false))
        assertEquals(Segment.CurrentMistake, Progress.segments(4, 2, true)[2])
        assertEquals(List(4) { Segment.Done }, Progress.segments(4, 4, false))
        assertTrue(Progress.segments(0, 0, false).isEmpty())
    }

    @Test fun stepResultCopy() {
        assertEquals("Nice. 8 s, faster than the expert.", StepResultCopy.moment(8.0, 10.0, true, 0).text)
        assertEquals("Done. 10 s, about the expert's time.", StepResultCopy.moment(10.4, 10.0, false, 0).text)
        assertEquals("Done. 9 s, about the expert's time.", StepResultCopy.moment(9.2, 10.0, false, 0).text)
        assertEquals("Done in 1:05.", StepResultCopy.moment(65.0, 10.0, false, 0).text)
        assertEquals("Done. 1 mistake fixed.", StepResultCopy.moment(65.0, 10.0, false, 1).text)
        assertEquals("Done. 2 mistakes fixed.", StepResultCopy.moment(null, 10.0, true, 2).text)
        assertEquals("Verified.", StepResultCopy.moment(null, 10.0, true, 0).text)
        assertEquals("Done.", StepResultCopy.moment(null, null, false, 0).text)
    }

    @Test fun scoreLabels() {
        assertEquals(ScoreLabel.Excellent, ScoreLabel.of(85))
        assertEquals(ScoreLabel.Good, ScoreLabel.of(84))
        assertEquals(ScoreLabel.Good, ScoreLabel.of(60))
        assertEquals(ScoreLabel.KeepPracticing, ScoreLabel.of(59))
        assertEquals(ScoreLabel.Excellent, ScoreLabel.of("Excellent", 10))
        assertEquals(ScoreLabel.Good, ScoreLabel.of("something new", 70))
    }

    @Test fun formats() {
        assertEquals("12 s", Format.secs(12.4))
        assertEquals("1:05", Format.secs(65.0))
        assertEquals("0:35", Format.clock(35.0))
        assertEquals("0.9 s", Format.latency(910))
        assertEquals("1 mistake", Format.count(1, "mistake"))
        assertEquals("3 steps", Format.count(3, "step"))
    }

    @Test fun pipLandsInTheCornerItIsThrownAt() {
        assertEquals(Corner.BottomRight, PipMath.corner(Offset(300f, 500f), Offset.Zero, 400f, 800f))
        assertEquals(Corner.TopLeft, PipMath.corner(Offset(100f, 100f), Offset.Zero, 400f, 800f))
        // Released bottom right but flung up and left fast.
        assertEquals(Corner.TopLeft, PipMath.corner(Offset(300f, 500f), Offset(-2000f, -3000f), 400f, 800f))
    }

    @Test fun hapticsMatchTheDesignMap() {
        assertEquals(HapticFeedbackConstants.CLOCK_TICK, HapticMap.constant(HOHaptic.Tap, 35))
        assertEquals(HapticFeedbackConstants.SEGMENT_TICK, HapticMap.constant(HOHaptic.Selection, 35))
        assertEquals(HapticFeedbackConstants.CONFIRM, HapticMap.constant(HOHaptic.Success, 35))
        assertEquals(HapticFeedbackConstants.CONTEXT_CLICK, HapticMap.constant(HOHaptic.StepChange, 35))
        assertEquals(HapticFeedbackConstants.REJECT, HapticMap.constant(HOHaptic.Warning, 35))
        assertEquals(HapticFeedbackConstants.LONG_PRESS, HapticMap.constant(HOHaptic.Heavy, 35))
        assertEquals(HapticFeedbackConstants.SEGMENT_FREQUENT_TICK, HapticMap.constant(HOHaptic.Snap, 35))
        // Android 10 has no CONFIRM or REJECT.
        assertEquals(HapticFeedbackConstants.VIRTUAL_KEY, HapticMap.constant(HOHaptic.Success, 29))
        assertEquals(HapticFeedbackConstants.LONG_PRESS, HapticMap.constant(HOHaptic.Error, 29))
    }

    @Test fun liveSourceShowsRecordingForFileAndUnknown() {
        assertTrue(LiveSource.of(CameraIdentity("Replay: a.mp4", "replay", CameraSource.File), false)!!.recording)
        assertTrue(LiveSource.of(CameraIdentity("Camera 1", "other", CameraSource.Unknown), false)!!.recording)
        assertEquals("Ray-Ban Meta", LiveSource.of(CameraIdentity("Ray-Ban Meta", "ios", CameraSource.Glasses), false)!!.label)
        assertEquals("This phone", LiveSource.of(null, true)!!.label)
        assertNull(LiveSource.of(null, false))
    }
}
