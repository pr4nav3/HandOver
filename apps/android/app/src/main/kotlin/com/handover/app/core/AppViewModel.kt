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
import java.util.concurrent.TimeUnit

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
        val socket = UiSocket(hub, http, viewModelScope)
        client = HubClient(hub, http)
        ui = socket
        _state.value = AppState(hub = hub, upload = _state.value.upload)
        connection = viewModelScope.launch {
            launch { socket.status.collect { s -> _state.update { it.copy(connection = s) } } }
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
                socket.state.collect { s ->
                    _state.update { if (s == null) it.copy(session = null) else it.reduce(HubMessage.State(s)) }
                    if (s != null) fetchLessonIfNeeded()
                }
            }
        }
        socket.start()
        refreshLessons()
    }

    fun disconnect() {
        connection?.cancel()
        lessonFetch?.cancel()
        ui?.stop()
        stopCamera()
        ui = null
        client = null
        _frame.value = null
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

    fun selectLesson(id: String) {
        if (ui?.selectLesson(id) != true) notConnected()
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

    /** Uploads a video as a new lesson and follows its job until done or error. */
    fun upload(video: UploadSource, title: String, id: String? = null) {
        val c = client ?: return notConnected()
        uploadJob?.cancel()
        _state.update { it.copy(upload = UploadState(title = title, total = video.length)) }
        uploadJob = viewModelScope.launch {
            val accepted = runHub {
                c.upload(video, title, id) { sent, total -> _state.update { s -> s.copy(upload = s.upload?.copy(sent = sent, total = total)) } }
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
        }
    }

    fun stopCamera() {
        camera?.stop()
        camera = null
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
        fun defaultHttpClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            // The hub pings every 10 s; this side pings too, so a hub that vanished is noticed.
            .pingInterval(15, TimeUnit.SECONDS)
            .build()

        fun defaultCameraName(): String = "${Build.MODEL ?: "Android"} camera".trim()

        val Factory = viewModelFactory {
            initializer { AppViewModel(SharedHubPrefs(this[APPLICATION_KEY]!!)) }
        }
    }
}
