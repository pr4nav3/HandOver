package com.handover.app.core

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/** Decoding the JSON samples in CONTRACT.md, and the edges the contract promises readers survive. */
class ModelsTest {

    // CONTRACT.md section 7, the `state` sample, verbatim.
    private val contractState = """
        {"type":"state","lesson_id":"fortune-teller-v1","rev":1763154180123,"step":4,"total":8,"status":"watching",
         "last_check":{"done":"no","confidence":0.82,"latency_ms":910,"reason":"seams still facing up"},
         "camera_connected":true,
         "camera":{"name":"Ray-Ban Meta via iPhone","platform":"ios","source":"glasses"},
         "check_offline":false,"check_offline_reason":null,
         "mistake":null}
    """.trimIndent()

    // CONTRACT.md section 7, the `mistake` sample, verbatim.
    private val contractMistake = """{"type":"mistake","step":4,"kind":"behind","looks_like":3,"message":"Flip it over first.","confidence":0.86,"source":"gemini"}"""

    private fun state(text: String) = HubJson.decodeFromString(HubState.serializer(), text)

    @Test fun contractStateSample() {
        val s = state(contractState)
        assertEquals("fortune-teller-v1", s.lessonId)
        assertEquals(1763154180123L, s.rev)
        assertEquals(4, s.step)
        assertEquals(8, s.total)
        assertEquals(StepStatus.Watching, s.status)
        assertEquals(LastCheck(Answer.No, 0.82, 910, "seams still facing up"), s.lastCheck)
        assertEquals("seams still facing up", s.lastCheck?.reasonToShow)
        assertTrue(s.cameraConnected)
        assertEquals(CameraIdentity("Ray-Ban Meta via iPhone", "ios", CameraSource.Glasses), s.camera)
        assertFalse(s.checkOffline)
        assertNull(s.checkOfflineReason)
        assertNull(s.mistake)
        assertFalse(s.isRecording)
        assertEquals(4, s.position)
    }

    @Test fun contractMistakeSample() {
        val m = HubJson.decodeFromString(Mistake.serializer(), contractMistake)
        assertEquals(Mistake(4, MistakeKind.Behind, 3, "Flip it over first.", 0.86, "gemini"), m)
    }

    @Test fun stateWithEveryHubBranchField() {
        val s = state(
            """{"type":"state","lesson_id":"x","rev":3,"step":1,"total":3,"status":"verified","last_check":null,
               "camera_connected":true,"camera":{"name":"Replay: take.mp4","platform":"replay","source":"file"},
               "check_offline":true,"check_offline_reason":"rate_limited",
               "mistake":{"step":1,"kind":"behind","looks_like":0,"message":"This still looks like step 1.","confidence":0.9,"source":"mock"},
               "check_mode":"claude","next_clip":"clips/03.mp4"}""",
        )
        assertEquals(StepStatus.Verified, s.status)
        assertEquals(OfflineReason.RateLimited, s.checkOfflineReason)
        assertTrue(s.isRecording)
        assertEquals("claude", s.checkMode)
        assertEquals("clips/03.mp4", s.nextClip)
        assertEquals(0, s.mistake?.looksLike)
    }

    @Test fun noLessonStateAndOldHub() {
        // What a Revision 5 hub with no lesson sends: only the EXISTS fields.
        val s = state("""{"type":"state","lesson_id":null,"rev":0,"step":0,"total":0,"status":"watching","last_check":null,"camera_connected":false}""")
        assertNull(s.lessonId)
        assertNull(s.camera)
        assertFalse(s.checkOffline)
        assertNull(s.checkMode)
        assertNull(s.nextClip)
    }

    @Test fun doneScreenPosition() {
        val s = state("""{"lesson_id":"x","rev":1,"step":7,"total":8,"status":"done","camera_connected":false}""")
        assertTrue(s.done)
        assertEquals(8, s.position)
    }

    @Test fun unknownKeysAndEnumValuesNeverFail() {
        val s = state(
            """{"lesson_id":"x","rev":1,"step":0,"total":2,"status":"thinking","future":{"a":[1,2]},
               "check_offline_reason":"solar_flare","camera":{"name":"N","platform":"android","source":"drone","extra":1}}""",
        )
        assertEquals(StepStatus.Watching, s.status)
        assertNull(s.checkOfflineReason)
        assertEquals("android", s.camera?.platform)
        assertEquals(CameraSource.Unknown, s.camera?.source)
    }

    @Test fun lowConfidenceReasonIsHidden() {
        assertNull(LastCheck(Answer.No, 0.5, 10, "seams up").reasonToShow)
        assertNull(LastCheck(Answer.No, 0.9, 10, null).reasonToShow)
    }

    @Test fun fullLessonJson() {
        val lesson = HubJson.decodeFromString(
            Lesson.serializer(),
            """{"id":"synthetic-fortune-teller-v1","title":"Fold a fortune teller","video":"norm.mp4",
               "safety":["Scissors are sharp"],"tools":["paper"],"steps":[
               {"n":1,"title":"Lay the sheet flat","start":"00:00","end":"00:03","clip":"clips/01.mp4","captions":"captions/01.vtt",
                "ref_frame":"frames/01.jpg","ref_time":"00:02","check_type":"manual","check_question":"","prerequisites":[],
                "common_mistake":"Start with a square sheet.","self_test":{"own":"yes","prev":"no","ok":true,"mock":true},"unknown":1},
               {"n":2,"title":"Fold corners","start":"00:03.5","end":"01:02:03","check_type":"camera","check_question":"Are all four corners folded?","prerequisites":[1],"ref_time":null}]}""",
        ).withDefaults()
        assertEquals(listOf("Scissors are sharp"), lesson.safety)
        assertEquals(listOf("paper"), lesson.tools)
        val (one, two) = lesson.steps
        assertEquals(CheckType.Manual, one.checkType)
        assertEquals("", one.checkQuestion)
        assertEquals("00:02", one.refTime)
        assertEquals(SelfTest(Answer.Yes, Answer.No, ok = true, mock = true), one.selfTest)
        assertEquals("Start with a square sheet.", one.commonMistake)
        assertEquals(listOf(1), two.prerequisites)
        assertNull(two.refTime)
        assertEquals("clips/02.mp4", two.clip)
        assertEquals("captions/02.vtt", two.captions)
        assertEquals("frames/02.jpg", two.refFrame)
        assertEquals(3.5, parseTimestamp(two.start)!!, 1e-9)
        assertEquals(3723.0, parseTimestamp(two.end)!!, 1e-9)
    }

    @Test fun lessonDefaultsFromTheContract() {
        val lesson = HubJson.decodeFromString(Lesson.serializer(), """{"steps":[{"start":12,"end":20.5},{"start":"00:20","end":"00:30"}]}""")
            .withDefaults("folder-name")
        assertEquals("folder-name", lesson.id)
        assertEquals("folder-name", lesson.title)
        assertEquals("norm.mp4", lesson.video)
        assertEquals(emptyList<String>(), lesson.safety)
        val first = lesson.steps[0]
        assertEquals(1, first.n)
        assertEquals("12", first.start)
        assertEquals("20.5", first.end)
        assertEquals(CheckType.Camera, first.checkType)
        assertEquals("Is this step finished?", first.checkQuestion)
        assertEquals("clips/01.mp4", first.clip)
        assertEquals(2, lesson.steps[1].n)
        assertNull(first.selfTest)
    }

    @Test fun timestamps() {
        assertEquals(65.0, parseTimestamp("01:05")!!, 1e-9)
        assertEquals(65.5, parseTimestamp("01:05.5")!!, 1e-9)
        assertEquals(3661.0, parseTimestamp("01:01:01")!!, 1e-9)
        assertEquals(7.25, parseTimestamp("7.25")!!, 1e-9)
        assertNull(parseTimestamp(""))
        assertNull(parseTimestamp("1::2"))
        assertNull(parseTimestamp("a:b"))
        assertNull(parseTimestamp("1:2:3:4"))
    }

    @Test fun restBodies() {
        val list = HubJson.decodeFromString(
            ListSerializer(LessonSummary.serializer()),
            """[{"id":"demo-v1","title":"Test pattern","steps":5},{"id":"b","title":"B","steps":0}]""",
        )
        assertEquals(LessonSummary("demo-v1", "Test pattern", 5), list[0])
        assertEquals(UploadResponse("abc123", "my-lesson"), HubJson.decodeFromString(UploadResponse.serializer(), """{"job":"abc123","id":"my-lesson"}"""))
        val job = HubJson.decodeFromString(JobStatus.serializer(), """{"status":"extracting","message":"Finding steps","id":"my-lesson"}""")
        assertEquals(JobPhase.Extracting, job.status)
        assertFalse(job.finished)
        assertTrue(HubJson.decodeFromString(JobStatus.serializer(), """{"status":"error","message":"no audio","id":"x"}""").finished)
        assertEquals(DeleteResponse("x"), HubJson.decodeFromString(DeleteResponse.serializer(), """{"deleted":"x"}"""))
    }

    @Test fun commandsMatchTheContract() {
        fun obj(text: String): JsonObject = Json.parseToJsonElement(text).jsonObject
        val hello = obj(HubJson.encodeToString(Hello.serializer(), Hello("android-1", "Pixel camera")))
        assertEquals(setOf("type", "device_id", "name", "source"), hello.keys)
        assertEquals("hello", hello["type"]!!.jsonPrimitive.content)
        assertEquals("phone", hello["source"]!!.jsonPrimitive.content)
        assertEquals(
            obj("""{"type":"next","reason":"button","from":3}"""),
            obj(HubJson.encodeToString(NextCommand.serializer(), NextCommand(from = 3))),
        )
        assertEquals(obj("""{"type":"back","from":2}"""), obj(HubJson.encodeToString(BackCommand.serializer(), BackCommand(2))))
        assertEquals(obj("""{"type":"back"}"""), obj(HubJson.encodeToString(BackCommand.serializer(), BackCommand(null))))
        assertEquals(obj("""{"type":"goto","step":1}"""), obj(HubJson.encodeToString(GotoCommand.serializer(), GotoCommand(1))))
        assertEquals(obj("""{"type":"select_lesson","id":"demo-v1"}"""), obj(HubJson.encodeToString(SelectLessonCommand.serializer(), SelectLessonCommand("demo-v1"))))
        assertEquals(obj("""{"type":"dismiss_mistake"}"""), obj(HubJson.encodeToString(DismissMistakeCommand.serializer(), DismissMistakeCommand())))
    }

    /** Every lesson.json in the repo's lessons folder decodes. Skipped when the folder is not there. */
    @Test fun repoLessonsDecode() {
        val dir = File("../../../lessons")
        val files = dir.listFiles()?.mapNotNull { File(it, "lesson.json").takeIf(File::isFile) }.orEmpty()
        assumeTrue("no lessons folder at ${dir.absolutePath}", files.isNotEmpty())
        for (file in files) {
            val lesson = HubJson.decodeFromString(Lesson.serializer(), file.readText()).withDefaults(file.parentFile!!.name)
            assertTrue("${file.path} has no steps", lesson.steps.isNotEmpty())
            lesson.steps.forEachIndexed { i, step ->
                assertEquals(i + 1, step.n)
                assertTrue("${file.path} step ${i + 1} start", parseTimestamp(step.start) != null)
                assertTrue("${file.path} step ${i + 1} end", parseTimestamp(step.end) != null)
            }
        }
    }
}
