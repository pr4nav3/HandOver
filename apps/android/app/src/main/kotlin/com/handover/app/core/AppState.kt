package com.handover.app.core

/** An upload in progress or just finished. */
data class UploadState(
    val title: String,
    val sent: Long = 0,
    val total: Long = 0,
    /** Set once the hub accepted the file. */
    val lessonId: String? = null,
    val job: JobStatus? = null,
    /** Plain words when the upload or the job failed. */
    val error: String? = null,
) {
    val fraction: Float get() = if (total > 0) (sent.toFloat() / total).coerceIn(0f, 1f) else 0f
    val finished: Boolean get() = error != null || job?.status == JobPhase.Done
}

/**
 * Everything the screens draw, in one value. The live camera picture is kept apart (see
 * [AppViewModel.frame]) so four pictures a second do not rebuild every screen.
 */
data class AppState(
    /** The hub the app talks to, or null before one is set. */
    val hub: HubUrl? = null,
    val connection: SocketStatus = SocketStatus(),
    /** The hub's newest `state`, or null while not connected. */
    val session: HubState? = null,
    /** The active lesson, fetched for [session]'s lesson id at [lessonRev]. */
    val lesson: Lesson? = null,
    val lessonRev: Long = 0,
    val lessons: List<LessonSummary> = emptyList(),
    val lessonsLoading: Boolean = false,
    val lastAdvance: Advance? = null,
    /** The newest `mistake` message, including `ahead`, which never appears in [HubState.mistake]. */
    val lastMistake: Mistake? = null,
    /** The newest problem to show, in plain words, or null. */
    val error: String? = null,
    val upload: UploadState? = null,
) {
    val connected: Boolean get() = connection.phase == SocketPhase.Open

    /** The current step of the active lesson, or null with no lesson or on the done screen. */
    val currentStep: Step? get() = session?.takeIf { !it.done }?.let { lesson?.steps?.getOrNull(it.step) }

    /** (lesson id, rev) to fetch when the session's lesson is not the one loaded, else null. */
    val lessonToFetch: Pair<String, Long>?
        get() {
            val id = session?.lessonId ?: return null
            val rev = session.rev
            return if (lesson?.id == id && lessonRev == rev) null else id to rev
        }

    /**
     * Applies one message from the hub. Pure, so the routing is tested without a socket. A new
     * lesson id drops the loaded lesson; a new rev keeps it on screen until the refetch lands.
     */
    fun reduce(message: HubMessage): AppState = when (message) {
        is HubMessage.State -> {
            val s = message.state
            copy(
                session = s,
                lesson = lesson?.takeIf { it.id == s.lessonId },
                lastMistake = lastMistake?.takeIf { s.lessonId == session?.lessonId && it.step == s.step },
            )
        }
        is HubMessage.Advanced -> copy(lastAdvance = message.advance, lastMistake = null)
        is HubMessage.MistakeRaised -> copy(lastMistake = message.mistake)
        is HubMessage.Error -> copy(error = message.message)
        is HubMessage.CameraStatus, is HubMessage.Unknown -> this
    }

    /** The fetched lesson, kept only when it is still the session's lesson at that rev. */
    fun withLesson(fetched: Lesson, rev: Long): AppState =
        if (session?.lessonId == fetched.id && session.rev == rev) copy(lesson = fetched, lessonRev = rev) else this
}
