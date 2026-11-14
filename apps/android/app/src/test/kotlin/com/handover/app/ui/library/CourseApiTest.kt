package com.handover.app.ui.library

import com.handover.app.core.HubException
import com.handover.app.core.HubUrl
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class CourseApiTest {
    private val server = MockWebServer()
    private lateinit var api: CourseApi

    @Before fun up() {
        server.start()
        api = CourseApi(HubUrl(server.hostName, server.port), OkHttpClient(), token = { "t0k" })
    }

    @After fun down() = server.shutdown()

    @Test fun missingLibraryRoutesReturnNull() = runBlocking {
        repeat(3) { server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"Not Found"}""")) }
        assertNull(api.courses())
        assertNull(api.orgs())
        assertNull(api.editMerge("x", 1))
    }

    @Test fun realNotFoundIsThrown() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"lesson not found"}"""))
        try {
            api.course("gone")
            fail("expected HubException")
        } catch (e: HubException) {
            assertEquals("lesson not found", e.detail)
        }
    }

    @Test fun coursesDecodeAndSendFilterAndToken() = runBlocking {
        server.enqueue(MockResponse().setBody("""[{"id":"a","title":"A","steps":3,"duration":12.5,"status":"draft","cover_url":"/lessons/a/frames/01.jpg","progress":null,"extra":1}]"""))
        val list = api.courses("mine", org = "o1")!!
        assertEquals("A", list[0].title)
        assertEquals(12.5, list[0].duration!!, 0.0)
        val req = server.takeRequest()
        assertEquals("/api/courses?filter=mine&org=o1", req.path)
        assertEquals("Bearer t0k", req.getHeader("Authorization"))
    }

    @Test fun orgsAcceptEitherShape() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"orgs":[{"id":"o1","name":"Makerspace","members":12,"role":"org_admin"}],"invites":[]}"""))
        val orgs = api.orgs()!!
        assertEquals(Org("o1", "Makerspace", 12, "org_admin"), orgs.single())
        assertTrue(orgs.single().canPublish)
    }

    @Test fun boundariesBodyNamesBothSteps() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"lesson":{"steps":[{"title":"a","start":"00:00","end":"00:05"},{"title":"b","start":"00:05","end":"00:09"}]},"history":{"undo":1,"redo":0},"recut":true}"""))
        val result = api.editBoundaries("x", listOf(Triple(1, null, "00:05"), Triple(2, "00:05", null)))!!
        assertEquals(2, result.lesson.steps.size)
        assertEquals("clips/02.mp4", result.lesson.steps[1].clip)
        assertEquals(1, result.history.undo)
        assertEquals("""{"steps":[{"n":1,"end":"00:05"},{"n":2,"start":"00:05"}]}""", server.takeRequest().body.readUtf8())
    }

    @Test fun rawJobKeepsUnknownStatus() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"status":"rendering","message":"step 2 of 8 done","id":"x"}"""))
        assertEquals(RawJob("rendering", "step 2 of 8 done"), api.job("j"))
    }
}
