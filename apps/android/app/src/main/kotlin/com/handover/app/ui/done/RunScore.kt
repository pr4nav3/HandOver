package com.handover.app.ui.done

import com.handover.app.core.CheckType
import com.handover.app.core.Lesson
import com.handover.app.core.parseTimestamp
import com.handover.app.ui.components.Format
import com.handover.app.ui.components.ScoreLabel
import kotlin.math.ceil
import kotlin.math.min
import kotlin.math.roundToInt

/** One step on the Done screen: the lesson's facts plus what this run recorded. */
data class StepView(
    val index: Int,
    val n: Int,
    val title: String,
    val expert: Double?,
    val manual: Boolean,
    val commonMistake: String,
    /** Your time in seconds; null when not recorded (not finished, skipped, or no time measured). */
    val seconds: Double?,
    val completion: Completion?,
    val mistakes: Int,
    val checksOff: Boolean,
) {
    val ratio: Double? get() = if (seconds != null && expert != null && expert > 0) seconds / expert else null
}

data class Pick(val index: Int, val n: Int, val title: String, val reason: String)

/** The three score parts as plain sentences, for "How the score works". */
data class ScoreParts(val checked: String?, val pace: String, val clean: String)

enum class ScoreSource { Local, Hub }

/** Everything the Done screen shows. Nulls mean "Not enough data", never zero. */
data class DoneModel(
    val lessonTitle: String,
    val score: Int?,
    val label: ScoreLabel?,
    val parts: ScoreParts?,
    val runSeconds: Double?,
    val expertSeconds: Double?,
    val checkedByCamera: Int,
    val cameraSteps: Int,
    val markedDone: Int,
    val mistakes: Int,
    val skipped: Int,
    val best: Pick?,
    val weakest: Pick?,
    val tip: String,
    val steps: List<StepView>,
    val source: ScoreSource = ScoreSource.Local,
) {
    /** The longest time across the lesson, the shared scale of every time bar. */
    val timeScale: Double get() = steps.flatMap { listOfNotNull(it.seconds, it.expert) }.maxOrNull() ?: 0.0
}

/** SCREENS.md section 20, on this device's record of the run. */
object RunScore {
    fun expertSeconds(start: String, end: String): Double? {
        val s = parseTimestamp(start) ?: return null
        val e = parseTimestamp(end) ?: return null
        return (e - s).takeIf { it > 0 }
    }

    fun steps(lesson: Lesson, run: RunData): List<StepView> = lesson.steps.mapIndexed { i, st ->
        val r = run.steps.getOrNull(i) ?: StepRun()
        val timed = r.completion != null && r.completion != Completion.Skipped && r.ms > 0 && !r.interrupted
        StepView(
            index = i, n = if (st.n > 0) st.n else i + 1, title = st.title, expert = expertSeconds(st.start, st.end),
            manual = st.checkType == CheckType.Manual, commonMistake = st.commonMistake.trim(),
            seconds = if (timed) r.ms / 1000.0 else null, completion = r.completion, mistakes = r.mistakes, checksOff = r.checksOff,
        )
    }

    fun model(lesson: Lesson, run: RunData): DoneModel {
        val steps = steps(lesson, run)
        val cameraSteps = steps.count { !it.manual }
        val (score, parts) = score(steps, run.interrupted)
        val qualifying = steps.filter { it.ratio != null && it.completion != Completion.Skipped }
        val weakest = if (qualifying.size >= 2) qualifying.sortedWith(compareByDescending<StepView> { it.mistakes }.thenByDescending { it.ratio }).first() else null
        val best = if (qualifying.size >= 2) {
            val clean = qualifying.filter { it.mistakes == 0 }
            (clean.filter { it.completion == Completion.Camera }.minByOrNull { it.ratio!! } ?: clean.minByOrNull { it.ratio!! })?.takeIf { it.index != weakest?.index }
        } else null
        val expertSum = steps.map { it.expert }.takeIf { list -> list.isNotEmpty() && list.all { it != null } }?.sumOf { it!! }
        return DoneModel(
            lessonTitle = lesson.title,
            score = score,
            label = score?.let { ScoreLabel.of(it) },
            parts = parts,
            runSeconds = if (run.interrupted) null else run.runMs?.div(1000.0),
            expertSeconds = expertSum,
            checkedByCamera = steps.count { !it.manual && it.completion == Completion.Camera },
            cameraSteps = cameraSteps,
            markedDone = steps.count { it.completion == Completion.Hand },
            mistakes = steps.sumOf { it.mistakes },
            skipped = steps.count { it.completion == Completion.Skipped },
            best = best?.let { Pick(it.index, it.n, it.title, bestReason(it)) },
            weakest = weakest?.let { Pick(it.index, it.n, it.title, weakestReason(it)) },
            tip = tip(steps, weakest),
            steps = steps,
        )
    }

    /**
     * Score (20.2): only when the run was not interrupted and at least half the steps have a time.
     * Checked = camera-verified camera steps over camera steps with checks on the whole time (dropped
     * when none qualify); Pace = mean of min(1, expert / yours), skipped steps 0; Clean = 1 - min(1,
     * mistakes / steps). 0.5, 0.3, 0.2, or 0.6 and 0.4 without Checked.
     */
    fun score(steps: List<StepView>, interrupted: Boolean): Pair<Int?, ScoreParts?> {
        val total = steps.size
        if (interrupted || total == 0) return null to null
        val timed = steps.filter { it.seconds != null }
        if (timed.size < ceil(total / 2.0).toInt()) return null to null
        val paceItems = steps.mapNotNull { s ->
            when {
                s.completion == Completion.Skipped -> 0.0
                s.ratio != null -> min(1.0, 1.0 / s.ratio!!)
                else -> null
            }
        }
        if (paceItems.isEmpty()) return null to null
        val pace = paceItems.average()
        val mistakes = steps.sumOf { it.mistakes }
        val clean = 1 - min(1.0, mistakes / total.toDouble())
        val qualifying = steps.filter { !it.manual && !it.checksOff }
        val verified = qualifying.count { it.completion == Completion.Camera }
        val score = if (qualifying.isEmpty()) 100 * (0.6 * pace + 0.4 * clean) else 100 * (0.5 * verified / qualifying.size + 0.3 * pace + 0.2 * clean)
        val parts = ScoreParts(
            checked = if (qualifying.isEmpty()) null else "$verified of ${qualifying.size} camera steps checked by camera.",
            pace = "Your pace was ${(pace * 100).roundToInt()}% of the expert's.",
            clean = "${Format.count(mistakes, "mistake")} in ${Format.count(total, "step")}.",
        )
        return score.roundToInt().coerceIn(0, 100) to parts
    }

    private fun bestReason(s: StepView): String =
        if (s.completion == Completion.Camera) "Checked by camera in ${Format.secs(s.seconds!!)}." else "Done in ${Format.secs(s.seconds!!)}."

    private fun weakestReason(s: StepView): String {
        val times = "${Format.clock(s.seconds!!)} against ${Format.clock(s.expert!!)}."
        return if (s.mistakes > 0) "${Format.count(s.mistakes, "mistake")}, $times" else times.replaceFirstChar { it.uppercase() }
    }

    /** The tip (20.4): the first rule that matches. */
    fun tip(steps: List<StepView>, weakest: StepView?): String {
        if (weakest != null) {
            if (weakest.commonMistake.isNotEmpty()) return "On step ${weakest.n}, watch for this: ${weakest.commonMistake}"
            if (weakest.mistakes > 0) return "Replay step ${weakest.n}'s clip before you try it again."
            if ((weakest.ratio ?: 0.0) > 2.0) return "Step ${weakest.n} took the longest. Watch the expert's hands closely there."
        }
        steps.firstOrNull { it.completion == Completion.Skipped }?.let { return "You skipped step ${it.n}. Try it once so the camera can check it." }
        if (steps.any { it.checksOff }) return "Checks were off for part of this run, so try again for a full score."
        return "Try it again without looking at the clip."
    }
}
