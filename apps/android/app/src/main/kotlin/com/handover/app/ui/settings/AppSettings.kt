package com.handover.app.ui.settings

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Caption Size (DESIGN.md 2.2): a scale on body text, then the system font size on top. */
enum class CaptionSize(val title: String, val scale: Float) {
    Small("Small", 0.85f), Medium("Medium", 1.0f), Large("Large", 1.25f), ExtraLarge("Extra Large", 1.5f),
}

enum class CameraFacing(val title: String) { Back("Back"), Front("Front") }

/**
 * Everything Settings changes, with the defaults SCREENS.md section 17 names. The theme and the
 * Appearance setting live in ui/theme's ThemeStore, not here.
 */
data class AppSettings(
    val captions: Boolean = true,
    val captionSize: CaptionSize = CaptionSize.Medium,
    /** Off by default and stays off until the learner turns it on (DESIGN.md 5). */
    val voiceNext: Boolean = false,
    val speakMistakes: Boolean = false,
    val stepResults: Boolean = true,
    val haptics: Boolean = true,
    val keepScreenOn: Boolean = true,
    val cameraFacing: CameraFacing = CameraFacing.Back,
    /** Camera Mode sends from the learner's Ray-Ban Meta glasses instead of the phone camera. */
    val useGlasses: Boolean = false,
) {}

/**
 * Reads and writes [AppSettings]. Every change is saved at once and published on [settings], so the
 * theme, haptics and caption size follow without a restart.
 */
class SettingsStore(private val kv: KeyValue) {
    private val _settings = MutableStateFlow(load())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    val current: AppSettings get() = _settings.value

    fun update(change: (AppSettings) -> AppSettings) {
        val next = change(_settings.value)
        if (next == _settings.value) return
        save(next)
        _settings.value = next
    }

    private fun load() = AppSettings(
        captions = kv.bool(K_CAPTIONS, true),
        captionSize = enumOr(kv.string(K_CAPTION_SIZE), CaptionSize.Medium),
        voiceNext = kv.bool(K_VOICE, false),
        speakMistakes = kv.bool(K_SPEAK, false),
        stepResults = kv.bool(K_RESULTS, true),
        haptics = kv.bool(K_HAPTICS, true),
        keepScreenOn = kv.bool(K_AWAKE, true),
        cameraFacing = enumOr(kv.string(K_FACING), CameraFacing.Back),
        useGlasses = kv.bool(K_GLASSES, false),
    )

    private fun save(s: AppSettings) {
        kv.putBool(K_CAPTIONS, s.captions)
        kv.putString(K_CAPTION_SIZE, s.captionSize.name)
        kv.putBool(K_VOICE, s.voiceNext)
        kv.putBool(K_SPEAK, s.speakMistakes)
        kv.putBool(K_RESULTS, s.stepResults)
        kv.putBool(K_HAPTICS, s.haptics)
        kv.putBool(K_AWAKE, s.keepScreenOn)
        kv.putString(K_FACING, s.cameraFacing.name)
        kv.putBool(K_GLASSES, s.useGlasses)
    }

    companion object {
        private const val K_CAPTIONS = "captions"
        private const val K_CAPTION_SIZE = "caption_size"
        private const val K_VOICE = "voice_next"
        private const val K_SPEAK = "speak_mistakes"
        private const val K_RESULTS = "step_results"
        private const val K_HAPTICS = "haptics"
        private const val K_AWAKE = "keep_screen_on"
        private const val K_FACING = "camera_facing"
        private const val K_GLASSES = "use_glasses"

        private inline fun <reified E : Enum<E>> enumOr(raw: String?, default: E): E =
            enumValues<E>().firstOrNull { it.name == raw } ?: default

        @Volatile private var shared: SettingsStore? = null

        /** The app's one store, kept in the "handover_settings" preferences file. */
        fun get(context: Context): SettingsStore =
            shared ?: synchronized(this) { shared ?: SettingsStore(SharedKeyValue(context, "handover_settings")).also { shared = it } }
    }
}
