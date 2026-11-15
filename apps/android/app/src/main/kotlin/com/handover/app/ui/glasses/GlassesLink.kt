package com.handover.app.ui.glasses

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.handover.app.ui.camera.FrameSize
import com.handover.app.ui.onboarding.has
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import kotlinx.coroutines.launch

/** The glasses as one screen sees them: the phase to show, and the one action that moves setup forward. */
class GlassesLink(
    val controller: GlassesController,
    /** The controller's state, with NeedsBluetooth when Android has not allowed Bluetooth yet. */
    val state: GlassesState,
    /** Allow Bluetooth, get Meta AI, connect, allow the camera, or start, whichever comes next. */
    val next: () -> Unit,
) {
    /** True once HandOver is connected to the glasses through Meta AI (streaming or ready to). */
    val connected: Boolean get() = state.phase in ConnectedPhases

    companion object {
        val ConnectedPhases = setOf(GlassesPhase.Ready, GlassesPhase.NeedsCameraPermission, GlassesPhase.Connecting, GlassesPhase.Streaming, GlassesPhase.Paused)
    }
}

/**
 * Starts the Meta toolkit (once Bluetooth is allowed) and walks setup with the same steps as Be the
 * Camera's glasses card. With [offer], the glasses stream as soon as they are ready; without it (the
 * start sheet), setup stops at connected. The controller stops when the caller leaves.
 */
@Composable
fun rememberGlassesLink(offer: ((FrameSize, () -> ByteArray) -> Boolean)? = null): GlassesLink {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val controller = remember { GlassesController(context.applicationContext, scope) }
    val state by controller.state.collectAsState()
    var bluetoothAllowed by remember { mutableStateOf(Build.VERSION.SDK_INT < 31 || context.has(Manifest.permission.BLUETOOTH_CONNECT)) }
    val bluetooth = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok -> bluetoothAllowed = ok }
    LaunchedEffect(bluetoothAllowed) { if (bluetoothAllowed) controller.initialize() }
    DisposableEffect(Unit) { onDispose { controller.stop() } }

    val latestOffer by rememberUpdatedState(offer)
    val send: (FrameSize, () -> ByteArray) -> Boolean = { size, jpeg -> latestOffer?.invoke(size, jpeg) == true }
    val cameraPermission = rememberLauncherForActivityResult(Wearables.RequestPermissionContract()) { result ->
        val granted = result.getOrDefault(PermissionStatus.Denied) == PermissionStatus.Granted
        controller.onCameraPermission(granted)
        if (granted && latestOffer != null) controller.start(send)
    }
    val shown = if (bluetoothAllowed) state else state.copy(phase = GlassesPhase.NeedsBluetooth)

    // Streaming callers start on their own once the glasses are ready.
    LaunchedEffect(shown.phase, offer != null) {
        if (offer != null && shown.phase == GlassesPhase.Ready) {
            if (controller.cameraAllowed()) controller.start(send) else controller.onCameraPermission(false)
        }
    }

    val next: () -> Unit = {
        when (shown.phase) {
            GlassesPhase.NeedsBluetooth -> bluetooth.launch(Manifest.permission.BLUETOOTH_CONNECT)
            GlassesPhase.MetaAiMissing -> runCatching {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.facebook.stella")))
            }
            GlassesPhase.NotRegistered, GlassesPhase.DeveloperMode -> context.findActivity()?.let(controller::register)
            GlassesPhase.NeedsCameraPermission -> cameraPermission.launch(Permission.CAMERA)
            else -> if (latestOffer != null) scope.launch {
                if (controller.cameraAllowed()) controller.start(send) else cameraPermission.launch(Permission.CAMERA)
            }
        }
    }
    return GlassesLink(controller, shown, next)
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
