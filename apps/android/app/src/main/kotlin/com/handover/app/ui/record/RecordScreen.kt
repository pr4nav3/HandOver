package com.handover.app.ui.record

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.FallbackStrategy
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.camera.view.PreviewView
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Cameraswitch
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.MicOff
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material.icons.outlined.VideocamOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.handover.app.ui.components.glass
import com.handover.app.ui.editor.ClipPlayer
import com.handover.app.ui.library.PrimaryButton
import com.handover.app.ui.library.QuietButton
import com.handover.app.ui.library.SecondaryButton
import com.handover.app.ui.library.rememberHaptics
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.PI
import kotlin.math.pow

/**
 * Record a take (SCREENS.md section 12) with CameraX: 1080p (or the closest the camera has) with the narration
 * from the microphone, like the Camera app. The shutter morphs from circle to rounded square, a red timer pill
 * and a level meter show while recording, and start and stop play haptics. After stop, the take is reviewed and
 * "Make Course" hands the file to Teach. [onImport] opens the photo picker for a video recorded on glasses.
 */
@Composable
fun RecordScreen(onClose: () -> Unit, onTake: (File) -> Unit, onImport: () -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current
    val haptics = rememberHaptics()
    val view = LocalView.current
    var ui by remember { mutableStateOf(RecordUi(cameraAllowed = granted(context, Manifest.permission.CAMERA))) }
    val meter = remember { LevelMeter() }
    val recorder = remember { Recorder.Builder().setQualitySelector(QualitySelector.from(Quality.FHD, FallbackStrategy.lowerQualityOrHigherThan(Quality.FHD))).build() }
    val videoCapture = remember { VideoCapture.withOutput(recorder) }
    var recording by remember { mutableStateOf<Recording?>(null) }
    var discardOnFinish by remember { mutableStateOf(false) }
    var confirmClose by remember { mutableStateOf(false) }
    var confirmRedo by remember { mutableStateOf(false) }
    val previewView = remember { PreviewView(context).apply { implementationMode = PreviewView.ImplementationMode.COMPATIBLE; scaleType = PreviewView.ScaleType.FILL_CENTER } }

    val askPermissions = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        ui = ui.copy(
            cameraAllowed = result[Manifest.permission.CAMERA] ?: granted(context, Manifest.permission.CAMERA),
            micAsked = true,
        )
    }
    LaunchedEffect(Unit) {
        val missing = listOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO).filterNot { granted(context, it) }
        if (missing.isNotEmpty()) askPermissions.launch(missing.toTypedArray()) else ui = ui.copy(micAsked = true)
    }
    DisposableEffect(Unit) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false; recording?.close() }
    }
    // Bind the camera whenever the lens changes or permission arrives.
    DisposableEffect(ui.cameraAllowed, ui.usingFront) {
        if (!ui.cameraAllowed) return@DisposableEffect onDispose {}
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        future.addListener({
            runCatching {
                provider = future.get().also { p ->
                    val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
                    val selector = if (ui.usingFront) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA
                    p.unbindAll()
                    p.bindToLifecycle(lifecycle, selector, preview, videoCapture)
                }
            }.onFailure { ui = ui.copy(error = "The camera could not start. Close and try again.") }
        }, ContextCompat.getMainExecutor(context))
        onDispose { provider?.unbindAll() }
    }

    fun start() {
        val dir = File(context.filesDir, "takes").apply { mkdirs() }
        val file = File(dir, "take-" + SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date()) + ".mp4")
        val withMic = granted(context, Manifest.permission.RECORD_AUDIO)
        meter.reset()
        discardOnFinish = false
        @SuppressLint("MissingPermission")
        val pending = recorder.prepareRecording(context, FileOutputOptions.Builder(file).build()).let { if (withMic) it.withAudioEnabled() else it }
        recording = pending.start(ContextCompat.getMainExecutor(context)) { event ->
            when (event) {
                is VideoRecordEvent.Start -> {
                    haptics.recordStart()
                    ui = ui.copy(phase = RecordPhase.Recording, elapsedMs = 0, micOff = !withMic, silent = false, error = null, levels = meter.bars.toList())
                }
                is VideoRecordEvent.Status -> {
                    val stats = event.recordingStats
                    val silent = if (withMic) meter.add(stats.audioStats.audioAmplitude, System.currentTimeMillis()) else false
                    ui = ui.copy(elapsedMs = stats.recordedDurationNanos / 1_000_000, levels = meter.bars.toList(), silent = silent)
                }
                is VideoRecordEvent.Finalize -> {
                    recording = null
                    val ok = !event.hasError() || event.error == VideoRecordEvent.Finalize.ERROR_SOURCE_INACTIVE
                    if (discardOnFinish || !ok) {
                        file.delete()
                        ui = ui.copy(phase = RecordPhase.Idle, elapsedMs = 0, error = if (!ok && !discardOnFinish) "The take could not be saved. Try again." else null)
                        if (discardOnFinish) onClose()
                    } else {
                        ui = ui.copy(phase = RecordPhase.Review, takePath = file.absolutePath, hasRecorded = true)
                    }
                }
                else -> Unit
            }
        }
    }

    fun stop() {
        haptics.recordStop()
        ui = ui.copy(phase = RecordPhase.Finishing)
        recording?.stop()
    }

    BackHandler {
        when (ui.phase) {
            RecordPhase.Recording -> confirmClose = true
            RecordPhase.Review -> confirmRedo = true
            else -> onClose()
        }
    }

    RecordContent(
        ui = ui,
        preview = { AndroidView({ previewView }, Modifier.fillMaxSize()) },
        onClose = { if (ui.phase == RecordPhase.Recording) confirmClose = true else onClose() },
        onShutter = { if (ui.phase == RecordPhase.Recording) stop() else if (ui.phase == RecordPhase.Idle) start() },
        onFlip = { ui = ui.copy(usingFront = !ui.usingFront) },
        onImport = onImport,
        onAllow = {
            if (ui.micAsked && !ui.cameraAllowed) openSettings(context)
            else askPermissions.launch(arrayOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO))
        },
        onMake = { ui.takePath?.let { onTake(File(it)) } },
        onRedo = { confirmRedo = true },
    )

    if (confirmClose) Confirm("Stop and discard this take?", null, "Discard", "Keep Recording",
        onConfirm = { confirmClose = false; discardOnFinish = true; recording?.stop() ?: onClose() },
        onDismiss = { confirmClose = false })
    if (confirmRedo) Confirm("Discard this take?", null, "Discard", "Cancel",
        onConfirm = {
            confirmRedo = false
            ui.takePath?.let { File(it).delete() }
            ui = ui.copy(phase = RecordPhase.Idle, takePath = null, elapsedMs = 0)
        },
        onDismiss = { confirmRedo = false })
}

@Composable
private fun Confirm(title: String, message: String?, action: String, keep: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = message?.let { { Text(it) } },
        confirmButton = { TextButton(onClick = onConfirm) { Text(action, color = HandOver.colors.bad) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(keep) } },
    )
}

private fun granted(context: Context, permission: String) =
    ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

private fun openSettings(context: Context) {
    context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}

private fun shutterSpring(reduce: Boolean): androidx.compose.animation.core.FiniteAnimationSpec<androidx.compose.ui.unit.Dp> =
    if (reduce) tween(0) else spring(dampingRatio = 0.80f, stiffness = (2 * PI / 0.30).pow(2).toFloat())

/**
 * The recorder, stateless: preview fills the screen (forced dark), controls float on it. Used by
 * [RecordScreen] and by previews and screenshot tests with a still [preview].
 */
@Composable
fun RecordContent(
    ui: RecordUi,
    preview: @Composable () -> Unit,
    onClose: () -> Unit = {},
    onShutter: () -> Unit = {},
    onFlip: () -> Unit = {},
    onImport: () -> Unit = {},
    onAllow: () -> Unit = {},
    onMake: () -> Unit = {},
    onRedo: () -> Unit = {},
) {
    val recordingNow = ui.phase == RecordPhase.Recording
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (ui.cameraAllowed) preview()
        else Column(Modifier.align(Alignment.Center).padding(HOSpace.xl).widthIn(max = 360.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(Icons.Outlined.VideocamOff, null, Modifier.size(44.dp), tint = Color.White.copy(alpha = 0.7f))
            Spacer(Modifier.height(HOSpace.m))
            Text("HandOver needs the camera to record a take.", color = Color.White, style = HandOver.type.body, textAlign = TextAlign.Center)
            Spacer(Modifier.height(HOSpace.l))
            SecondaryButton(if (ui.micAsked) "Open Settings" else "Allow Camera", onAllow, large = true)
        }

        // Top: close, timer pill, level meter.
        Column(Modifier.fillMaxWidth().statusBarsPadding().padding(HOSpace.l), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.fillMaxWidth()) {
                Box(
                    Modifier.size(44.dp).glass().clickable(role = Role.Button, onClick = onClose).semantics { contentDescription = "Close" },
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Outlined.Close, null, tint = Color.White) }
                if (recordingNow || ui.phase == RecordPhase.Finishing) {
                    Row(
                        Modifier.align(Alignment.Center).clip(CircleShape).background(HandOver.colors.record).padding(horizontal = 10.dp, vertical = 4.dp)
                            .semantics { contentDescription = timerSpoken(ui.elapsedMs); liveRegion = LiveRegionMode.Polite },
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(Modifier.size(7.dp).clip(CircleShape).background(Color.White))
                        Spacer(Modifier.width(6.dp))
                        Text(timerText(ui.elapsedMs), style = HandOver.type.timer, color = Color.White)
                    }
                }
            }
            if (recordingNow) {
                Spacer(Modifier.height(HOSpace.s))
                if (ui.micOff) {
                    Row(Modifier.glass(RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Outlined.MicOff, null, Modifier.size(14.dp), tint = Color.White)
                        Spacer(Modifier.width(4.dp))
                        Text("No narration", style = HandOver.type.footnote, color = Color.White)
                    }
                } else {
                    LevelBars(ui.levels, Modifier.width(120.dp).height(24.dp).semantics { contentDescription = "Narration level" })
                    if (ui.silent) Text("No sound. Check the mic.", style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.7f), modifier = Modifier.padding(top = HOSpace.xs))
                }
            }
        }

        if (ui.phase == RecordPhase.Review && ui.takePath != null) {
            Review(ui, onMake, onRedo)
            return@Box
        }

        // Bottom: hint, import, shutter row.
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().navigationBarsPadding().padding(bottom = HOSpace.xl), horizontalAlignment = Alignment.CenterHorizontally) {
            ui.error?.let {
                Text(it, style = HandOver.type.footnote, color = Color.White, textAlign = TextAlign.Center, modifier = Modifier.padding(horizontal = HOSpace.xl).glass(RoundedCornerShape(HORadius.control)).padding(HOSpace.s))
                Spacer(Modifier.height(HOSpace.m))
            }
            if (ui.phase == RecordPhase.Idle && ui.cameraAllowed) {
                if (!ui.hasRecorded) {
                    Text("Say each step out loud as you do it. Pause between steps.", style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.7f), textAlign = TextAlign.Center, modifier = Modifier.padding(horizontal = HOSpace.xl))
                    Spacer(Modifier.height(HOSpace.s))
                }
                Row(
                    Modifier.glass(RoundedCornerShape(50)).clickable(role = Role.Button, onClick = onImport).padding(horizontal = 14.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Outlined.PhotoLibrary, null, Modifier.size(16.dp), tint = Color.White)
                    Spacer(Modifier.width(6.dp))
                    Text("Recorded on glasses? Import it", style = HandOver.type.footnote, color = Color.White)
                }
                Spacer(Modifier.height(HOSpace.l))
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = HOSpace.xxl), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Spacer(Modifier.size(48.dp))
                Shutter(ui.phase, enabled = ui.cameraAllowed, onClick = onShutter)
                if (ui.phase == RecordPhase.Idle && ui.cameraAllowed) {
                    Box(
                        Modifier.size(48.dp).glass().clickable(role = Role.Button, onClick = onFlip).semantics { contentDescription = if (ui.usingFront) "Use back camera" else "Use front camera" },
                        contentAlignment = Alignment.Center,
                    ) { Icon(Icons.Outlined.Cameraswitch, null, tint = Color.White) }
                } else Spacer(Modifier.size(48.dp))
            }
        }
    }
}

/** DESIGN.md 3.8: 72 dp white ring; red circle 60 dp when ready, red rounded square 28 dp while recording. */
@Composable
private fun Shutter(phase: RecordPhase, enabled: Boolean, onClick: () -> Unit) {
    val reduce = HandOver.reduceMotion
    val square = phase == RecordPhase.Recording || phase == RecordPhase.Finishing
    val size by animateDpAsState(if (square) 28.dp else 60.dp, shutterSpring(reduce), label = "shutter size")
    val radius by animateDpAsState(if (square) 6.dp else 30.dp, shutterSpring(reduce), label = "shutter radius")
    val fill = if (enabled) HandOver.colors.record else Color(0xFF8E8E93)
    Box(
        Modifier.size(72.dp).border(4.dp, Color.White, CircleShape)
            .clickable(enabled = enabled && phase != RecordPhase.Finishing, role = Role.Button, onClick = onClick)
            .semantics { contentDescription = if (square) "Stop recording" else "Record" },
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(size).clip(RoundedCornerShape(radius)).background(fill))
        if (phase == RecordPhase.Finishing) CircularProgressIndicator(Modifier.size(72.dp), color = Color.White, strokeWidth = 2.dp)
    }
}

/** 24 bars, 3 dp wide with 2 dp gaps, white at 90% (DESIGN.md 3.9). */
@Composable
private fun LevelBars(levels: List<Float>, modifier: Modifier) {
    Canvas(modifier) {
        val bar = 3.dp.toPx()
        val gap = (size.width - bar * levels.size) / (levels.size - 1).coerceAtLeast(1)
        levels.forEachIndexed { i, level ->
            val h = (size.height * (0.12f + 0.88f * level)).coerceAtMost(size.height)
            drawRoundRect(
                Color.White.copy(alpha = 0.9f),
                topLeft = Offset(i * (bar + gap), (size.height - h) / 2),
                size = Size(bar, h),
                cornerRadius = CornerRadius(bar / 2),
            )
        }
    }
}

/** Review take (SCREENS.md 12.4): plays the take, then Make Course or Record Again. */
@Composable
private fun Review(ui: RecordUi, onMake: () -> Unit, onRedo: () -> Unit) {
    val inPreview = LocalInspectionMode.current
    Column(Modifier.fillMaxSize().background(Color.Black).statusBarsPadding().navigationBarsPadding().padding(HOSpace.l), verticalArrangement = Arrangement.Center) {
        Spacer(Modifier.height(56.dp))
        ClipPlayer(
            url = if (inPreview) null else ui.takePath?.let { Uri.fromFile(File(it)).toString() },
            poster = emptyList(),
            label = "Your take",
            modifier = Modifier.fillMaxWidth().weight(1f, fill = false).aspectRatio(9f / 16f, matchHeightConstraintsFirst = true).clip(RoundedCornerShape(HORadius.card)).align(Alignment.CenterHorizontally),
        )
        Spacer(Modifier.height(HOSpace.m))
        Text(timerText(ui.elapsedMs) + if (ui.micOff) ", no narration" else "", style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.7f), modifier = Modifier.align(Alignment.CenterHorizontally))
        if (ui.micOff) Text("Without narration, HandOver can only guess the steps.", style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.7f), textAlign = TextAlign.Center, modifier = Modifier.align(Alignment.CenterHorizontally))
        Spacer(Modifier.height(HOSpace.l))
        PrimaryButton("Make Course", onMake, Modifier.fillMaxWidth())
        Spacer(Modifier.height(HOSpace.s))
        QuietButton("Record Again", onRedo, Modifier.align(Alignment.CenterHorizontally), color = Color.White)
    }
}
