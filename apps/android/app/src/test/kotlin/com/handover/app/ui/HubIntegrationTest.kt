package com.handover.app.ui

import com.handover.app.core.AccountApi
import com.handover.app.core.HubClient
import com.handover.app.core.HubException
import com.handover.app.core.HubState
import com.handover.app.core.HubUrl
import com.handover.app.core.OrgRole
import com.handover.app.core.SocketPhase
import com.handover.app.core.StepStatus
import com.handover.app.core.UiSocket
import com.handover.app.ui.done.DoneApi
import com.handover.app.ui.done.ScoreFetch
import com.handover.app.ui.library.CourseApi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * The app's clients against the REAL hub (server.main) in mock check mode. Skipped when no hub
 * answers at HANDOVER_TEST_HUB (default 127.0.0.1:8300). Start one from the repo root with:
 *
 *   HANDOVER_PORT=8300 HANDOVER_HTTPS_PORT=8301 HANDOVER_CERTS=/nonexistent HANDOVER_CHECK=mock
 *   HANDOVER_NO_NETWORK=1 HANDOVER_MOCK_PASS_SECONDS=1 HANDOVER_DATA=/tmp/ho-and/data
 *   HANDOVER_EVENTS_JSONL=/tmp/ho-and/events.jsonl HANDOVER_LESSONS=<copy of lessons/> .venv/bin/python -m server.main
 *
 * One test, in order, because each step needs the one before: owner setup (or login on a rerun),
 * create an org, make an invite code, a second user joins with it, list courses, select a lesson
 * with the token, read check_mode and run_id from state, finish the run with server.replay plus
 * Next on the manual step, then fetch the run's score.
 */
class HubIntegrationTest {
    private val hub = HubUrl.parse(System.getenv("HANDOVER_TEST_HUB") ?: "127.0.0.1:8300")!!
    private val http = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val repo = File("../../..").canonicalFile
    private var replay: Process? = null

    @Before fun hubIsUp() {
        val up = runCatching {
            http.newCall(Request.Builder().url(hub.http("api/lessons")).build()).execute().use { it.isSuccessful }
        }.getOrDefault(false)
        assumeTrue("no hub at ${hub.display}; start server.main to run this test", up)
    }

    @After fun down() {
        replay?.destroy()
        replay?.waitFor(5, TimeUnit.SECONDS)
        replay?.destroyForcibly()
        scope.cancel()
    }

    @Test fun ownerOrgInviteJoinCoursesSelectStateAndScore() = runBlocking {
        val anonymous = AccountApi(hub, http) { null }
        val me = anonymous.me()
        assertNotNull("this hub has accounts", me)

        // 1. Owner setup on a fresh data folder, login on a rerun.
        val ownerName = "Owner"
        val ownerPass = "integration-pass-1"
        val ownerToken = if (me!!.setupNeeded) {
            anonymous.setupOwner(ownerName, ownerPass).also { assertEquals("owner", it.user.role) }.token
        } else {
            login(anonymous, ownerName, ownerPass)
        }
        val owner = AccountApi(hub, http) { ownerToken }
        val signedIn = owner.me()!!
        assertEquals(ownerName, signedIn.user?.name)

        // 2. Create an org and an invite code (learner, 1 day, no use limit).
        val orgName = "Bike Shop ${System.currentTimeMillis() % 100_000}"
        val org = owner.createOrg(orgName)
        assertEquals(orgName, org.name)
        assertEquals(OrgRole.Admin, org.myRole)
        val invite = owner.createInvite(org.id, OrgRole.Member, expiresDays = 1.0, maxUses = null)
        val code = invite.code ?: error("a new code invite carries its code")
        assertEquals(null, invite.maxUses)

        // 3. A second user (made by the hub owner) signs in and joins with the code.
        val learnerName = "Learner ${System.currentTimeMillis() % 100_000}"
        val learnerPass = "integration-pass-2"
        postJson("api/users", ownerToken, buildJsonObject { put("name", learnerName); put("role", "learner"); put("passcode", learnerPass) }.toString())
        val learnerToken = login(anonymous, learnerName, learnerPass)
        val learner = AccountApi(hub, http) { learnerToken }
        val joined = learner.join(code)
        assertEquals(org.id, joined.id)
        assertEquals(OrgRole.Member, joined.myRole)
        val page = owner.org(org.id)
        assertTrue("the learner is a member", page.members.any { it.name == learnerName && it.orgRole == OrgRole.Member })
        assertTrue("the owner sees the live invites", page.canManage && page.invites!!.any { it.id == invite.id && it.uses == 1 })
        assertTrue(learner.orgs()!!.orgs.any { it.id == org.id })
        val again = runCatching { learner.join(code) }.exceptionOrNull() as? HubException
        assertEquals(409, again?.status)

        // 4. List courses with the token.
        val courses = CourseApi(hub, http) { ownerToken }.courses("all")
        assertNotNull("this hub has the library", courses)
        val lessonId = "demo-v1"
        assertTrue("lessons copied into the hub's folder are listed", courses!!.any { it.id == lessonId })

        // 5. Select a lesson with the token on /ws/ui?frames=0, and read check_mode and run_id from state.
        val framesWhileOff = AtomicInteger()
        val ui = UiSocket(hub, http, scope, frames = false) { framesWhileOff.incrementAndGet(); null }
        ui.start()
        withTimeout(10_000) { ui.status.first { it.phase == SocketPhase.Open } }
        // The hub sends its state on connect. On a rerun it may still show the last run's done screen, so the
        // new run is the first state after the select with a different run_id.
        val before = withTimeout(10_000) { ui.state.filterNotNull().first() }.runId
        assertTrue(ui.selectLesson(lessonId, learnerToken))
        val first = withTimeout(10_000) {
            ui.state.filterNotNull().first { it.lessonId == lessonId && it.runId != null && it.runId != before && !it.done }
        }
        assertEquals("mock", first.checkMode)
        val runId = first.runId!!

        // 6. Finish the run: replay the lesson's own video as the camera, Next on the manual step.
        val python = File(repo, ".venv/bin/python")
        assumeTrue("the repo's .venv is needed to run server.replay", python.canExecute())
        replay = ProcessBuilder(
            python.path, "-m", "server.replay", File(repo, "lessons/$lessonId/norm.mp4").path,
            "--url", hub.cameraSocket, "--fps", "2", "--loop",
        ).directory(repo).redirectErrorStream(true).redirectOutput(File(System.getProperty("java.io.tmpdir"), "handover-replay.log")).start()
        val withFrames = AtomicInteger()
        val viewer = UiSocket(hub, http, scope) { withFrames.incrementAndGet(); null }
        viewer.start()
        val done = withTimeout(120_000) {
            var last: HubState? = null
            while (true) {
                val s = ui.state.value
                if (s != null && s.lessonId == lessonId && s.done) break
                if (s != null && s.status == StepStatus.Manual && s != last) ui.next(s)
                last = s
                delay(250)
            }
            ui.state.value!!
        }
        assertEquals("run_id is kept on the done screen", runId, done.runId)
        assertTrue("a plain viewer gets live frames", withFrames.get() > 0)
        assertEquals("frames=0 gets no live frames", 0, framesWhileOff.get())

        // 7. The Done screen's score for this run, with the learner's token.
        val score = DoneApi.runScore(hub, runId, http, learnerToken, retries = 6, retryDelayMs = 1_000)
        assertTrue("score fetched: $score", score is ScoreFetch.Found)
        val found = (score as ScoreFetch.Found).score
        assertTrue("a whole run has a score", found.score != null && found.label != null)

        // 8. And a rating from the learner (a legacy lesson anyone signed in may rate).
        assertEquals(null, DoneApi.rate(hub, lessonId, 5, "Clear steps", http, learnerToken))
        ui.stop()
        viewer.stop()
    }

    /** Login, honoring the hub's limit (429, Retry-After 60) when the test is rerun back to back. */
    private suspend fun login(api: AccountApi, name: String, passcode: String): String = try {
        api.login(name, passcode).token
    } catch (e: HubException) {
        if (e.status != 429) throw e
        delay(61_000)
        api.login(name, passcode).token
    }

    private fun postJson(path: String, token: String, body: String): String {
        val request = Request.Builder().url(hub.http(path)).header("Authorization", "Bearer $token")
            .post(body.toRequestBody("application/json".toMediaType())).build()
        http.newCall(request).execute().use { r ->
            val text = r.body?.string().orEmpty()
            if (!r.isSuccessful) throw HubException(r.code, HubClient.detailOf(text, r.message))
            return text
        }
    }
}
