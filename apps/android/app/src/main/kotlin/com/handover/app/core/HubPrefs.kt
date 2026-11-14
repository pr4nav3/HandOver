package com.handover.app.core

import android.content.Context
import androidx.core.content.edit
import java.util.UUID

/** What the app remembers between launches. An interface so the ViewModel can be built in a JVM test. */
interface HubPrefs {
    /** The last hub the person connected to, as [HubUrl.display], or null. */
    var hubAddress: String?

    /** This phone's id for camera hello, made once and kept, so the hub can tell a reconnect from a second phone. */
    val deviceId: String
}

class SharedHubPrefs(context: Context) : HubPrefs {
    private val prefs = context.applicationContext.getSharedPreferences("handover", Context.MODE_PRIVATE)

    override var hubAddress: String?
        get() = prefs.getString(KEY_HUB, null)
        set(value) = prefs.edit { putString(KEY_HUB, value) }

    override val deviceId: String by lazy {
        prefs.getString(KEY_DEVICE, null) ?: "android-${UUID.randomUUID()}".also { prefs.edit { putString(KEY_DEVICE, it) } }
    }

    private companion object {
        const val KEY_HUB = "hub"
        const val KEY_DEVICE = "device_id"
    }
}
