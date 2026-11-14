package com.handover.app.core

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * Where the hub is. Built from whatever the person has: a typed address, a scanned QR code, or a
 * handover:// link. Everything after the host and port is dropped; the app knows the hub's paths.
 *
 * Accepted:
 * - `192.168.1.20`, `192.168.1.20:8000`, `mac.local`, `[fe80::1]:8000` (port 8000 when left out)
 * - `http://...`, `https://...`, `ws://...`, `wss://...` with any path or query, such as the
 *   capture page QR `https://192.168.1.20:8443/capture?pair=4821`. Without a port, http means the
 *   hub's 8000 and https means 443 (a tunnel)
 * - `handover://connect?host=192.168.1.20&port=8000` and `handover://192.168.1.20:8000`
 *
 * The hub's https port 8443 uses a self-signed certificate that Android does not trust, and the same
 * hub serves the same session over plain http on 8000 (CONTRACT.md section 1), so https on 8443
 * becomes http on 8000. Any other https address (a tunnel with a real certificate) stays https.
 */
data class HubUrl(val host: String, val port: Int, val secure: Boolean = false) {

    private val base: HttpUrl
        get() = HttpUrl.Builder().scheme(if (secure) "https" else "http").host(host).port(port).build()

    /** `http://host:port/`, for REST and lesson files. */
    val httpBase: String get() = base.toString()

    /** What to show the person and store: `192.168.1.20:8000`, with `https://` only when secure. */
    val display: String
        get() {
            val h = if (':' in host) "[$host]" else host
            return (if (secure) "https://" else "") + "$h:$port"
        }

    /** The REST or file URL for [path], such as `api/lessons` or `lessons/<id>/clips/01.mp4`. */
    fun http(path: String): HttpUrl = base.newBuilder().addPathSegments(path.trimStart('/')).build()

    val uiSocket: String get() = socket("ws/ui")
    val cameraSocket: String get() = socket("ws/camera")

    private fun socket(path: String): String =
        http(path).toString().replaceFirst(if (secure) "https://" else "http://", if (secure) "wss://" else "ws://")

    companion object {
        const val DEFAULT_PORT = 8000
        const val HUB_HTTPS_PORT = 8443
        const val SCHEME = "handover"

        /** The hub address in [raw], or null when there is none. */
        fun parse(raw: String?): HubUrl? {
            val text = raw?.trim().orEmpty()
            if (text.isEmpty() || text.any { it.isWhitespace() }) return null
            val schemeEnd = text.indexOf("://")
            val scheme = if (schemeEnd > 0) text.substring(0, schemeEnd).lowercase() else null
            return when (scheme) {
                null -> fromHttp("http://$text", portGiven = hasPort(text))
                "http", "https" -> fromHttp(text, portGiven = hasPort(text.substring(schemeEnd + 3)))
                "ws", "wss" -> {
                    val rest = text.substring(schemeEnd + 3)
                    fromHttp((if (scheme == "wss") "https://" else "http://") + rest, portGiven = hasPort(rest))
                }
                SCHEME -> fromDeepLink(text.substring(schemeEnd + 3))
                else -> null
            }
        }

        private fun fromDeepLink(rest: String): HubUrl? {
            val url = "http://$rest".toHttpUrlOrNull() ?: return null
            val host = url.queryParameter("host")
            if (host != null) {
                // handover://connect?host=...&port=...&secure=1
                val port = url.queryParameter("port")?.let { it.toIntOrNull() ?: return null } ?: DEFAULT_PORT
                val secure = url.queryParameter("secure") in setOf("1", "true")
                val target = (if (secure) "https://" else "http://") + bracketed(host) + ":" + port
                return fromHttp(target, portGiven = true)
            }
            if (url.host == "connect") return null
            return fromHttp("http://$rest", portGiven = hasPort(rest))
        }

        private fun fromHttp(text: String, portGiven: Boolean): HubUrl? {
            val url = text.toHttpUrlOrNull() ?: return null
            if (url.host.isEmpty()) return null
            var secure = url.isHttps
            var port = if (portGiven) url.port else DEFAULT_PORT
            if (secure && portGiven && port == HUB_HTTPS_PORT) {
                secure = false
                port = DEFAULT_PORT
            } else if (secure && !portGiven) {
                port = 443
            }
            return HubUrl(url.host, port, secure)
        }

        /** Whether the authority part of [rest] (no scheme) names a port. */
        private fun hasPort(rest: String): Boolean {
            val authority = rest.substringBefore('/').substringBefore('?').substringBefore('#').substringAfter('@')
            return if (authority.startsWith("[")) authority.substringAfter(']').startsWith(":") else ':' in authority
        }

        private fun bracketed(host: String): String = if (':' in host && !host.startsWith("[")) "[$host]" else host
    }
}
