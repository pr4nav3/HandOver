package com.handover.app.ui.done

import com.handover.app.core.AccountSession
import com.handover.app.core.HubClient
import com.handover.app.core.HubJson
import com.handover.app.core.HubUrl
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
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

/** `GET /api/runs/{run_id}/score` (library.md, server/scoring.py). Every field optional. */
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
 * The two Done calls: the run score and the rating. They use core's shared client and send the
 * account session's bearer token, which the hub needs to show a learner their own run and to take
 * a rating.
 */
object DoneApi {
    /**
     * `GET /api/runs/{run_id}/score` for [runId] from `state.run_id`. A hub without the route, or one
     * that has not seen the run's events yet, is [ScoreFetch.NotOnHub] and the Done screen keeps its local
     * numbers. [retries] covers the short gap before the hub's event file has the run's last events.
     */
    suspend fun runScore(
        hub: HubUrl,
        runId: String,
        client: OkHttpClient = HubClient.sharedHttp,
        token: String? = AccountSession.token(hub),
        retries: Int = 2,
        retryDelayMs: Long = 1_500,
    ): ScoreFetch {
        var attempt = 0
        while (true) {
            val (result, runMissing) = fetchScore(hub, runId, client, token)
            if (!runMissing || attempt >= retries) return result
            attempt++
            delay(retryDelayMs)
        }
    }

    private suspend fun fetchScore(hub: HubUrl, runId: String, client: OkHttpClient, token: String?): Pair<ScoreFetch, Boolean> = withContext(Dispatchers.IO) {
        try {
            client.newCall(signed(Request.Builder().url(hub.http("api/runs/$runId/score")), token).get().build()).execute().use { r ->
                val text = r.body?.string().orEmpty()
                when {
                    r.code == 404 -> ScoreFetch.NotOnHub to (detail(text) == "run not found")
                    r.code == 405 || r.code == 401 || r.code == 403 -> ScoreFetch.NotOnHub to false
                    !r.isSuccessful -> ScoreFetch.Failed(detail(text) ?: "The hub answered ${r.code}.") to false
                    else -> runCatching { ScoreFetch.Found(HubJson.decodeFromString(HubRunScore.serializer(), text)) }
                        .getOrElse { ScoreFetch.Failed("The hub sent a score this app cannot read.") } to false
                }
            }
        } catch (e: IOException) {
            ScoreFetch.Failed("Could not reach the hub.") to false
        }
    }

    /** `POST /api/courses/{id}/rating`. Null on success, else the hub's message. */
    suspend fun rate(
        hub: HubUrl,
        lessonId: String,
        stars: Int,
        comment: String?,
        client: OkHttpClient = HubClient.sharedHttp,
        token: String? = AccountSession.token(hub),
    ): String? = withContext(Dispatchers.IO) {
        val body = buildJsonObject {
            put("stars", stars)
            if (!comment.isNullOrBlank()) put("comment", comment.trim())
        }.toString().toRequestBody("application/json".toMediaType())
        try {
            client.newCall(signed(Request.Builder().url(hub.http("api/courses/$lessonId/rating")), token).post(body).build()).execute().use { r ->
                val text = r.body?.string().orEmpty()
                if (r.isSuccessful) null
                else if (r.code == 405 || (r.code == 404 && detail(text) == "Not Found")) "This hub does not take ratings yet."
                else if (r.code == 401) "Sign in on the hub to send a rating."
                else detail(text)?.replaceFirstChar(Char::uppercase) ?: "The hub answered ${r.code}."
            }
        } catch (e: IOException) {
            "Could not reach the hub."
        }
    }

    private fun signed(builder: Request.Builder, token: String?): Request.Builder =
        builder.apply { token?.takeIf { it.isNotBlank() }?.let { header("Authorization", "Bearer $it") } }

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
