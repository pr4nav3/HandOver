package com.handover.app.ui.camera

import android.app.Activity
import android.Manifest
import android.content.Intent
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import com.handover.app.ui.glasses.GlassesCard
import com.handover.app.ui.glasses.GlassesController
import com.handover.app.ui.glasses.GlassesEvent
import com.handover.app.ui.glasses.GlassesPhase
import com.handover.app.ui.onboarding.has
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.PermissionStatus
import kotlinx.coroutines.launch
import android.content.Context
import android.content.ContextWrapper
import android.os.PowerManager
import android.os.SystemClock
import android.view.WindowManager
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.handover.app.core.AdvanceReason
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.core.CameraSocket
import com.handover.app.core.CheckType
import com.handover.app.core.HubMessage
import com.handover.app.core.SocketPhase
import com.handover.app.ui.components.Badge
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.onboarding.PermissionAsk
import com.handover.app.ui.onboarding.PermissionGate
import com.handover.app.ui.pairing.rememberRecentHubs
import com.handover.app.ui.settings.CameraFacing
import com.handover.app.ui.settings.SettingsStore
import kotlinx.coroutines.delay
import java.util.concurrent.Executors

/**
 * Camera Mode (SCREENS.md 10): this phone as the learner's camera. Asks for the camera with the
 * pre-prompt card first. The hub connection itself is core's [CameraSocket]; this screen feeds it
 * frames and draws what it reports.
 */
@Composable
fun CameraScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier, onClose: (() -> Unit)? = null) {
    if (state.hub == null) {
        CameraNoHub(modifier)
        return
    }
    var declined by remember { mutableStateOf(false) }
    if (declined) {
        CameraDeclined(onTryAgain = { declined = false }, modifier = modifier)
        return
    }
    PermissionGate(PermissionAsk.Camera, onDecline = { declined = true }) {
        CameraMode(state, vm, modifier, onClose)
    }
}

@Composable
private fun CameraMode(state: AppState, vm: AppViewModel, modifier: Modifier, onClose: (() -> Unit)?) {
    val context = LocalContext.current
    val view = LocalView.current
    val haptics = rememberHaptics()
    val settings = remember { SettingsStore.get(context) }
    val prefs by settings.settings.collectAsState()
    val recent = rememberRecentHubs()
    val hubName = recent.nameOf(state.hub?.display) ?: state.hub?.host ?: "the hub"

    var socket by remember { mutableStateOf<CameraSocket?>(null) }
    LifecycleEventEffect(Lifecycle.Event.ON_START) { socket = vm.startCamera() }
    // In the background the camera stops; closing the socket means the hub hears a fresh hello on return.
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) { vm.stopCamera(); socket = null }
    DisposableEffect(Unit) { onDispose { vm.stopCamera() } }

    val s = socket
    val status by (s?.status ?: remember { kotlinx.coroutines.flow.MutableStateFlow(com.handover.app.core.SocketStatus()) }).collectAsState()
    val active by (s?.active ?: remember { kotlinx.coroutines.flow.MutableStateFlow(false) }).collectAsState()
    val hubState by (s?.state ?: remember { kotlinx.coroutines.flow.MutableStateFlow(null) }).collectAsState()

    // The learner's glasses as the source (docs/research/glasses.md). The controller lives as long as this screen.
    val scope = rememberCoroutineScope()
    val glasses = remember { GlassesController(context.applicationContext, scope) }
    val glassesState by glasses.state.collectAsState()
    var glassesFrame by remember { mutableStateOf<ImageBitmap?>(null) }
    var toast by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(toast) { if (toast != null) { delay(4_000); toast = null } }
    val needsBluetooth = Build.VERSION.SDK_INT >= 31 && !context.has(Manifest.permission.BLUETOOTH_CONNECT)
    val bluetooth = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok -> if (ok) glasses.initialize() }
    LaunchedEffect(prefs.useGlasses, needsBluetooth) { if (prefs.useGlasses && !needsBluetooth) glasses.initialize() }
    LaunchedEffect(Unit) {
        glasses.events.collect { e ->
            if (e is GlassesEvent.FallBack) {
                settings.update { it.copy(useGlasses = false) }
                toast = e.reason
                haptics.play(HOHaptic.Warning)
            }
        }
    }
    // Tell the hub which source this camera is (hello may repeat; core sends it on change).
    LaunchedEffect(s, prefs.useGlasses, glassesState.device?.name) {
        s?.identify(
            name = if (prefs.useGlasses) "${glassesState.device?.name ?: "Ray-Ban Meta"} glasses" else AppViewModel.defaultCameraName(),
            source = if (prefs.useGlasses) "glasses" else "phone",
        )
    }
    DisposableEffect(Unit) { onDispose { glasses.stop() } }
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) { glasses.stop() }
    if (!prefs.useGlasses && glassesState.phase in setOf(GlassesPhase.Connecting, GlassesPhase.Streaming, GlassesPhase.Paused)) glasses.stop()

    // Haptics: success on a camera-verified step, warning on a mistake (SCREENS.md 10).
    LaunchedEffect(s) {
        s?.messages?.collect { m ->
            when {
                m is HubMessage.Advanced && m.advance.reason == AdvanceReason.Camera -> haptics.play(HOHaptic.Success)
                m is HubMessage.MistakeRaised -> haptics.play(HOHaptic.Warning)
            }
        }
    }

    val power = remember { context.getSystemService(Context.POWER_SERVICE) as PowerManager }
    var warm by remember { mutableStateOf(false) }
    var saver by remember { mutableStateOf(power.isPowerSaveMode) }
    LaunchedEffect(Unit) {
        while (true) {
            warm = power.currentThermalStatus >= PowerManager.THERMAL_STATUS_SEVERE
            saver = power.isPowerSaveMode
            delay(5_000)
        }
    }

    val gate = remember { FrameGate() }
    gate.intervalMs = if (warm) FramePipeline.SLOW_INTERVAL_MS else FramePipeline.INTERVAL_MS
    val meter = remember { FpsMeter() }
    var fps by remember { mutableStateOf(0.0) }
    var sentSize by remember { mutableStateOf<FrameSize?>(null) }
    LaunchedEffect(Unit) {
        while (true) {
            fps = meter.fps(SystemClock.elapsedRealtime())
            delay(1_000)
        }
    }

    // Keep the screen on while streaming; dim to 30% after 30 s without a touch (DESIGN.md 5).
    var lastTouch by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    var dimmed by remember { mutableStateOf(false) }
    DisposableEffect(view) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false }
    }
    LaunchedEffect(lastTouch) {
        dimmed = false
        delay(30_000)
        dimmed = true
    }
    val activity = remember(context) { context.findActivity() }
    DisposableEffect(dimmed, activity) {
        activity?.window?.let { w -> w.attributes = w.attributes.apply { screenBrightness = if (dimmed) 0.3f else WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE } }
        onDispose { activity?.window?.let { w -> w.attributes = w.attributes.apply { screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE } } }
    }

    var statsShown by remember { mutableStateOf(true) }
    var locked by remember { mutableStateOf(false) }
    val lesson = state.lesson?.takeIf { it.id == hubState?.lessonId }
    val step = hubState?.takeIf { !it.done }?.let { lesson?.steps?.getOrNull(it.step) }
    val manual = step?.checkType == CheckType.Manual
    val phase = when {
        status.phase == SocketPhase.Replaced -> CameraPhase.Replaced
        status.phase == SocketPhase.Waiting -> CameraPhase.Reconnecting
        status.phase != SocketPhase.Open -> CameraPhase.Connecting
        active -> CameraPhase.Sending
        hubState?.cameraConnected == true -> CameraPhase.Standby
        else -> CameraPhase.Paused
    }
    val ui = CameraUi(
        hubName = hubName,
        phase = phase,
        fps = fps,
        size = sentSize,
        source = if (prefs.useGlasses) "Glasses" else if (prefs.cameraFacing == CameraFacing.Front) "Phone front camera" else "Phone back camera",
        stepTitle = hubState?.let { h ->
            when {
                h.lessonId == null -> null
                h.done -> lesson?.title?.let { "Done: $it" } ?: "Lesson done"
                step != null -> "Step ${h.step + 1} of ${h.total}: ${step.title}"
                else -> "Step ${h.step + 1} of ${h.total}"
            }
        },
        badge = Badge.state(hubState, manual),
        canBack = hubState?.let { it.lessonId != null && !it.done && it.step > 0 } == true,
        canNext = hubState?.let { it.lessonId != null && !it.done } == true,
        lastStep = hubState?.let { it.total > 0 && it.step == it.total - 1 } == true,
        warm = warm,
        powerSaver = saver,
        statsShown = statsShown,
        locked = locked,
        glasses = prefs.useGlasses,
        toast = toast,
    )

    // One offer function for both sources: the gate lets about one frame a second through, the
    // socket sends only when idle, and the stats count only frames that left the phone.
    val offer: (FrameSize, () -> ByteArray) -> Boolean = { jpegSize, jpeg ->
        val now = SystemClock.elapsedRealtime()
        if (!gate.ready(now)) false else {
            val bytes = jpeg()
            val sent = socket?.sendFrame(bytes) == true
            if (sent) {
                gate.sent(now)
                meter.record(now)
                sentSize = jpegSize
                if (prefs.useGlasses) glassesFrame = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
            }
            sent
        }
    }
    val activityForGlasses = activity
    val cameraPermission = rememberLauncherForActivityResult(Wearables.RequestPermissionContract()) { result ->
        val granted = result.getOrDefault(PermissionStatus.Denied) == PermissionStatus.Granted
        glasses.onCameraPermission(granted)
        if (granted) glasses.start(offer)
    }
    fun glassesPrimary() {
        when (if (needsBluetooth) GlassesPhase.NeedsBluetooth else glassesState.phase) {
            GlassesPhase.NeedsBluetooth -> bluetooth.launch(Manifest.permission.BLUETOOTH_CONNECT)
            GlassesPhase.MetaAiMissing -> runCatching {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.facebook.stella")))
            }
            GlassesPhase.NotRegistered, GlassesPhase.DeveloperMode -> activityForGlasses?.let(glasses::register)
            GlassesPhase.NeedsCameraPermission -> cameraPermission.launch(com.meta.wearable.dat.core.types.Permission.CAMERA)
            else -> scope.launch { if (glasses.cameraAllowed()) glasses.start(offer) else cameraPermission.launch(com.meta.wearable.dat.core.types.Permission.CAMERA) }
        }
    }

    val facing by rememberUpdatedState(prefs.cameraFacing)
    CameraModeContent(
        ui = ui,
        modifier = modifier,
        onTouch = { lastTouch = SystemClock.elapsedRealtime() },
        onNext = { if (s?.next() == true) haptics.play(HOHaptic.StepChange) },
        onBack = { if (s?.back() == true) haptics.play(HOHaptic.StepChange) },
        onToggleStats = { statsShown = !statsShown },
        onSource = { i ->
            settings.update {
                when (i) {
                    0 -> it.copy(useGlasses = false, cameraFacing = CameraFacing.Back)
                    1 -> it.copy(useGlasses = false, cameraFacing = CameraFacing.Front)
                    else -> it.copy(useGlasses = true)
                }
            }
        },
        onLock = { locked = it },
        onSendAgain = { vm.stopCamera(); socket = vm.startCamera() },
        onClose = onClose,
        glassesCard = if (prefs.useGlasses && (needsBluetooth || glassesState.phase != GlassesPhase.Streaming)) ({
            GlassesCard(
                if (needsBluetooth) glassesState.copy(phase = GlassesPhase.NeedsBluetooth) else glassesState,
                onPrimary = ::glassesPrimary,
                onSecondary = { glasses.stop(); settings.update { it.copy(useGlasses = false) } },
            )
        }) else null,
        preview = {
            if (prefs.useGlasses) {
                // The glasses' own picture: the last frame sent, about once a second.
                glassesFrame?.let { Image(it, "Glasses view", contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize()) }
            } else CameraPreview(facing, offer)
        },
    )
}

/**
 * The camera preview and the frame source. [offer] is called on the analysis thread for each
 * camera picture with its sent size and a lazy JPEG; it returns whether the frame went out. The
 * JPEG is only made when the gate is open, so a 30 fps camera costs one encode per second.
 */
@Composable
private fun CameraPreview(facing: CameraFacing, offer: (FrameSize, () -> ByteArray) -> Boolean) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val latest by rememberUpdatedState(offer)
    val executor = remember { Executors.newSingleThreadExecutor() }
    val provider = remember { arrayOfNulls<ProcessCameraProvider>(1) }
    val previewView = remember { PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER } }
    DisposableEffect(Unit) {
        onDispose {
            runCatching { provider[0]?.unbindAll() }
            executor.shutdown()
        }
    }
    DisposableEffect(facing) {
        val future = ProcessCameraProvider.getInstance(context)
        val main = ContextCompat.getMainExecutor(context)
        future.addListener({
            val p = future.get().also { provider[0] = it }
            val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
            // Ask for about 1280 x 720; the pipeline scales to 960 on the long side either way.
            val selector = ResolutionSelector.Builder()
                .setResolutionStrategy(ResolutionStrategy(android.util.Size(1280, 720), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
                .build()
            val analysis = ImageAnalysis.Builder()
                .setResolutionSelector(selector)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                .build()
            analysis.setAnalyzer(executor) { image ->
                try {
                    val rotation = image.imageInfo.rotationDegrees
                    val size = FramePipeline.sentSize(image.width, image.height, rotation)
                    latest(size) {
                        val bitmap = image.toBitmap()
                        try { FramePipeline.encode(bitmap, rotation) } finally { bitmap.recycle() }
                    }
                } catch (e: Exception) {
                    // A bad frame is dropped; the next one tries again.
                } finally {
                    image.close()
                }
            }
            val camera = if (facing == CameraFacing.Front) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA
            runCatching {
                p.unbindAll()
                p.bindToLifecycle(owner, camera, preview, analysis)
            }
        }, main)
        onDispose { }
    }
    AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
