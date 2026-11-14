package com.handover.app.ui.learn

/** What a spoken line is for. Higher priority goes first when several wait. */
enum class SpeechKind(val priority: Int) { StepTitle(1), Result(2), Mistake(3), Complete(3) }

/** How much Learn says out loud. */
enum class Verbosity(val id: String, val title: String) {
    /** Mistakes and "Lesson complete" only. */
    Brief("brief", "Brief"),
    /** Plus the step title at each step and "Nice" after a step. */
    Standard("standard", "Standard"),
    /** Plus "Step 4." before titles and the full step result instead of "Nice". */
    Detailed("detailed", "Detailed");

    fun allows(kind: SpeechKind): Boolean = when (this) {
        Brief -> kind == SpeechKind.Mistake || kind == SpeechKind.Complete
        Standard, Detailed -> true
    }

    companion object {
        fun from(id: String?): Verbosity = entries.firstOrNull { it.id == id } ?: Standard
    }
}

data class Utterance(val text: String, val kind: SpeechKind, val id: Long)

/**
 * The order of spoken lines. Pure and clock-injected so it is tested on the JVM. Rules:
 * - Never two at once: a line starts only after the previous one finished ([done]).
 * - No repeats: the same words are dropped if they were spoken or queued in the last 3 s.
 * - A step title waiting for a newer step title is replaced (the old step is gone).
 * - At most [capacity] waiting; the oldest lowest-priority line is dropped first.
 * - Waiting lines go out by priority, then in arrival order.
 */
class SpeechQueue(private val clock: () -> Long, private val capacity: Int = 3, private val repeatWindowMs: Long = 3_000) {
    private val waiting = ArrayList<Utterance>()
    private val recent = LinkedHashMap<String, Long>()
    private var nextId = 1L

    /** The line being spoken, or null when idle. */
    var current: Utterance? = null
        private set

    /** Adds a line. Returns false when it is a repeat inside the window. */
    fun offer(text: String, kind: SpeechKind): Boolean {
        val words = text.trim()
        if (words.isEmpty()) return false
        val now = clock()
        recent.entries.removeAll { now - it.value >= repeatWindowMs }
        val key = words.lowercase()
        if (key in recent || current?.text?.lowercase() == key || waiting.any { it.text.lowercase() == key }) return false
        recent[key] = now
        if (kind == SpeechKind.StepTitle) waiting.removeAll { it.kind == SpeechKind.StepTitle }
        waiting += Utterance(words, kind, nextId++)
        while (waiting.size > capacity) {
            val drop = waiting.minWith(compareBy<Utterance> { it.kind.priority }.thenBy { it.id })
            waiting.remove(drop)
        }
        return true
    }

    /** The next line to speak when idle, which becomes [current]; null when busy or empty. */
    fun next(): Utterance? {
        if (current != null || waiting.isEmpty()) return null
        val u = waiting.maxWith(compareBy<Utterance> { it.kind.priority }.thenByDescending { it.id })
        waiting.remove(u)
        current = u
        return u
    }

    /** The current line finished (or failed). */
    fun done(id: Long) {
        if (current?.id == id) current = null
    }

    fun clear() {
        waiting.clear()
        current = null
    }

    val pending: List<Utterance> get() = waiting.toList()
}
