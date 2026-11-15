package com.handover.app.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonObjectBuilder
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

// Accounts and organizations, field for field from server/docs/library.md (server/routes_library.py).
// None of it is in CONTRACT.md, so it is feature-detected: a hub without a route answers FastAPI's own
// 404 "Not Found", which becomes NotOnHub (or null) and the app hides that feature.

@Serializable
data class HubUser(
    val id: String = "",
    val name: String = "",
    /** owner, teacher or learner. */
    val role: String = "learner",
    val created: String? = null,
) {
    val roleTitle: String get() = when (role) { "owner" -> "Owner"; "teacher" -> "Teacher"; else -> "Learner" }
}

/**
 * What the session may do (SCREENS.md 24). The hub does not send these today, so they come from the
 * library.md permission tables: every signed-in person may create an organization, and the hub owner
 * is the user with role owner. A hub that adds `capabilities` to /api/me overrides this.
 */
@Serializable
data class Capabilities(
    @SerialName("can_create_org") val canCreateOrg: Boolean = false,
    @SerialName("is_hub_owner") val isHubOwner: Boolean = false,
    @SerialName("can_teach_in") val canTeachIn: List<String> = emptyList(),
) {
    companion object {
        fun derive(user: HubUser?): Capabilities = Capabilities(canCreateOrg = user != null, isHubOwner = user?.role == "owner")
    }
}

/** `GET /api/me`. */
@Serializable
data class MeReply(
    val user: HubUser? = null,
    /** "optional" (anonymous callers allowed) or "required". */
    val auth: String = "optional",
    @SerialName("setup_needed") val setupNeeded: Boolean = false,
    val capabilities: Capabilities? = null,
)

/** `POST /api/auth/setup` and `/api/auth/login`. */
@Serializable
data class AuthReply(val user: HubUser, val token: String, val expires: String? = null)

/** The caller's own progress on one course, from real runs only (`progress` in a course summary). */
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

/** One row of `GET /api/courses` as the profile uses it. */
@Serializable
data class CourseItem(
    val id: String,
    val title: String = "",
    val steps: Int = 0,
    val progress: CourseProgress? = null,
)

/** Org roles. People see Admin, Teacher, Member (SCREENS.md 22); the hub says org_admin, teacher, learner. */
enum class OrgRole(val id: String, val title: String) {
    Admin("org_admin", "Admin"), Teacher("teacher", "Teacher"), Member("learner", "Member");

    companion object {
        fun from(id: String?): OrgRole = when (id?.lowercase()) {
            "org_admin", "admin" -> Admin
            "teacher" -> Teacher
            else -> Member
        }
    }
}

/**
 * An organization. `GET /api/orgs` sends `members` as a count; `GET /api/orgs/{id}` sends the list, so
 * [members] is the count either way. [lessons] is the number of courses the caller may see, from the
 * detail only.
 */
data class Org(
    val id: String = "",
    val name: String = "",
    val slug: String? = null,
    val created: String? = null,
    /** The caller's role in this org (org_admin, teacher, learner), or null when not a member (a hub owner looking in). */
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
    val role: String = "learner",
    val joined: String? = null,
) {
    val orgRole: OrgRole get() = OrgRole.from(role)
}

/** A course in an org, from the org's `courses` (course summaries). */
@Serializable
data class OrgLesson(val id: String = "", val title: String = "", val steps: Int = 0)

@Serializable
data class OrgRef(val id: String = "", val name: String = "", val slug: String? = null)

@Serializable
data class InviteUser(val id: String? = null, val name: String = "")

/**
 * An invite. `kind` is code or user. [code] is in the create reply only: the hub keeps just its hash,
 * so a listed code invite has no code. User invites carry [user] instead of the use counts.
 */
@Serializable
data class OrgInvite(
    val id: String = "",
    val kind: String = "code",
    val role: String = "learner",
    val created: String? = null,
    /** The name of the person who made it. */
    @SerialName("created_by") val createdBy: String? = null,
    /** ISO time. */
    val expires: String? = null,
    /** Null means no limit. */
    @SerialName("max_uses") val maxUses: Int? = null,
    val uses: Int = 0,
    val code: String? = null,
    val user: InviteUser? = null,
    /** On invites sent to me (`GET /api/orgs`), the org they are for. */
    val org: OrgRef? = null,
)

/** `GET /api/orgs`: my orgs, and invites addressed to me by name. */
data class MyOrgs(val orgs: List<Org>, val invites: List<OrgInvite>)

/**
 * The org page. [invites] is the live invite list, sent only to people who may manage the org (its
 * admins and the hub owner), so it doubles as the "can manage" signal.
 */
data class OrgPage(
    val org: Org,
    val members: List<OrgMember>,
    val lessons: List<OrgLesson>,
    val invites: List<OrgInvite>?,
    val owner: InviteUser? = null,
) {
    val canManage: Boolean get() = invites != null || org.isAdmin
}

/** A feature the hub does not have (404 "Not Found" on its route). */
class NotOnHub : IOException("not on this hub")

/** The hub's accounts and organizations routes. The bearer token comes from [token] on every call. */
class AccountApi(
    private val hub: HubUrl,
    private val http: OkHttpClient = HubClient.sharedHttp,
    private val token: () -> String? = { AccountSession.token(hub) },
) {

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
        post("api/auth/logout", null, JsonElement.serializer())
    }

    /** Courses the caller can see, each with their own progress when known. */
    suspend fun courses(): List<CourseItem> = get("api/courses", ListSerializer(CourseItem.serializer()))

    // ------------------------------------------------------------ organizations

    /** My orgs and invites sent to me, or null when the hub has no organizations. */
    suspend fun orgs(): MyOrgs? {
        val obj = try {
            get("api/orgs", JsonElement.serializer())
        } catch (e: NotOnHub) {
            return null
        }
        val rows = (obj as? JsonObject)?.get("orgs") as? JsonArray ?: obj as? JsonArray ?: JsonArray(emptyList())
        val invites = ((obj as? JsonObject)?.get("invites"))?.let { decodeList(it, OrgInvite.serializer()) }.orEmpty()
        return MyOrgs(rows.mapNotNull { (it as? JsonObject)?.let(::orgOf) }, invites)
    }

    /** `POST /api/orgs`. The caller becomes its admin. The hub makes the slug from the name. */
    suspend fun createOrg(name: String, slug: String? = null): Org =
        orgOf(post("api/orgs", body { put("name", name); if (!slug.isNullOrBlank()) put("slug", slug) }, JsonObject.serializer()))

    suspend fun org(id: String): OrgPage {
        val obj = get("api/orgs/$id", JsonObject.serializer())
        val invites = obj["invites"]?.takeIf { it !is JsonNull }?.let { decodeList(it, OrgInvite.serializer()) }
        return OrgPage(
            org = orgOf(obj),
            members = obj["members"]?.let { decodeList(it, OrgMember.serializer()) }.orEmpty(),
            lessons = obj["courses"]?.let { decodeList(it, OrgLesson.serializer()) }.orEmpty(),
            invites = invites,
            owner = (obj["owner"] as? JsonObject)?.let { runCatching { HubJson.decodeFromJsonElement(InviteUser.serializer(), it) }.getOrNull() },
        )
    }

    /** `PATCH /api/orgs/{id}`: rename. Admins only. */
    suspend fun renameOrg(id: String, name: String): Org =
        orgOf(send(Request.Builder().url(hub.http("api/orgs/$id")).patch(json(body { put("name", name) })), JsonObject.serializer()))

    /** `DELETE /api/orgs/{id}`: the creator or the hub owner. */
    suspend fun deleteOrg(id: String) {
        send(Request.Builder().url(hub.http("api/orgs/$id")).delete(), JsonElement.serializer())
    }

    /**
     * A code invite. [expiresDays] from 0.01 to 90 (the hub's default is 7); [maxUses] null means no
     * limit, and is sent as an explicit null because leaving it out means one use.
     */
    suspend fun createInvite(orgId: String, role: OrgRole, expiresDays: Double?, maxUses: Int?): OrgInvite =
        post("api/orgs/$orgId/invites", body {
            put("role", role.id)
            if (expiresDays != null) put("expires_days", expiresDays)
            put("max_uses", maxUses?.let(::JsonPrimitive) ?: JsonNull)
        }, OrgInvite.serializer())

    /** An invite to one person by name; they see it under their invites. */
    suspend fun inviteByName(orgId: String, username: String, role: OrgRole): OrgInvite =
        post("api/orgs/$orgId/invites", body { put("username", username); put("role", role.id) }, OrgInvite.serializer())

    /** `DELETE /api/orgs/{id}/invites/{invite}`: an admin revokes, or the invitee declines their own. */
    suspend fun revokeInvite(orgId: String, inviteId: String) {
        send(Request.Builder().url(hub.http("api/orgs/$orgId/invites/$inviteId")).delete(), JsonElement.serializer())
    }

    /** `POST /api/orgs/join {"code"}`. Codes are case sensitive; only surrounding space is dropped. */
    suspend fun join(code: String): Org = orgOf(post("api/orgs/join", body { put("code", code.trim()) }, JsonObject.serializer()))

    /** `POST /api/orgs/join {"invite_id"}`: accept an invite sent to me by name. */
    suspend fun acceptInvite(inviteId: String): Org =
        orgOf(post("api/orgs/join", body { put("invite_id", inviteId) }, JsonObject.serializer()))

    suspend fun leave(orgId: String) {
        post("api/orgs/$orgId/leave", null, JsonElement.serializer())
    }

    suspend fun setRole(orgId: String, userId: String, role: OrgRole) {
        send(Request.Builder().url(hub.http("api/orgs/$orgId/members/$userId")).patch(json(body { put("role", role.id) })), JsonElement.serializer())
    }

    suspend fun removeMember(orgId: String, userId: String) {
        send(Request.Builder().url(hub.http("api/orgs/$orgId/members/$userId")).delete(), JsonElement.serializer())
    }

    // ------------------------------------------------------------ plumbing

    private fun body(build: JsonObjectBuilder.() -> Unit) = buildJsonObject(build)

    private fun json(obj: JsonObject) = obj.toString().toRequestBody(JSON)

    private suspend fun <T> get(path: String, s: KSerializer<T>): T = send(Request.Builder().url(hub.http(path)).get(), s)

    private suspend fun <T> post(path: String, obj: JsonObject?, s: KSerializer<T>): T =
        send(Request.Builder().url(hub.http(path)).post(obj?.let(::json) ?: ByteArray(0).toRequestBody(null)), s)

    private suspend fun <T> send(builder: Request.Builder, s: KSerializer<T>): T = withContext(Dispatchers.IO) {
        token()?.takeIf { it.isNotBlank() }?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).await().use { r ->
            val text = r.body?.string().orEmpty()
            if (r.code == 404 && isRouteMissing(text)) throw NotOnHub()
            if (!r.isSuccessful) throw HubException(r.code, HubClient.detailOf(text, r.message))
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
        internal fun isRouteMissing(text: String): Boolean = HubClient.detailOf(text, "") == "Not Found"

        /** An org from either shape: the summary (`members` is a count) or the detail (`members` is a list). */
        fun orgOf(o: JsonObject): Org {
            fun str(key: String) = (o[key] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
            val id = str("id").orEmpty()
            return Org(
                id = id,
                name = str("name") ?: id,
                slug = str("slug"),
                created = str("created"),
                role = str("role"),
                members = (o["members"] as? JsonPrimitive)?.intOrNull ?: (o["members"] as? JsonArray)?.size,
                lessons = (o["courses"] as? JsonArray)?.size,
            )
        }

        /** A list where a bad row is skipped instead of failing the whole page. */
        private fun <T> decodeList(element: JsonElement, s: KSerializer<T>): List<T> =
            (element as? JsonArray)?.mapNotNull { runCatching { HubJson.decodeFromJsonElement(s, it) }.getOrNull() }.orEmpty()
    }
}
