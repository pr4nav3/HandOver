package com.handover.app.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HubUrlTest {
    private fun parse(raw: String?) = HubUrl.parse(raw)

    @Test fun typedAddresses() {
        assertEquals(HubUrl("192.168.1.20", 8000), parse("192.168.1.20"))
        assertEquals(HubUrl("192.168.1.20", 8000), parse("  192.168.1.20:8000  "))
        assertEquals(HubUrl("192.168.1.20", 9000), parse("192.168.1.20:9000"))
        assertEquals(HubUrl("mac.local", 8000), parse("mac.local"))
        assertEquals(HubUrl("mac.local", 8000), parse("MAC.local"))
        assertEquals(HubUrl("192.168.1.20", 8000), parse("192.168.1.20/"))
    }

    @Test fun ipv6() {
        val hub = parse("[fe80::1]:8001")!!
        assertEquals(8001, hub.port)
        assertEquals("fe80::1", hub.host)
        assertEquals("[fe80::1]:8001", hub.display)
        assertEquals("ws://[fe80::1]:8001/ws/ui", hub.uiSocket)
        assertEquals(8000, parse("[fe80::1]")!!.port)
    }

    @Test fun urls() {
        assertEquals(HubUrl("10.0.0.5", 8000), parse("http://10.0.0.5:8000/#/learn"))
        assertEquals(HubUrl("10.0.0.5", 8000), parse("http://10.0.0.5"))
        assertEquals(HubUrl("10.0.0.5", 8000), parse("HTTP://10.0.0.5:8000/api/lessons?x=1"))
        assertEquals(HubUrl("10.0.0.5", 8000), parse("ws://10.0.0.5:8000/ws/camera"))
        assertEquals(HubUrl("hub.example.com", 443, secure = true), parse("https://hub.example.com/capture"))
        assertEquals(HubUrl("hub.example.com", 443, secure = true), parse("wss://hub.example.com/ws/ui"))
        assertEquals(HubUrl("hub.example.com", 9443, secure = true), parse("https://hub.example.com:9443"))
    }

    @Test fun captureQrMapsToPlainHttp() {
        // The browser QR points at the hub's self-signed https port; the app uses plain http on 8000.
        assertEquals(HubUrl("192.168.1.20", 8000), parse("https://192.168.1.20:8443/capture?pair=4821"))
        assertEquals(HubUrl("192.168.1.20", 8000), parse("wss://192.168.1.20:8443/ws/camera"))
    }

    @Test fun deepLinks() {
        assertEquals(HubUrl("192.168.1.20", 8000), parse("handover://connect?host=192.168.1.20&port=8000"))
        assertEquals(HubUrl("192.168.1.20", 8000), parse("handover://connect?host=192.168.1.20"))
        assertEquals(HubUrl("192.168.1.20", 8123), parse("handover://192.168.1.20:8123"))
        assertEquals(HubUrl("192.168.1.20", 8000), parse("HANDOVER://192.168.1.20"))
        assertEquals(HubUrl("fe80::1", 8000), parse("handover://connect?host=fe80::1&port=8000"))
        assertEquals(HubUrl("t.example.com", 443, secure = true), parse("handover://connect?host=t.example.com&port=443&secure=1"))
        assertNull(parse("handover://connect"))
        assertNull(parse("handover://connect?host=1.2.3.4&port=abc"))
        assertNull(parse("handover://"))
    }

    @Test fun rejects() {
        assertNull(parse(null))
        assertNull(parse(""))
        assertNull(parse("   "))
        assertNull(parse("hello world"))
        assertNull(parse("ftp://10.0.0.5"))
        assertNull(parse("192.168.1.20:99999"))
        assertNull(parse("192.168.1.20:port"))
        assertNull(parse("http://"))
    }

    @Test fun derivedUrls() {
        val hub = HubUrl("192.168.1.20", 8000)
        assertEquals("http://192.168.1.20:8000/", hub.httpBase)
        assertEquals("ws://192.168.1.20:8000/ws/ui", hub.uiSocket)
        assertEquals("ws://192.168.1.20:8000/ws/camera", hub.cameraSocket)
        assertEquals("http://192.168.1.20:8000/api/lessons", hub.http("api/lessons").toString())
        assertEquals("192.168.1.20:8000", hub.display)
        val secure = HubUrl("t.example.com", 443, secure = true)
        assertEquals("wss://t.example.com/ws/ui", secure.uiSocket)
        assertEquals("https://t.example.com:443", secure.display)
        // What is stored is what comes back.
        assertEquals(hub, parse(hub.display))
        assertEquals(secure, parse(secure.display))
    }
}
