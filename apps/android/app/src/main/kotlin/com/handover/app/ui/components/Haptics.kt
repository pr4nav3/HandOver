package com.handover.app.ui.components

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalView
import com.handover.app.ui.theme.LocalHapticsEnabled

/**
 * The haptic events of DESIGN.md section 4, each mapped to the Android constant the spec names.
 * One haptic per real event the person sees; never per retry, check or state message.
 */
enum class HOHaptic {
    /** Any button that does something; a rating star; the PiP landing in a corner. CLOCK_TICK. */
    Tap,
    /** Tab or segment change. SEGMENT_TICK. */
    Selection,
    /** Step verified by camera, lesson done, connected, upload done. CONFIRM. */
    Success,
    /** Step change by Next, Back or goto; record stops. CONTEXT_CLICK. */
    StepChange,
    /** Mistake card appears, connection lost, destructive action confirmed. REJECT. */
    Warning,
    /** QR or passcode wrong, upload failed. REJECT. */
    Error,
    /** Record starts. LONG_PRESS. */
    Heavy,
    /** Timeline boundary snaps to a sentence edge. SEGMENT_FREQUENT_TICK. */
    Snap,
}

object HapticMap {
    /** The HapticFeedbackConstants value for [event] on [sdk], with the closest older constant below the API that added it. */
    fun constant(event: HOHaptic, sdk: Int = Build.VERSION.SDK_INT): Int = when (event) {
        HOHaptic.Tap -> HapticFeedbackConstants.CLOCK_TICK
        HOHaptic.Selection -> if (sdk >= 34) HapticFeedbackConstants.SEGMENT_TICK else HapticFeedbackConstants.CLOCK_TICK
        HOHaptic.Success -> if (sdk >= 30) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.VIRTUAL_KEY
        HOHaptic.StepChange -> HapticFeedbackConstants.CONTEXT_CLICK
        HOHaptic.Warning, HOHaptic.Error -> if (sdk >= 30) HapticFeedbackConstants.REJECT else HapticFeedbackConstants.LONG_PRESS
        HOHaptic.Heavy -> HapticFeedbackConstants.LONG_PRESS
        HOHaptic.Snap -> if (sdk >= 34) HapticFeedbackConstants.SEGMENT_FREQUENT_TICK else HapticFeedbackConstants.CLOCK_TICK
    }

    /** The predefined Vibrator effect used when the view cannot play [event] (no window, or a phone that ignores the constant). */
    fun effect(event: HOHaptic): Int = when (event) {
        HOHaptic.Tap, HOHaptic.Selection, HOHaptic.Snap -> VibrationEffect.EFFECT_TICK
        HOHaptic.StepChange -> VibrationEffect.EFFECT_CLICK
        HOHaptic.Success, HOHaptic.Warning, HOHaptic.Error -> VibrationEffect.EFFECT_DOUBLE_CLICK
        HOHaptic.Heavy -> VibrationEffect.EFFECT_HEAVY_CLICK
    }
}

/**
 * Plays [HOHaptic] events through the view, which respects the system "Touch feedback" setting.
 * Falls back to a predefined Vibrator effect only when the view declines and the app holds VIBRATE.
 */
class Haptics(private val view: View, private val enabled: Boolean) {
    fun play(event: HOHaptic) {
        if (!enabled) return
        if (view.performHapticFeedback(HapticMap.constant(event))) return
        vibrate(view.context, event)
    }

    private fun vibrate(context: Context, event: HOHaptic) {
        if (context.checkSelfPermission(Manifest.permission.VIBRATE) != PackageManager.PERMISSION_GRANTED) return
        val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= 31) {
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Vibrator::class.java)
        }
        runCatching { vibrator?.takeIf { it.hasVibrator() }?.vibrate(VibrationEffect.createPredefined(HapticMap.effect(event))) }
    }
}

@Composable
fun rememberHaptics(): Haptics {
    val view = LocalView.current
    val enabled = LocalHapticsEnabled.current
    return remember(view, enabled) { Haptics(view, enabled) }
}
