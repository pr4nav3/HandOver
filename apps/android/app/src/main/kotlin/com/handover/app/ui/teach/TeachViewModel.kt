package com.handover.app.ui.teach

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.handover.app.core.HubException
import com.handover.app.core.Lesson
import com.handover.app.core.UploadSource
import com.handover.app.ui.library.CourseBackend
import com.handover.app.ui.library.LibraryItem
import com.handover.app.ui.library.plainWords
import com.handover.app.ui.library.toItem
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.IOException

/** Where the Make Course flow is. */
enum class TeachPhase { Home, Naming, Uploading, Processing, Ready, Failed }

data class TeachUi(
    val phase: TeachPhase = TeachPhase.Home,
    /** The picked or recorded video waiting for a title, or being uploaded. */
    val video: UploadSource? = null,
    val title: String = "",
    val sent: Long = 0,
    val total: Long = 0,
    val rows: List<StageRow> = emptyList(),
    val lessonId: String? = null,
    val lesson: Lesson? = null,
    val error: String? = null,
    /** Lessons this person can edit, for "Your Lessons". Null while loading or on error. */
    val lessons: List<LibraryItem>? = null,
) {
    val percent: Int get() = if (total > 0) ((sent * 100) / total).toInt().coerceIn(0, 100) else 0
}

/**
 * Teach and Make Course (SCREENS.md sections 11 and 13): name the video, upload it with byte progress through
 * core's HubClient, then follow the hub's job with honest per-stage rows until the lesson is ready.
 */
class TeachViewModel(private val backend: CourseBackend, private val pollMs: Long = 1_000) : ViewModel() {
    private val _state = MutableStateFlow(TeachUi())
    val state: StateFlow<TeachUi> = _state.asStateFlow()
    private var work: Job? = null

    init { loadLessons() }

    fun loadLessons() {
        viewModelScope.launch {
            try {
                val me = runCatching { backend.me() }.getOrNull()
                val courses = backend.courses(if (me?.userId != null) "mine" else "all")
                val items = courses?.map { it.toItem(backend) } ?: backend.lessons().map { it.toItem(backend) }
                _state.update { it.copy(lessons = items) }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                _state.update { it.copy(lessons = emptyList()) }
            }
        }
    }

    /** A video was picked or recorded: ask for its title, prefilled from the file name (as Teach.tsx does). */
    fun pick(video: UploadSource, suggestedTitle: String? = null) {
        val title = suggestedTitle ?: titleFromFileName(video.fileName)
        _state.update { it.copy(phase = TeachPhase.Naming, video = video, title = title, error = null) }
    }

    fun setTitle(title: String) = _state.update { it.copy(title = title.take(120)) }

    /** Make Course: upload, then follow the job. */
    fun makeCourse() {
        val video = _state.value.video ?: return
        val title = _state.value.title.trim().ifEmpty { "Untitled lesson" }
        work?.cancel()
        _state.update {
            it.copy(
                phase = TeachPhase.Uploading, title = title, sent = 0, total = video.length,
                rows = listOf(StageRow(Stage.Upload, RowState.Active)), lessonId = null, lesson = null, error = null,
            )
        }
        work = viewModelScope.launch {
            val accepted = try {
                backend.upload(video, title) { sent, total -> _state.update { it.copy(sent = sent, total = total) } }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                fail(e.plainWords())
                return@launch
            }
            _state.update {
                it.copy(
                    phase = TeachPhase.Processing, lessonId = accepted.id, sent = it.total,
                    rows = it.rows.map { r -> if (r.stage == Stage.Upload) r.copy(state = RowState.Done) else r },
                )
            }
            follow(accepted.job, accepted.id)
        }
    }

    private suspend fun follow(job: String, lessonId: String) {
        var misses = 0
        while (true) {
            val status = try {
                backend.job(job).also { misses = 0 }
            } catch (e: CancellationException) {
                throw e
            } catch (e: HubException) {
                if (e.status == 404) return fail("The hub restarted and lost this job. Upload the video again.")
                null
            } catch (_: IOException) {
                null
            }
            if (status == null) {
                if (++misses >= MAX_MISSES) return fail("Lost contact with the hub. Check that it is running, then upload again.")
            } else {
                _state.update { it.copy(rows = it.rows.observe(status)) }
                when (status.status.lowercase()) {
                    "done" -> {
                        val lesson = runCatching { backend.lesson(lessonId) }.getOrNull()
                        _state.update { it.copy(phase = TeachPhase.Ready, lesson = lesson) }
                        loadLessons()
                        return
                    }
                    "error" -> {
                        _state.update { it.copy(phase = TeachPhase.Failed, error = status.message.ifBlank { "Processing failed." }) }
                        return
                    }
                }
            }
            delay(pollMs)
        }
    }

    private fun fail(message: String) {
        _state.update { s ->
            val rows = if (s.rows.any { it.state == RowState.Active }) s.rows.map { if (it.state == RowState.Active) it.copy(state = RowState.Failed, message = message) else it } else s.rows
            s.copy(phase = TeachPhase.Failed, error = message, rows = rows)
        }
    }

    /** Cancel during upload: the HTTP call is cancelled and the flow goes back to naming. */
    fun cancelUpload() {
        work?.cancel()
        _state.update { it.copy(phase = TeachPhase.Naming, sent = 0, rows = emptyList()) }
    }

    /** Try Again after an error: uploads the same video again. */
    fun retry() = makeCourse()

    /** Done: back to Teach home. The hub keeps working on a job still running. */
    fun finish() {
        work?.cancel()
        _state.update { TeachUi(lessons = it.lessons) }
        loadLessons()
    }

    companion object {
        /** Teach.tsx gives up after 30 polls without an answer. */
        const val MAX_MISSES = 30

        fun titleFromFileName(name: String): String =
            name.substringBeforeLast('.').replace('_', ' ').replace('-', ' ').trim()
                .replaceFirstChar { it.uppercase() }.ifEmpty { "Untitled lesson" }
    }
}
