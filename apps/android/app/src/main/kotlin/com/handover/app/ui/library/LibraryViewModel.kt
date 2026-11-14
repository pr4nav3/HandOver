package com.handover.app.ui.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.handover.app.core.LessonSummary
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** The Library filter row: Everyone, Mine, Shared with Me, then one per organization. */
sealed interface LibraryFilter {
    val label: String

    data object Everyone : LibraryFilter { override val label = "Everyone" }
    data object Mine : LibraryFilter { override val label = "Mine" }
    data object Shared : LibraryFilter { override val label = "Shared with Me" }
    data object MyOrgs : LibraryFilter { override val label = "My Orgs" }
    data class InOrg(val org: Org) : LibraryFilter { override val label get() = org.name }
}

/** One lesson card. [covers] are tried in order. */
data class LibraryItem(
    val id: String,
    val title: String,
    val steps: Int,
    val duration: Double?,
    val covers: List<String>,
    /** "Draft", "Unlisted" or null. Shown only to the people who can see drafts at all. */
    val badge: String? = null,
    /** Steps done in the person's last unfinished run, from the hub's real run events. */
    val continueAt: Int? = null,
    val completed: Boolean = false,
)

data class LibraryUiState(
    val loading: Boolean = true,
    val refreshing: Boolean = false,
    val error: String? = null,
    /** True on a hub without `/api/courses`: plain lesson list, no filters, no badges. */
    val legacy: Boolean = false,
    /** True when someone is signed in, so Mine and Shared mean something. */
    val signedIn: Boolean = false,
    val orgs: List<Org> = emptyList(),
    val filter: LibraryFilter = LibraryFilter.Everyone,
    val query: String = "",
    val all: List<LibraryItem> = emptyList(),
    /** The hub's live session, when it is mid-lesson: (lesson id, step index, total). */
    val session: Triple<String, Int, Int>? = null,
) {
    val filters: List<LibraryFilter>
        get() = if (legacy || !signedIn) emptyList()
        else listOf(LibraryFilter.Everyone, LibraryFilter.Mine, LibraryFilter.Shared) +
            (if (orgs.isEmpty()) emptyList() else listOf(LibraryFilter.MyOrgs) + orgs.map { LibraryFilter.InOrg(it) })

    /** The cards for the current search. */
    val items: List<LibraryItem>
        get() {
            val q = query.trim().lowercase()
            return if (q.isEmpty()) all else all.filter { q in it.title.lowercase() || q in it.id.lowercase() }
        }

    /** In-progress lessons: the hub's live session first, then unfinished runs the hub recorded for this person. */
    val continueItems: List<Pair<LibraryItem, Int>>
        get() {
            val out = mutableListOf<Pair<LibraryItem, Int>>()
            session?.let { (id, step, _) -> all.firstOrNull { it.id == id }?.let { if (step > 0) out += it to step } }
            all.forEach { item ->
                val at = item.continueAt ?: return@forEach
                if (at > 0 && at < item.steps && out.none { it.first.id == item.id }) out += item to at
            }
            return if (query.isBlank()) out else emptyList()
        }
}

/** Loads the Library from the hub: `/api/courses` when the hub has it, else `/api/lessons`. */
class LibraryViewModel(private val backend: CourseBackend) : ViewModel() {
    private val _state = MutableStateFlow(LibraryUiState())
    val state: StateFlow<LibraryUiState> = _state.asStateFlow()
    private var loadJob: Job? = null
    private var orgsLoaded = false

    init {
        load(initial = true)
    }

    fun refresh() {
        HubImages.forgetMisses()
        load(initial = false)
    }

    fun setQuery(query: String) = _state.update { it.copy(query = query.take(100)) }

    fun setFilter(filter: LibraryFilter) {
        if (filter == _state.value.filter) return
        _state.update { it.copy(filter = filter) }
        load(initial = false, quiet = true)
    }

    fun setSession(lessonId: String?, step: Int, total: Int, done: Boolean) {
        val session = if (lessonId != null && !done) Triple(lessonId, step, total) else null
        if (session != _state.value.session) _state.update { it.copy(session = session) }
    }

    private fun load(initial: Boolean, quiet: Boolean = false) {
        loadJob?.cancel()
        _state.update { it.copy(loading = initial || quiet && it.all.isEmpty(), refreshing = !initial && !quiet, error = null) }
        loadJob = viewModelScope.launch {
            try {
                val me = runCatching { backend.me() }.getOrNull()
                if (!orgsLoaded && me?.userId != null) {
                    _state.update { it.copy(orgs = runCatching { backend.orgs() }.getOrNull().orEmpty()) }
                    orgsLoaded = true
                }
                val filter = _state.value.filter
                val (wire, org) = when (filter) {
                    LibraryFilter.Everyone -> "all" to null
                    LibraryFilter.Mine -> "mine" to null
                    LibraryFilter.Shared -> "shared" to null
                    LibraryFilter.MyOrgs -> "orgs" to null
                    is LibraryFilter.InOrg -> "all" to filter.org.id
                }
                val courses = backend.courses(wire, org = org)
                val items = courses?.map { it.toItem(backend) } ?: backend.lessons().map { it.toItem(backend) }
                _state.update {
                    it.copy(loading = false, refreshing = false, legacy = courses == null, signedIn = me?.userId != null, all = items)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, refreshing = false, error = e.plainWords()) }
            }
        }
    }
}

/** Cover order (SCREENS.md section 5): the course cover, the produced cover, then the first reference frame. */
internal fun CourseSummary.toItem(backend: CourseBackend): LibraryItem {
    val covers = listOfNotNull(coverUrl?.let { backend.absoluteUrl(it) }) +
        listOf(backend.fileUrl(id, "produced/cover.jpg"), backend.fileUrl(id, "frames/01.jpg"))
    val prog = progress?.takeIf { it.known }
    return LibraryItem(
        id = id,
        title = title.ifBlank { id },
        steps = steps,
        duration = duration,
        covers = covers.distinct(),
        badge = statusLabel(status),
        continueAt = prog?.takeIf { !it.lastFinished }?.lastStepsDone,
        completed = prog?.let { it.completed > 0 } ?: false,
    )
}

internal fun LessonSummary.toItem(backend: CourseBackend) = LibraryItem(
    id = id,
    title = title.ifBlank { id },
    steps = steps,
    duration = null,
    covers = listOf(backend.fileUrl(id, "produced/cover.jpg"), backend.fileUrl(id, "frames/01.jpg")),
)
