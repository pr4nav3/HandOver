package com.handover.app.ui.camera

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.outlined.Cameraswitch
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.LockOpen
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.MobileOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.onLongClick
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.EmptyState
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.StatusBadge
import com.handover.app.ui.components.StatusDot
import com.handover.app.ui.components.Tone
import com.handover.app.ui.components.glass
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.paper
import kotlinx.coroutines.withTimeoutOrNull

/** Where this camera stands with the hub. */
enum class CameraPhase { Connecting, Sending, Paused, Standby, Reconnecting, Replaced }

/** Everything Camera Mode draws, in one value. */
data class CameraUi(
    val hubName: String,
    val phase: CameraPhase,
    /** Frames per second actually sent over the last 5 s. */
    val fps: Double = 0.0,
    /** The size of the last frame sent. */
    val size: FrameSize? = null,
    val source: String = "Phone back camera",
    /** "Step 4 of 8: Fold all four corners to center", or null with no lesson. */
    val stepTitle: String? = null,
    val badge: BadgeState = BadgeState.Watching,
    val canBack: Boolean = false,
    val canNext: Boolean = false,
    val lastStep: Boolean = false,
    val warm: Boolean = false,
    val powerSaver: Boolean = false,
    val statsShown: Boolean = true,
    val locked: Boolean = false,
    /** Sending from the glasses: the source chip shows the glasses symbol. */
    val glasses: Boolean = false,
    /** A one-line notice that leaves on its own, such as the glasses fallback. */
    val toast: String? = null,
)

/** The sources the chip's menu offers, in order (SCREENS.md 10). */
val CameraSources = listOf("Phone back camera", "Phone front camera", "Glasses")

/**
 * Camera Mode's layout (SCREENS.md 10), forced dark over the preview: capture indicator, stats and
 * source chips at the top; step title, badge, Back and Next in a glass panel at the bottom.
 */
@Composable
fun CameraModeContent(
    ui: CameraUi,
    modifier: Modifier = Modifier,
    onTouch: () -> Unit = {},
    onNext: () -> Unit = {},
    onBack: () -> Unit = {},
    onToggleStats: () -> Unit = {},
    onSource: (Int) -> Unit = {},
    onLock: (Boolean) -> Unit = {},
    onSendAgain: () -> Unit = {},
    onClose: (() -> Unit)? = null,
    glassesCard: (@Composable () -> Unit)? = null,
    preview: @Composable () -> Unit = {},
) {
    Box(
        modifier.fillMaxSize().background(Color.Black).pointerInput(Unit) {
            awaitEachGesture { awaitFirstDown(requireUnconsumed = false); onTouch() }
        },
    ) {
        SentFrame(ui.size) { preview() }
        if (ui.phase == CameraPhase.Replaced) {
            ReplacedPanel(onSendAgain)
            return@Box
        }
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(HOSpace.m)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                    CaptureIndicator(ui)
                    if (!ui.locked) {
                        Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                            if ((ui.phase == CameraPhase.Sending || ui.phase == CameraPhase.Standby) && ui.fps > 0) StatsChip(ui, onToggleStats)
                            SourceChip(ui, onSource)
                        }
                    }
                }
                if (onClose != null && !ui.locked) {
                    Box(Modifier.size(HOSize.touch).clickable(onClickLabel = "Close Be the Camera", onClick = onClose), contentAlignment = Alignment.Center) {
                        Box(Modifier.size(40.dp).glass(), contentAlignment = Alignment.Center) { Icon(Icons.Rounded.Close, "Close", tint = Color.White) }
                    }
                }
            }
            val banner = when {
                ui.phase == CameraPhase.Standby -> "Another camera is active. This one takes over if it stops."
                ui.warm -> "Phone is warm. Sending fewer frames."
                ui.powerSaver -> "Battery Saver is on. The screen dims to save power."
                else -> null
            }
            if (banner != null && !ui.locked) {
                Spacer(Modifier.height(HOSpace.s))
                Text(
                    banner, style = HandOver.type.footnote, color = Color.White,
                    modifier = Modifier.glass(RoundedCornerShape(HORadius.control)).padding(horizontal = HOSpace.m, vertical = HOSpace.s).semantics { liveRegion = LiveRegionMode.Polite },
                )
            }
            Spacer(Modifier.weight(1f))
            if (ui.toast != null) {
                Text(
                    ui.toast, style = HandOver.type.callout, color = Color.White,
                    modifier = Modifier.align(Alignment.CenterHorizontally).glass(RoundedCornerShape(26.dp)).padding(horizontal = HOSpace.l, vertical = HOSpace.m)
                        .semantics { liveRegion = LiveRegionMode.Polite },
                )
                Spacer(Modifier.height(HOSpace.m))
            }
            if (glassesCard != null && !ui.locked) {
                glassesCard()
                Spacer(Modifier.height(HOSpace.m))
            }
            AnimatedVisibility(!ui.locked, enter = fadeIn(), exit = fadeOut()) { ControlPanel(ui, onNext, onBack, onLock) }
            if (ui.locked) LockedPill(onUnlock = { onLock(false) }, modifier = Modifier.align(Alignment.CenterHorizontally))
        }
    }
}

/**
 * The preview fitted to the sent frame's shape, with a thin white 30% frame around exactly what is
 * sent. Before the first frame the preview fills the screen.
 */
@Composable
private fun SentFrame(size: FrameSize?, preview: @Composable () -> Unit) {
    BoxWithConstraints(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        val aspect = size?.let { it.width.toFloat() / it.height } ?: (maxWidth / maxHeight)
        val boxAspect = maxWidth / maxHeight
        val w = if (aspect > boxAspect) maxWidth else maxHeight * aspect
        val h = if (aspect > boxAspect) maxWidth / aspect else maxHeight
        Box(
            Modifier.size(w, h).drawWithFrame(size != null),
            contentAlignment = Alignment.Center,
        ) { preview() }
    }
}

private fun Modifier.drawWithFrame(show: Boolean): Modifier = if (!show) this else drawWithContent {
    drawContent()
    drawRoundRect(Color.White.copy(alpha = 0.3f), Offset.Zero, Size(size.width, size.height), CornerRadius(2f), style = Stroke(1.dp.toPx()))
}

@Composable
private fun CaptureIndicator(ui: CameraUi) {
    val (dot, text) = when (ui.phase) {
        CameraPhase.Connecting -> null to "Connecting to ${ui.hubName}"
        CameraPhase.Sending -> (if (ui.fps > 0) HandOver.colors.record else Color(0xFF8E8E93)) to when {
            ui.fps > 0 -> "Sending to ${ui.hubName}"
            ui.glasses -> "Waiting for the glasses"
            else -> "Starting the camera"
        }
        CameraPhase.Standby -> Color(0xFF8E8E93) to "Standby"
        CameraPhase.Reconnecting -> HandOver.colors.caution to "Reconnecting"
        CameraPhase.Paused, CameraPhase.Replaced -> Color(0xFF8E8E93) to "Paused"
    }
    Row(
        Modifier.glass().heightIn(min = 36.dp).padding(horizontal = HOSpace.m, vertical = 7.dp).semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (dot == null) CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(12.dp))
        else StatusDot(dot, size = 10.dp)
        Spacer(Modifier.width(HOSpace.s))
        Text(text, style = HandOver.type.callout.copy(fontWeight = FontWeight.SemiBold), color = Color.White, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun StatsChip(ui: CameraUi, onClick: () -> Unit) {
    val activeWord = if (ui.phase == CameraPhase.Sending) "Active camera" else "Standby"
    val text = if (ui.statsShown) listOfNotNull(FpsMeter.label(ui.fps), ui.size?.toString(), activeWord).joinToString(", ") else FpsMeter.label(ui.fps)
    Chip(text, null, label = "Stats. $text. Tap to ${if (ui.statsShown) "hide" else "show"} details", onClick = onClick)
}

@Composable
private fun Chip(text: String, icon: androidx.compose.ui.graphics.vector.ImageVector?, label: String, onClick: () -> Unit, trailing: androidx.compose.ui.graphics.vector.ImageVector? = null) {
    Row(
        Modifier.glass().heightIn(min = 32.dp).clickable(onClickLabel = label, onClick = onClick).padding(horizontal = HOSpace.m, vertical = 6.dp)
            .semantics(mergeDescendants = true) { contentDescription = label },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            Icon(icon, null, tint = Color.White, modifier = Modifier.size(15.dp))
            Spacer(Modifier.width(6.dp))
        }
        Text(text, style = HandOver.type.footnote.copy(fontFeatureSettings = "tnum"), color = Color.White, maxLines = 1)
        if (trailing != null) {
            Spacer(Modifier.width(6.dp))
            Icon(trailing, null, tint = Color.White.copy(alpha = 0.8f), modifier = Modifier.size(15.dp))
        }
    }
}

/** The source chip and its menu: phone back, phone front, glasses. */
@Composable
private fun SourceChip(ui: CameraUi, onSource: (Int) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        Chip(ui.source, if (ui.glasses) com.handover.app.ui.glasses.EyeglassesIcon else Icons.Outlined.PhoneAndroid, label = "${ui.source}. Change source", onClick = { open = true }, trailing = Icons.Outlined.Cameraswitch)
        DropdownMenu(open, { open = false }) {
            CameraSources.forEachIndexed { i, label -> DropdownMenuItem({ Text(label) }, { open = false; onSource(i) }) }
        }
    }
}

@Composable
private fun ControlPanel(ui: CameraUi, onNext: () -> Unit, onBack: () -> Unit, onLock: (Boolean) -> Unit) {
    Column(
        Modifier.fillMaxWidth().glass(RoundedCornerShape(HORadius.panel)).padding(HOSpace.l),
        verticalArrangement = Arrangement.spacedBy(HOSpace.m),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HOSpace.xs)) {
                Text("Be the Camera", style = HandOver.type.section, color = Color.White.copy(alpha = 0.7f))
                if (ui.stepTitle != null) {
                    Text(ui.stepTitle, style = HandOver.type.headline, color = Color.White, maxLines = 2, overflow = TextOverflow.Ellipsis)
                } else {
                    Text("Point this phone at the hands doing the task", style = HandOver.type.headline, color = Color.White)
                    Text("No lesson running yet. Start one on another screen and steps show here.", style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.7f))
                }
            }
            Box(Modifier.size(HOSize.touch).clickable(onClickLabel = "Lock controls") { onLock(true) }, contentAlignment = Alignment.Center) {
                Icon(Icons.Outlined.LockOpen, "Lock controls", tint = Color.White.copy(alpha = 0.85f), modifier = Modifier.size(20.dp))
            }
        }
        if (ui.stepTitle != null) StatusBadge(ui.badge, onVideo = true)
        Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
            if (ui.canBack) HOButton("Back", onBack, kind = ButtonKind.Glass, size = ButtonSize.Large, icon = Icons.AutoMirrored.Rounded.ArrowBack, modifier = Modifier.weight(1f))
            HOButton(
                if (ui.lastStep) "Finish" else "Next", onNext, kind = ButtonKind.Primary, size = ButtonSize.Large, enabled = ui.canNext,
                modifier = Modifier.weight(if (ui.canBack) 1.6f else 1f),
            )
        }
    }
}

/** Locked: only this pill shows. Touch and hold 1 s to unlock (SCREENS.md 10). */
@Composable
private fun LockedPill(onUnlock: () -> Unit, modifier: Modifier = Modifier) {
    var holding by remember { mutableStateOf(false) }
    Row(
        modifier.glass().heightIn(min = HOSize.touch).padding(horizontal = HOSpace.l)
            .semantics { contentDescription = "Unlock, double tap and hold"; onLongClick("Unlock") { onUnlock(); true } }
            .pointerInput(Unit) {
                detectTapGestures(onPress = {
                    holding = true
                    val released = withTimeoutOrNull(1_000) { tryAwaitRelease() }
                    holding = false
                    if (released == null) onUnlock()
                })
            },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.Lock, null, tint = Color.White, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(HOSpace.s))
        Text(if (holding) "Keep holding" else "Locked. Touch and hold to unlock", style = HandOver.type.callout, color = Color.White)
    }
}

@Composable
private fun ReplacedPanel(onSendAgain: () -> Unit) {
    Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.6f)), contentAlignment = Alignment.Center) {
        Column(
            Modifier.padding(HOSpace.xl).widthIn(max = 360.dp).glass(RoundedCornerShape(HORadius.panel)).padding(HOSpace.xl),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.m),
        ) {
            Icon(Icons.Rounded.MobileOff, null, tint = Color.White, modifier = Modifier.size(40.dp))
            Text("Another device took over", style = HandOver.type.title, color = Color.White, textAlign = TextAlign.Center)
            Text("This phone stopped sending. Tap to send again.", style = HandOver.type.callout, color = Color.White.copy(alpha = 0.75f), textAlign = TextAlign.Center)
            Spacer(Modifier.height(HOSpace.xs))
            PrimaryButton("Send Again", onSendAgain, fullWidth = true)
        }
    }
}

/** No hub yet: Camera Mode needs one. */
@Composable
fun CameraNoHub(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().paper(), contentAlignment = Alignment.Center) {
        EmptyState("Not connected yet", "The hub is HandOver running on a computer nearby. Connect to it in Settings, then this phone can be the camera.", icon = Icons.Outlined.WifiOff, tone = Tone.Caution)
    }
}

/** The person said Not Now to the camera. */
@Composable
fun CameraDeclined(onTryAgain: () -> Unit, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize().paper(), contentAlignment = Alignment.Center) {
        EmptyState("Camera is off", "Be the Camera sends what this phone sees to the hub, so it can check each step. Nothing is saved on the phone.", icon = Icons.Outlined.PhotoCamera) {
            PrimaryButton("Use the Camera", onTryAgain)
        }
    }
}
