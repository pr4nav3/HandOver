package com.handover.app.ui.start

import android.content.Context
import androidx.core.content.edit
import com.handover.app.core.HubUrl

/**
 * How HandOver sees the learner's hands while they follow a lesson. Chosen once in the start sheet,
 * remembered on this device, and changed from the "Camera: This phone, Change" row.
 */
enum class CameraChoice(val title: String, val line: String) {
    /** This phone's back camera, propped up facing the work. Learn streams it while showing the clip. */
    ThisPhone("This phone", "Prop it up so the back camera sees your hands."),

    /** Ray-Ban Meta glasses through the Meta toolkit. Experimental: not tested on real glasses yet. */
    Glasses("Meta glasses", "Wear them. Guidance plays in their speakers."),

    /** A second phone or laptop camera: the hub's capture page, or Be the Camera on another phone. */
    OtherDevice("Another device", "Use a second phone or a laptop camera."),
    ;

    companion object {
        private const val KEY = "camera_choice"

        /** The saved choice, or null before the person has picked one. */
        fun load(context: Context): CameraChoice? =
            context.getSharedPreferences("handover", Context.MODE_PRIVATE).getString(KEY, null)?.let(::parse)

        fun save(context: Context, choice: CameraChoice) =
            context.getSharedPreferences("handover", Context.MODE_PRIVATE).edit { putString(KEY, choice.name) }

        fun parse(raw: String?): CameraChoice? = entries.firstOrNull { it.name == raw }
    }
}

/** Pure helpers for the start flow, tested on the JVM. */
object StartFlow {
    /**
     * The hub's camera page for a second device. Phone browsers only open the camera on a secure page,
     * so a plain hub address points at the hub's https port (8443, CONTRACT.md section 1); a hub
     * already on https (a tunnel) keeps its own address.
     */
    fun captureLink(hub: HubUrl): String =
        if (hub.secure) hub.http("capture").toString()
        else hub.copy(port = HubUrl.HUB_HTTPS_PORT, secure = true).http("capture").toString()

    /** "Camera: This phone", for the row under Start. */
    fun cameraRow(choice: CameraChoice?): String = "Camera: ${choice?.title ?: "Not chosen"}"

    /** Whether Start must ask first: only before the person has ever chosen. */
    fun mustAsk(choice: CameraChoice?): Boolean = choice == null
}
