package com.handover.app.ui.editor

import com.handover.app.ui.library.CueEdit
import kotlin.math.roundToLong

/** One caption line, times relative to the step's clip. */
data class Cue(val start: Double, val end: Double, val text: String)

/** WebVTT cues from a captions file. Headers, notes and cue ids are skipped; unreadable cues are dropped. */
fun parseVtt(text: String): List<Cue> {
    val out = mutableListOf<Cue>()
    val blocks = text.replace("\r\n", "\n").split(Regex("\n\\s*\n"))
    for (block in blocks) {
        val lines = block.lines().filter { it.isNotBlank() }
        val timing = lines.indexOfFirst { "-->" in it }
        if (timing < 0) continue
        val (a, b) = lines[timing].split("-->").map { it.trim().substringBefore(' ') }.let { it.getOrNull(0) to it.getOrNull(1) }
        val start = a?.let(::vttSeconds) ?: continue
        val end = b?.let(::vttSeconds) ?: continue
        val body = lines.drop(timing + 1).joinToString("\n").trim()
        if (body.isNotEmpty() && end > start) out += Cue(start, end, body)
    }
    return out.sortedBy { it.start }
}

/** "00:00:01.500" or "00:01.500" as seconds. */
fun vttSeconds(raw: String): Double? {
    val parts = raw.trim().split(':')
    if (parts.size !in 2..3) return null
    return parts.fold(0.0) { acc, p -> acc * 60 + (p.toDoubleOrNull() ?: return null) }
}

/** "00:00:01.500", the hub's `fmt_vtt`. */
fun formatVtt(seconds: Double): String {
    var ms = (seconds.coerceAtLeast(0.0) * 1000).roundToLong()
    val h = ms / 3_600_000; ms %= 3_600_000
    val m = ms / 60_000; ms %= 60_000
    val s = ms / 1000; ms %= 1000
    return "%02d:%02d:%02d.%03d".format(h, m, s, ms)
}

fun Cue.toEdit() = CueEdit(formatVtt(start), formatVtt(end), text.trim())

/**
 * Snap points for timeline boundaries: every caption cue edge, moved from clip time to lesson time by its
 * step's start. [cues] is per step, in step order.
 */
fun snapPoints(stepStarts: List<Double>, cues: List<List<Cue>>): List<Double> =
    cues.flatMapIndexed { i, list ->
        val offset = stepStarts.getOrNull(i) ?: return@flatMapIndexed emptyList()
        list.flatMap { listOf(offset + it.start, offset + it.end) }
    }.distinct().sorted()
