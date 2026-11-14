package com.handover.app.ui.pairing

import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.QrCode2
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.MultiFormatReader
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.handover.app.ui.theme.HOMotion
import com.handover.app.ui.theme.HandOver
import java.util.concurrent.Executors

/**
 * The back camera, reading QR codes with ZXing on the luminance plane (as vibeflux's pairing does;
 * no Play Services model). [onCode] runs on the main thread, once per distinct code.
 */
@Composable
fun QrCamera(onCode: (String) -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val latest by rememberUpdatedState(onCode)
    val executor = remember { Executors.newSingleThreadExecutor() }
    val reader = remember {
        MultiFormatReader().apply { setHints(mapOf(DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE), DecodeHintType.TRY_HARDER to true)) }
    }
    val main = remember { ContextCompat.getMainExecutor(context) }
    val provider = remember { arrayOfNulls<ProcessCameraProvider>(1) }
    DisposableEffect(Unit) {
        onDispose {
            runCatching { provider[0]?.unbindAll() }
            executor.shutdown()
        }
    }
    AndroidView(
        factory = { ctx ->
            val view = PreviewView(ctx).apply { scaleType = PreviewView.ScaleType.FILL_CENTER }
            val future = ProcessCameraProvider.getInstance(ctx)
            future.addListener({
                val p = future.get().also { provider[0] = it }
                val preview = Preview.Builder().build().also { it.surfaceProvider = view.surfaceProvider }
                val analysis = ImageAnalysis.Builder().setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                var last: String? = null
                analysis.setAnalyzer(executor) { image ->
                    val text = decode(reader, image)
                    image.close()
                    if (text != null && text != last) {
                        last = text
                        main.execute { latest(text) }
                    }
                }
                runCatching {
                    p.unbindAll()
                    p.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                }
            }, main)
            view
        },
        modifier = modifier.fillMaxSize(),
    )
}

private fun decode(reader: MultiFormatReader, image: ImageProxy): String? {
    val plane = image.planes.firstOrNull() ?: return null
    val buffer = plane.buffer
    val data = ByteArray(buffer.remaining()).also { buffer.get(it) }
    val source = PlanarYUVLuminanceSource(data, plane.rowStride, image.height, 0, 0, image.width, image.height, false)
    return try {
        reader.decodeWithState(BinaryBitmap(HybridBinarizer(source)))?.text
    } catch (e: Exception) {
        null
    } finally {
        reader.reset()
    }
}

/**
 * The window over the camera (SCREENS.md 3.1 and 25.3): a 50% dim with a rounded square cut out
 * and white corner brackets. When a code is found the brackets close in to 86% and turn `good`.
 * Without a working camera, a dashed frame with a QR symbol stands in.
 */
@Composable
fun Viewfinder(cameraWorks: Boolean, found: Boolean, modifier: Modifier = Modifier) {
    val reduce = HandOver.reduceMotion
    val good = HandOver.colors.good
    val shrink by animateFloatAsState(if (found && !reduce) 0.86f else 1f, HOMotion.layout(reduce), label = "frame")
    val bracket by animateColorAsState(if (found) good else Color.White, HOMotion.layout(reduce), label = "bracket")
    BoxWithConstraints(modifier.fillMaxSize()) {
        val side = minOf(maxWidth - 96.dp, 280.dp)
        Canvas(Modifier.fillMaxSize().graphicsLayer(compositingStrategy = CompositingStrategy.Offscreen)) {
            val s = side.toPx()
            val tl = Offset((size.width - s) / 2, (size.height - s) / 2)
            val r = s * 0.14f
            if (cameraWorks) {
                drawRect(Color.Black.copy(alpha = 0.5f))
                drawRoundRect(Color.Transparent, tl, Size(s, s), CornerRadius(r), blendMode = BlendMode.Clear)
                // Corner brackets, inset as the code is found.
                val k = s * shrink
                val o = Offset(tl.x + (s - k) / 2, tl.y + (s - k) / 2)
                val arm = k * 0.22f
                val rr = r * shrink
                val stroke = Stroke(4.dp.toPx(), cap = StrokeCap.Round)
                fun corner(cx: Float, cy: Float, dx: Float, dy: Float) {
                    val p = Path().apply {
                        moveTo(cx, cy + dy * arm)
                        lineTo(cx, cy + dy * rr)
                        quadraticTo(cx, cy, cx + dx * rr, cy)
                        lineTo(cx + dx * arm, cy)
                    }
                    drawPath(p, bracket, style = stroke)
                }
                corner(o.x, o.y, 1f, 1f)
                corner(o.x + k, o.y, -1f, 1f)
                corner(o.x, o.y + k, 1f, -1f)
                corner(o.x + k, o.y + k, -1f, -1f)
            } else {
                drawRoundRect(
                    Color.White.copy(alpha = 0.3f), tl, Size(s, s), CornerRadius(r),
                    style = Stroke(3.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(8.dp.toPx(), 8.dp.toPx()))),
                )
            }
        }
        if (!cameraWorks) Icon(Icons.Outlined.QrCode2, null, tint = Color.White.copy(alpha = 0.3f), modifier = Modifier.align(Alignment.Center).size(64.dp))
    }
}
