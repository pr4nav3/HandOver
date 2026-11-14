package com.handover.app.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** UiSocket and CameraSocket against a local fake hub. */
class SocketsTest {
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private val http = OkHttpClient()
    private val fast = Backoff(baseMs = 20, maxMs = 100, jitter = 0.0)

    /** One fake hub connection: what it received, and its socket to send on. */
    private class FakeHub : WebSocketListener() {
        val received = LinkedBlockingQueue<Any>()
        val opened = LinkedBlockingQueue<WebSocket>()
        override fun onOpen(webSocket: WebSocket, response: Response) { opened += webSocket }
        override fun onMessage(webSocket: WebSocket, text: String) { received += text }
        override fun onMessage(webSocket: WebSocket, bytes: ByteString) { received += bytes }
        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(CloseCodes.NORMAL, null) }
        fun socket(): WebSocket = opened.poll(5, TimeUnit.SECONDS) ?: error("no connection")
        fun next(): Any = received.poll(5, TimeUnit.SECONDS) ?: error("nothing received")
    }

    @Before fun setUp() {
        server = MockWebServer().apply { start() }
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    }

    @After fun tearDown() {
        scope.cancel()
        server.shutdown()
    }

    private fun hub() = HubUrl(server.hostName, server.port)
    private fun accept(fake: FakeHub) = server.enqueue(MockResponse().withWebSocketUpgrade(fake))
    private suspend fun <T> soon(block: suspend () -> T): T = withTimeout(5_000) { block() }

    private val state2of4 = """{"type":"state","lesson_id":"x","rev":1,"step":2,"total":4,"status":"watching","camera_connected":true}"""

    @Test fun uiSocketRoutesStateAndSendsNextWithFrom() = runBlocking {
        val fake = FakeHub().also(::accept)
        val frames = LinkedBlockingQueue<ByteArray>()
        val ui = UiSocket(hub(), http, scope, fast) { frames += it; null }
        ui.start()
        val ws = fake.socket()
        assertEquals("/ws/ui", server.takeRequest().path)
        ws.send(state2of4)
        val state = soon { ui.state.first { it != null } }!!
        assertEquals(2, state.step)
        assertEquals(SocketPhase.Open, ui.status.value.phase)

        assertTrue(ui.next())
        assertEquals("""{"from":2,"reason":"button","type":"next"}""", fake.next())
        assertTrue(ui.back())
        assertEquals("""{"from":2,"type":"back"}""", fake.next())
        assertTrue(ui.selectLesson("demo-v1"))
        assertEquals("""{"id":"demo-v1","type":"select_lesson"}""", fake.next())

        // Binary frames go to the decoder.
        val jpeg = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 3)
        ws.send(jpeg.toByteString())
        assertArrayEquals(jpeg, frames.poll(5, TimeUnit.SECONDS))
        ui.stop()
    }

    @Test fun uiSocketSendsNothingForANoOp() = runBlocking {
        val fake = FakeHub().also(::accept)
        val ui = UiSocket(hub(), http, scope, fast) { null }
        ui.start()
        val ws = fake.socket()
        ws.send("""{"type":"state","lesson_id":"x","rev":1,"step":3,"total":4,"status":"done","camera_connected":false}""")
        soon { ui.state.first { it != null } }
        assertFalse("next on the done screen", ui.next())
        assertTrue(ui.back())
        assertEquals("""{"from":4,"type":"back"}""", fake.next())
        ui.stop()
    }

    @Test fun uiSocketReconnectsAfterTheHubDropsIt() = runBlocking {
        val first = FakeHub().also(::accept)
        val second = FakeHub().also(::accept)
        val ui = UiSocket(hub(), http, scope, fast) { null }
        ui.start()
        first.socket().close(CloseCodes.STALLED, "stalled")
        val ws = second.socket()
        ws.send(state2of4)
        assertEquals(2, soon { ui.state.first { it != null } }!!.step)
        assertEquals(SocketPhase.Open, ui.status.value.phase)
        ui.stop()
        assertEquals(SocketPhase.Idle, ui.status.value.phase)
        assertNull(ui.state.value)
    }

    @Test fun cameraSaysHelloFirstThenSendsFramesWhenIdle() = runBlocking {
        val fake = FakeHub().also(::accept)
        var now = 10_000L
        val cam = CameraSocket(hub(), http, scope, deviceId = "android-1", name = "Pixel camera", backoff = fast, clock = { now })
        cam.start()
        val ws = fake.socket()
        assertEquals("/ws/camera", server.takeRequest().path)
        assertEquals("""{"device_id":"android-1","name":"Pixel camera","source":"phone","type":"hello"}""", fake.next())
        soon { cam.status.first { it.phase == SocketPhase.Open } }

        val jpeg = ByteArray(1000).also { it[0] = 0xFF.toByte(); it[1] = 0xD8.toByte() }
        assertTrue(cam.sendFrame(jpeg))
        assertEquals(jpeg.toByteString(), fake.next())
        assertFalse("too soon after the last frame", cam.sendFrame(jpeg))
        now += 300
        assertTrue(cam.sendFrame(jpeg))
        assertEquals(jpeg.toByteString(), fake.next())
        assertEquals(2, cam.framesSent.value)

        assertFalse("not a JPEG", cam.sendFrame(byteArrayOf(1, 2, 3, 4)))
        assertFalse("over 2 MB", cam.sendFrame(ByteArray(CameraSocket.MAX_FRAME_BYTES + 1).also { it[0] = 0xFF.toByte(); it[1] = 0xD8.toByte() }))

        ws.send("""{"type":"camera_status","active":true}""")
        assertTrue(soon { cam.active.first { it } })

        cam.identify(source = "glasses")
        assertEquals("""{"device_id":"android-1","name":"Pixel camera","source":"glasses","type":"hello"}""", fake.next())

        ws.send(state2of4)
        soon { cam.state.first { it != null } }
        assertTrue(cam.next())
        assertEquals("""{"from":2,"reason":"button","type":"next"}""", fake.next())
        cam.stop()
        assertFalse(cam.active.value)
    }

    @Test fun cameraStopsOnReplaced() = runBlocking {
        val fake = FakeHub().also(::accept)
        val cam = CameraSocket(hub(), http, scope, deviceId = "android-1", name = "Pixel camera", backoff = fast)
        cam.start()
        fake.socket().close(CloseCodes.REPLACED, "replaced")
        val status = soon { cam.status.first { it.phase == SocketPhase.Replaced } }
        assertEquals("Another connection from this phone took over", status.lastError)
        Thread.sleep(300)
        assertEquals("no reconnect after 4000", 1, server.requestCount)
    }
}
