package com.handover.app.ui.account

import com.handover.app.core.HubException
import com.handover.app.core.HubJson
import com.handover.app.core.HubUrl
import com.handover.app.core.await
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

// Accounts (server/routes_library.py, /api/me and /api/auth/*) and organizations. Everything is
// feature-detected: a hub without the route answers 404 and the app hides the feature. The
// organization routes do not exist on the hub yet (SCREENS.md section 19); the shapes below are the
// app's proposal and every field is optional so a slightly different hub still decodes.

@Serializable
data class HubUser(
    val id: String = "",
    val name: String = "",
    /** owner, teacher or learner. */
    val role: String = "learner",
    val username: String? = null,
) {
    val roleTitle: String get() = when (role) { "owner" -> "Owner"; "teacher" -> "Teacher"; else -> "Learner" }
}

/** What the session may do (SCREENS.md 24). Missing means not allowed: the app never guesses. */
@Serializable
data class Capabilities(
    @SerialName("can_create_org") val canCreateOrg: Boolean = false,
    @SerialName("is_hub_owner") val isHubOwner: Boolean = false,
)

@Serializable
data class MeReply(
    val user: HubUser? = null,
    /** "optional" (anonymous callers allowed) or "required". */
    val auth: String = "optional",
    @SerialName("setup_needed") val setupNeeded: Boolean = false,
    val capabilities: Capabilities? = null,
)

@Serializable
data class AuthReply(val user: HubUser, val token: String, val expires: String? = null)

/** The caller's own progress on one course, from real runs only (library.progress on the hub). */
@Serializable
data class CourseProgress(
    val known: Boolean = false,
    val runs: Int = 0,
    val completed: Int = 0,
    @SerialName("best_steps_done") val bestStepsDone: Int = 0,
    @SerialName("last_steps_done") val lastStepsDone: Int = 0,
    @SerialName("last_finished") val lastFinished: Boolean = false,
    val total: Int = 0,
)

@Serializable
data class CourseItem(
    val id: String,
    val title: String = "",
    val steps: Int = 0,
    val progress: CourseProgress? = null,
)

/** Org roles (SCREENS.md 22): Admin, Teacher, Member. */
enum class OrgRole(val id: String, val title: String) {
    Admin("admin", "Admin"), Teacher("teacher", "Teacher"), Member("member", "Member");

    companion object {
        fun from(id: String?): OrgRole = entries.firstOrNull { it.id == id?.lowercase() } ?: Member
    }
}

@Serializable
data class Org(
    val id: String = "",
    val name: String = "",
    val about: String? = null,
    /** The caller's role in this org, or null when not a member. */
    val role: String? = null,
    val members: Int? = null,
    val lessons: Int? = null,
) {
    val myRole: OrgRole? get() = role?.let(OrgRole::from)
    val isAdmin: Boolean get() = myRole == OrgRole.Admin
}

@Serializable
data class OrgMember(
    @SerialName("user_id") val userId: String = "",
    val name: String = "",
    val username: String? = null,
    val role: String = "member",
) {
    val orgRole: OrgRole get() = OrgRole.from(role)
}

@Serializable
data class OrgLesson(val id: String = "", val title: String = "", val steps: Int = 0)

@Serializable
data class OrgInvite(
    val code: String = "",
    val role: String = "member",
    /** ISO time, or null for never. */
    val expires: String? = null,
    val uses: Int = 0,
    @SerialName("max_uses") val maxUses: Int? = null,
    val expired: Boolean = false,
)

/** The org page: the org, its members and its lessons, and the active codes for admins. */
data class OrgPage(val org: Org, val members: List<OrgMember>, val lessons: List<OrgLesson>, val invites: List<OrgInvite>)

/** What an invite code opens, before joining (SCREENS.md 22.3). */
@Serializable
data class InvitePreview(val org: Org = Org(), val role: String = "member", @SerialName("already_member") val alreadyMember: Boolean = false)

/** A feature the hub does not have (404 on its route). */
class NotOnHub : IOException("not on this hub")

class AccountApi(private val hub: HubUrl, private val http: OkHttpClient, private val token: () -> String?) {

    /** The session, or null when the hub has no accounts at all. */
    suspend fun me(): MeReply? = try {
        get("api/me", MeReply.serializer())
    } catch (e: NotOnHub) {
        null
    }

    suspend fun setupOwner(name: String, passcode: String): AuthReply =
        post("api/auth/setup", body { put("name", name); put("passcode", passcode) }, AuthReply.serializer())

    suspend fun login(name: String, passcode: String): AuthReply =
        post("api/auth/login", body { put("name", name); put("passcode", passcode) }, AuthReply.serializer())

    suspend fun logout() {
        post("api/auth/logout", body {}, JsonElement.serializer())
    }

    /** Courses the caller can see, each with their own progress when known. */
    suspend fun courses(): List<CourseItem> = get("api/courses", ListSerializer(CourseItem.serializer()))

    // ------------------------------------------------------------ organizations (proposed routes)

    /** My orgs, or null when the hub has no organizations. */
    suspend fun orgs(): List<Org>? = try {
        get("api/orgs", ListSerializer(Org.serializer()))
    } catch (e: NotOnHub) {
        null
    }

    suspend fun createOrg(name: String, about: String?): Org =
        post("api/orgs", body { put("name", name); if (!about.isNullOrBlank()) put("about", about) }, Org.serializer())

    suspend fun org(id: String): OrgPage {
        val obj = get("api/orgs/$id", JsonObject.serializer())
        val orgJson = obj["org"] as? JsonObject ?: obj
        fun <T> list(key: String, s: KSerializer<T>): List<T> =
            obj[key]?.let { runCatching { HubJson.decodeFromJsonElement(ListSerializer(s), it) }.getOrNull() }.orEmpty()
        val org = HubJson.decodeFromJsonElement(Org.serializer(), orgJson)
        val members = list("members", OrgMember.serializer()).takeIf { obj["members"] !is JsonPrimitive }.orEmpty()
        val lessons = list("lessons", OrgLesson.serializer()).takeIf { obj["lessons"] !is JsonPrimitive }.orEmpty()
        return OrgPage(org, members, lessons, list("invites", OrgInvite.serializer()))
    }

    suspend fun previewInvite(code: String): InvitePreview = get("api/invites/$code", InvitePreview.serializer())

    suspend fun acceptInvite(code: String): Org = post("api/invites/$code/accept", body {}, Org.serializer())

    suspend fun createInvite(orgId: String, role: OrgRole, expiresInHours: Int?, maxUses: Int?): OrgInvite =
        post("api/orgs/$orgId/invites", body {
            put("role", role.id)
            if (expiresInHours != null) put("expires_in_hours", expiresInHours)
            if (maxUses != null) put("max_uses", maxUses)
        }, OrgInvite.serializer())

    suspend fun revokeInvite(orgId: String, code: String) {
        send(Request.Builder().url(hub.http("api/orgs/$orgId/invites/$code")).delete(), JsonElement.serializer())
    }

    suspend fun setRole(orgId: String, userId: String, role: OrgRole) {
        send(Request.Builder().url(hub.http("api/orgs/$orgId/members/$userId")).patch(json(body { put("role", role.id) })), JsonElement.serializer())
    }

    suspend fun removeMember(orgId: String, userId: String) {
        send(Request.Builder().url(hub.http("api/orgs/$orgId/members/$userId")).delete(), JsonElement.serializer())
    }

    suspend fun leave(orgId: String) {
        post("api/orgs/$orgId/leave", body {}, JsonElement.serializer())
    }

    // ------------------------------------------------------------ plumbing

    private fun body(build: kotlinx.serialization.json.JsonObjectBuilder.() -> Unit) = buildJsonObject(build)

    private fun json(obj: JsonObject) = obj.toString().toRequestBody(JSON)

    private suspend fun <T> get(path: String, s: KSerializer<T>): T = send(Request.Builder().url(hub.http(path)).get(), s)

    private suspend fun <T> post(path: String, obj: JsonObject, s: KSerializer<T>): T =
        send(Request.Builder().url(hub.http(path)).post(json(obj)), s)

    private suspend fun <T> send(builder: Request.Builder, s: KSerializer<T>): T = withContext(Dispatchers.IO) {
        token()?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).await().use { r ->
            val text = r.body?.string().orEmpty()
            if (r.code == 404 && isRouteMissing(text)) throw NotOnHub()
            if (!r.isSuccessful) throw HubException(r.code, detailOf(text, r.message))
            try {
                HubJson.decodeFromString(s, text.ifEmpty { "{}" })
            } catch (e: Exception) {
                throw IOException("unexpected reply from the hub", e)
            }
        }
    }

    companion object {
        private val JSON = "application/json".toMediaType()

        /** FastAPI answers an unknown route with exactly `{"detail":"Not Found"}`; a missing org or code says more. */
        internal fun isRouteMissing(text: String): Boolean = detailOf(text, "") == "Not Found"

        internal fun detailOf(text: String, fallback: String): String =
            (runCatching { HubJson.parseToJsonElement(text) as? JsonObject }.getOrNull()?.get("detail") as? JsonPrimitive)?.content
                ?: fallback.ifEmpty { "request failed" }
    }
}
