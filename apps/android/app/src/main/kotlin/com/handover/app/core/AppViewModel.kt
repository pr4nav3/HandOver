package com.handover.app.core

import android.graphics.Bitmap
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider.AndroidViewModelFactory.Companion.APPLICATION_KEY
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.io.IOException

/**
 * The app's one source of truth. Holds [AppState] in a StateFlow, keeps the viewer socket to the
 * hub, refetches the lesson when the session's lesson or rev changes, and runs uploads. Screens read
 * [state] and call the methods here; none of them talk to the hub directly.
 */
class AppViewModel(
    private val prefs: HubPrefs,
    private val http: OkHttpClient = defaultHttpClient(),
) : ViewModel() {

    private val _state = MutableStateFlow(AppState())
    val state: StateFlow<AppState> = _state.asStateFlow()

    private val _frame = MutableStateFlow<Bitmap?>(null)

    /** The newest live picture from the hub's active camera. */
    val frame: StateFlow<Bitmap?> = _frame.asStateFlow()

    private val _events = MutableSharedFlow<HubMessage>(extraBufferCapacity = 16, onBufferOverflow = BufferOverflow.DROP_OLDEST)

    /** One-shot moments for sound and haptics: `advance` (chime when reason is camera), `mistake`, `error`. */
    val events: SharedFlow<HubMessage> = _events.asSharedFlow()

    private var client: HubClient? = null
    private var ui: UiSocket? = null
    private var connection: Job? = null
    private var lessonFetch: Job? = null
    private var uploadJob: Job? = null
    private var camera: CameraSocket? = null

    /** True while this phone sends its own camera to the hub; the viewer socket then skips live frames. */
    private var phoneIsCamera = false

    init {
        HubUrl.parse(prefs.hubAddress)?.let { connect(it) }
    }

    /** Connects to the hub in [raw] (typed, scanned or a deep link). False, with an error shown, when it is not an address. */
    fun connect(raw: String): Boolean {
        val hub = HubUrl.parse(raw)
        if (hub == null) {
            _state.update { it.copy(error = "That is not a hub address. Try something like 192.168.1.20:8000.") }
            return false
        }
        connect(hub)
        return true
    }

    private fun connect(hub: HubUrl) {
        disconnect()
        prefs.hubAddress = hub.display
        client = HubClient(hub, http)
        _state.value = AppState(hub = hub, upload = _state.value.upload)
        openUi(hub)
        refreshLessons()
    }

    /**
     * Opens the viewer socket. While this phone is the hub's camera it asks for `/ws/ui?frames=0`
     * (contract-proposals P27): every text message, none of the live pictures it is itself sending.
     * A hub that does not know the query ignores it and sends frames as before.
     */
    private fun openUi(hub: HubUrl) {
        val socket = UiSocket(hub, http, viewModelScope, frames = !phoneIsCamera)
        ui = socket
        connection = viewModelScope.launch {
            launch {
                socket.status.collect { s ->
                    // A lost connection drops the session; while connecting the last one stays on screen.
                    val lost = s.phase == SocketPhase.Waiting || s.phase == SocketPhase.Replaced
                    _state.update { it.copy(connection = s, session = if (lost) null else it.session) }
                }
            }
            launch { socket.frame.collect { _frame.value = it } }
            launch {
                // Everything except state, which comes from socket.state below.
                socket.messages.collect { message ->
                    if (message is HubMessage.State || message is HubMessage.Unknown) return@collect
                    _state.update { it.reduce(message) }
                    _events.tryEmit(message)
                }
            }
            launch {
                // The newest state only (the hub may skip states too, P17). A dropped connection clears the
                // session; the first state after reconnecting is a full one.
                // The new socket's empty start is skipped, so a reopen (frames on or off) keeps the session until
                // the hub resends it.
                var started = false
                socket.state.collect { s ->
                    if (!started && s == null) {
                        started = true
                        return@collect
                    }
                    started = true
                    _state.update { if (s == null) it.copy(session = null) else it.reduce(HubMessage.State(s)) }
                    if (s != null) fetchLessonIfNeeded()
                }
            }
        }
        socket.start()
    }

    private fun closeUi() {
        connection?.cancel()
        connection = null
        ui?.stop()
        ui = null
        _frame.value = null
    }

    fun disconnect() {
        lessonFetch?.cancel()
        closeUi()
        camera?.stop()
        camera = null
        phoneIsCamera = false
        client = null
        _state.update { AppState(hub = it.hub, upload = it.upload) }
    }

    /** Tries again now after a 4000 or a long wait. */
    fun reconnect() {
        _state.value.hub?.let { connect(it) }
    }

    fun refreshLessons() {
        val c = client ?: return
        viewModelScope.launch {
            _state.update { it.copy(lessonsLoading = true) }
            val result = runHub { c.lessons() }
            _state.update { s -> result.fold({ s.copy(lessons = it, lessonsLoading = false) }, { s.copy(lessonsLoading = false, error = it) }) }
        }
    }

    /** Chooses the lesson on the hub. Signed in, the sign-in token goes along so the hub tags the run with this learner. */
    fun selectLesson(id: String) {
        if (ui?.selectLesson(id, AccountSession.token(_state.value.hub)) != true) notConnected()
        else _state.update { it.copy(ended = null) }
    }

    /** Back into the hub's current lesson after End on this phone (Start or Continue on the same lesson). */
    fun resumeLesson() = _state.update { it.copy(ended = null) }

    /**
     * End on Learn: stops this phone's camera, tells the hub (end_lesson stops the run and unloads
     * the lesson for every screen), and marks the run as ended here, so Learn shows "No lesson running".
     */
    fun endLesson() {
        stopCamera()
        ui?.endLesson()
        _state.update { s ->
            val id = s.session?.lessonId ?: return@update s
            s.copy(ended = EndedRun(id, s.session.runId))
        }
    }

    /** Next from the step on screen. Nothing is sent on the done screen or with no lesson. */
    fun next(reason: String = "button") {
        ui?.next(_state.value.session, reason)
    }

    fun back() {
        ui?.back(_state.value.session)
    }

    fun goto(step: Int) {
        ui?.goto(step, _state.value.session)
    }

    fun dismissMistake() {
        ui?.dismissMistake()
    }

    fun clearError() = _state.update { it.copy(error = null) }

    /** A lesson file URL with the cache-busting rev, or null when not connected. */
    fun lessonFile(path: String): String? {
        val s = _state.value
        val id = s.session?.lessonId ?: return null
        return client?.lessonFile(id, path, s.session.rev)?.toString()
    }

    /**
     * Uploads a video as a new lesson and follows its job until done or error. Signed in, it becomes a
     * course owned by this person (in [orgId] when given); see [HubClient.upload].
     */
    fun upload(video: UploadSource, title: String, id: String? = null, orgId: String? = null) {
        val c = client ?: return notConnected()
        uploadJob?.cancel()
        _state.update { it.copy(upload = UploadState(title = title, total = video.length)) }
        uploadJob = viewModelScope.launch {
            val accepted = runHub {
                c.upload(video, title, id, orgId) { sent, total -> _state.update { s -> s.copy(upload = s.upload?.copy(sent = sent, total = total)) } }
            }
            val response = accepted.getOrElse { e ->
                _state.update { s -> s.copy(upload = s.upload?.copy(error = e)) }
                return@launch
            }
            _state.update { s -> s.copy(upload = s.upload?.copy(lessonId = response.id)) }
            val polled = runHub {
                c.pollJob(response.job).collect { job ->
                    _state.update { s -> s.copy(upload = s.upload?.copy(job = job, error = if (job.status == JobPhase.Error) job.message else null)) }
                }
            }
            polled.onFailure { e -> _state.update { s -> s.copy(upload = s.upload?.copy(error = e)) } }
            refreshLessons()
        }
    }

    fun clearUpload() {
        uploadJob?.cancel()
        _state.update { it.copy(upload = null) }
    }

    /** Opens this phone's camera socket to the hub, for the Camera screen. The same socket is returned while open. */
    fun startCamera(name: String = defaultCameraName()): CameraSocket? {
        camera?.let { return it }
        val hub = _state.value.hub ?: return null
        return CameraSocket(hub, http, viewModelScope, prefs.deviceId, name).also {
            camera = it
            it.start()
            setPhoneIsCamera(true)
        }
    }

    fun stopCamera() {
        camera?.stop()
        camera = null
        setPhoneIsCamera(false)
    }

    /** Reopens the viewer socket with or without live frames. The session stays on screen; the hub resends state on connect. */
    private fun setPhoneIsCamera(on: Boolean) {
        if (phoneIsCamera == on) return
        phoneIsCamera = on
        val hub = _state.value.hub ?: return
        if (ui == null) return
        closeUi()
        openUi(hub)
    }

    override fun onCleared() {
        disconnect()
    }

    private fun fetchLessonIfNeeded() {
        val (id, rev) = _state.value.lessonToFetch ?: return
        val c = client ?: return
        if (lessonFetch?.isActive == true) return
        lessonFetch = viewModelScope.launch {
            runHub { c.lesson(id) }.fold(
                { lesson -> _state.update { it.withLesson(lesson, rev) } },
                { e -> _state.update { it.copy(error = e) } },
            )
            // The session may have moved on while this fetch ran.
            if (_state.value.lessonToFetch != null && _state.value.lessonToFetch != id to rev) fetchLessonIfNeeded()
        }
    }

    private fun notConnected() = _state.update { it.copy(error = "Not connected to the hub.") }

    /** Runs a hub call; failures come back as plain words. Cancellation still cancels. */
    private suspend fun <T> runHub(block: suspend () -> T): Outcome<T> = try {
        Outcome.Ok(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: HubException) {
        Outcome.Failed(e.detail)
    } catch (e: IOException) {
        Outcome.Failed("Could not reach the hub: ${e.message ?: "network error"}")
    }

    private sealed interface Outcome<out T> {
        data class Ok<T>(val value: T) : Outcome<T>
        data class Failed(val message: String) : Outcome<Nothing>
    }

    private inline fun <T, R> Outcome<T>.fold(ok: (T) -> R, failed: (String) -> R): R = when (this) {
        is Outcome.Ok -> ok(value)
        is Outcome.Failed -> failed(message)
    }

    private inline fun <T> Outcome<T>.getOrElse(failed: (String) -> T): T = when (this) {
        is Outcome.Ok -> value
        is Outcome.Failed -> failed(message)
    }

    private inline fun <T> Outcome<T>.onFailure(failed: (String) -> Unit) {
        if (this is Outcome.Failed) failed(message)
    }

    companion object {
        /** The app's one client ([HubClient.sharedHttp]). */
        fun defaultHttpClient(): OkHttpClient = HubClient.sharedHttp

        fun defaultCameraName(): String = "${Build.MODEL ?: "Android"} camera".trim()

        val Factory = viewModelFactory {
            initializer { AppViewModel(SharedHubPrefs(this[APPLICATION_KEY]!!)) }
        }
    }
}
