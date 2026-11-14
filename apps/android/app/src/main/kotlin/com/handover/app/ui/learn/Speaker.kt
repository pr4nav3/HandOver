package com.handover.app.ui.learn

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.core.content.edit
import java.util.Locale

/** Spoken guidance settings. Unset "on" means: on when a Bluetooth audio device is connected. */
class SpeechPrefs(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("handover", Context.MODE_PRIVATE)

    /** The person's choice, or null when they never chose (then it follows the Bluetooth route). */
    var spokenGuidance: Boolean?
        get() = if (prefs.contains(KEY_ON)) prefs.getBoolean(KEY_ON, true) else null
        set(value) = prefs.edit { if (value == null) remove(KEY_ON) else putBoolean(KEY_ON, value) }

    var verbosity: Verbosity
        get() = Verbosity.from(prefs.getString(KEY_VERBOSITY, null))
        set(value) = prefs.edit { putString(KEY_VERBOSITY, value.id) }

    companion object {
        const val KEY_ON = "spoken_guidance"
        const val KEY_VERBOSITY = "spoken_verbosity"

        /** On by default only with Bluetooth audio connected (glasses or headphones). */
        fun effective(choice: Boolean?, bluetooth: Boolean): Boolean = choice ?: bluetooth
    }
}

/** The audio output: the Bluetooth device's name when audio goes to Bluetooth (A2DP, headset or LE), else null. */
object AudioRoute {
    private val bluetoothTypes = buildSet {
        add(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)
        add(AudioDeviceInfo.TYPE_BLUETOOTH_SCO)
        if (android.os.Build.VERSION.SDK_INT >= 31) { add(AudioDeviceInfo.TYPE_BLE_HEADSET); add(AudioDeviceInfo.TYPE_BLE_SPEAKER) }
    }

    fun isBluetooth(type: Int): Boolean = type in bluetoothTypes

    fun bluetoothName(audio: AudioManager): String? =
        audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).firstOrNull { isBluetooth(it.type) }?.let { it.productName?.toString()?.ifBlank { null } ?: "Bluetooth" }
}

/**
 * Speaks Learn's lines through TextToSpeech on whatever route is active (the glasses, when they
 * are the Bluetooth headphones). Lines go through [SpeechQueue], so they never overlap or repeat
 * within 3 s. While speaking it holds transient audio focus with ducking (other apps duck) and
 * reports [speaking] so the clip ducks too.
 */
class Speaker(context: Context) {
    private val app = context.applicationContext
    private val audio = app.getSystemService(AudioManager::class.java)
    private val main = Handler(Looper.getMainLooper())
    private val queue = SpeechQueue(System::currentTimeMillis)
    private var ready = false
    private val attributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()
    private val focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        .setAudioAttributes(attributes).setWillPauseWhenDucked(false).build()

    var speaking by mutableStateOf(false)
        private set
    var bluetoothName by mutableStateOf(audio?.let(AudioRoute::bluetoothName))
        private set

    private val tts: TextToSpeech = TextToSpeech(app) { status ->
        main.post {
            ready = status == TextToSpeech.SUCCESS
            if (ready) setup()
            pump()
        }
    }

    private val routes = object : AudioDeviceCallback() {
        override fun onAudioDevicesAdded(added: Array<out AudioDeviceInfo>) { bluetoothName = audio?.let(AudioRoute::bluetoothName) }
        override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) { bluetoothName = audio?.let(AudioRoute::bluetoothName) }
    }

    init {
        audio?.registerAudioDeviceCallback(routes, main)
    }

    private fun setup() {
        tts.setAudioAttributes(attributes)
        bestVoice(tts.voices.orEmpty())?.let { tts.voice = it } ?: tts.setLanguage(Locale.US)
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String) {}
            override fun onDone(utteranceId: String) { main.post { finished(utteranceId) } }
            @Deprecated("Deprecated in Java", ReplaceWith("onError(utteranceId, errorCode)"))
            @Suppress("OVERRIDE_DEPRECATION")
            override fun onError(utteranceId: String) { main.post { finished(utteranceId) } }
            override fun onError(utteranceId: String, errorCode: Int) { main.post { finished(utteranceId) } }
        })
    }

    fun say(text: String, kind: SpeechKind) {
        if (queue.offer(text, kind)) pump()
    }

    fun stop() {
        queue.clear()
        if (ready) tts.stop()
        release()
    }

    fun shutdown() {
        stop()
        audio?.unregisterAudioDeviceCallback(routes)
        tts.shutdown()
    }

    private fun pump() {
        if (!ready) return
        val u = queue.next() ?: return
        if (!speaking) {
            audio?.requestAudioFocus(focus)
            speaking = true
        }
        val params = Bundle()
        if (tts.speak(u.text, TextToSpeech.QUEUE_ADD, params, u.id.toString()) != TextToSpeech.SUCCESS) finished(u.id.toString())
    }

    private fun finished(id: String) {
        id.toLongOrNull()?.let(queue::done)
        if (queue.current == null && queue.pending.isEmpty()) release() else pump()
    }

    private fun release() {
        if (speaking) {
            audio?.abandonAudioFocusRequest(focus)
            speaking = false
        }
    }

    companion object {
        /**
         * The best installed en-US voice: on device (no network), then highest quality, then lowest
         * latency. Null when none is en-US.
         */
        fun bestVoice(voices: Collection<Voice>): Voice? = voices
            .filter { it.locale.language == "en" && it.locale.country == "US" && !it.features.orEmpty().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) }
            .sortedWith(compareBy<Voice> { it.isNetworkConnectionRequired }.thenByDescending { it.quality }.thenBy { it.latency })
            .firstOrNull()
    }
}

/** A speaker for the composition, shut down when it leaves. Null in previews. */
@Composable
fun rememberSpeaker(): Speaker? {
    if (LocalInspectionMode.current) return null
    val context = LocalContext.current
    val speaker = remember { runCatching { Speaker(context) }.getOrNull() }
    DisposableEffect(speaker) { onDispose { speaker?.shutdown() } }
    return speaker
}
