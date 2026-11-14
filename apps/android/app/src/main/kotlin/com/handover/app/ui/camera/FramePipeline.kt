package com.handover.app.ui.camera

import android.graphics.Bitmap
import android.graphics.Matrix
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.roundToInt

/** A width and height in pixels. */
data class FrameSize(val width: Int, val height: Int) {
    override fun toString() = "$width x $height"
}

/**
 * How a camera picture becomes a frame for the hub (CONTRACT.md section 6): turned upright, scaled
 * so the long side is at most [MAX_LONG_SIDE], JPEG at [JPEG_QUALITY], about one per second. Never
 * mirrored, never saved. The socket's send-when-idle drops a frame rather than queue it.
 */
object FramePipeline {
    const val MAX_LONG_SIDE = 960
    const val JPEG_QUALITY = 70
    const val INTERVAL_MS = 1_000L

    /** Thermal or battery trouble halves the rate (SCREENS.md 10). */
    const val SLOW_INTERVAL_MS = 2_000L

    /** The upright size of a [width] x [height] sensor picture after [rotation] degrees. */
    fun upright(width: Int, height: Int, rotation: Int): FrameSize =
        if (rotation % 180 == 0) FrameSize(width, height) else FrameSize(height, width)

    /** [size] scaled down so its long side is at most [maxLong]. Never scaled up; each side at least 1. */
    fun scaled(size: FrameSize, maxLong: Int = MAX_LONG_SIDE): FrameSize {
        val long = max(size.width, size.height)
        if (long <= maxLong || long <= 0) return size
        val k = maxLong.toDouble() / long
        return FrameSize(max(1, (size.width * k).roundToInt()), max(1, (size.height * k).roundToInt()))
    }

    /** The size a [width] x [height] picture at [rotation] is sent at. */
    fun sentSize(width: Int, height: Int, rotation: Int): FrameSize = scaled(upright(width, height, rotation))

    /** Turns [bitmap] upright, scales it and encodes a JPEG. One new bitmap at most; [bitmap] is left for the caller. */
    fun encode(bitmap: Bitmap, rotation: Int): ByteArray {
        val target = sentSize(bitmap.width, bitmap.height, rotation)
        val turned = upright(bitmap.width, bitmap.height, rotation)
        val matrix = Matrix().apply {
            postRotate(rotation.toFloat())
            val k = target.width.toFloat() / turned.width
            postScale(k, k)
        }
        val frame = if (rotation % 360 == 0 && target.width == bitmap.width) bitmap
        else Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        return ByteArrayOutputStream(64 * 1024).use { out ->
            frame.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
            if (frame !== bitmap) frame.recycle()
            out.toByteArray()
        }
    }
}

/**
 * Lets one frame through per interval on average. Each frame is due one interval after the last
 * one was due, and may go [slackMs] early, so camera jitter neither skips a frame nor speeds the
 * rate up. After a long gap (nothing could be sent) the schedule restarts from now.
 */
class FrameGate(@Volatile var intervalMs: Long = FramePipeline.INTERVAL_MS, private val slackMs: Long = 50) {
    private var due = Long.MIN_VALUE / 2

    @Synchronized
    fun ready(now: Long): Boolean = now >= due - slackMs

    @Synchronized
    fun sent(now: Long) {
        due = if (now - due > intervalMs) now + intervalMs else due + intervalMs
    }
}

/**
 * Frames per second actually sent: frames in the last [windowMs] divided by the time covered, which
 * is the whole window once the meter has run that long (the stats chip, SCREENS.md 10).
 */
class FpsMeter(private val windowMs: Long = 5_000) {
    private val times = ArrayDeque<Long>()
    private var started: Long? = null

    @Synchronized
    fun record(now: Long) {
        if (started == null) started = now
        times.addLast(now)
        trim(now)
    }

    @Synchronized
    fun fps(now: Long): Double {
        val since = started ?: return 0.0
        trim(now)
        val covered = (now - since).coerceIn(1_000, windowMs)
        return times.size * 1000.0 / covered
    }

    @Synchronized
    fun reset() {
        times.clear()
        started = null
    }

    private fun trim(now: Long) {
        while (times.isNotEmpty() && now - times.first() >= windowMs) times.removeFirst()
    }

    companion object {
        /** "1.0 fps". */
        fun label(fps: Double): String = String.format(java.util.Locale.US, "%.1f fps", fps)
    }
}
