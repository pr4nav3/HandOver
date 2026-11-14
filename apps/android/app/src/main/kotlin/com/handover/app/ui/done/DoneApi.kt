package com.handover.app.ui.done

import com.handover.app.core.HubJson
import com.handover.app.core.HubUrl
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** `GET /api/runs/{run_id}/score` on the hub branch (server/scoring.py). Every field optional. */
@Serializable
data class HubRunScore(
    val score: Int? = null,
    val label: String? = null,
    val reason: String? = null,
    @SerialName("best_step") val bestStep: HubStepRef? = null,
    @SerialName("weakest_step") val weakestStep: HubStepRef? = null,
    val tip: String? = null,
    val finished: Boolean = false,
)

@Serializable
data class HubStepRef(val n: Int, val score: Int? = null)

sealed interface ScoreFetch {
    data class Found(val score: HubRunScore) : ScoreFetch

    /** The hub has no score route, or no such run (404 or 405): compute what we can locally. */
    data object NotOnHub : ScoreFetch
    data class Failed(val message: String) : ScoreFetch
}

/**
 * The two Done calls core's HubClient does not have yet: the run score and the rating. Kept here
 * until core adds them (see the report). Its own small OkHttp client.
 */
object DoneApi {
    private val http by lazy {
        OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(10, TimeUnit.SECONDS).build()
    }

    suspend fun runScore(hub: HubUrl, runId: String, client: OkHttpClient = http): ScoreFetch = withContext(Dispatchers.IO) {
        try {
            client.newCall(Request.Builder().url(hub.http("api/runs/$runId/score")).get().build()).execute().use { r ->
                val text = r.body?.string().orEmpty()
                when {
                    r.code == 404 || r.code == 405 -> ScoreFetch.NotOnHub
                    !r.isSuccessful -> ScoreFetch.Failed(detail(text) ?: "The hub answered ${r.code}.")
                    else -> runCatching { ScoreFetch.Found(HubJson.decodeFromString(HubRunScore.serializer(), text)) }
                        .getOrElse { ScoreFetch.Failed("The hub sent a score this app cannot read.") }
                }
            }
        } catch (e: IOException) {
            ScoreFetch.Failed("Could not reach the hub.")
        }
    }

    /** `POST /api/courses/{id}/rating`. Null on success, else the hub's message. */
    suspend fun rate(hub: HubUrl, lessonId: String, stars: Int, comment: String?, client: OkHttpClient = http): String? = withContext(Dispatchers.IO) {
        val body = buildJsonObject {
            put("stars", stars)
            if (!comment.isNullOrBlank()) put("comment", comment.trim())
        }.toString().toRequestBody("application/json".toMediaType())
        try {
            client.newCall(Request.Builder().url(hub.http("api/courses/$lessonId/rating")).post(body).build()).execute().use { r ->
                if (r.isSuccessful) null
                else if (r.code == 404 || r.code == 405) "This hub does not take ratings yet."
                else if (r.code == 401) "Sign in on the hub to send a rating."
                else detail(r.body?.string().orEmpty()) ?: "The hub answered ${r.code}."
            }
        } catch (e: IOException) {
            "Could not reach the hub."
        }
    }

    private fun detail(text: String): String? = runCatching {
        ((HubJson.parseToJsonElement(text) as? JsonObject)?.get("detail") as? JsonPrimitive)?.content
    }.getOrNull()
}

/** The hub's score laid over the local model: score, label and tip from the hub; stats stay local. */
fun DoneModel.withHub(hub: HubRunScore): DoneModel {
    val s = hub.score ?: return this
    fun pick(ref: HubStepRef?, fallback: Pick?): Pick? {
        val step = ref?.let { r -> steps.firstOrNull { it.n == r.n } } ?: return fallback
        return if (fallback?.index == step.index) fallback else Pick(step.index, step.n, step.title, fallback?.takeIf { it.index == step.index }?.reason ?: "Step score ${ref.score ?: s}.")
    }
    return copy(
        score = s,
        label = com.handover.app.ui.components.ScoreLabel.of(hub.label, s),
        tip = hub.tip?.takeIf { it.isNotBlank() } ?: tip,
        best = pick(hub.bestStep, best),
        weakest = pick(hub.weakestStep, weakest),
        source = ScoreSource.Hub,
    )
}
