package com.handover.app.ui.learn

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.min
import kotlin.math.sin

/**
 * The chime for a step the camera verified (CONTRACT 7: "UI plays the chime when reason is
 * camera"). Two soft sine notes, E6 then A6, synthesized once into 16 bit PCM; no bundled file.
 */
object Chime {
    private const val RATE = 44_100

    /** The samples, pure so a test checks length and peak. Peak about 30% of full scale. */
    fun samples(): ShortArray {
        val notes = listOf(1318.51 to 0.0, 1760.0 to 0.09)
        val length = 0.42
        val n = (RATE * length).toInt()
        val out = ShortArray(n)
        for (i in 0 until n) {
            val t = i / RATE.toDouble()
            var v = 0.0
            for ((f, start) in notes) {
                val dt = t - start
                if (dt < 0) continue
                val attack = min(1.0, dt / 0.006)
                v += sin(2 * PI * f * dt) * attack * exp(-dt * 9.0) * 0.5
            }
            out[i] = (v.coerceIn(-1.0, 1.0) * 0.6 * Short.MAX_VALUE).toInt().toShort()
        }
        return out
    }

    private val pcm by lazy { samples() }

    fun play() {
        runCatching {
            val data = pcm
            val track = AudioTrack.Builder()
                .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                .setAudioFormat(AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_16BIT).setSampleRate(RATE).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setTransferMode(AudioTrack.MODE_STATIC)
                .setBufferSizeInBytes(data.size * 2)
                .build()
            track.write(data, 0, data.size)
            track.setNotificationMarkerPosition(data.size)
            track.setPlaybackPositionUpdateListener(object : AudioTrack.OnPlaybackPositionUpdateListener {
                override fun onMarkerReached(t: AudioTrack) = t.release()
                override fun onPeriodicNotification(t: AudioTrack) {}
            })
            track.play()
        }
    }
}
