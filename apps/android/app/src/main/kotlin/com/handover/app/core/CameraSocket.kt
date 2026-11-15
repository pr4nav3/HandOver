package com.handover.app.core

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import okhttp3.OkHttpClient
import okhttp3.WebSocket
import okio.ByteString.Companion.toByteString

/**
 * The camera socket, `/ws/camera` (CONTRACT.md section 6): this phone as the hub's camera.
 * Sends `hello` first on every connection, then JPEG frames, and next or back with `from`.
 * Receives `camera_status`, and after hello the same `state`, `advance`, `mistake` and `error`
 * the viewers get, so the camera screen can show the step.
 *
 * Frames are sent only when the previous one has left the phone (send when idle), so a slow
 * network drops frames instead of building a queue of stale pictures.
 *
 * `platform` is left out of hello: the hub accepts only ios, web and replay there and ignores the
 * whole hello for any other value, so an Android hello would be lost. Left out, the hub shows
 * "other". Add "android" here once the hub lists it.
 */
class CameraSocket(
    hub: HubUrl,
    http: OkHttpClient,
    scope: CoroutineScope,
    private val deviceId: String,
    name: String,
    source: String = "phone",
    backoff: Backoff = Backoff(),
    /** Just under the 15 a second the senders aim for, so camera jitter never drops a due frame. */
    private val minFrameGapMs: Long = 50,
    private val clock: () -> Long = System::currentTimeMillis,
) : HubSocket(hub.cameraSocket, http, scope, backoff) {

    @Volatile private var name = name
    @Volatile private var source = source
    @Volatile private var lastFrameAt = Long.MIN_VALUE / 2

    private val _active = MutableStateFlow(false)

    /** True while the hub judges this camera's frames (`camera_status`). */
    val active: StateFlow<Boolean> = _active.asStateFlow()

    private val _framesSent = MutableStateFlow(0)
    val framesSent: StateFlow<Int> = _framesSent.asStateFlow()

    override fun onOpened(ws: WebSocket) {
        ws.send(helloText())
    }

    override fun onMessage(message: HubMessage) {
        if (message is HubMessage.CameraStatus) _active.value = message.active
    }

    override fun onEnded() {
        _active.value = false
    }

    /** Changes the name or source and says hello again when connected (hello may repeat). */
    fun identify(name: String = this.name, source: String = this.source) {
        if (name == this.name && source == this.source) return
        this.name = name
        this.source = source
        sendText(helloText())
    }

    /** True when a frame could not go out now: not open, or the last frame is still leaving the phone. */
    fun isBusy(): Boolean {
        val ws = currentSocket() ?: return true
        return ws.queueSize() > 0 || clock() - lastFrameAt < minFrameGapMs
    }

    /**
     * Sends one JPEG if the socket is idle. Returns false, without sending, when the socket is not
     * open, the previous frame is still leaving the phone, the last frame went out under
     * [minFrameGapMs] ago, or the bytes are not a JPEG under 2 MB (the hub ignores those).
     */
    fun sendFrame(jpeg: ByteArray): Boolean {
        if (!isUsableJpeg(jpeg)) return false
        val ws = currentSocket() ?: return false
        val now = clock()
        if (ws.queueSize() > 0 || now - lastFrameAt < minFrameGapMs) return false
        if (!ws.send(jpeg.toByteString())) return false
        lastFrameAt = now
        _framesSent.update { it + 1 }
        return true
    }

    fun next(shown: HubState? = state.value): Boolean =
        Nav.next(shown)?.let { sendText(HubJson.encodeToString(NextCommand.serializer(), it)) } ?: false

    fun back(shown: HubState? = state.value): Boolean =
        Nav.back(shown)?.let { sendText(HubJson.encodeToString(BackCommand.serializer(), it)) } ?: false

    private fun helloText(): String = HubJson.encodeToString(Hello.serializer(), Hello(deviceId = deviceId, name = name, source = source))

    companion object {
        const val MAX_FRAME_BYTES = 2 * 1024 * 1024

        fun isUsableJpeg(bytes: ByteArray): Boolean =
            bytes.size in 3..MAX_FRAME_BYTES && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte()
    }
}
