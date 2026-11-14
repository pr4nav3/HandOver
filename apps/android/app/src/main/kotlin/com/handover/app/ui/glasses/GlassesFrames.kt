package com.handover.app.ui.glasses

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * How the glasses lay out a raw (decoded) frame. The toolkit does not document it
 * (docs/research/glasses.md, "YUV layout"), so both common 4:2:0 layouts are handled and
 * [GlassesFrames.swapUV] flips chroma order if colors come out wrong on a real device.
 */
enum class YuvLayout {
    /** I420: the Y plane, then the whole U plane, then the whole V plane. */
    Planar,

    /** NV12 or NV21: the Y plane, then U and V interleaved. */
    SemiPlanar,
}

/**
 * Raw glasses frames to JPEG for the hub (CONTRACT.md section 6): build NV21, then
 * `YuvImage.compressToJpeg` at [JPEG_QUALITY] (the toolkit research's path). Pure byte work is in
 * [toNv21] so it is unit-tested; the JPEG step needs Android.
 */
object GlassesFrames {
    const val JPEG_QUALITY = 60

    /**
     * Set when a device test shows swapped colors (blue skin, orange sky). Off by default. Kept here,
     * not in Settings: it is a device fact, not a preference.
     */
    @Volatile var swapUV: Boolean = false

    /** Bytes in a 4:2:0 frame of [width] x [height] (even sizes). */
    fun frameBytes(width: Int, height: Int): Int = width * height + 2 * ((width + 1) / 2) * ((height + 1) / 2)

    /** The layout for a buffer of [size] bytes, or null when it is not a 4:2:0 frame of that size. */
    fun layoutFor(size: Int, width: Int, height: Int): YuvLayout? = if (width > 0 && height > 0 && size >= frameBytes(width, height)) YuvLayout.Planar else null

    /**
     * NV21 (Y, then V and U interleaved, V first) from [src]. [layout] says how [src] is arranged;
     * [swap] exchanges U and V, for a device whose planes are the other way round.
     */
    fun toNv21(src: ByteArray, width: Int, height: Int, layout: YuvLayout = YuvLayout.Planar, swap: Boolean = swapUV): ByteArray {
        val ySize = width * height
        val cw = (width + 1) / 2
        val ch = (height + 1) / 2
        val cSize = cw * ch
        require(src.size >= ySize + 2 * cSize) { "frame is ${src.size} bytes, need ${ySize + 2 * cSize} for $width x $height" }
        val out = ByteArray(ySize + 2 * cSize)
        System.arraycopy(src, 0, out, 0, ySize)
        var o = ySize
        when (layout) {
            YuvLayout.Planar -> {
                // I420 has U then V; NV21 wants V then U.
                val u = ySize
                val v = ySize + cSize
                val first = if (swap) u else v
                val second = if (swap) v else u
                for (i in 0 until cSize) {
                    out[o++] = src[first + i]
                    out[o++] = src[second + i]
                }
            }
            YuvLayout.SemiPlanar -> {
                // Interleaved already. NV12 (U first) is assumed, so swap to NV21 unless told otherwise.
                for (i in 0 until cSize) {
                    val a = src[ySize + 2 * i]
                    val b = src[ySize + 2 * i + 1]
                    out[o++] = if (swap) a else b
                    out[o++] = if (swap) b else a
                }
            }
        }
        return out
    }

    /** Copies a direct or heap buffer without moving its position. */
    fun bytesOf(buffer: ByteBuffer): ByteArray {
        val dup = buffer.duplicate()
        return ByteArray(dup.remaining()).also { dup.get(it) }
    }

    /** NV21 to JPEG at [JPEG_QUALITY]. */
    fun nv21ToJpeg(nv21: ByteArray, width: Int, height: Int, quality: Int = JPEG_QUALITY): ByteArray {
        val image = YuvImage(nv21, ImageFormat.NV21, width, height, null)
        return ByteArrayOutputStream(48 * 1024).use { out ->
            image.compressToJpeg(Rect(0, 0, width, height), quality, out)
            out.toByteArray()
        }
    }
}

/**
 * The fallback rule: once the glasses session is STARTED, a frame must arrive within [timeoutMs]
 * or the app switches to the phone camera (docs/research/glasses.md, "Auto fallback"). Pure, with
 * the time passed in, so it is tested without a device.
 */
class FrameWatchdog(private val timeoutMs: Long = 5_000) {
    private var startedAt: Long? = null
    private var lastFrameAt: Long? = null

    /** The session reached STARTED. */
    fun started(now: Long) {
        startedAt = now
        lastFrameAt = null
    }

    fun frame(now: Long) { lastFrameAt = now }

    fun reset() {
        startedAt = null
        lastFrameAt = null
    }

    /** True when STARTED was [timeoutMs] or more ago and no frame has come since. */
    fun shouldFallBack(now: Long): Boolean {
        val s = startedAt ?: return false
        return lastFrameAt == null && now - s >= timeoutMs
    }

    /** How long to wait before checking again, or null when no check is pending. */
    fun waitMs(now: Long): Long? {
        val s = startedAt ?: return null
        if (lastFrameAt != null) return null
        return (s + timeoutMs - now).coerceAtLeast(0)
    }
}
