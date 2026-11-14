package com.handover.app.ui.record

import kotlin.math.ln
import kotlin.math.max

/** Where the recorder is (DESIGN.md 3.8 shutter states, SCREENS.md 12.4 review). */
enum class RecordPhase { Idle, Recording, Finishing, Review }

/** What the record screen draws. Pure data, so every state has a preview and a screenshot. */
data class RecordUi(
    val phase: RecordPhase = RecordPhase.Idle,
    val elapsedMs: Long = 0,
    /** The narration meter: newest bar last, each 0 to 1. */
    val levels: List<Float> = List(LevelMeter.BARS) { 0f },
    /** No sound for 3 s while recording. */
    val silent: Boolean = false,
    /** Recording without the microphone (permission declined, the person chose to go on). */
    val micOff: Boolean = false,
    val cameraAllowed: Boolean = true,
    val micAsked: Boolean = false,
    val usingFront: Boolean = false,
    val error: String? = null,
    /** The finished take's file, in Review. */
    val takePath: String? = null,
    val hasRecorded: Boolean = false,
)

/** "00:42", "12:05", "1:02:05": the timer pill. */
fun timerText(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0)
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%02d:%02d".format(m, s)
}

/** What VoiceOver hears, updated every 10 s, not every second (DESIGN.md 3.9). */
fun timerSpoken(ms: Long): String {
    val s = (ms / 10_000) * 10
    return if (s < 60) "Recording, $s seconds" else "Recording, ${s / 60} minutes ${s % 60} seconds"
}

/**
 * The narration meter (DESIGN.md 3.9): 24 bars from the microphone level, smoothed so it reads as speech and
 * not as noise. CameraX reports amplitude as 0 to 1 (of full scale); speech sits low on that scale, so the
 * bar height follows a log curve over a 50 dB range.
 */
class LevelMeter {
    private var smoothed = 0f
    private var quietSinceMs: Long? = null
    val bars = ArrayDeque(List(BARS) { 0f })

    /** Adds one reading; returns true when the mic has been silent for [SILENT_MS]. */
    fun add(amplitude: Double, nowMs: Long): Boolean {
        val level = toLevel(amplitude)
        smoothed = if (level > smoothed) level else smoothed * 0.6f + level * 0.4f
        bars.removeFirst()
        bars.addLast(smoothed)
        if (level > QUIET) quietSinceMs = null else if (quietSinceMs == null) quietSinceMs = nowMs
        return quietSinceMs?.let { nowMs - it >= SILENT_MS } ?: false
    }

    fun reset() {
        smoothed = 0f
        quietSinceMs = null
        repeat(BARS) { bars[it] = 0f }
    }

    companion object {
        const val BARS = 24
        const val SILENT_MS = 3_000L
        private const val QUIET = 0.04f
        private const val RANGE_DB = 50.0

        fun toLevel(amplitude: Double): Float {
            if (amplitude <= 0.0 || amplitude.isNaN()) return 0f
            val db = 20 * ln(amplitude.coerceAtMost(1.0)) / ln(10.0)
            return max(0.0, (db + RANGE_DB) / RANGE_DB).toFloat().coerceIn(0f, 1f)
        }
    }
}
