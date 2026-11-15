package com.handover.app.ui.shell

import com.handover.app.core.HubUrl
import com.handover.app.ui.pairing.PairingLink
import com.handover.app.ui.pairing.PairingTarget
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * What a handover:// link that opened the app means. Pure, so MainActivity's routing is tested on the JVM.
 *
 * - `handover://connect?host=...&port=...&name=...` and `handover://192.168.1.20:8000`: a hub, connect.
 * - `handover://join?code=...` (with the hub's host when it came from another hub): open Join.
 * - Anything else on the scheme: the Meta AI app returning after glasses registration. It must never
 *   become a connect, so a bare word host (`handover://mwdat`) is not read as a hub name.
 */
sealed interface AppLink {
    data class Connect(val target: PairingTarget) : AppLink
    data class Join(val code: String, val target: PairingTarget?) : AppLink
    data object Glasses : AppLink

    companion object {
        const val SCHEME = HubUrl.SCHEME

        fun route(raw: String): AppLink? {
            val text = raw.trim()
            val prefix = "$SCHEME://"
            if (!text.startsWith(prefix, ignoreCase = true)) return null
            val url = ("http://" + text.substring(prefix.length)).toHttpUrlOrNull()
            val host = url?.host.orEmpty().lowercase()
            if (host == "join") return (PairingLink.parse(text) as? PairingLink.Join)?.let { Join(it.code, it.target) } ?: Glasses
            if (url != null && looksLikeHub(host, text, url.queryParameter("host"))) {
                (PairingLink.parse(text) as? PairingLink.Connect)?.let { return Connect(it.target) }
            }
            return Glasses
        }

        /**
         * A connect link names its hub with `connect?host=`, or puts an address in the authority: an IP,
         * a dotted name such as mac.local, `localhost`, or a host with an explicit port.
         */
        private fun looksLikeHub(host: String, text: String, hostParam: String?): Boolean {
            if (host == "connect") return hostParam != null
            if (host.isEmpty()) return false
            val authority = text.substringAfter("://").substringBefore('/').substringBefore('?').substringBefore('#')
            return '.' in host || ':' in host || host == "localhost" || authority.startsWith("[") || authority.substringAfterLast(']').contains(':')
        }
    }
}
