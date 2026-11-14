package com.handover.app.ui.library

import com.handover.app.core.AppViewModel
import com.handover.app.core.HubClient
import com.handover.app.core.HubException
import com.handover.app.core.HubJson
import com.handover.app.core.HubUrl
import com.handover.app.core.Lesson
import com.handover.app.core.LessonSummary
import com.handover.app.core.UploadResponse
import com.handover.app.core.UploadSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

// The hub's course library, editor, ratings and organizations API (server/routes_library.py, documented in
// server/docs/library.md). None of it is in CONTRACT.md Revision 5, so every call here is feature-detected:
// a route the hub does not have answers 404 with FastAPI's own "Not Found", and the call returns null so the
// screen hides that feature instead of failing. Legacy hubs keep working through GET /api/lessons and recut.
//
// TODO(core): these calls belong in core/HubClient once the library API is in the contract. HubClient keeps its
// OkHttpClient private, so this file makes its own (same settings) and adds the bearer token when one is set.

/** A course row from `GET /api/courses`. */
@Serializable
data class CourseSummary(
    val id: String,
    val title: String = "",
    @SerialName("cover_url") val coverUrl: String? = null,
    val steps: Int = 0,
    /** Seconds from the first step's start to the last step's end, or null when unreadable. */
    val duration: Double? = null,
    /** draft, published or unlisted. */
    val status: String = "published",
    /** only_me, shared or everyone. */
    val visibility: String = "everyone",
    val owner: CourseOwner? = null,
    val legacy: Boolean = false,
    val version: Int = 0,
    val progress: CourseProgress? = null,
)

@Serializable
data class CourseOwner(val id: String = "", val name: String = "")

/** The caller's own progress from real run events. Present only when `known` is true. */
@Serializable
data class CourseProgress(
    val known: Boolean = false,
    val runs: Int = 0,
    val completed: Int = 0,
    @SerialName("last_steps_done") val lastStepsDone: Int = 0,
    @SerialName("last_finished") val lastFinished: Boolean = false,
    val total: Int = 0,
)

@Serializable
data class CoursePermissions(
    @SerialName("can_view") val canView: Boolean = true,
    @SerialName("can_edit") val canEdit: Boolean = false,
    @SerialName("can_publish") val canPublish: Boolean = false,
    @SerialName("can_manage") val canManage: Boolean = false,
    @SerialName("can_rate") val canRate: Boolean = false,
)

@Serializable
data class HistoryCounts(val undo: Int = 0, val redo: Int = 0)

@Serializable
data class CourseInfo(
    val id: String = "",
    val title: String = "",
    val description: String? = null,
    val status: String = "published",
    val visibility: String = "everyone",
    @SerialName("cover_url") val coverUrl: String? = null,
    val steps: Int = 0,
    val duration: Double? = null,
    val version: Int = 0,
    val legacy: Boolean = false,
    /** The organization the course belongs to, when the hub has organizations. */
    val org: OrgRef? = null,
) {
    val orgId: String? get() = org?.id
}

@Serializable
data class OrgRef(val id: String = "", val name: String = "")

/** `GET /api/courses/{id}`. */
@Serializable
data class CourseDetail(
    val course: CourseInfo = CourseInfo(),
    val lesson: Lesson = Lesson(),
    val permissions: CoursePermissions = CoursePermissions(),
    val history: HistoryCounts? = null,
)

@Serializable
data class RatingSummary(val average: Double? = null, val count: Int = 0)

/** What every editor operation answers. */
@Serializable
data class EditResult(
    val lesson: Lesson = Lesson(),
    val history: HistoryCounts = HistoryCounts(),
    val recut: Boolean = false,
)

@Serializable
data class SelfTestRow(val n: Int = 0, @SerialName("self_test") val selfTest: com.handover.app.core.SelfTest? = null)

@Serializable
data class SelfTestResponse(
    val results: List<SelfTestRow> = emptyList(),
    val lesson: Lesson = Lesson(),
    val history: HistoryCounts = HistoryCounts(),
)

/** A voiceover job (`GET /api/courses/{id}/jobs/{job}`): queued, running, done or error. */
@Serializable
data class CourseJob(val job: String = "", val status: String = "queued", val message: String = "") {
    val finished: Boolean get() = status == "done" || status == "error"
}

/** An upload job as the hub reports it, with the status as free text so new stages are never lost. */
data class RawJob(val status: String, val message: String, val progress: Double? = null)

/** `GET /api/me`: who is signed in, and whether the hub has accounts at all. */
data class Me(val userId: String?, val userName: String?, val role: String?, val auth: String)

/** An organization the person belongs to. */
data class Org(val id: String, val name: String, val members: Int?, val role: String?) {
    /** Org admins and teachers may publish to the org (SCREENS.md section 15.2; roles from library.md). */
    val canPublish: Boolean get() = role?.lowercase() in setOf("org_admin", "admin", "teacher")
}

/** One caption cue relative to the clip start. */
@Serializable
data class CueEdit(val start: String, val end: String, val text: String)

/** Every call the library, teach and editor screens make. An interface so view models are tested with fakes. */
interface CourseBackend {
    /** Who is signed in, or null on a hub without accounts. */
    suspend fun me(): Me?

    /** Courses for [filter] (all, mine, shared, everyone) or [org], or null on a hub without the library API. */
    suspend fun courses(filter: String = "all", query: String = "", org: String? = null): List<CourseSummary>?

    /** The person's organizations, or null on a hub without organizations. */
    suspend fun orgs(): List<Org>?

    suspend fun lessons(): List<LessonSummary>
    suspend fun lesson(id: String): Lesson

    /** lesson.json as the hub sends it, unknown fields included, for the legacy recut save. */
    suspend fun lessonJson(id: String): JsonObject

    /** The course with its lesson and permissions, or null on a hub without the library API. */
    suspend fun course(id: String): CourseDetail?

    suspend fun ratings(id: String): RatingSummary?

    /** The text of a lesson file such as `captions/01.vtt`, or null when missing. */
    suspend fun lessonText(lessonId: String, path: String, rev: Long = 0): String?

    fun fileUrl(lessonId: String, path: String, rev: Long = 0): String
    fun absoluteUrl(path: String): String

    suspend fun upload(video: UploadSource, title: String, onProgress: (Long, Long) -> Unit): UploadResponse
    suspend fun job(job: String): RawJob

    // Editor. Each returns null when the hub does not have that route.
    suspend fun editBoundaries(id: String, edits: List<Triple<Int, String?, String?>>): EditResult?
    suspend fun editSplit(id: String, n: Int, at: String): EditResult?
    suspend fun editMerge(id: String, n: Int): EditResult?
    suspend fun editDelete(id: String, n: Int): EditResult?
    suspend fun editStep(id: String, n: Int, fields: Map<String, String>): EditResult?
    suspend fun editCaptions(id: String, n: Int, cues: List<CueEdit>): EditResult?
    suspend fun selfTest(id: String, n: Int): SelfTestResponse?
    suspend fun undo(id: String): EditResult?
    suspend fun redo(id: String): EditResult?
    suspend fun voiceover(id: String, steps: List<Int>): CourseJob?
    suspend fun courseJob(id: String, job: String): CourseJob?
    /** Publishes as published or unlisted, setting [visibility] (only_me, shared, org, everyone) and [org] when given. */
    suspend fun publish(id: String, status: String, visibility: String? = null, org: String? = null): CourseInfo?
    suspend fun unpublish(id: String): CourseInfo?
    suspend fun setVisibility(id: String, visibility: String): CourseInfo?

    /** The legacy save: the full lesson, recut on the hub (CONTRACT.md section 4). */
    suspend fun recut(id: String, lesson: JsonObject): Lesson
}

/** The HTTP implementation of [CourseBackend] for one hub. */
class CourseApi(
    val hub: HubUrl,
    private val http: OkHttpClient = sharedHttp,
    /** The signed-in session's bearer token, when the app has one. TODO(core): no token store exists yet. */
    private val token: () -> String? = { tokenProvider() },
) : CourseBackend {

    private val core = HubClient(hub, http)

    override suspend fun me(): Me? {
        val obj = getJson("api/me") as? JsonObject ?: return null
        val user = obj["user"] as? JsonObject
        return Me(
            userId = user?.str("id"),
            userName = user?.str("name"),
            role = user?.str("role"),
            auth = obj.str("auth") ?: "optional",
        )
    }

    override suspend fun courses(filter: String, query: String, org: String?): List<CourseSummary>? {
        val url = hub.http("api/courses").newBuilder().apply {
            addQueryParameter("filter", filter)
            if (query.isNotBlank()) addQueryParameter("q", query.trim().take(100))
            if (org != null) addQueryParameter("org", org)
        }.build()
        return optional { decode(send(get(url)), ListSerializer(CourseSummary.serializer())) }
    }

    override suspend fun orgs(): List<Org>? {
        val json = getJson("api/orgs") ?: return null
        val rows = (json as? JsonArray) ?: ((json as? JsonObject)?.get("orgs") as? JsonArray) ?: return emptyList()
        return rows.mapNotNull { row ->
            val o = row as? JsonObject ?: return@mapNotNull null
            val id = o.str("id") ?: return@mapNotNull null
            Org(
                id = id,
                name = o.str("name") ?: id,
                members = (o["members"] as? JsonPrimitive)?.intOrNull ?: (o["member_count"] as? JsonPrimitive)?.intOrNull,
                role = o.str("role"),
            )
        }
    }

    override suspend fun lessons(): List<LessonSummary> = core.lessons()
    override suspend fun lesson(id: String): Lesson = core.lesson(id)

    override suspend fun lessonJson(id: String): JsonObject =
        HubJson.parseToJsonElement(send(get(hub.http("api/lessons/$id")))) as? JsonObject ?: throw IOException("unexpected reply from the hub")

    override suspend fun course(id: String): CourseDetail? = optional {
        val detail = decode(send(get(hub.http("api/courses/$id"))), CourseDetail.serializer())
        detail.copy(lesson = detail.lesson.withDefaults(id))
    }

    override suspend fun ratings(id: String): RatingSummary? =
        optional { decode(send(get(hub.http("api/courses/$id/ratings"))), RatingSummary.serializer()) }

    override suspend fun lessonText(lessonId: String, path: String, rev: Long): String? = try {
        send(get(core.lessonFile(lessonId, path, rev)))
    } catch (e: HubException) {
        if (e.status == 404) null else throw e
    }

    override fun fileUrl(lessonId: String, path: String, rev: Long): String = core.lessonFile(lessonId, path, rev).toString()

    override fun absoluteUrl(path: String): String = hub.http(path.trimStart('/')).toString()

    override suspend fun upload(video: UploadSource, title: String, onProgress: (Long, Long) -> Unit): UploadResponse =
        core.upload(video, title, onProgress = onProgress)

    override suspend fun job(job: String): RawJob {
        val obj = HubJson.parseToJsonElement(send(get(hub.http("api/jobs/$job")))) as? JsonObject
            ?: throw IOException("unexpected reply from the hub")
        return RawJob(
            status = obj.str("status") ?: "queued",
            message = obj.str("message").orEmpty(),
            progress = (obj["progress"] as? JsonPrimitive)?.contentOrNull?.toDoubleOrNull(),
        )
    }

    override suspend fun editBoundaries(id: String, edits: List<Triple<Int, String?, String?>>): EditResult? = edit(id, "boundaries",
        buildJsonObject {
            put("steps", buildJsonArray {
                edits.forEach { (n, start, end) ->
                    add(buildJsonObject {
                        put("n", n)
                        start?.let { put("start", it) }
                        end?.let { put("end", it) }
                    })
                }
            })
        })

    override suspend fun editSplit(id: String, n: Int, at: String) = edit(id, "split", buildJsonObject { put("n", n); put("at", at) })
    override suspend fun editMerge(id: String, n: Int) = edit(id, "merge", buildJsonObject { put("n", n) })
    override suspend fun editDelete(id: String, n: Int) = edit(id, "delete", buildJsonObject { put("n", n) })

    override suspend fun editStep(id: String, n: Int, fields: Map<String, String>) = edit(id, "step",
        buildJsonObject { put("n", n); fields.forEach { (k, v) -> put(k, v) } })

    override suspend fun editCaptions(id: String, n: Int, cues: List<CueEdit>) = edit(id, "captions", buildJsonObject {
        put("n", n)
        put("cues", HubJson.encodeToJsonElement(ListSerializer(CueEdit.serializer()), cues))
    })

    override suspend fun selfTest(id: String, n: Int): SelfTestResponse? =
        optional { decode(send(post("api/courses/$id/edit/selftest", buildJsonObject { put("n", n) })), SelfTestResponse.serializer()) }

    override suspend fun undo(id: String) = edit(id, "undo", null)
    override suspend fun redo(id: String) = edit(id, "redo", null)

    override suspend fun voiceover(id: String, steps: List<Int>): CourseJob? = optional {
        val body = buildJsonObject { put("steps", buildJsonArray { steps.forEach { add(JsonPrimitive(it)) } }) }
        decode(send(post("api/courses/$id/edit/voiceover", body)), CourseJob.serializer())
    }

    override suspend fun courseJob(id: String, job: String): CourseJob? =
        optional { decode(send(get(hub.http("api/courses/$id/jobs/$job"))), CourseJob.serializer()) }

    override suspend fun publish(id: String, status: String, visibility: String?, org: String?): CourseInfo? = optional {
        val body = buildJsonObject {
            put("status", status)
            visibility?.let { put("visibility", it) }
            org?.let { put("org_id", it) }
        }
        decode(send(post("api/courses/$id/publish", body)), CourseInfo.serializer())
    }

    override suspend fun unpublish(id: String): CourseInfo? =
        optional { decode(send(post("api/courses/$id/unpublish", null)), CourseInfo.serializer()) }

    override suspend fun setVisibility(id: String, visibility: String): CourseInfo? = optional {
        val request = authed(Request.Builder().url(hub.http("api/courses/$id")))
            .patch(buildJsonObject { put("visibility", visibility) }.toString().toRequestBody(JSON)).build()
        decode(send(request), CourseInfo.serializer())
    }

    override suspend fun recut(id: String, lesson: JsonObject): Lesson {
        val request = authed(Request.Builder().url(hub.http("api/lessons/$id/recut")))
            .post(lesson.toString().toRequestBody(JSON)).build()
        return decode(send(request), Lesson.serializer()).withDefaults(id)
    }

    // ------------------------------------------------------------ plumbing

    private suspend fun edit(id: String, op: String, body: JsonObject?): EditResult? = optional {
        val result = decode(send(post("api/courses/$id/edit/$op", body)), EditResult.serializer())
        result.copy(lesson = result.lesson.withDefaults(id))
    }

    private suspend fun getJson(path: String): JsonElement? = optional { HubJson.parseToJsonElement(send(get(hub.http(path)))) }

    private fun authed(builder: Request.Builder): Request.Builder = builder.apply {
        token()?.takeIf { it.isNotBlank() }?.let { header("Authorization", "Bearer $it") }
    }

    private fun get(url: HttpUrl): Request = authed(Request.Builder().url(url)).get().build()

    private fun post(path: String, body: JsonObject?): Request =
        authed(Request.Builder().url(hub.http(path))).post((body?.toString() ?: "").toRequestBody(if (body != null) JSON else null)).build()

    private suspend fun send(request: Request): String = withContext(Dispatchers.IO) {
        http.newCall(request).await().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) throw HubException(response.code, detailOf(text, response.message))
            text
        }
    }

    private fun <T> decode(text: String, serializer: KSerializer<T>): T = try {
        HubJson.decodeFromString(serializer, text)
    } catch (e: IllegalArgumentException) {
        throw IOException("unexpected reply from the hub: ${e.message}", e)
    }

    companion object {
        private val JSON = "application/json".toMediaType()

        /** One client for every hub call these screens make; the same settings as the app's own. */
        val sharedHttp: OkHttpClient by lazy { AppViewModel.defaultHttpClient() }

        /** Where the signed-in token comes from. Set by whoever owns sign in; null means anonymous. */
        @Volatile var tokenProvider: () -> String? = { null }

        private val cache = mutableMapOf<HubUrl, CourseApi>()

        /** The API for [hub], made once per hub. */
        fun forHub(hub: HubUrl): CourseApi = synchronized(cache) { cache.getOrPut(hub) { CourseApi(hub) } }

        /** FastAPI's `{"detail": "..."}`, or [fallback]. */
        internal fun detailOf(text: String, fallback: String): String {
            val obj = runCatching { HubJson.parseToJsonElement(text) as? JsonObject }.getOrNull()
            val detail = obj?.get("detail") ?: return fallback.ifEmpty { "request failed" }
            (detail as? JsonPrimitive)?.let { return it.content }
            val first = (detail as? JsonArray)?.firstOrNull() as? JsonObject
            return first?.str("msg") ?: detail.toString()
        }
    }
}

/**
 * Runs [block] and returns null when the hub has no such route: FastAPI answers an unknown path (and a method
 * the path does not take) with 404 "Not Found" or 405. A 404 with any other detail ("lesson not found") is a
 * real answer and is thrown.
 */
suspend fun <T> optional(block: suspend () -> T): T? = try {
    block()
} catch (e: HubException) {
    if (isMissingRoute(e)) null else throw e
}

fun isMissingRoute(e: HubException): Boolean = (e.status == 404 && e.detail == "Not Found") || e.status == 405

/** A hub failure in plain words for the screen: the hub's own text when it sent one. */
fun Throwable.plainWords(): String = when (this) {
    is HubException -> when (status) {
        413 -> "This video is over 2 GB. Trim it or record a shorter take."
        429 -> if (detail == "too many jobs") "The hub is busy with other lessons. Try again when one finishes." else detail
        401 -> "Sign in to the hub to do this."
        403 -> "Your account cannot do this on this hub."
        409 -> if (detail == "recut already running") "The hub is still updating clips. Try again when it finishes." else detail
        else -> detail
    }
    is IOException -> "Could not reach the hub. Check that it is running and on the same Wi-Fi."
    else -> message ?: "Something went wrong."
}

private fun JsonObject.str(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content

private suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    cont.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) = cont.resume(response)
        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) cont.resumeWithException(e)
        }
    })
}
