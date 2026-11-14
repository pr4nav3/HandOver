package com.handover.app.ui.pairing

import com.handover.app.core.HubClient
import com.handover.app.core.HubException
import com.handover.app.core.HubUrl
import kotlinx.coroutines.CancellationException
import okhttp3.OkHttpClient
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

/** The answer to "is there a HandOver hub at this address?" (SCREENS.md 3.3). */
sealed interface ProbeResult {
    data class Connected(val lessons: Int) : ProbeResult

    /** Something answered, but not HandOver. */
    data object NotAHub : ProbeResult

    /** Nothing answered. [reason] is one plain sentence. */
    data class Unreachable(val reason: String) : ProbeResult
}

/** Checks a hub with `GET /api/lessons`, which every hub serves and returns a JSON array. */
object HubProbe {
    suspend fun probe(hub: HubUrl, http: OkHttpClient): ProbeResult = try {
        ProbeResult.Connected(HubClient(hub, http).lessons().size)
    } catch (e: CancellationException) {
        throw e
    } catch (e: HubException) {
        ProbeResult.NotAHub
    } catch (e: IOException) {
        classify(e)
    }

    internal fun classify(e: IOException): ProbeResult = when {
        e.message?.startsWith("unexpected reply") == true -> ProbeResult.NotAHub
        e is UnknownHostException -> ProbeResult.Unreachable("That name does not lead to a computer on this network.")
        e is SocketTimeoutException -> ProbeResult.Unreachable("The hub did not answer in time.")
        e is NoRouteToHostException -> ProbeResult.Unreachable("This device cannot see that address.")
        e is ConnectException -> ProbeResult.Unreachable("Nothing is listening at that address and port.")
        else -> ProbeResult.Unreachable("The connection failed.")
    }
}
