package com.handover.app.ui.glasses

import android.app.Activity
import android.content.Context
import android.os.SystemClock
import com.handover.app.ui.camera.FrameSize
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.StreamError
import com.meta.wearable.dat.camera.types.StreamState
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import com.meta.wearable.dat.core.session.DeviceSessionState
import com.meta.wearable.dat.core.types.ChargingState
import com.meta.wearable.dat.core.types.Device
import com.meta.wearable.dat.core.types.DeviceSessionError
import com.meta.wearable.dat.core.types.LinkState
import com.meta.wearable.dat.core.types.Permission
import com.meta.wearable.dat.core.types.PermissionStatus
import com.meta.wearable.dat.core.types.RegistrationError
import com.meta.wearable.dat.core.types.RegistrationState
import com.meta.wearable.dat.core.types.ThermalLevel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Where the glasses stand, as the card shows it (SCREENS.md 12.2). */
enum class GlassesPhase {
    /** Android's Bluetooth permission is needed before the toolkit can start. */
    NeedsBluetooth,
    MetaAiMissing,
    /** Registration failed; in Developer Mode builds this almost always means Developer Mode is off. */
    DeveloperMode,
    NotRegistered,
    Registering,
    NoDevice,
    /** Registered and the glasses are here; not streaming. */
    Ready,
    NeedsCameraPermission,
    Connecting,
    Streaming,
    Paused,
    BatteryLow,
    TooHot,
    PowerLimit,
    Disconnected,
    /** Anything else; [GlassesState.detail] has the toolkit's own words. */
    Failed,
}

/** What the toolkit reports about the glasses. Null fields were not reported, so nothing is shown for them. */
data class GlassesDevice(
    val name: String,
    val battery: Int? = null,
    val charging: Boolean? = null,
    /** "Normal", "Warm", "Hot", or null when unknown. */
    val thermal: String? = null,
    val connected: Boolean = false,
)

data class GlassesState(
    val phase: GlassesPhase = GlassesPhase.NotRegistered,
    val device: GlassesDevice? = null,
    val frameSize: FrameSize? = null,
    /** The toolkit's own description of the last failure, when the phase is [GlassesPhase.Failed]. */
    val detail: String? = null,
)

/** One-off moments the camera screen reacts to. */
sealed interface GlassesEvent {
    /** Switch to the phone camera, with a one-line reason for the toast. */
    data class FallBack(val reason: String) : GlassesEvent
}

/**
 * The learner's Ray-Ban Meta glasses as a frame source, through the Meta Wearables Device Access
 * Toolkit 1.0.1 (API checked against the 1.0.1 AARs and Meta's CameraAccess sample). The session
 * streams VideoQuality.LOW at 2 fps, raw frames; each frame the caller accepts becomes a JPEG at
 * quality 60 through NV21. A session that reaches STARTED but sends no frame in 5 s, or a critical
 * stream error, asks the screen to fall back to the phone camera.
 *
 * Not device-tested in this repo: everything here compiles against the real toolkit, but no glasses
 * were connected while building it.
 */
class GlassesController(private val context: Context, private val scope: CoroutineScope) {
    private val _state = MutableStateFlow(GlassesState())
    val state: StateFlow<GlassesState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<GlassesEvent>(extraBufferCapacity = 4, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: SharedFlow<GlassesEvent> = _events.asSharedFlow()

    private var initialized = false
    private var watchers: Job? = null
    private var sessionJobs: Job? = null
    private var session: DeviceSession? = null
    private var camera: Camera? = null
    private val watchdog = FrameWatchdog()

    /**
     * Starts the toolkit and watches registration and devices. Call after BLUETOOTH_CONNECT is
     * granted. Safe to call again.
     */
    fun initialize() {
        if (initialized) return
        val result = Wearables.initialize(context.applicationContext)
        if (result.isFailure) {
            _state.update { it.copy(phase = GlassesPhase.Failed, detail = result.errorOrNull()?.toString()) }
            return
        }
        initialized = true
        watchers = scope.launch {
            launch { Wearables.registrationState.collect { onRegistration(it) } }
            launch {
                Wearables.registrationErrorStream.collect { e ->
                    _state.update { it.copy(phase = if (e == RegistrationError.META_AI_NOT_INSTALLED) GlassesPhase.MetaAiMissing else GlassesPhase.DeveloperMode) }
                }
            }
            launch {
                Wearables.devices.collect { ids ->
                    val id = ids.firstOrNull()
                    if (id == null) {
                        _state.update { s -> s.copy(device = null, phase = if (s.phase == GlassesPhase.Ready || s.phase == GlassesPhase.NeedsCameraPermission) GlassesPhase.NoDevice else s.phase) }
                    } else {
                        Wearables.devicesMetadata[id]?.collect { d -> _state.update { s -> s.copy(device = describe(d), phase = if (s.phase == GlassesPhase.NoDevice) GlassesPhase.Ready else s.phase) } }
                    }
                }
            }
        }
    }

    private fun onRegistration(r: RegistrationState) {
        _state.update { s ->
            when (r) {
                RegistrationState.REGISTERING -> s.copy(phase = GlassesPhase.Registering)
                RegistrationState.REGISTERED -> s.copy(phase = if (s.phase.isStreamingish()) s.phase else if (s.device == null) GlassesPhase.NoDevice else GlassesPhase.Ready)
                RegistrationState.AVAILABLE, RegistrationState.UNREGISTERING ->
                    if (s.phase == GlassesPhase.MetaAiMissing || s.phase == GlassesPhase.DeveloperMode) s else s.copy(phase = GlassesPhase.NotRegistered)
                RegistrationState.UNAVAILABLE -> s.copy(phase = GlassesPhase.MetaAiMissing)
            }
        }
    }

    private fun GlassesPhase.isStreamingish() = this == GlassesPhase.Connecting || this == GlassesPhase.Streaming || this == GlassesPhase.Paused

    /** Opens the Meta AI app to approve HandOver (the app returns through the handover:// scheme). */
    fun register(activity: Activity) {
        initialize()
        _state.update { it.copy(phase = GlassesPhase.Registering) }
        Wearables.startRegistration(activity)
    }

    /** Whether the glasses already let HandOver use their camera. */
    suspend fun cameraAllowed(): Boolean =
        Wearables.checkPermissionStatus(Permission.CAMERA).getOrNull() == PermissionStatus.Granted

    /** After the toolkit's permission contract returns. */
    fun onCameraPermission(granted: Boolean) {
        if (!granted) _state.update { it.copy(phase = GlassesPhase.NeedsCameraPermission) }
    }

    /**
     * Starts a session and the camera. [offer] gets each frame's size and a lazy JPEG on a
     * background thread and returns whether it was sent; only accepted frames are encoded.
     */
    fun start(offer: (FrameSize, () -> ByteArray) -> Boolean) {
        stop()
        _state.update { it.copy(phase = GlassesPhase.Connecting, detail = null) }
        val created = Wearables.createSession(AutoDeviceSelector())
        val s = created.getOrNull()
        if (s == null) {
            val e = created.errorOrNull()
            fail(if (e == DeviceSessionError.NO_ELIGIBLE_DEVICE) GlassesPhase.NoDevice else GlassesPhase.Failed, e?.description, fallBack = "Glasses not found. Using the phone camera.")
            return
        }
        session = s
        sessionJobs = scope.launch {
            // Subscribe before start() so no transition is missed (as Meta's sample does).
            launch { s.state.collect { onSession(it, s, offer) } }
            launch { s.errors.collect { onSessionError(it) } }
        }
        s.start()
    }

    private fun onSession(st: DeviceSessionState, s: DeviceSession, offer: (FrameSize, () -> ByteArray) -> Boolean) {
        when (st) {
            DeviceSessionState.STARTED -> if (camera == null) {
                val now = SystemClock.elapsedRealtime()
                watchdog.started(now)
                armWatchdog()
                startCamera(s, offer)
            } else _state.update { it.copy(phase = GlassesPhase.Streaming) }
            DeviceSessionState.PAUSED -> _state.update { it.copy(phase = GlassesPhase.Paused) }
            DeviceSessionState.STOPPED -> if (_state.value.phase == GlassesPhase.Streaming) fail(GlassesPhase.Disconnected, null, fallBack = "Glasses disconnected. Using the phone camera.")
            else -> Unit
        }
    }

    private fun startCamera(s: DeviceSession, offer: (FrameSize, () -> ByteArray) -> Boolean) {
        val added = s.addCamera(StreamConfiguration(videoQuality = VideoQuality.LOW, frameRate = 2, compressVideo = false))
        val cam = added.getOrNull()
        if (cam == null) {
            fail(GlassesPhase.Failed, added.errorOrNull()?.description, fallBack = "The glasses camera did not start. Using the phone camera.")
            return
        }
        camera = cam
        val stream = cam.stream
        scope.launch(Dispatchers.Default) {
            stream.videoStream.collect { f ->
                if (f.isCompressed || f.isCodecConfig) return@collect
                val now = SystemClock.elapsedRealtime()
                watchdog.frame(now)
                val size = FrameSize(f.width, f.height)
                if (_state.value.frameSize != size || _state.value.phase != GlassesPhase.Streaming) _state.update { it.copy(phase = GlassesPhase.Streaming, frameSize = size) }
                val raw = GlassesFrames.bytesOf(f.buffer)
                val layout = GlassesFrames.layoutFor(raw.size, f.width, f.height) ?: return@collect
                offer(size) { GlassesFrames.nv21ToJpeg(GlassesFrames.toNv21(raw, f.width, f.height, layout), f.width, f.height) }
            }
        }
        scope.launch { stream.errorStream.collect { onStreamError(it) } }
        scope.launch {
            stream.state.collect { st -> if (st == StreamState.PAUSED) _state.update { it.copy(phase = GlassesPhase.Paused) } }
        }
        stream.start().onFailure { e, _ -> fail(GlassesPhase.Failed, e.description, fallBack = "The glasses camera did not start. Using the phone camera.") }
    }

    private fun armWatchdog() {
        scope.launch {
            val wait = watchdog.waitMs(SystemClock.elapsedRealtime()) ?: return@launch
            delay(wait)
            if (watchdog.shouldFallBack(SystemClock.elapsedRealtime())) {
                fail(GlassesPhase.Failed, "No picture from the glasses.", fallBack = "No picture from the glasses. Using the phone camera.")
            }
        }
    }

    private fun onStreamError(e: StreamError) {
        when (e) {
            StreamError.BATTERY_LOW -> _state.update { it.copy(phase = GlassesPhase.BatteryLow) }
            StreamError.THERMAL_HOT -> _state.update { it.copy(phase = GlassesPhase.TooHot) }
            StreamError.PEAK_POWER_LIMIT -> _state.update { it.copy(phase = GlassesPhase.PowerLimit) }
            StreamError.HINGE_CLOSED -> fail(GlassesPhase.Disconnected, "The glasses were folded.", fallBack = "The glasses were folded. Using the phone camera.")
            StreamError.PERMISSIONS_DENIED -> fail(GlassesPhase.NeedsCameraPermission, null, fallBack = "The glasses camera is not allowed. Using the phone camera.")
            StreamError.CRITICAL_STREAM_ERROR -> fail(GlassesPhase.Disconnected, e.description, fallBack = "The glasses stream stopped. Using the phone camera.")
            StreamError.STREAM_ERROR, StreamError.TIMEOUT -> _state.update { it.copy(detail = e.description) }
        }
    }

    private fun onSessionError(e: DeviceSessionError) {
        when (e) {
            DeviceSessionError.BATTERY_CRITICAL -> fail(GlassesPhase.BatteryLow, null, fallBack = "Glasses battery is too low. Using the phone camera.")
            DeviceSessionError.THERMAL_CRITICAL, DeviceSessionError.THERMAL_EMERGENCY -> fail(GlassesPhase.TooHot, null, fallBack = "The glasses are too hot. Using the phone camera.")
            DeviceSessionError.PEAK_POWER_SHUTDOWN -> fail(GlassesPhase.PowerLimit, null, fallBack = "The glasses hit a power limit. Using the phone camera.")
            DeviceSessionError.DEVICE_DISCONNECTED, DeviceSessionError.SESSION_ENDED_BY_DEVICE -> fail(GlassesPhase.Disconnected, null, fallBack = "Glasses disconnected. Using the phone camera.")
            else -> fail(GlassesPhase.Failed, e.description, fallBack = "The glasses stopped. Using the phone camera.")
        }
    }

    private fun fail(phase: GlassesPhase, detail: String?, fallBack: String?) {
        stopStreams()
        _state.update { it.copy(phase = phase, detail = detail) }
        if (fallBack != null) _events.tryEmit(GlassesEvent.FallBack(fallBack))
    }

    private fun stopStreams() {
        watchdog.reset()
        runCatching { camera?.stop() }
        camera = null
        sessionJobs?.cancel()
        sessionJobs = null
        // A stopped session cannot restart; the next start creates a new one.
        runCatching { session?.stop() }
        session = null
    }

    /** Stops streaming; registration and device watching stay. */
    fun stop() {
        stopStreams()
        _state.update { s -> if (s.phase.isStreamingish()) s.copy(phase = if (s.device == null) GlassesPhase.NoDevice else GlassesPhase.Ready) else s }
    }

    companion object {
        fun describe(d: Device): GlassesDevice = GlassesDevice(
            name = d.name.ifBlank { "Ray-Ban Meta" },
            // The toolkit reports an int; negative means it does not know.
            battery = d.batteryLevel.takeIf { it in 0..100 },
            charging = when (d.chargingState) { ChargingState.CHARGING -> true; ChargingState.NOT_CHARGING -> false; else -> null },
            thermal = when (d.thermalLevel) {
                ThermalLevel.NONE, ThermalLevel.LIGHT -> "Normal"
                ThermalLevel.MODERATE -> "Warm"
                ThermalLevel.SEVERE, ThermalLevel.CRITICAL, ThermalLevel.EMERGENCY, ThermalLevel.SHUTDOWN -> "Hot"
                else -> null
            },
            connected = d.linkState == LinkState.CONNECTED,
        )
    }
}
