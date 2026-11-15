package com.handover.app.ui.pairing

import com.handover.app.core.HubUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/** A hub to connect to, with the name the QR code or link gave it (the hub has no name endpoint yet). */
data class PairingTarget(val hub: HubUrl, val name: String? = null) {
    /** What to call the hub on screen: its name, else its host. */
    val title: String get() = name?.takeIf { it.isNotBlank() } ?: hub.host
}

/** What a scanned code, a pasted text or an opened link turned out to be. */
sealed interface PairingLink {
    /** A hub address: `handover://connect?...`, `http://ip:8000`, or a bare `ip:port`. */
    data class Connect(val target: PairingTarget) : PairingLink

    /** An org invite: `handover://join?code=...`, with the hub address when the code came from another hub. */
    data class Join(val code: String, val target: PairingTarget?) : PairingLink

    companion object {
        /**
         * Reads [raw] from the QR scanner, the clipboard or a deep link. Hub parsing itself is
         * [HubUrl.parse]; this adds the `name` the QR carries and the `join` links. Null when the
         * text is not something HandOver can use.
         */
        fun parse(raw: String?): PairingLink? {
            val text = raw?.trim().orEmpty()
            if (text.isEmpty()) return null
            val prefix = HubUrl.SCHEME + "://"
            if (text.startsWith(prefix, ignoreCase = true)) {
                val url = ("http://" + text.substring(prefix.length)).toHttpUrlOrNull() ?: return null
                if (url.host.equals("join", ignoreCase = true)) {
                    val code = InviteCode.normalize(url.queryParameter("code")) ?: return null
                    val target = url.queryParameter("host")?.let { targetOf(text.replaceFirst("://join", "://connect", ignoreCase = true), url.queryParameter("name")) }
                    return Join(code, target)
                }
                return targetOf(text, url.queryParameter("name"))?.let(::Connect)
            }
            return targetOf(text, null)?.let(::Connect)
        }

        /** Text with a user part or a non-web scheme (mailto:, tel:) is never a hub, whatever the URL parser makes of it. */
        private fun looksLikeHub(text: String): Boolean {
            if ('@' in text) return false
            val colon = text.indexOf(':')
            if (colon < 0 || text.startsWith("[")) return true
            val head = text.substring(0, colon)
            return text.regionMatches(colon, "://", 0, 3) || head.all { it.isLetterOrDigit() || it == '.' || it == '-' } && text.substring(colon + 1).takeWhile(Char::isDigit).isNotEmpty()
        }

        private fun targetOf(text: String, name: String?): PairingTarget? =
            if (!looksLikeHub(text)) null else HubUrl.parse(text)?.let { PairingTarget(it, name?.trim()?.take(60)?.takeIf(String::isNotEmpty)) }

        /** True when the typed address field can be connected (SCREENS.md 3.2: Connect stays disabled until then). */
        fun isTypedAddress(text: String): Boolean = HubUrl.parse(text) != null
    }
}

/**
 * An org invite code. The hub makes them with `secrets.token_urlsafe(12)`: 16 characters of letters
 * (upper and lower case matter), digits, `-` and `_`, and keeps only a hash, so the code must reach it
 * exactly. People see it in groups of four and may paste it with spaces; only the spaces are dropped.
 */
object InviteCode {
    const val MIN = 4
    const val MAX = 64

    fun normalize(raw: String?): String? {
        val code = raw.orEmpty().filterNot(Char::isWhitespace)
        if (code.any { !(it.isLetterOrDigit() && it.code < 128) && it != '-' && it != '_' }) return null
        return code.takeIf { it.length in MIN..MAX }
    }

    fun grouped(code: String): String = code.chunked(4).joinToString(" ")

    /** For screen readers: one character at a time (DESIGN.md 3.25). */
    fun spoken(code: String): String = "Invite code " + code.toList().joinToString(" ")
}
