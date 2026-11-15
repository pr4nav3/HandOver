package com.handover.app.ui.pairing

import com.handover.app.core.HubUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingLinkTest {
    private fun connect(raw: String) = PairingLink.parse(raw) as PairingLink.Connect

    @Test fun hubQrCarriesHostPortAndName() {
        val t = connect("handover://connect?host=192.168.1.20&port=8000&name=Workshop%20hub").target
        assertEquals(HubUrl("192.168.1.20", 8000), t.hub)
        assertEquals("Workshop hub", t.title)
    }

    @Test fun hubQrWithoutNameFallsBackToHost() {
        val t = connect("handover://connect?host=10.0.0.5").target
        assertEquals(HubUrl("10.0.0.5", 8000), t.hub)
        assertNull(t.name)
        assertEquals("10.0.0.5", t.title)
    }

    @Test fun plainUrlsAndTypedAddressesWork() {
        assertEquals(HubUrl("192.168.1.20", 8000), connect("http://192.168.1.20:8000").target.hub)
        // The capture page QR: https on 8443 becomes plain http on 8000 (core HubUrl rule).
        assertEquals(HubUrl("192.168.1.20", 8000), connect("https://192.168.1.20:8443/capture?pair=4821").target.hub)
        assertEquals(HubUrl("hub.local", 8000), connect("hub.local").target.hub)
        assertEquals(HubUrl("192.168.1.20", 8000), connect("handover://192.168.1.20:8000").target.hub)
    }

    @Test fun joinLinksCarryNormalizedCodeAndOptionalHub() {
        val local = PairingLink.parse("handover://join?code=k7qm-2xpa") as PairingLink.Join
        assertEquals("k7qm-2xpa", local.code)
        assertNull(local.target)

        val remote = PairingLink.parse("handover://join?host=192.168.1.30&port=8001&code=K7QM%202XPA&name=Shop") as PairingLink.Join
        assertEquals("K7QM2XPA", remote.code)
        assertEquals(HubUrl("192.168.1.30", 8001), remote.target?.hub)
        assertEquals("Shop", remote.target?.name)
    }

    @Test fun junkIsRejected() {
        assertNull(PairingLink.parse(""))
        assertNull(PairingLink.parse("hello world"))
        assertNull(PairingLink.parse("handover://connect"))
        assertNull(PairingLink.parse("handover://join?code=ab"))
        assertNull(PairingLink.parse("mailto:someone@example.com"))
    }

    @Test fun typedAddressGate() {
        assertTrue(PairingLink.isTypedAddress("192.168.1.20"))
        assertTrue(PairingLink.isTypedAddress("192.168.1.20:8000"))
        assertFalse(PairingLink.isTypedAddress(""))
        assertFalse(PairingLink.isTypedAddress("not an address"))
    }

    @Test fun inviteCodeFormatting() {
        // The hub's codes are token_urlsafe(12): case sensitive, with - and _. Only spaces are dropped.
        assertEquals("k7Qm-2x_PaZ9wE4r", InviteCode.normalize(" k7Qm -2x_ PaZ9 wE4r "))
        assertEquals("K7QM 2XPA", InviteCode.grouped("K7QM2XPA"))
        assertEquals("Invite code K 7 Q M", InviteCode.spoken("K7QM"))
        assertNull(InviteCode.normalize("ab"))
        assertNull(InviteCode.normalize("ab+c/de=f"))
    }
}
