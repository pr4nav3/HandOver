package com.handover.app.ui.components

import android.graphics.Bitmap
import android.graphics.Matrix
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.handover.app.core.CameraIdentity
import com.handover.app.core.CameraSource
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import kotlin.math.max
import kotlin.math.roundToInt

/** What the live pane shows (DESIGN.md 3.5). */
enum class LiveState { Live, Waiting, Lost, Reconnecting }

/** The source chip on the live pane: symbol and name; Recording is in caution with the record dot. */
data class LiveSource(val label: String, val icon: ImageVector, val recording: Boolean = false) {
    companion object {
        /**
         * From the hub's active camera. A file source, or a camera the hub could not identify
         * (source unknown), shows "Recording", so a replay is never taken for a live camera.
         */
        fun of(camera: CameraIdentity?, thisPhone: Boolean): LiveSource? = when {
            thisPhone -> LiveSource("This phone", Icons.Outlined.PhoneAndroid)
            camera == null -> null
            camera.source == CameraSource.File || camera.source == CameraSource.Unknown -> LiveSource("Recording", Icons.Outlined.Movie, recording = true)
            camera.source == CameraSource.Glasses -> LiveSource(camera.name.ifBlank { "Glasses" }, Icons.Outlined.Videocam)
            else -> LiveSource(camera.name.ifBlank { "Camera" }, Icons.Outlined.Videocam)
        }
    }
}

/**
 * The learner's camera pane: aspect fit on `stage`, never cropped, so what the learner sees is
 * what the check sees. [preview] replaces [frame] when this phone is the camera.
 */
@Composable
fun LiveView(
    frame: ImageBitmap?,
    state: LiveState,
    source: LiveSource?,
    modifier: Modifier = Modifier,
    radius: Dp = HORadius.card,
    compact: Boolean = false,
    preview: (@Composable (Modifier) -> Unit)? = null,
    waitingAction: (@Composable () -> Unit)? = null,
) {
    val spoken = when (state) {
        LiveState.Live -> "Your camera, live"
        LiveState.Lost -> "Your camera, lost"
        LiveState.Waiting -> "Your camera, waiting"
        LiveState.Reconnecting -> "Your camera, reconnecting"
    }
    Box(
        modifier.clip(RoundedCornerShape(radius)).background(HandOver.colors.stage).clearAndSetSemantics { contentDescription = spoken },
        contentAlignment = Alignment.Center,
    ) {
        when {
            state == LiveState.Reconnecting -> Placeholder("Reconnecting to the hub", null, compact)
            preview != null -> preview(Modifier.fillMaxSize())
            frame != null && state != LiveState.Waiting ->
                Image(frame, null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().alpha(if (state == LiveState.Lost) 0.4f else 1f))
            else -> Placeholder("Waiting for camera", if (compact) null else "Open HandOver on your phone and tap Be the Camera.", compact, waitingAction)
        }
        if (state == LiveState.Lost) {
            CaptionBar("Camera lost. Keep going with Next.", Modifier.align(Alignment.BottomCenter).padding(if (compact) HOSpace.xs else HOSpace.m), compact = compact)
        }
        if (source != null && state != LiveState.Reconnecting) {
            SourceChip(source, compact, Modifier.align(Alignment.TopStart).padding(if (compact) 6.dp else HOSpace.s))
        }
    }
}

@Composable
private fun Placeholder(title: String, hint: String?, compact: Boolean, action: (@Composable () -> Unit)? = null) {
    Column(Modifier.padding(HOSpace.m).widthIn(max = 300.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        Icon(Icons.Outlined.Videocam, null, tint = Color.White.copy(alpha = 0.4f), modifier = Modifier.size(if (compact) 20.dp else 28.dp))
        Text(title, style = if (compact) HandOver.type.caption else HandOver.type.callout, color = Color.White, textAlign = TextAlign.Center)
        if (hint != null) Text(hint, style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.6f), textAlign = TextAlign.Center)
        if (action != null && !compact) action()
    }
}

@Composable
private fun SourceChip(source: LiveSource, compact: Boolean, modifier: Modifier) {
    val caution = Color(0xFFFFC46B)
    Row(modifier.glass().padding(horizontal = 8.dp, vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        if (source.recording) StatusDot(HandOver.colors.record, size = 7.dp)
        else Icon(source.icon, null, tint = Color.White, modifier = Modifier.size(13.dp))
        if (!compact || source.recording) {
            Spacer(Modifier.width(5.dp))
            Text(source.label, style = HandOver.type.badge, color = if (source.recording) caution else Color.White, maxLines = 1)
        }
    }
}

/** Frame rules from SCREENS.md 10: long side at most 1280, JPEG quality 70, never mirrored. */
object FrameEncoder {
    const val LONG_SIDE = 1280
    const val QUALITY = 70

    /** The size a frame of [w] x [h] is scaled to so its long side is at most [LONG_SIDE]. */
    fun scaled(w: Int, h: Int): Pair<Int, Int> {
        val long = max(w, h)
        if (long <= LONG_SIDE) return w to h
        val f = LONG_SIDE.toDouble() / long
        return (w * f).roundToInt() to (h * f).roundToInt()
    }

    fun encode(bitmap: Bitmap, rotation: Int): ByteArray {
        val (w, h) = scaled(bitmap.width, bitmap.height)
        val m = Matrix().apply {
            postScale(w / bitmap.width.toFloat(), h / bitmap.height.toFloat())
            if (rotation != 0) postRotate(rotation.toFloat())
        }
        val out = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, m, true)
        return ByteArrayOutputStream().use { s -> out.compress(Bitmap.CompressFormat.JPEG, QUALITY, s); s.toByteArray() }
    }
}

/**
 * This phone's back camera, previewed at full frame rate (letterboxed) while one JPEG about every
 * [intervalMs] goes to [onFrame] for the hub's camera socket. Needs the CAMERA permission.
 */
@Composable
fun PhoneCameraPreview(onFrame: (ByteArray) -> Unit, modifier: Modifier = Modifier, intervalMs: Long = 1_000) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val send = rememberUpdatedState(onFrame)
    val view = remember {
        PreviewView(context).apply {
            scaleType = PreviewView.ScaleType.FIT_CENTER
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
            setBackgroundColor(android.graphics.Color.BLACK)
        }
    }
    DisposableEffect(owner) {
        val executor = Executors.newSingleThreadExecutor()
        val future = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var last = 0L
        future.addListener({
            val p = runCatching { future.get() }.getOrNull() ?: return@addListener
            provider = p
            val preview = Preview.Builder().build().also { it.surfaceProvider = view.surfaceProvider }
            val analysis = ImageAnalysis.Builder()
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setResolutionSelector(
                    ResolutionSelector.Builder()
                        .setResolutionStrategy(ResolutionStrategy(Size(1280, 720), ResolutionStrategy.FALLBACK_RULE_CLOSEST_LOWER_THEN_HIGHER))
                        .build(),
                )
                .build()
            analysis.setAnalyzer(executor) { image ->
                image.use {
                    val now = System.currentTimeMillis()
                    if (now - last >= intervalMs) {
                        last = now
                        runCatching { FrameEncoder.encode(it.toBitmap(), it.imageInfo.rotationDegrees) }.getOrNull()?.let { jpeg -> send.value(jpeg) }
                    }
                }
            }
            runCatching {
                p.unbindAll()
                p.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            }
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            provider?.unbindAll()
            executor.shutdown()
        }
    }
    AndroidView(factory = { view }, modifier = modifier)
}
