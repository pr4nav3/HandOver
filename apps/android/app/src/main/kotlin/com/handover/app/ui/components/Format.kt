package com.handover.app.ui.components

import kotlin.math.roundToInt

object Format {
    /** "12 s" under a minute, else "1:05" (as `formatSecs` in web/src/Learn.tsx). */
    fun secs(seconds: Double): String {
        val s = seconds.roundToInt().coerceAtLeast(0)
        return if (s < 60) "$s s" else "${s / 60}:${(s % 60).toString().padStart(2, '0')}"
    }

    /** Always m:ss, for stats and time bars. */
    fun clock(seconds: Double): String {
        val s = seconds.roundToInt().coerceAtLeast(0)
        return "${s / 60}:${(s % 60).toString().padStart(2, '0')}"
    }

    /** "0.9 s" for a check latency in milliseconds. */
    fun latency(ms: Int): String = "%.1f s".format(java.util.Locale.US, ms / 1000.0)

    /** "1 mistake" or "2 mistakes". */
    fun count(n: Int, one: String, many: String = one + "s"): String = "$n ${if (n == 1) one else many}"
}
