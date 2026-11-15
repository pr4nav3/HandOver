package com.handover.app.core

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive

// The wire models, field for field from CONTRACT.md (sections 3, 4, 6 and 7) plus the fields the hub
// sends today on branch soham/server (check_mode, next_clip). Every field the contract marks NEW, or
// that only exists on the hub branch, is optional here: readers ignore unknown keys and tolerate
// missing ones. Enum values the app does not know fall back to the field's default instead of failing.

/** The one Json the app uses for the hub. Unknown keys and unknown enum values never fail a decode. */
val HubJson: Json = Json {
    ignoreUnknownKeys = true
    coerceInputValues = true
    explicitNulls = false
    encodeDefaults = true
    isLenient = true
}

// ---------------------------------------------------------------- lesson.json (section 3)

@Serializable
data class Lesson(
    val id: String = "",
    val title: String = "",
    val video: String = "norm.mp4",
    val steps: List<Step> = emptyList(),
    val safety: List<String> = emptyList(),
    val tools: List<String> = emptyList(),
) {
    /**
     * The lesson with the contract's per-step defaults filled in: `n` = index + 1, and `clip`,
     * `captions`, `ref_frame` as `clips/NN.mp4`, `captions/NN.vtt`, `frames/NN.jpg`. [folderId] stands
     * in for a missing `id` and `title` (the contract's default is the folder name).
     */
    fun withDefaults(folderId: String = id): Lesson {
        val lessonId = id.ifEmpty { folderId }
        return copy(
            id = lessonId,
            title = title.ifEmpty { lessonId },
            steps = steps.mapIndexed { i, s ->
                val nn = (i + 1).toString().padStart(2, '0')
                s.copy(
                    n = if (s.n > 0) s.n else i + 1,
                    clip = s.clip ?: "clips/$nn.mp4",
                    captions = s.captions ?: "captions/$nn.vtt",
                    refFrame = s.refFrame ?: "frames/$nn.jpg",
                )
            },
        )
    }
}

@Serializable
data class Step(
    /** 1-based. 0 means absent; [Lesson.withDefaults] fills it in. */
    val n: Int = 0,
    val title: String = "",
    @Serializable(with = TimeStringSerializer::class) val start: String = "",
    @Serializable(with = TimeStringSerializer::class) val end: String = "",
    val clip: String? = null,
    val captions: String? = null,
    @SerialName("ref_frame") val refFrame: String? = null,
    @SerialName("check_type") val checkType: CheckType = CheckType.Camera,
    @SerialName("check_question") val checkQuestion: String = "Is this step finished?",
    val prerequisites: List<Int> = emptyList(),
    /** Absolute time in norm.mp4 for the reference frame; null = last frame of the clip. */
    @SerialName("ref_time") @Serializable(with = TimeStringSerializer::class) val refTime: String? = null,
    @SerialName("common_mistake") val commonMistake: String = "",
    @SerialName("self_test") val selfTest: SelfTest? = null,
)

@Serializable
enum class CheckType {
    @SerialName("camera") Camera,
    @SerialName("manual") Manual,
}

@Serializable
data class SelfTest(
    val own: Answer = Answer.Unsure,
    val prev: Answer = Answer.Unsure,
    val ok: Boolean = false,
    /** Present (true) only when the self-test ran in mock mode. */
    val mock: Boolean = false,
)

/** A check answer: `yes`, `no` or `unsure`. */
@Serializable
enum class Answer {
    @SerialName("yes") Yes,
    @SerialName("no") No,
    @SerialName("unsure") Unsure,
}

// ---------------------------------------------------------------- REST (section 4)

/** One row of `GET /api/lessons`. `steps` is the step count there, not the steps. */
@Serializable
data class LessonSummary(
    val id: String,
    val title: String = "",
    val steps: Int = 0,
)

/** `POST /api/lesson`. */
@Serializable
data class UploadResponse(
    val job: String,
    val id: String,
)

/** `GET /api/jobs/{job}`. */
@Serializable
data class JobStatus(
    val status: JobPhase = JobPhase.Queued,
    val message: String = "",
    val id: String = "",
) {
    val finished: Boolean get() = status == JobPhase.Done || status == JobPhase.Error
}

/**
 * A job stage as the hub spells it. The known ones have names; any other status the hub adds later
 * ("transcribing", "voicing") is kept as its text, so a new stage shows instead of being lost.
 */
@Serializable(with = JobPhaseSerializer::class)
data class JobPhase(val wire: String) {
    val known: Boolean get() = wire in KNOWN

    companion object {
        val Queued = JobPhase("queued")
        val Normalizing = JobPhase("normalizing")
        val Extracting = JobPhase("extracting")
        val Cutting = JobPhase("cutting")
        val Done = JobPhase("done")
        val Error = JobPhase("error")
        private val KNOWN = setOf("queued", "normalizing", "extracting", "cutting", "done", "error")
    }
}

object JobPhaseSerializer : KSerializer<JobPhase> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("HandOverJobPhase", PrimitiveKind.STRING)
    override fun serialize(encoder: Encoder, value: JobPhase) = encoder.encodeString(value.wire)
    override fun deserialize(decoder: Decoder): JobPhase {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement()
        val text = if (element == null) decoder.decodeString() else (element as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
        return text?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }?.let(::JobPhase) ?: JobPhase.Queued
    }
}

/** `DELETE /api/lessons/{id}`. */
@Serializable
data class DeleteResponse(val deleted: String)

// ---------------------------------------------------------------- hub to client, both sockets (sections 6 and 7)

/** The `state` message. Sent on connect and on every change. */
@Serializable
data class HubState(
    @SerialName("lesson_id") val lessonId: String? = null,
    val rev: Long = 0,
    /** 0-based. Stays at total - 1 on the done screen. */
    val step: Int = 0,
    val total: Int = 0,
    val status: StepStatus = StepStatus.Watching,
    @SerialName("last_check") val lastCheck: LastCheck? = null,
    @SerialName("camera_connected") val cameraConnected: Boolean = false,
    val camera: CameraIdentity? = null,
    @SerialName("check_offline") val checkOffline: Boolean = false,
    @SerialName("check_offline_reason") val checkOfflineReason: OfflineReason? = null,
    val mistake: Mistake? = null,
    /** Who answers the live check: "mock", "claude" or "gemini". Hub branch only; free text on purpose. */
    @SerialName("check_mode") val checkMode: String? = null,
    /** The next step's clip path, once this step has one confident yes, so it can be preloaded. Hub branch only. */
    @SerialName("next_clip") val nextClip: String? = null,
    /** How far the current step looks, 0 to 1, from the hub's understanding; null when it is off. Reset on step change. */
    val progress: Double? = null,
    /** The current stage inside the step, from the same source as [progress]. */
    val stage: StepStage? = null,
    /** The current run, for `GET /api/runs/{run_id}/score` on the Done screen. New on every select; kept on the done screen. */
    @SerialName("run_id") val runId: String? = null,
) {
    val done: Boolean get() = status == StepStatus.Done

    /** The contract's position: `total` on the done screen, else `step`. */
    val position: Int get() = if (done) total else step

    /** True when the UI should show the "Recording" banner. */
    val isRecording: Boolean get() = camera?.source == CameraSource.File
}

/** `state.stage`: the stage [index] of [count] inside the step, with the rubric's [label]. */
@Serializable
data class StepStage(val index: Int = 0, val count: Int = 0, val label: String = "")

@Serializable
enum class StepStatus {
    @SerialName("watching") Watching,
    @SerialName("checking") Checking,
    @SerialName("verified") Verified,
    @SerialName("manual") Manual,
    @SerialName("done") Done,
}

@Serializable
data class LastCheck(
    val done: Answer = Answer.Unsure,
    val confidence: Double = 0.0,
    @SerialName("latency_ms") val latencyMs: Int = 0,
    /** Up to 8 words on what differs from the reference. Show it only at confidence >= 0.7. */
    val reason: String? = null,
) {
    val reasonToShow: String? get() = reason?.takeIf { confidence >= 0.7 && it.isNotBlank() }
}

@Serializable
data class CameraIdentity(
    val name: String = "",
    /** "ios", "web", "replay" or "other". Free text so a new platform never fails a decode. */
    val platform: String = "other",
    val source: CameraSource = CameraSource.Unknown,
)

@Serializable
enum class CameraSource {
    @SerialName("glasses") Glasses,
    @SerialName("phone") Phone,
    @SerialName("browser") Browser,
    @SerialName("file") File,
    /** The hub reports this for a camera that never said hello. */
    @SerialName("unknown") Unknown,
}

@Serializable
enum class OfflineReason {
    @SerialName("no_key") NoKey,
    @SerialName("rate_limited") RateLimited,
    @SerialName("errors") Errors,
    /** A Claude spending cap on the hub is reached; no call is made until it resets. */
    @SerialName("budget") Budget,
}

/** The mistake object, both as `state.mistake` and (with `type`) as the `mistake` message. */
@Serializable
data class Mistake(
    val step: Int = 0,
    val kind: MistakeKind = MistakeKind.Behind,
    /** The 0-based step the picture looks like. `behind` and `ahead` carry it; `live` does not. */
    @SerialName("looks_like") val looksLike: Int? = null,
    val message: String = "",
    val confidence: Double = 0.0,
    /** "gemini", "claude" or "mock". */
    val source: String = "",
    /** `live` only: the short name of what went wrong, from the step's rubric. */
    val label: String? = null,
)

@Serializable
enum class MistakeKind {
    @SerialName("behind") Behind,
    @SerialName("ahead") Ahead,
    /** Advisory, from the hub's understanding: never moves the step, carries [Mistake.label] and no looks_like. */
    @SerialName("live") Live,
}

/** The `advance` message, sent right before the matching state. `to` may equal total (finished). */
@Serializable
data class Advance(
    val from: Int,
    val to: Int,
    val reason: AdvanceReason = AdvanceReason.Button,
)

@Serializable
enum class AdvanceReason {
    @SerialName("camera") Camera,
    @SerialName("button") Button,
    @SerialName("voice") Voice,
}

// ---------------------------------------------------------------- client to hub

/** The camera's `hello`. `platform` is left out on purpose: see [CameraSocket]. */
@Serializable
data class Hello(
    @SerialName("device_id") val deviceId: String,
    val name: String,
    val source: String = "phone",
    val platform: String? = null,
    val type: String = "hello",
)

/** Next and back carry `from`, the position the client showed, so a stale tap is ignored (section 5). */
@Serializable
data class NextCommand(val from: Int? = null, val reason: String = "button", val type: String = "next")

@Serializable
data class BackCommand(val from: Int? = null, val type: String = "back")

@Serializable
data class GotoCommand(val step: Int, val type: String = "goto")

/** [token] is the sign-in token, so the hub tags the run with the learner; left out when signed out. */
@Serializable
data class SelectLessonCommand(val id: String, val token: String? = null, val type: String = "select_lesson")

@Serializable
data class DismissMistakeCommand(val type: String = "dismiss_mistake")

@Serializable
data class EndLessonCommand(val type: String = "end_lesson")

// ---------------------------------------------------------------- timestamps

/** `start`, `end`: "MM:SS", "MM:SS.s", "HH:MM:SS" or plain seconds, which may arrive as a JSON number. */
object TimeStringSerializer : KSerializer<String> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("HandOverTime", PrimitiveKind.STRING)
    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)
    override fun deserialize(decoder: Decoder): String {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement() ?: return decoder.decodeString()
        return (element as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content ?: ""
    }
}

/** Seconds from a contract timestamp ("MM:SS", "MM:SS.s", "HH:MM:SS" or plain seconds), or null when unreadable. */
fun parseTimestamp(raw: String): Double? {
    val parts = raw.trim().split(':')
    if (parts.isEmpty() || parts.size > 3 || parts.any { it.isBlank() }) return null
    val numbers = parts.map { it.toDoubleOrNull()?.takeIf { v -> v >= 0 } ?: return null }
    return numbers.fold(0.0) { acc, v -> acc * 60 + v }
}
