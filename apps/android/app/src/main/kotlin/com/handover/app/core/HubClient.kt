package com.handover.app.core

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okio.Buffer
import okio.BufferedSink
import okio.ForwardingSink
import okio.buffer
import okio.source
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** A REST call the hub answered with an error status. [detail] is the hub's message, exact per the contract. */
class HubException(val status: Int, val detail: String) : IOException("$status $detail")

/** A video to upload. [length] must be known: the hub answers 411 without a Content-Length. */
class UploadSource(
    val fileName: String,
    val mimeType: String,
    val length: Long,
    val open: () -> InputStream,
) {
    companion object {
        fun of(file: File, mimeType: String = "video/mp4") = UploadSource(file.name, mimeType, file.length()) { file.inputStream() }
    }
}

/**
 * The hub's REST API (CONTRACT.md section 4) over OkHttp. Every call is main-safe: it runs on
 * Dispatchers.IO and cancels its HTTP call when the coroutine is cancelled. Every request carries the
 * signed-in session's bearer token when there is one ([AccountSession]).
 */
class HubClient(
    val hub: HubUrl,
    private val http: OkHttpClient = sharedHttp,
    private val token: () -> String? = { AccountSession.token(hub) },
) {
    suspend fun lessons(): List<LessonSummary> = get("api/lessons", ListSerializer(LessonSummary.serializer()))

    /** The lesson with the contract's defaults filled in. */
    suspend fun lesson(id: String): Lesson = get("api/lessons/$id", Lesson.serializer()).withDefaults(id)

    suspend fun job(job: String): JobStatus = get("api/jobs/$job", JobStatus.serializer())

    /**
     * Polls [job] every [intervalMs] and emits each status that differs from the last one, ending
     * after `done` or `error`. A 404 (the hub restarted and forgot the job) is thrown as [HubException].
     */
    fun pollJob(job: String, intervalMs: Long = 1_000): Flow<JobStatus> = flow {
        var last: JobStatus? = null
        while (true) {
            val now = job(job)
            if (now != last) emit(now)
            last = now
            if (now.finished) return@flow
            delay(intervalMs)
        }
    }

    /**
     * Uploads a video as a new lesson. Signed in, it goes to `POST /api/courses` (library.md), so the
     * course is owned by this person, optionally inside [orgId]; signed out, to `POST /api/lesson`
     * (CONTRACT.md section 4). A hub without the library falls back to `/api/lesson` too. [onProgress]
     * gets (bytes sent, bytes total) on OkHttp's thread as the body is written. Returns the job to poll
     * and the lesson id the hub chose.
     */
    suspend fun upload(
        video: UploadSource,
        title: String,
        id: String? = null,
        orgId: String? = null,
        onProgress: (sent: Long, total: Long) -> Unit = { _, _ -> },
    ): UploadResponse {
        fun form(course: Boolean) = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("title", title)
            .apply { if (!id.isNullOrBlank()) addFormDataPart("id", id) }
            .apply { if (course && !orgId.isNullOrBlank()) addFormDataPart("org_id", orgId) }
            .addFormDataPart("file", video.fileName, StreamBody(video))
            .build()
        fun request(path: String, course: Boolean) = Request.Builder().url(hub.http(path)).post(ProgressBody(form(course), onProgress)).build()
        if (token() != null) {
            try {
                return call(request("api/courses", course = true), UploadResponse.serializer())
            } catch (e: HubException) {
                // FastAPI's own 404 or 405: this hub has no library, so the lesson goes in the classic way.
                if (!((e.status == 404 && e.detail == "Not Found") || e.status == 405)) throw e
            }
        }
        return call(request("api/lesson", course = false), UploadResponse.serializer())
    }

    /** Recuts a lesson. With [lesson] null the hub recuts from its stored lesson.json. */
    suspend fun recut(id: String, lesson: Lesson? = null): Lesson {
        val body = lesson?.let { HubJson.encodeToString(Lesson.serializer(), it) }.orEmpty()
        val request = Request.Builder().url(hub.http("api/lessons/$id/recut"))
            .post(body.toRequestBody(if (lesson != null) JSON else null))
            .build()
        return call(request, Lesson.serializer()).withDefaults(id)
    }

    suspend fun delete(id: String): DeleteResponse =
        call(Request.Builder().url(hub.http("api/lessons/$id")).delete().build(), DeleteResponse.serializer())

    /**
     * A lesson file (clip, captions, reference frame), with `?v=<rev>` so a recut lesson never plays
     * a cached old file (CONTRACT.md section 5).
     */
    fun lessonFile(lessonId: String, path: String, rev: Long): HttpUrl =
        hub.http("lessons/$lessonId/$path").newBuilder().addQueryParameter("v", rev.toString()).build()

    // ------------------------------------------------------------ plumbing

    private suspend fun <T> get(path: String, serializer: KSerializer<T>): T =
        call(Request.Builder().url(hub.http(path)).get().build(), serializer)

    private suspend fun <T> call(request: Request, serializer: KSerializer<T>): T = withContext(Dispatchers.IO) {
        val signed = token()?.takeIf { it.isNotBlank() }?.let { request.newBuilder().header("Authorization", "Bearer $it").build() } ?: request
        http.newCall(signed).await().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) throw HubException(response.code, detailOf(text, response.message))
            try {
                HubJson.decodeFromString(serializer, text)
            } catch (e: SerializationException) {
                throw IOException("unexpected reply from the hub: ${e.message}", e)
            } catch (e: IllegalArgumentException) {
                throw IOException("unexpected reply from the hub: ${e.message}", e)
            }
        }
    }

    companion object {
        private val JSON: MediaType = "application/json".toMediaType()

        /** The app's one OkHttp client for every hub call and socket, so connections and threads are shared. */
        val sharedHttp: OkHttpClient by lazy {
            OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .writeTimeout(30, TimeUnit.SECONDS)
                // The hub pings every 10 s; this side pings too, so a hub that vanished is noticed.
                .pingInterval(15, TimeUnit.SECONDS)
                .build()
        }

        /** FastAPI's `{"detail": "..."}`. A 422 carries a list there; its first `msg` is used. */
        internal fun detailOf(text: String, fallback: String): String {
            val obj = runCatching { HubJson.parseToJsonElement(text) as? JsonObject }.getOrNull()
            val detail = obj?.get("detail") ?: return fallback.ifEmpty { "request failed" }
            (detail as? JsonPrimitive)?.let { return it.content }
            val first = runCatching { (detail as kotlinx.serialization.json.JsonArray).first() as JsonObject }.getOrNull()
            return (first?.get("msg") as? JsonPrimitive)?.content ?: detail.toString()
        }
    }
}

/** Runs an OkHttp call as a suspend function; cancelling the coroutine cancels the call. */
internal suspend fun Call.await(): Response = suspendCancellableCoroutine { cont ->
    cont.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) = cont.resume(response)
        override fun onFailure(call: Call, e: IOException) {
            if (!cont.isCancelled) cont.resumeWithException(e)
        }
    })
}

/** A body read from a stream of known length, so the multipart body has a Content-Length. */
private class StreamBody(private val source: UploadSource) : RequestBody() {
    override fun contentType(): MediaType? = source.mimeType.toMediaTypeOrNull()
    override fun contentLength(): Long = source.length
    override fun writeTo(sink: BufferedSink) {
        source.open().source().use { sink.writeAll(it) }
    }
}

/** Wraps a body and reports bytes written. OkHttp may write a body twice (a retry); progress restarts then. */
private class ProgressBody(
    private val inner: RequestBody,
    private val onProgress: (Long, Long) -> Unit,
) : RequestBody() {
    override fun contentType(): MediaType? = inner.contentType()
    override fun contentLength(): Long = inner.contentLength()
    override fun writeTo(sink: BufferedSink) {
        val total = contentLength()
        var sent = 0L
        var lastReported = -1L
        val counting = object : ForwardingSink(sink) {
            override fun write(source: Buffer, byteCount: Long) {
                super.write(source, byteCount)
                sent += byteCount
                // At most about 200 callbacks per upload, plus the final one.
                if (sent == total || sent - lastReported >= maxOf(total / 200, 64 * 1024)) {
                    lastReported = sent
                    onProgress(sent, total)
                }
            }
        }.buffer()
        inner.writeTo(counting)
        counting.flush()
    }
}
