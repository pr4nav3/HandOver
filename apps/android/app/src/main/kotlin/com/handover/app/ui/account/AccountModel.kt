package com.handover.app.ui.account

import com.handover.app.core.AccountApi
import com.handover.app.core.AuthReply
import com.handover.app.core.Capabilities
import com.handover.app.core.CourseItem
import com.handover.app.core.HubException
import com.handover.app.core.HubUrl
import com.handover.app.core.HubUser
import com.handover.app.core.Org
import com.handover.app.core.OrgInvite
import com.handover.app.core.OrgPage
import com.handover.app.core.OrgRole
import com.handover.app.core.TokenStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.io.IOException

/** Where accounts stand on the current hub. */
enum class AccountSupport {
    /** Not checked yet, or no hub. */
    Unknown,

    /** The hub has no /api/me: one shared session, no account screens (SCREENS.md 4). */
    None,

    /** The hub has accounts. */
    Available,
}

data class AccountState(
    val support: AccountSupport = AccountSupport.Unknown,
    /** "required" means nothing works until sign in. */
    val authRequired: Boolean = false,
    /** No users yet: this device may become the owner (SCREENS.md 4.5). */
    val setupNeeded: Boolean = false,
    val user: HubUser? = null,
    val capabilities: Capabilities = Capabilities(),
    /** Courses with the signed-in person's own progress, from real runs. */
    val courses: List<CourseItem> = emptyList(),
    /** Null when the hub has no organizations; empty when it has them and I am in none. */
    val orgs: List<Org>? = null,
    /** Invites sent to me by name that I have not answered (each carries its org). */
    val invites: List<OrgInvite> = emptyList(),
    val busy: Boolean = false,
    /** One plain sentence for the field or card that failed, or null. */
    val error: String? = null,
) {
    val signedIn: Boolean get() = user != null
    val orgsSupported: Boolean get() = orgs != null
    val inProgress: List<CourseItem> get() = courses.filter { val p = it.progress; p != null && p.known && !p.lastFinished && p.lastStepsDone > 0 }
    val completed: List<CourseItem> get() = courses.filter { (it.progress?.completed ?: 0) > 0 }
}

/** What joining with a code gave: the org, the role, and whether this person was already in it. */
data class InvitePreview(val org: Org = Org(), val role: String = "learner", val alreadyMember: Boolean = false, val joined: Boolean = false)

/**
 * The accounts and organizations session for one hub. Screens call these methods; failures land in
 * [AccountState.error] as one sentence. A token the hub refuses (401 on /api/me) is dropped. Tokens
 * are kept per hub in [tokens] (the app passes core's Keystore-backed AccountSession store).
 */
class AccountModel(
    private val tokens: TokenStore,
    private val http: OkHttpClient,
    private val scope: CoroutineScope,
) {
    private val _state = MutableStateFlow(AccountState())
    val state: StateFlow<AccountState> = _state.asStateFlow()

    private var hub: HubUrl? = null
    private var api: AccountApi? = null
    private var refreshJob: Job? = null

    /** Points the model at [hub] and checks what it supports. Same hub again just refreshes. */
    fun attach(hub: HubUrl?) {
        if (hub == this.hub && _state.value.support != AccountSupport.Unknown) return
        this.hub = hub
        api = hub?.let { h -> AccountApi(h, http) { tokens.token(h.display) } }
        _state.value = AccountState()
        refresh()
    }

    fun refresh() {
        val a = api ?: return
        refreshJob?.cancel()
        refreshJob = scope.launch {
            val me = try {
                a.me()
            } catch (e: HubException) {
                if (e.status == 401) {
                    hub?.let { tokens.save(it.display, null) }
                    runCatching { a.me() }.getOrNull()
                } else null
            } catch (e: CancellationException) {
                throw e
            } catch (e: IOException) {
                null
            }
            if (me == null) {
                _state.update { it.copy(support = if (it.support == AccountSupport.Unknown) AccountSupport.None else it.support) }
                return@launch
            }
            _state.update {
                it.copy(
                    support = AccountSupport.Available, authRequired = me.auth == "required", setupNeeded = me.setupNeeded,
                    user = me.user, capabilities = me.capabilities ?: Capabilities.derive(me.user),
                )
            }
            loadSignedIn(a)
        }
    }

    private suspend fun loadSignedIn(a: AccountApi) {
        // GET /api/orgs needs a signed-in user; signed out, organizations stay hidden.
        val mine = if (_state.value.user != null) quiet { a.orgs() } else null
        _state.update { it.copy(orgs = mine?.orgs, invites = mine?.invites.orEmpty()) }
        if (_state.value.user != null) {
            val courses = quiet { a.courses() }.orEmpty()
            _state.update { it.copy(courses = courses) }
        }
    }

    fun signIn(name: String, passcode: String, onDone: () -> Unit = {}) = auth(onDone) { it.login(name.trim(), passcode) }

    fun setupOwner(name: String, passcode: String, onDone: () -> Unit = {}) = auth(onDone) { it.setupOwner(name.trim(), passcode) }

    private fun auth(onDone: () -> Unit, call: suspend (AccountApi) -> AuthReply) {
        val a = api ?: return
        val h = hub ?: return
        run({ e -> authError(e) }) {
            val reply = call(a)
            tokens.save(h.display, reply.token)
            _state.update { it.copy(user = reply.user, setupNeeded = false) }
            refresh()
            onDone()
        }
    }

    fun signOut() {
        val a = api ?: return
        val h = hub ?: return
        scope.launch {
            quiet { a.logout() }
            tokens.save(h.display, null)
            _state.update { it.copy(user = null, courses = emptyList(), orgs = null, invites = emptyList(), capabilities = Capabilities()) }
            refresh()
        }
    }

    fun clearError() = _state.update { it.copy(error = null) }

    // ------------------------------------------------------------ organizations

    fun createOrg(name: String, onDone: (Org) -> Unit) {
        val a = api ?: return
        run({ e -> if (e is HubException && e.status == 409) "An organization with that name already exists." else generic(e) }) {
            val org = a.createOrg(name.trim())
            refresh()
            onDone(org)
        }
    }

    suspend fun org(id: String): Result<OrgPage> = call { it.org(id) }

    /**
     * Joins with an invite code. The hub has no preview route (library.md), so the code is used right
     * away and the welcome card shows the org that was joined. Already a member comes back as a 409.
     */
    suspend fun join(code: String): Result<InvitePreview> =
        call { api -> api.join(code).let { org -> InvitePreview(org, role = org.role ?: "learner", joined = true) } }
            .also { if (it.isSuccess) refresh() }

    /** Accepts an invite sent to me by name. */
    fun acceptInvite(invite: OrgInvite, onDone: (Org) -> Unit) {
        val a = api ?: return
        run(::inviteError) {
            val org = a.acceptInvite(invite.id)
            refresh()
            onDone(org)
        }
    }

    /** Declines an invite sent to me by name. */
    suspend fun declineInvite(invite: OrgInvite): Result<Unit> {
        val orgId = invite.org?.id ?: return Result.failure(java.io.IOException("This invite has no organization."))
        return call { it.revokeInvite(orgId, invite.id) }.also { if (it.isSuccess) refresh() }
    }

    /** A code invite: [hours] until it expires (null = the hub's longest, 90 days), [uses] null for no limit. */
    suspend fun createInvite(orgId: String, role: OrgRole, hours: Int?, uses: Int?): Result<OrgInvite> =
        call { it.createInvite(orgId, role, inviteDays(hours), uses) }

    suspend fun revokeInvite(orgId: String, inviteId: String): Result<Unit> = call { it.revokeInvite(orgId, inviteId) }

    suspend fun setRole(orgId: String, userId: String, role: OrgRole): Result<Unit> = call { it.setRole(orgId, userId, role) }

    suspend fun removeMember(orgId: String, userId: String): Result<Unit> = call { it.removeMember(orgId, userId) }

    suspend fun leave(orgId: String): Result<Unit> = call { it.leave(orgId) }.also { if (it.isSuccess) refresh() }

    // ------------------------------------------------------------ plumbing

    private suspend fun <T> call(block: suspend (AccountApi) -> T): Result<T> {
        val a = api ?: return Result.failure(IOException("Not connected to the hub."))
        return try {
            Result.success(block(a))
        } catch (e: CancellationException) {
            throw e
        } catch (e: IOException) {
            Result.failure(IOException(if (e is HubException) e.detail.replaceFirstChar(Char::uppercase) else generic(e), e))
        }
    }

    private fun run(message: (IOException) -> String, block: suspend () -> Unit) {
        scope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                block()
                _state.update { it.copy(busy = false) }
            } catch (e: CancellationException) {
                throw e
            } catch (e: IOException) {
                _state.update { it.copy(busy = false, error = message(e)) }
            }
        }
    }

    private suspend fun <T> quiet(block: suspend () -> T): T? = try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: IOException) {
        null
    }

    companion object {
        fun authError(e: IOException): String = when ((e as? HubException)?.status) {
            401 -> "That name and passcode do not match."
            429 -> "Too many tries. Wait a minute, then try again."
            409 -> "Someone else set up this hub. Sign in with the account they give you."
            400 -> (e as HubException).detail.replaceFirstChar(Char::uppercase).trimEnd('.') + "."
            else -> generic(e)
        }

        fun inviteError(e: IOException): String {
            val h = e as? HubException ?: return generic(e)
            val detail = h.detail.lowercase()
            return when {
                h.status == 409 -> "You are already in this organization."
                h.status == 429 -> "Too many tries. Wait a minute, then try again."
                "expired" in detail -> "That code has expired. Ask the admin for a new one."
                "used" in detail -> "That code has been used up. Ask the admin for a new one."
                h.status in setOf(400, 404, 410) -> "That code does not work. Check it with the admin."
                else -> generic(e)
            }
        }

        /** Hours to the hub's `expires_days` (0.01 to 90). Null, "Never" on screen, becomes the 90 day limit. */
        fun inviteDays(hours: Int?): Double = ((hours ?: (90 * 24)) / 24.0).coerceIn(0.01, 90.0)

        fun generic(e: IOException): String =
            if (e is HubException) e.detail.replaceFirstChar(Char::uppercase) else "Could not reach the hub. Check the Wi-Fi and try again."
    }
}
