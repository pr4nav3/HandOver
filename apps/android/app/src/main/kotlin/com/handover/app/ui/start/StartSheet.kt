package com.handover.app.ui.start

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Devices
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Science
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.handover.app.core.HubUrl
import com.handover.app.core.LessonSummary
import com.handover.app.ui.account.QrImage
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.Pill
import com.handover.app.ui.components.Tone
import com.handover.app.ui.glasses.EyeglassesIcon
import com.handover.app.ui.glasses.GlassesLink
import com.handover.app.ui.glasses.GlassesPhase
import com.handover.app.ui.glasses.GlassesState
import com.handover.app.ui.glasses.rememberGlassesLink
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.Hairline
import com.handover.app.ui.theme.HandOver

/**
 * "How should HandOver see your hands?" as a bottom sheet. [confirm] is the button's words: "Start
 * Lesson" when the sheet opened from Start, "Done" when it only changes the camera.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CameraChoiceSheet(
    hub: HubUrl?,
    current: CameraChoice?,
    confirm: String,
    onConfirm: (CameraChoice) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    var picked by remember { mutableStateOf(current ?: CameraChoice.ThisPhone) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = HandOver.colors.raised) {
        // The toolkit only starts while the glasses option is open, so other choices never touch Bluetooth.
        val glasses: GlassesLink? = if (picked == CameraChoice.Glasses) rememberGlassesLink() else null
        CameraChoiceBody(
            picked = picked,
            onPick = { picked = it },
            hub = hub,
            glasses = glasses?.state,
            onConnectGlasses = { glasses?.next?.invoke() },
            confirm = confirm,
            onConfirm = { onConfirm(picked) },
            modifier = Modifier.verticalScroll(rememberScrollState()),
        )
    }
}

/** The sheet's content, stateless so screenshot tests draw every option. */
@Composable
fun CameraChoiceBody(
    picked: CameraChoice,
    onPick: (CameraChoice) -> Unit,
    hub: HubUrl?,
    glasses: GlassesState?,
    onConnectGlasses: () -> Unit,
    confirm: String,
    onConfirm: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = HandOver.colors
    Column(modifier.fillMaxWidth().padding(horizontal = HOSpace.xl).padding(bottom = HOSpace.l).navigationBarsPadding()) {
        Text("How should HandOver see your hands?", style = HandOver.type.title, color = c.ink, modifier = Modifier.semantics { heading() })
        Spacer(Modifier.height(HOSpace.xs))
        Text("A camera watches your hands so the hub can tell when each step is done.", style = HandOver.type.callout, color = c.ink2)
        Spacer(Modifier.height(HOSpace.l))
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
            CameraChoice.entries.forEach { choice ->
                OptionRow(choice, choice == picked) { onPick(choice) }
            }
        }
        Spacer(Modifier.height(HOSpace.l))
        when (picked) {
            CameraChoice.ThisPhone -> Hint("HandOver asks for the camera when the lesson starts. The video goes only to the hub.")
            CameraChoice.Glasses -> GlassesSetup(glasses, onConnectGlasses)
            CameraChoice.OtherDevice -> OtherDevice(hub)
        }
        Spacer(Modifier.height(HOSpace.xl))
        HOButton(confirm, onConfirm, Modifier.fillMaxWidth(), ButtonKind.Primary, ButtonSize.Large)
    }
}

private fun CameraChoice.icon(): ImageVector = when (this) {
    CameraChoice.ThisPhone -> Icons.Outlined.PhoneAndroid
    CameraChoice.Glasses -> EyeglassesIcon
    CameraChoice.OtherDevice -> Icons.Outlined.Devices
}

@Composable
private fun OptionRow(choice: CameraChoice, selected: Boolean, onClick: () -> Unit) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(HORadius.card)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 72.dp).clip(shape)
            .background(if (selected) c.accentSoft else c.paper)
            .border(if (selected) 1.5.dp else Hairline, if (selected) c.accent else c.line, shape)
            .selectable(selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = HOSpace.l, vertical = HOSpace.m),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(40.dp).background(c.raised, CircleShape), contentAlignment = Alignment.Center) {
            Icon(choice.icon(), null, tint = if (selected) c.accentInk else c.ink2, modifier = Modifier.size(22.dp))
        }
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(choice.title, style = HandOver.type.headline, color = c.ink)
                if (choice == CameraChoice.Glasses) {
                    Spacer(Modifier.width(HOSpace.s))
                    Pill("Experimental", Tone.Caution, icon = Icons.Outlined.Science)
                }
            }
            Text(choice.line, style = HandOver.type.callout, color = c.ink2)
        }
        RadioButton(selected, onClick = null, colors = RadioButtonDefaults.colors(selectedColor = c.accent, unselectedColor = c.ink3))
    }
}

@Composable
private fun Hint(text: String) = Text(text, style = HandOver.type.footnote, color = HandOver.colors.ink2)

/** Setup steps until HandOver is connected to the glasses, then a short ready line. */
@Composable
private fun GlassesSetup(state: GlassesState?, onConnect: () -> Unit) {
    val c = HandOver.colors
    val phase = state?.phase ?: GlassesPhase.NotRegistered
    if (phase in GlassesLink.ConnectedPhases) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.CheckCircle, null, tint = c.good, modifier = Modifier.size(20.dp))
            Spacer(Modifier.width(HOSpace.s))
            Text("${state?.device?.name ?: "Glasses"} connected. Put them on before you start.", style = HandOver.type.callout, color = c.ink)
        }
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
        Text("Set up once", style = HandOver.type.section, color = c.ink2)
        NumberedLine(1, "Pair your glasses in the Meta AI app.")
        NumberedLine(2, "In Meta AI, open Settings, then App Info. Tap the version 5 times and turn on Developer Mode.")
        NumberedLine(3, "Tap Connect, then approve HandOver in Meta AI.")
        val label = when (phase) {
            GlassesPhase.NeedsBluetooth -> "Allow Bluetooth"
            GlassesPhase.MetaAiMissing -> "Get Meta AI"
            GlassesPhase.Registering -> "Waiting for Meta AI"
            GlassesPhase.NoDevice -> "Try Again"
            else -> "Connect"
        }
        val note = when (phase) {
            GlassesPhase.NeedsBluetooth -> "HandOver needs Bluetooth to reach your glasses."
            GlassesPhase.MetaAiMissing -> "The Meta AI app is not on this phone yet."
            GlassesPhase.DeveloperMode -> "Meta AI said no. Check that Developer Mode is on, then try again."
            GlassesPhase.NoDevice -> "Connected, but the glasses are not nearby. Put them on and try again."
            GlassesPhase.Failed -> state?.detail ?: "The glasses did not answer. Try again."
            else -> null
        }
        if (note != null) Text(note, style = HandOver.type.footnote, color = c.caution)
        Spacer(Modifier.height(HOSpace.xs))
        HOButton(label, onConnect, Modifier.fillMaxWidth(), ButtonKind.Secondary, ButtonSize.Regular, enabled = phase != GlassesPhase.Registering, icon = EyeglassesIcon)
        Hint("Experimental: not yet tested with real glasses. You can switch to This phone any time.")
    }
}

@Composable
private fun NumberedLine(n: Int, text: String) {
    val c = HandOver.colors
    Row(verticalAlignment = Alignment.Top) {
        Box(Modifier.size(22.dp).background(c.well, CircleShape), contentAlignment = Alignment.Center) {
            Text("$n", style = HandOver.type.footnote, color = c.ink)
        }
        Spacer(Modifier.width(HOSpace.s))
        Text(text, style = HandOver.type.callout, color = c.ink, modifier = Modifier.weight(1f).padding(top = 1.dp))
    }
}

/** A QR code and link to the hub's camera page, and the Be the Camera option for a second phone. */
@Composable
private fun OtherDevice(hub: HubUrl?) {
    val c = HandOver.colors
    if (hub == null) {
        Hint("Connect to a hub first. Then this shows a code to scan.")
        return
    }
    val link = StartFlow.captureLink(hub)
    Row(verticalAlignment = Alignment.CenterVertically) {
        QrImage(link, 112.dp)
        Spacer(Modifier.width(HOSpace.l))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HOSpace.xs)) {
            Text("Scan with the other device", style = HandOver.type.headline, color = c.ink)
            Text(link, style = HandOver.type.code, color = c.accentInk, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text("If the browser warns about the page, tap Advanced, then continue.", style = HandOver.type.footnote, color = c.ink2)
        }
    }
    Spacer(Modifier.height(HOSpace.m))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Outlined.Videocam, null, tint = c.ink2, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(HOSpace.s))
        Hint("Second phone with HandOver? Open Be the Camera on it instead.")
    }
}

/** "Camera: This phone   Change", shown under Start and on the empty Learn screen. */
@Composable
fun CameraRow(choice: CameraChoice?, onChange: () -> Unit, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    val shape = RoundedCornerShape(HORadius.control)
    Row(
        modifier.fillMaxWidth().heightIn(min = 48.dp).clip(shape).border(Hairline, c.line, shape)
            .clickable(onClickLabel = "Change camera", onClick = onChange).padding(horizontal = HOSpace.m),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(choice?.icon() ?: Icons.Outlined.Videocam, null, tint = c.ink2, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(HOSpace.s))
        Text(StartFlow.cameraRow(choice), style = HandOver.type.callout, color = c.ink, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text("Change", style = HandOver.type.bodyMedium, color = c.accentInk)
    }
}

/** "Pick a lesson": the hub's lessons in a sheet, for the Learn tab and Home's Learn a Lesson. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LessonPickerSheet(lessons: List<LessonSummary>, loading: Boolean, onPick: (LessonSummary) -> Unit, onDismiss: () -> Unit) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = HandOver.colors.raised) {
        LessonPickerBody(lessons, loading, onPick, Modifier.verticalScroll(rememberScrollState()))
    }
}

@Composable
fun LessonPickerBody(lessons: List<LessonSummary>, loading: Boolean, onPick: (LessonSummary) -> Unit, modifier: Modifier = Modifier) {
    val c = HandOver.colors
    Column(modifier.fillMaxWidth().padding(horizontal = HOSpace.xl).padding(bottom = HOSpace.xl).navigationBarsPadding()) {
        Text("Pick a lesson", style = HandOver.type.title, color = c.ink, modifier = Modifier.semantics { heading() })
        Spacer(Modifier.height(HOSpace.xs))
        Text("Everyone following this hub sees the lesson you pick.", style = HandOver.type.callout, color = c.ink2)
        Spacer(Modifier.height(HOSpace.m))
        when {
            lessons.isEmpty() && loading -> Hint("Loading lessons.")
            lessons.isEmpty() -> Hint("No lessons on this hub yet. Someone needs to teach one first.")
            else -> lessons.forEach { l ->
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 56.dp).clip(RoundedCornerShape(HORadius.control)).clickable { onPick(l) }.padding(vertical = HOSpace.s),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(l.title.ifBlank { l.id }, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(if (l.steps == 1) "1 step" else "${l.steps} steps", style = HandOver.type.footnote, color = c.ink2)
                    }
                    Text("Start", style = HandOver.type.bodyMedium, color = c.accentInk)
                }
            }
        }
    }
}
