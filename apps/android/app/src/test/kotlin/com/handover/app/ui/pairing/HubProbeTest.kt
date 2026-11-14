package com.handover.app.ui.pairing

import com.handover.app.core.HubUrl
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.ServerSocket
import java.util.concurrent.TimeUnit

class HubProbeTest {
    private val server = MockWebServer()
    private val http = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()

    @Before fun up() = server.start()
    @After fun down() = server.shutdown()

    private fun hub() = HubUrl(server.hostName, server.port)

    @Test fun lessonsArrayMeansConnectedWithCount() = runBlocking {
        server.enqueue(MockResponse().setBody("""[{"id":"a","title":"A","steps":3},{"id":"b"}]"""))
        assertEquals(ProbeResult.Connected(2), HubProbe.probe(hub(), http))
        assertEquals("/api/lessons", server.takeRequest().path)
    }

    @Test fun somethingElseAnsweringIsNotAHub() = runBlocking {
        server.enqueue(MockResponse().setBody("<html>router login</html>"))
        assertEquals(ProbeResult.NotAHub, HubProbe.probe(hub(), http))
        server.enqueue(MockResponse().setResponseCode(404).setBody("nope"))
        assertEquals(ProbeResult.NotAHub, HubProbe.probe(hub(), http))
    }

    @Test fun closedPortIsUnreachableWithAReason() = runBlocking {
        val port = ServerSocket(0).use { it.localPort }
        val result = HubProbe.probe(HubUrl("127.0.0.1", port), http)
        assertTrue(result is ProbeResult.Unreachable)
        assertEquals("Nothing is listening at that address and port.", (result as ProbeResult.Unreachable).reason)
    }
}
