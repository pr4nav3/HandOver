package com.handover.app.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import kotlin.random.Random

/** Where a socket is in its life. */
enum class SocketPhase {
    /** Not started, or stopped by the app. */
    Idle,
    Connecting,
    Open,

    /** Lost; waiting [SocketStatus.retryInMs] before the next try. */
    Waiting,

    /** Closed with 4000: a newer connection from this device took over. Never reconnects on its own. */
    Replaced,
}

data class SocketStatus(
    val phase: SocketPhase = SocketPhase.Idle,
    /** Failed tries since the last open. */
    val attempt: Int = 0,
    val retryInMs: Long = 0,
    /** Why the last connection ended, in plain words, or null. */
    val lastError: String? = null,
)

/** Close codes the hub uses (CONTRACT.md section 6, contract-proposals P15). */
object CloseCodes {
    const val NORMAL = 1000
    const val STALLED = 1011
    const val TRY_LATER = 1013
    const val REPLACED = 4000
}

/**
 * When to try again. Doubling from [baseMs] up to [maxMs], each delay shrunk by up to [jitter] so
 * phones that lost the hub together do not all come back in the same instant.
 */
class Backoff(
    private val baseMs: Long = 500,
    private val maxMs: Long = 10_000,
    private val jitter: Double = 0.2,
    private val random: Random = Random.Default,
) {
    /**
     * The wait before try number [attempt] (0 = the first retry), or null to stop. 4000 stops; 1011
     * (the hub gave up on a slow send) retries at once the first time, since the hub is fine.
     */
    fun delayFor(attempt: Int, closeCode: Int?): Long? {
        if (closeCode == CloseCodes.REPLACED) return null
        if (closeCode == CloseCodes.STALLED && attempt == 0) return 0
        val raw = (baseMs shl attempt.coerceIn(0, 20)).coerceAtMost(maxMs)
        return (raw * (1 - jitter * random.nextDouble())).toLong()
    }
}

/**
 * One WebSocket to the hub that keeps itself connected: it reconnects with [Backoff] after any loss
 * except close 4000. Callbacks from OkHttp's threads are matched to the socket that raised them, so a
 * late callback from an old socket never touches the new one.
 */
abstract class HubSocket(
    private val url: String,
    private val http: OkHttpClient,
    private val scope: CoroutineScope,
    private val backoff: Backoff = Backoff(),
) {
    private val lock = Any()
    private var socket: WebSocket? = null
    private var running = false
    private var attempt = 0
    private var retry: Job? = null

    private val _status = MutableStateFlow(SocketStatus())
    val status: StateFlow<SocketStatus> = _status.asStateFlow()

    private val _messages = MutableSharedFlow<HubMessage>(extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)

    /** Every text message the hub sends, routed. Unknown types arrive as [HubMessage.Unknown]. */
    val messages: SharedFlow<HubMessage> = _messages.asSharedFlow()

    private val _state = MutableStateFlow<HubState?>(null)

    /** The newest `state`, or null before the first one on this connection. */
    val state: StateFlow<HubState?> = _state.asStateFlow()

    fun start() = synchronized(lock) {
        if (running) return
        running = true
        attempt = 0
        open()
    }

    fun stop() = synchronized(lock) {
        running = false
        retry?.cancel()
        retry = null
        val wasOpen = socket != null
        socket?.close(CloseCodes.NORMAL, null)
        socket = null
        _state.value = null
        _status.value = SocketStatus()
        if (wasOpen) onEnded()
    }

    /** Sends text on the open socket; false when there is none. */
    protected fun sendText(text: String): Boolean = synchronized(lock) { socket?.takeIf { isOpen() }?.send(text) ?: false }

    protected fun currentSocket(): WebSocket? = synchronized(lock) { socket?.takeIf { isOpen() } }

    private fun isOpen() = _status.value.phase == SocketPhase.Open

    /** Called on OkHttp's thread when a socket opens, before any message. */
    protected open fun onOpened(ws: WebSocket) {}

    /** Called for each routed text message, after [state] is updated. */
    protected open fun onMessage(message: HubMessage) {}

    /** Called for each binary message. */
    protected open fun onBinary(bytes: ByteArray) {}

    /** Called when a socket ends for any reason. */
    protected open fun onEnded() {}

    private fun open() {
        _status.value = _status.value.copy(phase = SocketPhase.Connecting, retryInMs = 0)
        val request = Request.Builder().url(url).build()
        socket = http.newWebSocket(request, Listener())
    }

    private fun ended(ws: WebSocket, code: Int?, why: String) {
        synchronized(lock) {
            if (ws !== socket) return
            socket = null
            _state.value = null
            onEnded()
            if (!running) return
            val wait = backoff.delayFor(attempt, code)
            if (wait == null) {
                running = false
                _status.value = SocketStatus(SocketPhase.Replaced, attempt, 0, why)
                return
            }
            attempt++
            _status.value = SocketStatus(SocketPhase.Waiting, attempt, wait, why)
            retry = scope.launch {
                delay(wait)
                synchronized(lock) { if (running && socket == null) open() }
            }
        }
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            synchronized(lock) {
                if (webSocket !== socket) return
                attempt = 0
                _status.value = SocketStatus(SocketPhase.Open)
                onOpened(webSocket)
            }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (webSocket !== synchronized(lock) { socket }) return
            val message = HubMessages.parse(text) ?: return
            if (message is HubMessage.State) _state.value = message.state
            onMessage(message)
            _messages.tryEmit(message)
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (webSocket !== synchronized(lock) { socket }) return
            onBinary(bytes.toByteArray())
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(CloseCodes.NORMAL, null)
            ended(webSocket, code, closeText(code, reason))
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = ended(webSocket, code, closeText(code, reason))

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) =
            ended(webSocket, null, t.message ?: t.javaClass.simpleName)
    }

    private fun closeText(code: Int, reason: String): String = when (code) {
        CloseCodes.REPLACED -> "Another connection from this phone took over"
        CloseCodes.STALLED -> "The hub dropped a slow connection"
        CloseCodes.TRY_LATER -> reason.ifEmpty { "The hub is full" }
        else -> reason.ifEmpty { "Closed ($code)" }
    }
}
