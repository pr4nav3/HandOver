package com.handover.app.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** Text frames to [HubMessage], and messages to [AppState]. */
class RoutingTest {

    @Test fun routesEveryKnownType() {
        assertTrue(HubMessages.parse("""{"type":"state","lesson_id":"x","rev":1,"step":0,"total":2,"status":"manual","camera_connected":false}""") is HubMessage.State)
        assertEquals(
            HubMessage.Advanced(Advance(2, 3, AdvanceReason.Camera)),
            HubMessages.parse("""{"type":"advance","from":2,"to":3,"reason":"camera"}"""),
        )
        assertEquals(
            HubMessage.MistakeRaised(Mistake(4, MistakeKind.Ahead, 5, "You're ahead.", 0.9, "gemini")),
            HubMessages.parse("""{"type":"mistake","step":4,"kind":"ahead","looks_like":5,"message":"You're ahead.","confidence":0.9,"source":"gemini"}"""),
        )
        assertEquals(HubMessage.CameraStatus(true), HubMessages.parse("""{"type":"camera_status","active":true}"""))
        assertEquals(HubMessage.CameraStatus(false), HubMessages.parse("""{"type":"camera_status","active":false}"""))
        assertEquals(HubMessage.Error("no lesson selected"), HubMessages.parse("""{"type":"error","message":"no lesson selected"}"""))
    }

    @Test fun unknownAndBrokenInput() {
        assertEquals(HubMessage.Unknown("spectator_joined"), HubMessages.parse("""{"type":"spectator_joined","n":2}"""))
        assertEquals(HubMessage.Unknown(null), HubMessages.parse("""{"no_type":true}"""))
        assertNull(HubMessages.parse("not json"))
        assertNull(HubMessages.parse("[1,2]"))
        assertNull(HubMessages.parse(""))
        // A known type without its required fields is dropped, not fatal.
        assertNull(HubMessages.parse("""{"type":"advance","reason":"camera"}"""))
        // Advance with an unknown reason still routes.
        assertEquals(AdvanceReason.Button, (HubMessages.parse("""{"type":"advance","from":0,"to":1,"reason":"gesture"}""") as HubMessage.Advanced).advance.reason)
    }

    private fun stateMsg(lesson: String?, step: Int, total: Int = 3, rev: Long = 1, status: StepStatus = StepStatus.Watching) =
        HubMessage.State(HubState(lessonId = lesson, rev = rev, step = step, total = total, status = status))

    private val lessonA = Lesson(id = "a", title = "A", steps = listOf(Step(title = "one"), Step(title = "two"), Step(title = "three"))).withDefaults()

    @Test fun stateAsksForTheLessonOnceAndAgainOnNewRev() {
        var s = AppState().reduce(stateMsg("a", 0))
        assertEquals("a" to 1L, s.lessonToFetch)
        s = s.withLesson(lessonA, 1)
        assertNull(s.lessonToFetch)
        assertEquals("one", s.currentStep?.title)
        s = s.reduce(stateMsg("a", 1))
        assertNull(s.lessonToFetch)
        assertEquals("two", s.currentStep?.title)
        // A recut bumps rev: keep showing the old lesson while the new one loads.
        s = s.reduce(stateMsg("a", 1, rev = 2))
        assertEquals("a" to 2L, s.lessonToFetch)
        assertEquals("two", s.currentStep?.title)
    }

    @Test fun newLessonDropsTheOldOne() {
        val s = AppState().reduce(stateMsg("a", 0)).withLesson(lessonA, 1).reduce(stateMsg("b", 0, rev = 5))
        assertNull(s.lesson)
        assertEquals("b" to 5L, s.lessonToFetch)
    }

    @Test fun staleFetchIsIgnored() {
        val s = AppState().reduce(stateMsg("b", 0, rev = 5))
        assertSame(s, s.withLesson(lessonA, 1))
    }

    @Test fun doneScreenHasNoCurrentStep() {
        val s = AppState().reduce(stateMsg("a", 2, status = StepStatus.Done)).withLesson(lessonA, 1)
        assertNull(s.currentStep)
    }

    @Test fun advanceMistakeAndErrorLand() {
        val behind = Mistake(1, MistakeKind.Behind, 0, "Flip it over first.", 0.86, "gemini")
        var s = AppState().reduce(stateMsg("a", 1)).reduce(HubMessage.MistakeRaised(behind))
        assertEquals(behind, s.lastMistake)
        s = s.reduce(stateMsg("a", 1))
        assertEquals("a mistake on this step survives a state on the same step", behind, s.lastMistake)
        s = s.reduce(HubMessage.Advanced(Advance(1, 2, AdvanceReason.Button)))
        assertEquals(Advance(1, 2, AdvanceReason.Button), s.lastAdvance)
        assertNull(s.lastMistake)
        s = s.reduce(HubMessage.Error("lesson not found"))
        assertEquals("lesson not found", s.error)
    }

    @Test fun ignoredMessagesChangeNothing() {
        val s = AppState().reduce(stateMsg("a", 0))
        assertSame(s, s.reduce(HubMessage.Unknown("x")))
        assertSame(s, s.reduce(HubMessage.CameraStatus(true)))
    }
}
