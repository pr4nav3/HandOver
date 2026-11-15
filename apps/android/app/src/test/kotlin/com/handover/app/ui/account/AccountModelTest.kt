package com.handover.app.ui.account

import com.handover.app.core.HubUrl
import com.handover.app.core.MemoryTokenStore
import com.handover.app.core.OrgRole
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
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

class AccountModelTest {
    private val server = MockWebServer()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @After fun down() = server.shutdown()

    private fun serve(routes: (RecordedRequest) -> MockResponse) {
        server.dispatcher = object : Dispatcher() { override fun dispatch(request: RecordedRequest) = routes(request) }
        server.start()
    }

    private fun model(kv: MemoryTokenStore = MemoryTokenStore()) = AccountModel(kv, OkHttpClient(), scope)
    private fun hub() = HubUrl(server.hostName, server.port)
    private val notFound = MockResponse().setResponseCode(404).setBody("""{"detail":"Not Found"}""")

    private fun AccountModel.await(test: (AccountState) -> Boolean) = runBlocking { withTimeout(5_000) { state.first(test) } }

    @Test fun hubWithoutAccountsHidesEverything() {
        serve { notFound }
        val m = model().apply { attach(hub()) }
        val s = m.await { it.support != AccountSupport.Unknown }
        assertEquals(AccountSupport.None, s.support)
        assertFalse(s.orgsSupported)
    }

    @Test fun firstRunSetupThenSignedInWithProgressFromRealRuns() {
        var token: String? = null
        serve { r ->
            val auth = r.getHeader("Authorization")
            when (r.path) {
                "/api/me" -> MockResponse().setBody(
                    if (auth == "Bearer t1") """{"user":{"id":"u1","name":"Sam","role":"owner"},"auth":"optional","setup_needed":false,"capabilities":{"can_create_org":true}}"""
                    else """{"user":null,"auth":"optional","setup_needed":${token == null}}""",
                )
                "/api/auth/setup" -> { token = "t1"; MockResponse().setBody("""{"user":{"id":"u1","name":"Sam","role":"owner"},"token":"t1"}""") }
                "/api/orgs" -> notFound
                "/api/courses" -> MockResponse().setBody(
                    """[{"id":"a","title":"Fold","steps":5,"progress":{"known":true,"runs":2,"completed":1,"last_steps_done":5,"last_finished":true,"total":5}},
                        {"id":"b","title":"Tie","steps":4,"progress":{"known":true,"runs":1,"completed":0,"last_steps_done":2,"last_finished":false,"total":4}},
                        {"id":"c","title":"New","steps":3,"progress":null}]""",
                )
                else -> notFound
            }
        }
        val kv = MemoryTokenStore()
        val m = model(kv).apply { attach(hub()) }
        assertTrue(m.await { it.support == AccountSupport.Available }.setupNeeded)
        m.setupOwner(" Sam ", "4821")
        val s = m.await { it.signedIn && it.courses.isNotEmpty() }
        assertEquals("Owner", s.user?.roleTitle)
        assertTrue(s.capabilities.canCreateOrg)
        assertEquals(listOf("a"), s.completed.map { it.id })
        assertEquals(listOf("b"), s.inProgress.map { it.id })
        assertNull("orgs stay hidden on a hub without them", s.orgs)
        assertEquals("t1", kv.token(hub().display))
        assertTrue(server.takeRequest().path == "/api/me")
    }

    @Test fun wrongPasscodeIsPlainWords() {
        serve { r ->
            when (r.path) {
                "/api/me" -> MockResponse().setBody("""{"user":null,"auth":"required","setup_needed":false}""")
                "/api/auth/login" -> MockResponse().setResponseCode(401).setBody("""{"detail":"wrong name or passcode"}""")
                else -> notFound
            }
        }
        val m = model().apply { attach(hub()) }
        assertTrue(m.await { it.support == AccountSupport.Available }.authRequired)
        m.signIn("Sam", "0000")
        assertEquals("That name and passcode do not match.", m.await { it.error != null }.error)
    }

    @Test fun orgsAreDetectedAndInviteErrorsMapped() {
        serve { r ->
            when (r.path) {
                "/api/me" -> MockResponse().setBody("""{"user":{"id":"u1","name":"Sam"},"auth":"optional"}""")
                "/api/orgs" -> MockResponse().setBody(
                    """{"orgs":[{"id":"o1","name":"Bike Shop","slug":"bike-shop","created":"2026-11-14T10:00:00Z","members":4,"role":"org_admin"}],
                        "invites":[{"id":"i1","kind":"user","role":"teacher","created":"2026-11-14T10:00:00Z","created_by":"Ana","expires":"2026-12-14T10:00:00Z","user":{"id":"u1","name":"Sam"},"org":{"id":"o2","name":"Origami","slug":"origami"}}]}""",
                )
                "/api/courses" -> MockResponse().setBody("[]")
                else -> notFound
            }
        }
        val m = model().apply { attach(hub()) }
        val s = m.await { it.orgs != null }
        val org = s.orgs!!.single()
        assertTrue(org.isAdmin)
        assertEquals(4, org.members)
        assertEquals(OrgRole.Teacher, OrgRole.from(s.invites.single().role))
        assertEquals("Origami", s.invites.single().org?.name)
        assertTrue("signed in people may create orgs (library.md)", s.capabilities.canCreateOrg)
        val e = com.handover.app.core.HubException(410, "invite expired")
        assertEquals("That code has expired. Ask the admin for a new one.", AccountModel.inviteError(e))
        assertEquals("That code does not work. Check it with the admin.", AccountModel.inviteError(com.handover.app.core.HubException(404, "invite code is not valid")))
        assertEquals("You are already in this organization.", AccountModel.inviteError(com.handover.app.core.HubException(409, "you are already a member of this organization")))
        assertEquals("Too many tries. Wait a minute, then try again.", AccountModel.inviteError(com.handover.app.core.HubException(429, "too many join attempts; try again in a minute")))
        assertEquals(7.0, AccountModel.inviteDays(168), 0.0001)
        assertEquals(90.0, AccountModel.inviteDays(null), 0.0001)
    }

    @Test fun refusedTokenIsDropped() {
        val kv = MemoryTokenStore()
        serve { r ->
            if (r.path == "/api/me" && r.getHeader("Authorization") != null) MockResponse().setResponseCode(401).setBody("""{"detail":"sign in required"}""")
            else if (r.path == "/api/me") MockResponse().setBody("""{"user":null}""") else notFound
        }
        kv.save(hub().display, "old")
        val m = model(kv).apply { attach(hub()) }
        m.await { it.support == AccountSupport.Available }
        assertNull(kv.token(hub().display))
    }
}
