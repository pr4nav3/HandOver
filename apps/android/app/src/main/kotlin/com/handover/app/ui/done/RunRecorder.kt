package com.handover.app.ui.done

import com.handover.app.core.Advance
import com.handover.app.core.AdvanceReason
import com.handover.app.core.HubState
import com.handover.app.core.Mistake
import com.handover.app.core.MistakeKind

/** How a step was left forward in this run (DESIGN.md 3.20). */
enum class Completion(val words: String) { Camera("Checked by camera"), Hand("Marked done"), Skipped("Skipped") }

/** What this device saw on one step in this run. */
data class StepRun(
    /** Time on the step, summed across visits, in ms. */
    val ms: Long = 0,
    val completion: Completion? = null,
    /** `behind` mistakes raised on this step. */
    val mistakes: Int = 0,
    /** Checks were off at some moment while on this step. */
    val checksOff: Boolean = false,
    /** The step's timer was cut by a hub disconnect. */
    val interrupted: Boolean = false,
)

/** The whole run, frozen as a value for the Done screen. */
data class RunData(
    val lessonId: String? = null,
    val rev: Long = 0,
    val steps: List<StepRun> = emptyList(),
    /** Start to done, in ms; null until done, or when the run did not start at step 1 on this device. */
    val runMs: Long? = null,
    /** The hub was gone for more than 10 s during the run (SCREENS.md 20.1). */
    val interrupted: Boolean = false,
    val finished: Boolean = false,
)

/** What a forward step change means for the step result moment (SCREENS.md 7.10). */
data class Forward(val step: Int, val seconds: Double?, val byCamera: Boolean, val mistakesFixed: Int)

/**
 * Records a run from the messages this device receives: `state` position changes (time charged on
 * each change, as web/src/Learn.tsx does), `advance` (how a step was left), `mistake`, and
 * `check_offline`. Pure and clock-injected, so the rules are tested on the JVM. Never invents a
 * number: anything it did not see stays null.
 */
class RunRecorder(private val clock: () -> Long = System::currentTimeMillis) {
    private var lessonId: String? = null
    private var rev: Long = 0
    private var steps = mutableListOf<StepRun>()
    private var position = 0
    private var total = 0
    private var enteredAt: Long? = null
    private var visitStart: Long? = null
    private var startedAt: Long? = null
    private var endedAt: Long? = null
    private var disconnectedAt: Long? = null
    private var interrupted = false
    private var pendingGoto = false
    private var restartPending = false

    val data: RunData
        get() = RunData(
            lessonId, rev, steps.toList(),
            runMs = if (startedAt != null && endedAt != null) endedAt!! - startedAt!! else null,
            interrupted = interrupted, finished = total > 0 && position >= total,
        )

    fun onState(s: HubState?) {
        val now = clock()
        if (s == null) {
            if (enteredAt != null) {
                charge(now)
                if (position < total) update(position) { it.copy(interrupted = true) }
                enteredAt = null
                disconnectedAt = now
            }
            return
        }
        val id = s.lessonId ?: return
        if (id != lessonId || s.rev != rev || s.total != total || (restartPending && s.position == 0)) {
            start(id, s.rev, s.total, s.position, now)
        } else if (disconnectedAt != null) {
            if (now - disconnectedAt!! > 10_000) interrupted = true
            disconnectedAt = null
            enteredAt = now
            visitStart = now
        }
        if (s.position != position) move(s.position, now)
        if (s.checkOffline && position < total) update(position) { it.copy(checksOff = true) }
    }

    /** Returns the forward step change for the result moment, or null (back, goto, last step, stale). */
    fun onAdvance(a: Advance): Forward? {
        if (lessonId == null || a.from !in 0..total) return null
        val now = clock()
        val wasGoto = pendingGoto
        pendingGoto = false
        if (a.to <= a.from) {
            move(a.to, now)
            return null
        }
        val visit = visitStart?.let { now - it }
        if (position == a.from) charge(now)
        val camera = a.reason == AdvanceReason.Camera
        if (a.from < total) {
            update(a.from) { it.copy(completion = if (camera) Completion.Camera else if (wasGoto) Completion.Skipped else Completion.Hand) }
        }
        for (k in (a.from + 1) until minOf(a.to, total)) {
            // An ahead jump by camera was confirmed by a check on the step it passed; a button jump skipped it.
            update(k) { if (it.completion == null) it.copy(completion = if (camera) Completion.Camera else Completion.Skipped) else it }
        }
        position = a.to
        enteredAt = now
        visitStart = now
        if (a.to >= total) {
            endedAt = now
            return null
        }
        if (wasGoto || a.from >= total) return null
        val step = steps[a.from]
        val seconds = if (visit != null && visit >= 1_000 && !step.interrupted) step.ms / 1000.0 else null
        return Forward(a.from, seconds, camera, step.mistakes)
    }

    fun onMistake(m: Mistake) {
        if (m.kind == MistakeKind.Behind && m.step in 0 until total) update(m.step) { it.copy(mistakes = it.mistakes + 1) }
    }

    /** This device is about to send goto: the step being left forward counts as skipped. */
    fun willGoto(to: Int) {
        pendingGoto = to > position
    }

    /** Clears one step's record before practicing it, so its new result replaces the old one. */
    fun resetStep(index: Int) {
        if (index in steps.indices) steps[index] = StepRun()
    }

    /** Start Over: a fresh run begins with the next state at step 1. */
    fun restart() {
        restartPending = true
    }

    private fun start(id: String, rev: Long, total: Int, position: Int, now: Long) {
        lessonId = id
        this.rev = rev
        this.total = total
        steps = MutableList(total) { StepRun() }
        this.position = position
        enteredAt = now
        visitStart = now
        startedAt = if (position == 0) now else null
        endedAt = null
        interrupted = false
        disconnectedAt = null
        pendingGoto = false
        restartPending = false
    }

    private fun move(to: Int, now: Long) {
        if (to == position) return
        charge(now)
        if (position >= total && to < total) endedAt = null
        position = to
        enteredAt = now
        visitStart = now
        if (to >= total && endedAt == null && total > 0) endedAt = now
    }

    private fun charge(now: Long) {
        val from = enteredAt ?: return
        if (position in 0 until total) update(position) { it.copy(ms = it.ms + (now - from)) }
        enteredAt = now
    }

    private inline fun update(i: Int, f: (StepRun) -> StepRun) {
        if (i in steps.indices) steps[i] = f(steps[i])
    }
}
