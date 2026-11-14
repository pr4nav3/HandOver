package com.handover.app.core

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** One text message from the hub, on either socket (CONTRACT.md sections 6 and 7). */
sealed interface HubMessage {
    data class State(val state: HubState) : HubMessage
    data class Advanced(val advance: Advance) : HubMessage
    data class MistakeRaised(val mistake: Mistake) : HubMessage

    /** `/ws/camera` only: this camera became the one the hub judges, or stopped being it. */
    data class CameraStatus(val active: Boolean) : HubMessage
    data class Error(val message: String) : HubMessage

    /** A type this app does not know. Readers ignore it; kept so a log can show it. */
    data class Unknown(val type: String?) : HubMessage
}

object HubMessages {
    /**
     * Routes one text frame. Returns null for text that is not a JSON object, and for a known type
     * whose body does not decode (the hub never sends one; a broken message is dropped, not fatal).
     */
    fun parse(text: String): HubMessage? {
        val obj = try {
            HubJson.parseToJsonElement(text) as? JsonObject
        } catch (_: SerializationException) {
            null
        } ?: return null
        val type = (obj["type"] as? JsonPrimitive)?.contentOrNull
        return try {
            when (type) {
                "state" -> HubMessage.State(HubJson.decodeFromJsonElement(HubState.serializer(), obj))
                "advance" -> HubMessage.Advanced(HubJson.decodeFromJsonElement(Advance.serializer(), obj))
                "mistake" -> HubMessage.MistakeRaised(HubJson.decodeFromJsonElement(Mistake.serializer(), obj))
                "camera_status" -> HubMessage.CameraStatus((obj["active"] as? JsonPrimitive)?.contentOrNull == "true")
                "error" -> HubMessage.Error((obj["message"] as? JsonPrimitive)?.contentOrNull.orEmpty())
                else -> HubMessage.Unknown(type)
            }
        } catch (_: SerializationException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }
}

/**
 * The stale guard on next and back (CONTRACT.md section 5). Each command carries `from`, the position
 * the client showed when the person tapped. The hub ignores it when the position has moved on since,
 * so a double tap or a tap racing a camera advance never skips a step. These builders also drop
 * taps the hub would treat as a no-op, so nothing is sent for them.
 */
object Nav {
    /** Next from what [shown] displays, or null when there is nothing to go to. */
    fun next(shown: HubState?, reason: String = "button"): NextCommand? {
        if (shown == null || shown.lessonId == null || shown.total <= 0 || shown.done) return null
        return NextCommand(from = shown.position, reason = if (reason == "voice") "voice" else "button")
    }

    /** Back from what [shown] displays, or null on the first step. Back from the done screen returns to the last step. */
    fun back(shown: HubState?): BackCommand? {
        if (shown == null || shown.lessonId == null || shown.total <= 0 || shown.position <= 0) return null
        return BackCommand(from = shown.position)
    }

    /** Jump to a 0-based step, or null when it is out of range or already showing. */
    fun goto(shown: HubState?, step: Int): GotoCommand? {
        if (shown == null || shown.lessonId == null || step !in 0 until shown.total || step == shown.position) return null
        return GotoCommand(step)
    }

    /**
     * Whether the hub would apply a command carrying [from] given its current [state]: the mirror of
     * the hub's rule, where on the done screen both total - 1 and total count.
     */
    fun hubAccepts(from: Int?, state: HubState): Boolean {
        if (from == null) return true
        if (state.done) return from == state.total - 1 || from == state.total
        return from == state.step
    }
}
