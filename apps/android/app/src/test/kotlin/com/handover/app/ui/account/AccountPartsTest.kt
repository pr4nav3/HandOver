package com.handover.app.ui.account

import com.handover.app.core.HubUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AccountPartsTest {
    @Test fun passcodeStrengthFollowsTheSpecTable() {
        assertEquals(Strength.TooShort, Passcode.strength("12"))
        assertEquals(Strength.Easy, Passcode.strength("4821"))
        assertEquals(Strength.Easy, Passcode.strength("111111"))
        assertEquals(Strength.Easy, Passcode.strength("123456"))
        assertEquals(Strength.Easy, Passcode.strength("abcdefgh"))
        assertEquals(Strength.Ok, Passcode.strength("482913"))
        assertEquals(Strength.Ok, Passcode.strength("pumpkins"))
        assertEquals(Strength.Hard, Passcode.strength("fold4corners"))
        assertTrue(Passcode.isRun("dcba"))
        assertFalse(Passcode.isRun("1243"))
    }

    @Test fun initialsAndStableHue() {
        assertEquals("SR", Initials.of("Sam Rivera"))
        assertEquals("S", Initials.of("sam"))
        assertEquals("AB", Initials.of("  ann   bell  carter "))
        assertEquals("?", Initials.of(""))
        assertEquals(AvatarHue.forName("Sam Rivera"), AvatarHue.forName(" sam rivera "))
    }

    @Test fun joinLinkCarriesTheHub() {
        assertEquals(
            "handover://join?code=K7QM2XPA&host=192.168.1.20&port=8000&name=Bike%20Shop",
            joinLink("K7QM2XPA", HubUrl("192.168.1.20", 8000), "Bike Shop"),
        )
        assertEquals("handover://join?code=K7QM2XPA", joinLink("K7QM2XPA", null, null))
    }

    @Test fun orgMetaLeavesOutWhatTheHubDidNotSend() {
        assertEquals("1 lesson, 4 members", orgMeta(Org(name = "A", lessons = 1, members = 4)))
        assertEquals("4 members", orgMeta(Org(name = "A", members = 4)))
        assertEquals(null, orgMeta(Org(name = "A")))
    }
}
