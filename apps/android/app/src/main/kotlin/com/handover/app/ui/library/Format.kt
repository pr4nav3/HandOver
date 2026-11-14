package com.handover.app.ui.library

import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.core.parseTimestamp
import kotlin.math.roundToInt

/** "0:42", "3:12", "1:02:05": the clock format SCREENS.md uses for lengths. */
fun clock(seconds: Double): String {
    val total = seconds.coerceAtLeast(0.0).roundToInt()
    val h = total / 3600
    val m = (total % 3600) / 60
    val s = total % 60
    return if (h > 0) "%d:%02d:%02d".format(h, m, s) else "%d:%02d".format(m, s)
}

/** "8 steps, 3:12", or "8 steps" when the length is unknown. */
fun stepsMeta(steps: Int, duration: Double?): String {
    val count = if (steps == 1) "1 step" else "$steps steps"
    return if (duration != null && duration > 0) "$count, ${clock(duration)}" else count
}

/** A step's length in seconds, or null when its times are unreadable. */
fun Step.seconds(): Double? {
    val a = parseTimestamp(start) ?: return null
    val b = parseTimestamp(end) ?: return null
    return (b - a).takeIf { it >= 0 }
}

/** First start to last end, as the hub's `lesson_duration` computes it. */
fun Lesson.durationSeconds(): Double? {
    val a = steps.firstOrNull()?.let { parseTimestamp(it.start) } ?: return null
    val b = steps.lastOrNull()?.let { parseTimestamp(it.end) } ?: return null
    return (b - a).takeIf { it >= 0 }
}

/** The badge text for a course status, or null for published (published is the quiet default). */
fun statusLabel(status: String): String? = when (status) {
    "draft" -> "Draft"
    "unlisted" -> "Unlisted"
    "processing" -> "Processing"
    else -> null
}
