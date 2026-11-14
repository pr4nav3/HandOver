package com.handover.app.ui.account

import com.handover.app.core.HubException
import com.handover.app.core.HubUrl
import com.handover.app.ui.settings.KeyValue
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
    val busy: Boolean = false,
    /** One plain sentence for the field or card that failed, or null. */
    val error: String? = null,
) {
    val signedIn: Boolean get() = user != null
    val orgsSupported: Boolean get() = orgs != null
    val inProgress: List<CourseItem> get() = courses.filter { val p = it.progress; p != null && p.known && !p.lastFinished && p.lastStepsDone > 0 }
    val completed: List<CourseItem> get() = courses.filter { (it.progress?.completed ?: 0) > 0 }
}

/** Remembers the sign-in token for each hub, so switching hubs keeps each one's session. */
class TokenStore(private val kv: KeyValue) {
    fun token(hub: String): String? = kv.string("token:$hub")
    fun save(hub: String, token: String?) = kv.putString("token:$hub", token)
}

/**
 * The accounts and organizations session for one hub. Screens call these methods; failures land in
 * [AccountState.error] as one sentence. A token the hub refuses (401 on /api/me) is dropped.
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
                    user = me.user, capabilities = me.capabilities ?: Capabilities(),
                )
            }
            loadSignedIn(a)
        }
    }

    private suspend fun loadSignedIn(a: AccountApi) {
        val orgs = quiet { a.orgs() }
        _state.update { it.copy(orgs = orgs) }
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
            _state.update { it.copy(user = null, courses = emptyList(), capabilities = Capabilities()) }
            refresh()
        }
    }

    fun clearError() = _state.update { it.copy(error = null) }

    // ------------------------------------------------------------ organizations

    fun createOrg(name: String, about: String?, onDone: (Org) -> Unit) {
        val a = api ?: return
        run({ e -> if (e is HubException && e.status == 409) "An organization with that name already exists." else generic(e) }) {
            val org = a.createOrg(name.trim(), about?.trim())
            refresh()
            onDone(org)
        }
    }

    suspend fun org(id: String): Result<OrgPage> = call { it.org(id) }

    suspend fun previewInvite(code: String): Result<InvitePreview> = call { it.previewInvite(code) }

    fun acceptInvite(code: String, onDone: (Org) -> Unit) {
        val a = api ?: return
        run(::inviteError) {
            val org = a.acceptInvite(code)
            refresh()
            onDone(org)
        }
    }

    suspend fun createInvite(orgId: String, role: OrgRole, hours: Int?, uses: Int?): Result<OrgInvite> = call { it.createInvite(orgId, role, hours, uses) }

    suspend fun revokeInvite(orgId: String, code: String): Result<Unit> = call { it.revokeInvite(orgId, code) }

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
                "expired" in detail -> "That code has expired. Ask the admin for a new one."
                "used" in detail -> "That code has been used up. Ask the admin for a new one."
                h.status in setOf(400, 404, 410) -> "That code does not work. Check it with the admin."
                else -> generic(e)
            }
        }

        fun generic(e: IOException): String =
            if (e is HubException) e.detail.replaceFirstChar(Char::uppercase) else "Could not reach the hub. Check the Wi-Fi and try again."
    }
}
