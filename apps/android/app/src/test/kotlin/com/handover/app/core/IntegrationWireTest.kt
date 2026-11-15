package com.handover.app.core

import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList

/** The fields and routes the integration pass added: state fields, select token, frames=0, uploads, org routes. */
class IntegrationWireTest {
    private val server = MockWebServer()
    private val seen = CopyOnWriteArrayList<RecordedRequest>()

    @After fun down() = server.shutdown()

    private fun serve(routes: (RecordedRequest) -> MockResponse) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse { seen += request; return routes(request) }
        }
        server.start()
    }

    private fun hub() = HubUrl(server.hostName, server.port)

    @Test fun stateCarriesProgressStageRunIdAndLiveMistakes() {
        val text = """{"type":"state","lesson_id":"a","step":1,"total":3,"status":"watching","check_mode":"mock",
            "check_offline":true,"check_offline_reason":"budget","progress":0.42,"stage":{"index":1,"count":3,"label":"Fold the corners"},
            "run_id":"r-123","camera":{"name":"Desk","platform":"android","source":"unknown"},
            "mistake":{"step":1,"kind":"live","label":"corner not creased","message":"Crease the corner.","confidence":0.8,"source":"mock"}}"""
        val s = (HubMessages.parse(text) as HubMessage.State).state
        assertEquals("mock", s.checkMode)
        assertEquals(OfflineReason.Budget, s.checkOfflineReason)
        assertEquals(0.42, s.progress!!, 1e-9)
        assertEquals(StepStage(1, 3, "Fold the corners"), s.stage)
        assertEquals("r-123", s.runId)
        assertEquals(CameraSource.Unknown, s.camera?.source)
        assertEquals(MistakeKind.Live, s.mistake?.kind)
        assertEquals("corner not creased", s.mistake?.label)
        assertNull("live mistakes carry no looks_like", s.mistake?.looksLike)
    }

    @Test fun unknownJobStatusesStayAsText() {
        val job = HubJson.decodeFromString(JobStatus.serializer(), """{"status":"transcribing","message":"Listening"}""")
        assertEquals("transcribing", job.status.wire)
        assertFalse(job.status.known)
        assertFalse(job.finished)
        assertEquals(JobPhase.Done, HubJson.decodeFromString(JobStatus.serializer(), """{"status":"done"}""").status)
    }

    @Test fun selectLessonCarriesTheTokenOnlyWhenSignedIn() {
        assertEquals("""{"id":"a","token":"t1","type":"select_lesson"}""", HubJson.encodeToString(SelectLessonCommand.serializer(), SelectLessonCommand("a", "t1")))
        assertEquals("""{"id":"a","type":"select_lesson"}""", HubJson.encodeToString(SelectLessonCommand.serializer(), SelectLessonCommand("a")))
        assertEquals("ws://10.0.0.5:8000/ws/ui?frames=0", HubUrl("10.0.0.5", 8000).uiSocket(frames = false))
        assertEquals("ws://10.0.0.5:8000/ws/ui", HubUrl("10.0.0.5", 8000).uiSocket(frames = true))
    }

    @Test fun signedInUploadsGoToCoursesWithOrgElseToLesson() {
        serve { MockResponse().setBody("""{"job":"j1","id":"fold"}""") }
        val video = UploadSource("take.mp4", "video/mp4", 4) { "abcd".byteInputStream() }
        runBlocking {
            HubClient(hub(), OkHttpClient()) { "t1" }.upload(video, "Fold", orgId = "o1")
            HubClient(hub(), OkHttpClient()) { null }.upload(video, "Fold", orgId = "o1")
        }
        val course = seen[0]
        assertEquals("/api/courses", course.path)
        assertEquals("Bearer t1", course.getHeader("Authorization"))
        val form = course.body.readUtf8()
        assertTrue(form.contains("name=\"org_id\"") && form.contains("\r\n\r\no1\r\n"))
        val lesson = seen[1]
        assertEquals("/api/lesson", lesson.path)
        assertNull(lesson.getHeader("Authorization"))
        assertFalse(lesson.body.readUtf8().contains("org_id"))
    }

    @Test fun signedInUploadFallsBackOnAHubWithoutTheLibrary() {
        serve { r -> if (r.path == "/api/courses") MockResponse().setResponseCode(404).setBody("""{"detail":"Not Found"}""") else MockResponse().setBody("""{"job":"j1","id":"fold"}""") }
        val video = UploadSource("take.mp4", "video/mp4", 4) { "abcd".byteInputStream() }
        val reply = runBlocking { HubClient(hub(), OkHttpClient()) { "t1" }.upload(video, "Fold") }
        assertEquals("fold", reply.id)
        assertEquals(listOf("/api/courses", "/api/lesson"), seen.map { it.path })
    }

    @Test fun orgClientUsesTheRealRoutesAndFields() {
        serve { r ->
            when ("${r.method} ${r.path}") {
                "GET /api/orgs/o1" -> MockResponse().setBody(
                    """{"id":"o1","name":"Shop","slug":"shop","created":"2026-11-14T10:00:00Z","role":"org_admin","owner":{"id":"u1","name":"Sam"},
                        "members":[{"user_id":"u1","name":"Sam","role":"org_admin","joined":"2026-11-14T10:00:00Z"},{"user_id":"u2","name":"Lee","role":"learner","joined":null}],
                        "courses":[{"id":"fold","title":"Fold","steps":8}],
                        "invites":[{"id":"i1","kind":"code","role":"learner","created":"2026-11-14T10:00:00Z","created_by":"Sam","expires":"2026-11-21T10:00:00Z","max_uses":null,"uses":2}]}""",
                )
                "POST /api/orgs/o1/invites" -> MockResponse().setBody("""{"id":"i2","kind":"code","role":"teacher","created":"x","created_by":"Sam","expires":"y","max_uses":null,"uses":0,"code":"k7Qm2x_PaZ9wE4r-"}""")
                "POST /api/orgs/join" -> MockResponse().setBody("""{"id":"o1","name":"Shop","slug":"shop","created":"x","members":3,"role":"teacher"}""")
                else -> MockResponse().setBody("{}")
            }
        }
        val api = AccountApi(hub(), OkHttpClient()) { "t1" }
        runBlocking {
            val page = api.org("o1")
            assertEquals(2, page.org.members)
            assertEquals(1, page.org.lessons)
            assertTrue(page.org.isAdmin && page.canManage)
            assertEquals(OrgRole.Member, page.members[1].orgRole)
            assertNull(page.invites!!.single().code)
            val invite = api.createInvite("o1", OrgRole.Teacher, 7.0, null)
            assertEquals("k7Qm2x_PaZ9wE4r-", invite.code)
            assertEquals(OrgRole.Teacher, OrgRole.from(api.join(" k7Qm2x_PaZ9wE4r- ").role))
            api.revokeInvite("o1", "i2")
            api.setRole("o1", "u2", OrgRole.Admin)
            api.removeMember("o1", "u2")
            api.leave("o1")
            api.renameOrg("o1", "Bike Shop")
            api.deleteOrg("o1")
        }
        val calls = seen.map { "${it.method} ${it.path}" }
        assertEquals(
            listOf("GET /api/orgs/o1", "POST /api/orgs/o1/invites", "POST /api/orgs/join", "DELETE /api/orgs/o1/invites/i2",
                "PATCH /api/orgs/o1/members/u2", "DELETE /api/orgs/o1/members/u2", "POST /api/orgs/o1/leave", "PATCH /api/orgs/o1", "DELETE /api/orgs/o1"),
            calls,
        )
        assertTrue(seen.all { it.getHeader("Authorization") == "Bearer t1" })
        assertEquals("""{"role":"teacher","expires_days":7.0,"max_uses":null}""", seen[1].body.readUtf8())
        assertEquals("""{"code":"k7Qm2x_PaZ9wE4r-"}""", seen[2].body.readUtf8())
        assertEquals("""{"role":"org_admin"}""", seen[4].body.readUtf8())
    }
}
