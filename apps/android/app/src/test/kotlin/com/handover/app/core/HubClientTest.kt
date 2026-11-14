package com.handover.app.core

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import java.util.Collections

/** HubClient against a local fake hub. */
class HubClientTest {
    private lateinit var server: MockWebServer
    private lateinit var client: HubClient

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        client = HubClient(HubUrl(server.hostName, server.port), OkHttpClient())
    }

    @After fun tearDown() = server.shutdown()

    private fun json(body: String, code: Int = 200) = MockResponse().setResponseCode(code).setHeader("Content-Type", "application/json").setBody(body)

    @Test fun lessonsAndLesson() = runBlocking {
        server.enqueue(json("""[{"id":"demo-v1","title":"Demo","steps":5}]"""))
        server.enqueue(json("""{"title":"Demo","steps":[{"start":"00:00","end":"00:08"}]}"""))
        assertEquals(listOf(LessonSummary("demo-v1", "Demo", 5)), client.lessons())
        val lesson = client.lesson("demo-v1")
        assertEquals("demo-v1", lesson.id)
        assertEquals("clips/01.mp4", lesson.steps.single().clip)
        assertEquals("/api/lessons", server.takeRequest().path)
        assertEquals("/api/lessons/demo-v1", server.takeRequest().path)
    }

    @Test fun errorsCarryTheHubsDetail() = runBlocking {
        server.enqueue(json("""{"detail":"lesson not found"}""", 404))
        server.enqueue(json("""{"detail":[{"loc":["body","file"],"msg":"Field required","type":"missing"}]}""", 422))
        server.enqueue(MockResponse().setResponseCode(500).setBody("<html>oops</html>"))
        for (expected in listOf(404 to "lesson not found", 422 to "Field required", 500 to "Server Error")) {
            try {
                client.lesson("nope")
                fail("expected HubException")
            } catch (e: HubException) {
                assertEquals(expected.first, e.status)
                assertEquals(expected.second, e.detail)
            }
        }
    }

    @Test fun uploadSendsAMultipartFormWithLengthAndReportsProgress() = runBlocking {
        server.enqueue(json("""{"job":"j1","id":"my-take"}"""))
        val video = ByteArray(300_000) { (it % 251).toByte() }
        val progress = Collections.synchronizedList(mutableListOf<Pair<Long, Long>>())
        val response = client.upload(
            UploadSource("take.mp4", "video/mp4", video.size.toLong()) { video.inputStream() },
            title = "My take",
            id = "My Take",
        ) { sent, total -> progress += sent to total }
        assertEquals(UploadResponse("j1", "my-take"), response)

        val request = server.takeRequest()
        assertEquals("/api/lesson", request.path)
        assertEquals("POST", request.method)
        assertTrue(request.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        val length = request.getHeader("Content-Length")!!.toLong()
        assertEquals("the hub answers 411 without a Content-Length", request.bodySize, length)
        val body = request.body.readUtf8()
        assertTrue(body.contains("name=\"title\"") && body.contains("\r\n\r\nMy take\r\n"))
        assertTrue(body.contains("name=\"id\""))
        assertTrue(body.contains("name=\"file\"; filename=\"take.mp4\""))
        assertTrue(body.contains("Content-Type: video/mp4"))

        assertTrue(progress.isNotEmpty())
        assertEquals(length to length, progress.last())
        assertTrue("progress only grows", progress.zipWithNext().all { (a, b) -> b.first >= a.first })
    }

    @Test fun pollJobEmitsChangesUntilDone() = runBlocking {
        server.enqueue(json("""{"status":"queued","message":"","id":"x"}"""))
        server.enqueue(json("""{"status":"queued","message":"","id":"x"}"""))
        server.enqueue(json("""{"status":"extracting","message":"Finding steps","id":"x"}"""))
        server.enqueue(json("""{"status":"done","message":"","id":"x"}"""))
        val seen = client.pollJob("j1", intervalMs = 1).toList()
        assertEquals(listOf(JobPhase.Queued, JobPhase.Extracting, JobPhase.Done), seen.map { it.status })
        assertEquals(4, server.requestCount)
        assertEquals("/api/jobs/j1", server.takeRequest().path)
    }

    @Test fun pollJobStopsOnError() = runBlocking {
        server.enqueue(json("""{"status":"error","message":"no audio track","id":"x"}"""))
        val seen = client.pollJob("j1", intervalMs = 1).toList()
        assertEquals("no audio track", seen.single().message)
    }

    @Test fun recutAndDelete() = runBlocking {
        server.enqueue(json("""{"id":"a","steps":[{"start":"0","end":"5"}]}"""))
        server.enqueue(json("""{"deleted":"a"}"""))
        assertEquals(1, client.recut("a").steps.size)
        assertEquals(DeleteResponse("a"), client.delete("a"))
        assertEquals("/api/lessons/a/recut", server.takeRequest().path)
        val delete = server.takeRequest()
        assertEquals("DELETE", delete.method)
        assertEquals("/api/lessons/a", delete.path)
    }

    @Test fun lessonFileCarriesRev() {
        assertEquals(
            "http://${server.hostName}:${server.port}/lessons/demo-v1/clips/01.mp4?v=42",
            client.lessonFile("demo-v1", "clips/01.mp4", 42).toString(),
        )
    }
}
