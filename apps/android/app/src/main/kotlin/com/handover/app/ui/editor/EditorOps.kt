package com.handover.app.ui.editor

import com.handover.app.core.CheckType
import com.handover.app.core.Lesson
import com.handover.app.core.Step
import com.handover.app.core.parseTimestamp
import kotlin.math.abs
import kotlin.math.roundToInt

// The course editor's edits as pure functions on a Lesson, so they are tested without a hub. They mirror the
// hub's editor routes (server/routes_library.py): the client shows the result at once, then the hub's answer
// replaces it. On a legacy hub (no editor routes) these results are what gets saved through recut.

/** The shortest step the editor makes (DESIGN.md 3.18: "Minimum step length 0.5 s"). */
const val MIN_STEP_SECONDS = 0.5

/** How far a dragged boundary reaches for a caption cue edge (DESIGN.md 3.18). */
const val SNAP_SECONDS = 0.4

/** "MM:SS" or "MM:SS.s", the hub's own `fmt_time`. */
fun formatTimestamp(seconds: Double): String {
    val tenths = (seconds.coerceAtLeast(0.0) * 10).roundToInt()
    val m = tenths / 600
    val s = (tenths % 600) / 10
    val t = tenths % 10
    return "%02d:%02d".format(m, s) + if (t != 0) ".$t" else ""
}

/** "01:14.5", always with tenths: the editor's floating label and time fields. */
fun formatEditorTime(seconds: Double): String {
    val tenths = (seconds.coerceAtLeast(0.0) * 10).roundToInt()
    return "%02d:%02d.%d".format(tenths / 600, (tenths % 600) / 10, tenths % 10)
}

fun Step.startSeconds(): Double = parseTimestamp(start) ?: 0.0
fun Step.endSeconds(): Double = parseTimestamp(end) ?: startSeconds()

/** The times between steps: boundary k sits between step k and step k + 1 (both 0-based). */
fun Lesson.boundaries(): List<Double> = steps.dropLast(1).map { it.endSeconds() }

fun Lesson.totalSeconds(): Double = steps.lastOrNull()?.endSeconds() ?: 0.0

/**
 * Snaps [t] to the nearest point within [tolerance], or rounds it to 0.1 s when none is near (free placement).
 * Returns the time and whether it snapped, so the caller plays the snap haptic once per new snap point.
 */
fun snap(t: Double, points: List<Double>, tolerance: Double = SNAP_SECONDS): Pair<Double, Boolean> {
    val nearest = points.minByOrNull { abs(it - t) }
    return if (nearest != null && abs(nearest - t) <= tolerance + 1e-9) nearest to true else (t * 10).roundToInt() / 10.0 to false
}

/** The range boundary [k] may move in, keeping both neighbors at least [MIN_STEP_SECONDS] long. */
fun Lesson.boundaryRange(k: Int): ClosedFloatingPointRange<Double> {
    val lo = steps[k].startSeconds() + MIN_STEP_SECONDS
    val hi = steps[k + 1].endSeconds() - MIN_STEP_SECONDS
    return lo..maxOf(lo, hi)
}

/** Moves boundary [k] to [t] (clamped). The hub drops the reference time and self-test of a retimed step. */
fun Lesson.moveBoundary(k: Int, t: Double): Lesson {
    if (k !in 0 until steps.size - 1) return this
    val at = t.coerceIn(boundaryRange(k))
    val stamp = formatTimestamp(at)
    return copy(steps = steps.mapIndexed { i, s ->
        when (i) {
            k -> s.copy(end = stamp, refTime = null, selfTest = null)
            k + 1 -> s.copy(start = stamp, refTime = null, selfTest = null)
            else -> s
        }
    })
}

/** Whether step [i] can be split at [at]: both parts at least [MIN_STEP_SECONDS]. */
fun Lesson.canSplit(i: Int, at: Double): Boolean {
    val s = steps.getOrNull(i) ?: return false
    return at >= s.startSeconds() + MIN_STEP_SECONDS && at <= s.endSeconds() - MIN_STEP_SECONDS
}

/** Splits step [i] at [at]; the second part copies the check and gets "<title> (part 2)", as the hub does. */
fun Lesson.split(i: Int, at: Double): Lesson? {
    if (!canSplit(i, at)) return null
    val s = steps[i]
    val stamp = formatTimestamp(at)
    val first = s.clearDerived().copy(end = stamp)
    val second = s.clearDerived().copy(start = stamp, title = "${s.title.ifBlank { "Step ${i + 1}" }} (part 2)")
    return renumbered(steps.take(i) + first + second + steps.drop(i + 1))
}

/** Merges step [i] with the next: the first's title and start, the second's end and check (the hub's rule). */
fun Lesson.merge(i: Int): Lesson? {
    if (i !in 0 until steps.size - 1) return null
    val a = steps[i]
    val b = steps[i + 1]
    val merged = b.copy(start = a.start, title = a.title.ifBlank { b.title }, clip = null, captions = null, refFrame = null, selfTest = null)
    return renumbered(steps.take(i) + merged + steps.drop(i + 2))
}

/** Deletes step [i]. A lesson keeps at least one step. */
fun Lesson.deleteStep(i: Int): Lesson? {
    if (steps.size <= 1 || i !in steps.indices) return null
    return renumbered(steps.filterIndexed { k, _ -> k != i })
}

/** Title, check type, check question, common mistake. Manual steps carry no question (CONTRACT.md section 3). */
fun Lesson.editStep(i: Int, title: String? = null, checkType: CheckType? = null, question: String? = null, mistake: String? = null): Lesson {
    if (i !in steps.indices) return this
    return copy(steps = steps.mapIndexed { k, s ->
        if (k != i) return@mapIndexed s
        var out = s
        if (title != null) out = out.copy(title = title)
        if (checkType != null) out = out.copy(checkType = checkType)
        if (question != null) out = out.copy(checkQuestion = question)
        if (mistake != null) out = out.copy(commonMistake = mistake)
        if (out.checkType == CheckType.Manual) out = out.copy(checkQuestion = "")
        else if (out.checkQuestion.isBlank()) out = out.copy(checkQuestion = DEFAULT_QUESTION)
        if (checkType != null || question != null) out = out.copy(selfTest = null)
        out
    })
}

const val DEFAULT_QUESTION = "Is this step finished?"

private fun Step.clearDerived() = copy(clip = null, captions = null, refFrame = null, refTime = null, selfTest = null)

/** Steps renumbered 1..n with the per-index file names the hub will write after the recut. */
private fun Lesson.renumbered(list: List<Step>): Lesson =
    copy(steps = list.map { it.copy(n = 0, clip = null, captions = null, refFrame = null) }).withDefaults(id)
