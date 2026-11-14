package com.handover.app.ui.glasses

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.BatteryChargingFull
import androidx.compose.material.icons.outlined.BatteryStd
import androidx.compose.material.icons.outlined.Thermostat
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.StatusDot
import com.handover.app.ui.components.glass
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver

/** What the card says and offers for one phase (SCREENS.md 12.2, with "phone" for "iPhone"). */
data class GlassesCopy(val title: String, val line: String?, val primary: String?, val secondary: String?, val busy: Boolean = false)

fun glassesCopy(s: GlassesState): GlassesCopy = when (s.phase) {
    GlassesPhase.NeedsBluetooth -> GlassesCopy("Ray-Ban Meta", "HandOver needs Bluetooth to reach your glasses.", "Allow Bluetooth", "Use Phone")
    GlassesPhase.MetaAiMissing -> GlassesCopy("Meta AI app needed", "Install the Meta AI app and pair your glasses there, then come back.", "Get Meta AI", "Use Phone")
    GlassesPhase.DeveloperMode -> GlassesCopy(
        "Turn on Developer Mode", "In the Meta AI app: Settings > App Info, tap the version 5 times, then turn on Developer Mode.", "Try Again", "Use Phone",
    )
    GlassesPhase.NotRegistered -> GlassesCopy("Ray-Ban Meta", "Not connected to HandOver. HandOver asks the Meta AI app for access to your glasses camera.", "Connect Glasses", "Use Phone")
    GlassesPhase.Registering -> GlassesCopy("Waiting for Meta AI", "Approve HandOver in the Meta AI app.", null, "Cancel", busy = true)
    GlassesPhase.NoDevice -> GlassesCopy("Glasses not found", "Put on your glasses and make sure they are connected to this phone.", "Try Again", "Use Phone")
    GlassesPhase.Ready -> GlassesCopy(s.device?.name ?: "Ray-Ban Meta", "Ready. The glasses send what you see to the hub.", "Use Glasses", "Use Phone")
    GlassesPhase.NeedsCameraPermission -> GlassesCopy("Allow camera access", "The glasses need permission to share their camera with HandOver.", "Allow", "Use Phone")
    GlassesPhase.Connecting -> GlassesCopy("Connecting", "Starting the glasses camera.", null, "Use Phone", busy = true)
    GlassesPhase.Streaming -> GlassesCopy(s.device?.name ?: "Glasses", null, null, null)
    GlassesPhase.Paused -> GlassesCopy("Paused", "The glasses paused the camera.", "Resume", "Use Phone")
    GlassesPhase.BatteryLow -> GlassesCopy("Glasses battery low", "Charge the glasses or switch to the phone camera.", null, "Use Phone")
    GlassesPhase.TooHot -> GlassesCopy("Glasses too hot", "Let them cool down, or switch to the phone camera.", null, "Use Phone")
    GlassesPhase.PowerLimit -> GlassesCopy("Glasses need a break", "They hit a power limit. Try again, or switch to the phone camera.", "Try Again", "Use Phone")
    GlassesPhase.Disconnected -> GlassesCopy("Glasses disconnected", s.detail, "Reconnect", "Use Phone")
    GlassesPhase.Failed -> GlassesCopy("Glasses did not start", s.detail ?: "Try again, or use the phone camera.", "Try Again", "Use Phone")
}

/**
 * The glasses card over the camera preview (DESIGN.md 3.17), forced dark like everything on video.
 * Battery and heat show only when the toolkit reports them (honesty rule in 3.17).
 */
@Composable
fun GlassesCard(state: GlassesState, onPrimary: () -> Unit, onSecondary: () -> Unit, modifier: Modifier = Modifier) {
    val copy = glassesCopy(state)
    Column(
        modifier.fillMaxWidth().glass(RoundedCornerShape(HORadius.panel)).padding(HOSpace.l).semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalArrangement = Arrangement.spacedBy(HOSpace.m),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(EyeglassesIcon, null, tint = Color.White, modifier = Modifier.size(32.dp).glass(RoundedCornerShape(9.dp)).padding(5.dp))
            Spacer(Modifier.width(HOSpace.m))
            Column(Modifier.weight(1f)) {
                Text(copy.title, style = HandOver.type.headline, color = Color.White)
                state.device?.let { DeviceMeters(it) }
            }
            if (copy.busy) CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(20.dp))
        }
        if (copy.line != null) Text(copy.line, style = HandOver.type.callout, color = Color.White.copy(alpha = 0.8f))
        if (copy.primary != null || copy.secondary != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                if (copy.secondary != null) HOButton(copy.secondary, onSecondary, kind = ButtonKind.Glass, size = ButtonSize.Regular, modifier = Modifier.weight(1f))
                if (copy.primary != null) HOButton(copy.primary, onPrimary, kind = ButtonKind.Primary, size = ButtonSize.Regular, modifier = Modifier.weight(1.4f))
            }
        }
    }
}

/** Battery, charging and heat, each only when reported. */
@Composable
private fun DeviceMeters(d: GlassesDevice) {
    val parts = buildList {
        if (d.battery != null) add((if (d.charging == true) Icons.Outlined.BatteryChargingFull else Icons.Outlined.BatteryStd) to "${d.battery}%")
        if (d.thermal != null) add(Icons.Outlined.Thermostat to d.thermal)
    }
    if (parts.isEmpty() && !d.connected) return
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        StatusDot(if (d.connected) HandOver.colors.good else Color(0xFF8E8E93), size = 7.dp)
        Text(if (d.connected) "Connected" else "Not connected", style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.8f))
        parts.forEach { (icon, text) ->
            Icon(icon, null, tint = Color.White.copy(alpha = 0.8f), modifier = Modifier.size(14.dp))
            Text(text, style = HandOver.type.footnote.copy(fontWeight = FontWeight.Medium), color = Color.White.copy(alpha = 0.8f))
        }
    }
}
