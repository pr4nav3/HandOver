package com.handover.app.core

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient

/**
 * The viewer socket, `/ws/ui` (CONTRACT.md section 7): the learn screen's view of the session.
 * Receives `state`, `advance`, `mistake` and `error`, plus the live camera picture as JPEG frames.
 * Sends select, next, back, goto and dismiss. Next and back always carry `from` (see [Nav]).
 */
class UiSocket(
    hub: HubUrl,
    http: OkHttpClient,
    scope: CoroutineScope,
    backoff: Backoff = Backoff(),
    /** False asks for `/ws/ui?frames=0`: no live pictures, for a phone that is itself the camera. */
    frames: Boolean = true,
    /** JPEG bytes to a Bitmap. Replaceable so JVM tests can run without Android's decoder. */
    private val decodeFrame: (ByteArray) -> Bitmap? = { BitmapFactory.decodeByteArray(it, 0, it.size) },
) : HubSocket(hub.uiSocket(frames), http, scope, backoff) {

    private val _frame = MutableStateFlow<Bitmap?>(null)

    /** The newest live picture from the active camera, or null before the first one on this connection. */
    val frame: StateFlow<Bitmap?> = _frame.asStateFlow()

    override fun onBinary(bytes: ByteArray) {
        decodeFrame(bytes)?.let { _frame.value = it }
    }

    override fun onEnded() {
        _frame.value = null
    }

    /** Selects [id]. [token] (the sign-in token) tags the run with the learner; null leaves it anonymous. */
    fun selectLesson(id: String, token: String? = null): Boolean =
        send(SelectLessonCommand(id, token?.takeIf { it.isNotBlank() }), SelectLessonCommand.serializer())

    /** Next from the position [shown] (the newest state by default). False when nothing was sent. */
    fun next(shown: HubState? = state.value, reason: String = "button"): Boolean =
        Nav.next(shown, reason)?.let { send(it, NextCommand.serializer()) } ?: false

    /** Back from the position [shown] (the newest state by default). False when nothing was sent. */
    fun back(shown: HubState? = state.value): Boolean =
        Nav.back(shown)?.let { send(it, BackCommand.serializer()) } ?: false

    fun goto(step: Int, shown: HubState? = state.value): Boolean =
        Nav.goto(shown, step)?.let { send(it, GotoCommand.serializer()) } ?: false

    fun dismissMistake(): Boolean = send(DismissMistakeCommand(), DismissMistakeCommand.serializer())

    /** Stops the run and unloads the lesson on the hub, for every screen. */
    fun endLesson(): Boolean = send(EndLessonCommand(), EndLessonCommand.serializer())

    private fun <T> send(command: T, serializer: kotlinx.serialization.KSerializer<T>): Boolean =
        sendText(HubJson.encodeToString(serializer, command))
}
