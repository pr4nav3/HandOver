package com.handover.app.ui.editor

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.handover.app.core.Answer
import com.handover.app.core.CheckType
import com.handover.app.core.HubJson
import com.handover.app.core.Lesson
import com.handover.app.core.SelfTest
import com.handover.app.ui.library.CourseBackend
import com.handover.app.ui.library.CourseInfo
import com.handover.app.ui.library.CoursePermissions
import com.handover.app.ui.library.EditResult
import com.handover.app.ui.library.Org
import com.handover.app.ui.library.plainWords
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject

/** The save indicator (SCREENS.md 14.5). */
sealed interface SaveState {
    data object Idle : SaveState
    data object Saving : SaveState
    data object UpdatingClips : SaveState
    data object Saved : SaveState
    data class Failed(val message: String) : SaveState
}

/** A self-test for one step: running, or its result. */
data class SelfTestUi(val running: Boolean = false, val result: SelfTest? = null, val error: String? = null)

/** A voiceover job for one step. */
data class VoiceUi(val running: Boolean = false, val message: String? = null, val failed: Boolean = false)

/** Which editor features this hub has. Each one is hidden when false. */
data class EditorFeatures(
    /** The hub's editor routes. False on a legacy hub, which saves the whole lesson through recut instead. */
    val serverEdits: Boolean = false,
    val captions: Boolean = false,
    val selfTest: Boolean = false,
    val voiceover: Boolean = false,
    val publish: Boolean = false,
)

data class EditorUi(
    val loading: Boolean = true,
    val loadError: String? = null,
    val lesson: Lesson? = null,
    val course: CourseInfo? = null,
    val permissions: CoursePermissions = CoursePermissions(canEdit = true),
    val features: EditorFeatures = EditorFeatures(),
    val selected: Int = 0,
    /** Caption cues per step, in step order. */
    val cues: List<List<Cue>> = emptyList(),
    val snaps: List<Double> = emptyList(),
    val save: SaveState = SaveState.Idle,
    /** An error from the hub, verbatim, shown in a banner. */
    val banner: String? = null,
    val canUndo: Boolean = false,
    val canRedo: Boolean = false,
    val selfTests: Map<Int, SelfTestUi> = emptyMap(),
    val voice: Map<Int, VoiceUi> = emptyMap(),
    val orgs: List<Org> = emptyList(),
    /** The lesson file revision for cache-busting clip and frame URLs; bumped after every recut. */
    val rev: Long = 0,
) {
    val step get() = lesson?.steps?.getOrNull(selected)

    /** True while a recut runs: the timeline is read only (SCREENS.md 14.5). */
    val busy: Boolean get() = save == SaveState.UpdatingClips
}

/** One editor change: the local result and the hub call that makes it. */
private class Change(
    val local: (Lesson) -> Lesson?,
    val retimes: Boolean,
    val send: suspend (CourseBackend, String) -> EditResult?,
)

/**
 * The course editor (SCREENS.md section 14). Every change shows at once, then goes to the hub one at a time
 * (the hub refuses overlapping edits with 409). With the hub's editor routes, undo and redo are the hub's own
 * history; on a legacy hub the editor keeps its own [UndoStack] and saves the whole lesson through recut one
 * second after the last change.
 */
class EditorViewModel(private val backend: CourseBackend, private val lessonId: String) : ViewModel() {
    private val _state = MutableStateFlow(EditorUi())
    val state: StateFlow<EditorUi> = _state.asStateFlow()

    private val queue = Mutex()
    private val localHistory = UndoStack<Lesson>()
    private var synced: Lesson? = null
    private var raw: JsonObject? = null
    private var saveJob: Job? = null
    private var dragStart: Lesson? = null

    init { load() }

    fun load() {
        _state.update { it.copy(loading = true, loadError = null) }
        viewModelScope.launch {
            try {
                val detail = backend.course(lessonId)
                val lesson = detail?.lesson ?: backend.lesson(lessonId)
                if (detail == null) raw = runCatching { backend.lessonJson(lessonId) }.getOrNull()
                synced = lesson
                val server = detail != null
                val orgs = if (server && detail.permissions.canPublish) runCatching { backend.orgs() }.getOrNull().orEmpty() else emptyList()
                _state.update {
                    it.copy(
                        loading = false,
                        lesson = lesson,
                        course = detail?.course,
                        permissions = detail?.permissions ?: CoursePermissions(canEdit = true),
                        features = EditorFeatures(serverEdits = server, captions = server, selfTest = server, voiceover = server, publish = server && detail.permissions.canPublish),
                        canUndo = (detail?.history?.undo ?: 0) > 0,
                        canRedo = (detail?.history?.redo ?: 0) > 0,
                        selected = it.selected.coerceIn(0, (lesson.steps.size - 1).coerceAtLeast(0)),
                        orgs = orgs.filter { o -> o.canPublish },
                    )
                }
                loadCues(lesson)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, loadError = e.plainWords()) }
            }
        }
    }

    private suspend fun loadCues(lesson: Lesson) {
        val rev = _state.value.rev
        val cues = lesson.steps.map { s ->
            val path = s.captions ?: return@map emptyList()
            runCatching { backend.lessonText(lessonId, path, rev)?.let(::parseVtt) }.getOrNull().orEmpty()
        }
        _state.update { it.copy(cues = cues, snaps = snapPoints(lesson.steps.map { s -> s.startSeconds() }, cues)) }
    }

    fun select(i: Int) = _state.update { it.copy(selected = i.coerceIn(0, ((it.lesson?.steps?.size ?: 1) - 1).coerceAtLeast(0))) }

    fun dismissBanner() = _state.update { it.copy(banner = null) }

    // ------------------------------------------------------------ edits

    /** Live boundary drag: moves the boundary on screen only. [commitBoundary] makes it one undoable change. */
    fun dragBoundary(k: Int, t: Double) {
        val lesson = _state.value.lesson ?: return
        if (dragStart == null) dragStart = lesson
        _state.update { it.copy(lesson = (dragStart ?: lesson).moveBoundary(k, t)) }
    }

    fun commitBoundary(k: Int, t: Double) {
        val start = dragStart ?: _state.value.lesson ?: return
        dragStart = null
        val moved = start.moveBoundary(k, t)
        if (moved.steps == start.steps) {
            _state.update { it.copy(lesson = start) }
            return
        }
        _state.update { it.copy(lesson = start) }
        apply(Change({ it.moveBoundary(k, t) }, retimes = true) { b, id ->
            b.editBoundaries(id, listOf(Triple(k + 1, null, moved.steps[k].end), Triple(k + 2, moved.steps[k + 1].start, null)))
        })
    }

    fun split(i: Int, at: Double) {
        val lesson = _state.value.lesson ?: return
        if (!lesson.canSplit(i, at)) return
        apply(Change({ it.split(i, at) }, retimes = true) { b, id -> b.editSplit(id, i + 1, formatTimestamp(at)) })
        _state.update { it.copy(selected = i + 1) }
    }

    fun merge(i: Int) = apply(Change({ it.merge(i) }, retimes = true) { b, id -> b.editMerge(id, i + 1) })

    fun delete(i: Int) {
        apply(Change({ it.deleteStep(i) }, retimes = true) { b, id -> b.editDelete(id, i + 1) })
        _state.update { it.copy(selected = (i - 1).coerceAtLeast(0)) }
    }

    fun rename(i: Int, title: String) {
        val t = title.trim()
        if (t.isEmpty() || t == _state.value.lesson?.steps?.getOrNull(i)?.title) return
        stepEdit(i, mapOf("title" to t)) { it.editStep(i, title = t) }
    }

    fun setCheckType(i: Int, type: CheckType) {
        if (_state.value.lesson?.steps?.getOrNull(i)?.checkType == type) return
        stepEdit(i, mapOf("check_type" to if (type == CheckType.Camera) "camera" else "manual")) { it.editStep(i, checkType = type) }
        _state.update { it.copy(selfTests = it.selfTests - i) }
    }

    fun setQuestion(i: Int, question: String) {
        val q = question.trim()
        if (q == _state.value.lesson?.steps?.getOrNull(i)?.checkQuestion) return
        stepEdit(i, mapOf("check_question" to q)) { it.editStep(i, question = q) }
        _state.update { it.copy(selfTests = it.selfTests - i) }
    }

    fun setMistake(i: Int, text: String) {
        val m = text.trim()
        if (m == _state.value.lesson?.steps?.getOrNull(i)?.commonMistake) return
        stepEdit(i, mapOf("common_mistake" to m)) { it.editStep(i, mistake = m) }
    }

    private fun stepEdit(i: Int, fields: Map<String, String>, local: (Lesson) -> Lesson) =
        apply(Change({ local(it) }, retimes = false) { b, id -> b.editStep(id, i + 1, fields) })

    /** Saves step [i]'s caption cues (hub editor routes only). */
    fun saveCaptions(i: Int, cues: List<Cue>) {
        if (!_state.value.features.captions) return
        val cleaned = cues.filter { it.text.isNotBlank() && it.end > it.start }.sortedBy { it.start }
        val before = _state.value.cues
        _state.update { it.copy(cues = it.cues.mapIndexed { k, l -> if (k == i) cleaned else l }) }
        apply(Change({ it }, retimes = false) { b, id -> b.editCaptions(id, i + 1, cleaned.map { c -> c.toEdit() }) }, onFailure = {
            _state.update { it.copy(cues = before) }
        })
    }

    private fun apply(change: Change, onFailure: () -> Unit = {}) {
        val before = _state.value.lesson ?: return
        val after = change.local(before) ?: return
        val server = _state.value.features.serverEdits
        if (!server) localHistory.push(before)
        _state.update {
            it.copy(
                lesson = after,
                selected = it.selected.coerceIn(0, (after.steps.size - 1).coerceAtLeast(0)),
                canUndo = if (server) true else localHistory.canUndo,
                canRedo = if (server) false else localHistory.canRedo,
                banner = null,
            )
        }
        if (!server) {
            scheduleLegacySave(change.retimes)
            return
        }
        viewModelScope.launch {
            queue.withLock {
                _state.update { it.copy(save = if (change.retimes) SaveState.UpdatingClips else SaveState.Saving) }
                try {
                    val result = change.send(backend, lessonId)
                    if (result == null) {
                        revert(onFailure, "This hub cannot make that change.")
                    } else {
                        accept(result)
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    revert(onFailure, e.plainWords())
                }
            }
        }
    }

    private suspend fun accept(result: EditResult) {
        synced = result.lesson
        _state.update {
            it.copy(
                lesson = result.lesson,
                save = SaveState.Saved,
                canUndo = result.history.undo > 0,
                canRedo = result.history.redo > 0,
                rev = if (result.recut) it.rev + 1 else it.rev,
                selected = it.selected.coerceIn(0, (result.lesson.steps.size - 1).coerceAtLeast(0)),
            )
        }
        if (result.recut || result.lesson.steps.size != _state.value.cues.size) loadCues(result.lesson)
    }

    private fun revert(onFailure: () -> Unit, message: String) {
        onFailure()
        _state.update { it.copy(lesson = synced ?: it.lesson, save = SaveState.Failed(message), banner = message) }
    }

    // ------------------------------------------------------------ undo and redo

    fun undo() = history(redo = false)
    fun redo() = history(redo = true)

    private fun history(redo: Boolean) {
        val s = _state.value
        val current = s.lesson ?: return
        if (!s.features.serverEdits) {
            val target = (if (redo) localHistory.redo(current) else localHistory.undo(current)) ?: return
            _state.update { it.copy(lesson = target, canUndo = localHistory.canUndo, canRedo = localHistory.canRedo, selected = it.selected.coerceIn(0, (target.steps.size - 1).coerceAtLeast(0))) }
            scheduleLegacySave(retimes = target.steps.map { it.start to it.end } != current.steps.map { it.start to it.end })
            return
        }
        viewModelScope.launch {
            queue.withLock {
                _state.update { it.copy(save = SaveState.UpdatingClips) }
                try {
                    val result = if (redo) backend.redo(lessonId) else backend.undo(lessonId)
                    if (result == null) revert({}, "This hub cannot undo.") else accept(result)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    revert({}, e.plainWords())
                }
            }
        }
    }

    // ------------------------------------------------------------ legacy save

    private fun scheduleLegacySave(retimes: Boolean) {
        saveJob?.cancel()
        _state.update { it.copy(save = SaveState.Saving) }
        saveJob = viewModelScope.launch {
            delay(LEGACY_SAVE_DELAY_MS)
            saveLegacy(retimes)
        }
    }

    /** Try Again after "Could not save". */
    fun retrySave() {
        if (_state.value.features.serverEdits) load() else scheduleLegacySave(true)
    }

    private suspend fun saveLegacy(retimes: Boolean) {
        val lesson = _state.value.lesson ?: return
        queue.withLock {
            _state.update { it.copy(save = if (retimes) SaveState.UpdatingClips else SaveState.Saving) }
            try {
                val saved = backend.recut(lessonId, mergeUnknown(raw, lesson))
                synced = saved
                _state.update { it.copy(save = SaveState.Saved, rev = it.rev + 1) }
                loadCues(saved)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val message = e.plainWords()
                _state.update { it.copy(save = SaveState.Failed(message), banner = message) }
            }
        }
    }

    // ------------------------------------------------------------ test question, voiceover, publish

    /** "Test This Question": the hub's self-test for one camera step. */
    fun testQuestion(i: Int) {
        if (!_state.value.features.selfTest) return
        _state.update { it.copy(selfTests = it.selfTests + (i to SelfTestUi(running = true))) }
        viewModelScope.launch {
            queue.withLock {
                try {
                    val response = backend.selfTest(lessonId, i + 1)
                    if (response == null) {
                        _state.update { it.copy(selfTests = it.selfTests - i, features = it.features.copy(selfTest = false)) }
                        return@withLock
                    }
                    val row = response.results.firstOrNull { it.n == i + 1 }?.selfTest
                    synced = response.lesson
                    _state.update {
                        it.copy(
                            lesson = response.lesson,
                            canUndo = response.history.undo > 0,
                            canRedo = response.history.redo > 0,
                            selfTests = it.selfTests + (i to SelfTestUi(result = row, error = if (row == null) "The test could not run on this step." else null)),
                        )
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    _state.update { it.copy(selfTests = it.selfTests + (i to SelfTestUi(error = e.plainWords()))) }
                }
            }
        }
    }

    /** Regenerates step [i]'s voiceover and follows the job until it ends. */
    fun regenerateVoiceover(i: Int) {
        if (!_state.value.features.voiceover) return
        _state.update { it.copy(voice = it.voice + (i to VoiceUi(running = true, message = "Writing voiceover"))) }
        viewModelScope.launch {
            try {
                val job = queue.withLock { backend.voiceover(lessonId, listOf(i + 1)) }
                if (job == null) {
                    _state.update { it.copy(voice = it.voice - i, features = it.features.copy(voiceover = false)) }
                    return@launch
                }
                var status: com.handover.app.ui.library.CourseJob = job
                while (!status.finished) {
                    delay(VOICE_POLL_MS)
                    status = backend.courseJob(lessonId, job.job) ?: break
                }
                val failed = status.status == "error"
                _state.update {
                    it.copy(
                        voice = it.voice + (i to VoiceUi(message = if (failed) status.message else "Voiceover added", failed = failed)),
                        rev = if (failed) it.rev else it.rev + 1,
                    )
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(voice = it.voice + (i to VoiceUi(message = e.plainWords(), failed = true))) }
            }
        }
    }

    /**
     * Publish (SCREENS.md 15.2). [audience] is only_me, shared, everyone, or an org id with [toOrg]. Unlisted
     * keeps the course out of Library. Calls back with null on success or the hub's words on failure.
     */
    fun publish(audience: String, toOrg: Boolean, unlisted: Boolean, done: (String?) -> Unit) {
        viewModelScope.launch {
            try {
                val info = queue.withLock {
                    val status = if (unlisted) "unlisted" else "published"
                    // One call: POST /publish takes the visibility and org with it (server/docs/library.md).
                    if (toOrg) backend.publish(lessonId, status, visibility = "org", org = audience)
                    else backend.publish(lessonId, status, visibility = audience)
                }
                if (info == null) done("This hub cannot publish lessons.")
                else {
                    _state.update { it.copy(course = info) }
                    done(null)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                done(e.plainWords())
            }
        }
    }

    companion object {
        const val LEGACY_SAVE_DELAY_MS = 1_000L
        const val VOICE_POLL_MS = 1_500L
    }
}

/**
 * The lesson to send with a legacy recut: the edited lesson, plus every field the hub sent that the app's
 * model does not know (so a recut never drops them). Step fields carry over by position only while the step
 * count is unchanged; after a split, merge or delete the hub rebuilds them anyway.
 */
fun mergeUnknown(raw: JsonObject?, lesson: Lesson): JsonObject {
    val edited = HubJson.encodeToJsonElement(Lesson.serializer(), lesson) as JsonObject
    if (raw == null) return edited
    val rawSteps = raw["steps"] as? JsonArray
    val editedSteps = edited["steps"] as? JsonArray ?: JsonArray(emptyList())
    val steps = buildJsonArray {
        editedSteps.forEachIndexed { i, step ->
            val mine = step as? JsonObject ?: return@forEachIndexed
            val theirs = rawSteps?.takeIf { it.size == editedSteps.size }?.getOrNull(i) as? JsonObject
            add(if (theirs == null) mine else JsonObject(theirs.filterKeys { it !in mine && it !in DROP_ON_EDIT } + mine))
        }
    }
    return buildJsonObject {
        raw.forEach { (k, v) -> if (k !in edited && k != "steps") put(k, v) }
        edited.forEach { (k, v) -> if (k != "steps") put(k, v) }
        put("steps", steps)
    }
}

/** Fields the app clears on purpose (null in the model, so absent from the edited JSON); never restore them. */
private val DROP_ON_EDIT = setOf("ref_time", "self_test", "clip", "captions", "ref_frame")

/** The summary under a self-test (SCREENS.md 14.3). */
fun SelfTest.works(): Boolean = own == Answer.Yes && prev == Answer.No
