package com.handover.app.ui.editor

import com.handover.app.core.CheckType
import com.handover.app.core.HubException
import com.handover.app.core.HubJson
import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.ui.library.CourseDetail
import com.handover.app.ui.library.CourseInfo
import com.handover.app.ui.library.CoursePermissions
import com.handover.app.ui.library.EditResult
import com.handover.app.ui.library.FakeBackend
import com.handover.app.ui.library.HistoryCounts
import com.handover.app.ui.library.MainDispatcherRule
import com.handover.app.ui.library.Org
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class EditorViewModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val lesson = Lesson(
        id = "fold",
        title = "Fold",
        steps = listOf(
            Step(title = "One", start = "00:00", end = "00:04"),
            Step(title = "Two", start = "00:04", end = "00:08"),
            Step(title = "Three", start = "00:08", end = "00:12"),
        ),
    ).withDefaults()

    private fun serverBackend() = FakeBackend().apply {
        courseResult = CourseDetail(CourseInfo(id = "fold", status = "draft"), lesson, CoursePermissions(canEdit = true, canPublish = true), HistoryCounts())
        orgsResult = listOf(Org("o1", "Makerspace", 5, "teacher"), Org("o2", "Book club", 9, "learner"))
        texts = mapOf("captions/01.vtt" to "WEBVTT\n\n00:00:01.000 --> 00:00:03.800\nhello\n")
    }

    @Test fun serverModeSendsTheMatchingRouteAndTakesTheHubsLesson() = runTest(main.dispatcher) {
        val b = serverBackend()
        val fromHub = lesson.moveBoundary(0, 3.8)
        b.editResult = { op -> if (op.startsWith("boundaries")) EditResult(fromHub, HistoryCounts(undo = 1), recut = true) else null }
        val vm = EditorViewModel(b, "fold")
        advanceUntilIdle()
        val s0 = vm.state.value
        assertTrue(s0.features.serverEdits && s0.features.captions && s0.features.publish)
        assertEquals(listOf(1.0, 3.8), s0.snaps)
        assertEquals("only orgs the person may publish to", listOf("o1"), s0.orgs.map { it.id })

        vm.dragBoundary(0, 3.5)
        assertEquals("00:03.5", vm.state.value.lesson!!.steps[0].end)
        vm.commitBoundary(0, 3.8)
        runCurrent()
        advanceUntilIdle()
        assertTrue("boundaries:1,null,00:03.8;2,00:03.8,null" in b.calls)
        val s = vm.state.value
        assertEquals(SaveState.Saved, s.save)
        assertEquals("00:03.8", s.lesson!!.steps[0].end)
        assertTrue(s.canUndo)
        assertEquals(1L, s.rev)
    }

    @Test fun serverRefusalRevertsAndShowsTheHubText() = runTest(main.dispatcher) {
        val b = object : FakeBackend() {
            override suspend fun editSplit(id: String, n: Int, at: String): EditResult? = throw HubException(400, "step 2: bad timestamp: '01:7x'")
        }.apply { courseResult = serverBackend().courseResult }
        val vm = EditorViewModel(b, "fold")
        advanceUntilIdle()
        vm.split(1, 6.0)
        assertEquals(4, vm.state.value.lesson!!.steps.size)
        advanceUntilIdle()
        assertEquals(3, vm.state.value.lesson!!.steps.size)
        assertEquals("step 2: bad timestamp: '01:7x'", vm.state.value.banner)
        assertEquals(SaveState.Failed("step 2: bad timestamp: '01:7x'"), vm.state.value.save)
    }

    @Test fun serverUndoUsesTheHubsHistory() = runTest(main.dispatcher) {
        val b = serverBackend()
        b.editResult = { op -> when {
            op.startsWith("step") -> EditResult(lesson.editStep(0, title = "Lay it flat"), HistoryCounts(1, 0))
            op == "undo" -> EditResult(lesson, HistoryCounts(0, 1))
            else -> null
        } }
        val vm = EditorViewModel(b, "fold")
        advanceUntilIdle()
        vm.rename(0, "Lay it flat")
        advanceUntilIdle()
        assertEquals("Lay it flat", vm.state.value.lesson!!.steps[0].title)
        vm.undo()
        advanceUntilIdle()
        assertEquals("One", vm.state.value.lesson!!.steps[0].title)
        assertFalse(vm.state.value.canUndo)
        assertTrue(vm.state.value.canRedo)
        assertTrue("undo" in b.calls)
    }

    @Test fun legacyModeKeepsItsOwnUndoStackAndSavesThroughRecutOnce() = runTest(main.dispatcher) {
        val b = FakeBackend().apply {
            lessonResult = { lesson }
            recutResult = { body -> HubJson.decodeFromJsonElement(Lesson.serializer(), body).withDefaults("fold") }
        }
        val vm = EditorViewModel(b, "fold")
        advanceUntilIdle()
        val f = vm.state.value.features
        assertFalse(f.serverEdits || f.captions || f.selfTest || f.voiceover || f.publish)

        vm.rename(0, "Lay it flat")
        vm.setCheckType(0, CheckType.Manual)
        vm.setMistake(1, "Corners first.")
        assertTrue(vm.state.value.canUndo)
        advanceTimeBy(500)
        assertEquals("no save before the 1 s pause", 0, b.recutBodies.size)
        advanceUntilIdle()
        assertEquals("one save for three quick edits", 1, b.recutBodies.size)
        val sent = b.recutBodies.single()["steps"]!!.jsonArray
        assertEquals("Lay it flat", sent[0].jsonObject["title"]!!.jsonPrimitive.content)
        assertEquals("manual", sent[0].jsonObject["check_type"]!!.jsonPrimitive.content)

        vm.undo()
        assertEquals("", vm.state.value.lesson!!.steps[1].commonMistake)
        vm.undo()
        assertEquals(CheckType.Camera, vm.state.value.lesson!!.steps[0].checkType)
        vm.redo()
        assertEquals(CheckType.Manual, vm.state.value.lesson!!.steps[0].checkType)
        assertTrue(vm.state.value.canRedo)
        vm.rename(2, "Last")
        assertFalse("a new change clears redo", vm.state.value.canRedo)
        advanceUntilIdle()
        assertEquals(2, b.recutBodies.size)
    }

    @Test fun publishToAnOrgSendsTheOrg() = runTest(main.dispatcher) {
        val b = serverBackend()
        val vm = EditorViewModel(b, "fold")
        advanceUntilIdle()
        var result: String? = "pending"
        vm.publish("o1", toOrg = true, unlisted = false) { result = it }
        advanceUntilIdle()
        assertEquals(null, result)
        assertTrue("publish:published:org:o1" in b.calls)
        assertEquals("o1", vm.state.value.course?.orgId)
        vm.publish("everyone", toOrg = false, unlisted = true) { result = it }
        advanceUntilIdle()
        assertTrue("publish:unlisted:everyone:" in b.calls)
    }

    @Test fun mergeUnknownKeepsFieldsTheAppDoesNotKnow() {
        val raw = JsonObject(mapOf(
            "id" to JsonPrimitive("fold"),
            "voiceover" to JsonPrimitive("af_heart"),
            "steps" to kotlinx.serialization.json.JsonArray(lesson.steps.map { JsonObject(mapOf("title" to JsonPrimitive(it.title), "rubric" to JsonPrimitive("r"), "ref_time" to JsonPrimitive("00:01"))) }),
        ))
        val edited = lesson.editStep(0, title = "Lay flat")
        val merged = mergeUnknown(raw, edited)
        assertEquals("af_heart", merged["voiceover"]!!.jsonPrimitive.content)
        val step = merged["steps"]!!.jsonArray[0].jsonObject
        assertEquals("Lay flat", step["title"]!!.jsonPrimitive.content)
        assertEquals("r", step["rubric"]!!.jsonPrimitive.content)
        assertFalse("a cleared ref_time is not restored", "ref_time" in step)
        val afterDelete = mergeUnknown(raw, lesson.deleteStep(0)!!)
        assertFalse("step fields carry over only while the count matches", "rubric" in afterDelete["steps"]!!.jsonArray[0].jsonObject)
    }
}
