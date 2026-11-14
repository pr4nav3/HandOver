package com.handover.app.ui.pairing

import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.automirrored.outlined.HelpOutline
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.QrCodeScanner
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.handover.app.core.AppViewModel
import com.handover.app.core.HubUrl
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.QuietButton
import com.handover.app.ui.components.SecondaryButton
import com.handover.app.ui.components.card
import com.handover.app.ui.components.glass
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.onboarding.PermissionAsk
import com.handover.app.ui.onboarding.PermissionGate
import com.handover.app.ui.settings.FormGroup
import com.handover.app.ui.settings.FormSection
import com.handover.app.ui.settings.HOField
import com.handover.app.ui.settings.PushedBar
import com.handover.app.ui.settings.SharedKeyValue
import com.handover.app.ui.settings.SymbolTile
import com.handover.app.ui.settings.pressRow
import com.handover.app.ui.theme.HOSize
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.paper
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

/** Where a pairing flow starts: the scanner or the typed address page. */
enum class PairingStart { Scan, Typed }

/** The connection test's states (SCREENS.md 3.3). */
sealed interface ConnectState {
    data class Connecting(val title: String) : ConnectState
    data class Connected(val title: String, val lessons: Int) : ConnectState
    data class NotAHub(val title: String) : ConnectState
    data class Unreachable(val host: String, val reason: String) : ConnectState
}

/** The recent hubs store for this app, in the "handover_hubs" preferences file. */
@Composable
fun rememberRecentHubs(): RecentHubs {
    val context = LocalContext.current
    return remember(context) { RecentHubs(SharedKeyValue(context, "handover_hubs")) }
}

/**
 * Scan or type an address, test it, and connect the app. [onConnected] runs after the 1.2 s
 * success hold with the hub and its lesson count; the caller decides what comes next (onboarding
 * goes on to accounts, Settings closes). Close always means nothing changed.
 */
@Composable
fun PairingFlow(
    vm: AppViewModel,
    start: PairingStart,
    onClose: () -> Unit,
    onConnected: (PairingTarget, Int) -> Unit,
    onJoinCode: ((PairingLink.Join) -> Unit)? = null,
) {
    val recent = rememberRecentHubs()
    val hubs by recent.hubs.collectAsState()
    val scope = rememberCoroutineScope()
    val haptics = rememberHaptics()
    val http = remember { AppViewModel.defaultHttpClient().newBuilder().connectTimeout(4, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS).build() }
    var page by remember { mutableStateOf(start) }
    var typed by remember { mutableStateOf("") }
    var target by remember { mutableStateOf<PairingTarget?>(null) }
    var status by remember { mutableStateOf<ConnectState?>(null) }
    var attempt by remember { mutableStateOf(0) }

    fun test(t: PairingTarget) {
        target = t
        typed = t.hub.display.removePrefix("https://")
        status = ConnectState.Connecting(t.title)
        attempt++
    }

    LaunchedEffect(attempt) {
        val t = target ?: return@LaunchedEffect
        if (attempt == 0) return@LaunchedEffect
        val result = HubProbe.probe(t.hub, http)
        status = when (result) {
            is ProbeResult.Connected -> ConnectState.Connected(t.title, result.lessons)
            ProbeResult.NotAHub -> ConnectState.NotAHub(t.title)
            is ProbeResult.Unreachable -> ConnectState.Unreachable(t.hub.host, result.reason)
        }
        haptics.play(if (result is ProbeResult.Connected) HOHaptic.Success else HOHaptic.Error)
        if (result is ProbeResult.Connected) {
            recent.remember(t)
            vm.connect(t.hub.display)
            delay(1_200)
            onConnected(t, result.lessons)
        }
    }

    BackHandler(status != null || page == PairingStart.Typed && start == PairingStart.Scan) {
        when {
            status != null -> { status = null; attempt = 0 }
            else -> page = PairingStart.Scan
        }
    }

    val s = status
    when {
        s != null -> ConnectStatusScreen(
            s,
            onCancel = { status = null },
            onRetry = { target?.let(::test) },
            onEdit = { status = null; page = PairingStart.Typed },
        )
        page == PairingStart.Scan -> PermissionGate(PermissionAsk.Camera, onDecline = { page = PairingStart.Typed }) {
            ScanPage(
                onLink = { link ->
                    when (link) {
                        is PairingLink.Connect -> { scope.launch { delay(350); test(link.target) } ; true }
                        is PairingLink.Join -> if (onJoinCode != null) { onJoinCode(link); true } else false
                    }
                },
                onTyped = { page = PairingStart.Typed },
                onClose = onClose,
            )
        }
        else -> TypedAddressScreen(
            text = typed,
            onText = { typed = it },
            recent = hubs,
            onConnect = { PairingLink.parse(typed).let { it as? PairingLink.Connect }?.let { test(it.target) } },
            onPick = { hub -> HubUrl.parse(hub.address)?.let { test(PairingTarget(it, hub.name)) } },
            onRemove = { recent.remove(it.address) },
            onBack = if (start == PairingStart.Scan) ({ page = PairingStart.Scan }) else onClose,
        )
    }
}

/** The live scanner with paste and type fallbacks. [onLink] returns false when the code is not one this screen takes. */
@Composable
private fun ScanPage(onLink: (PairingLink) -> Boolean, onTyped: () -> Unit, onClose: () -> Unit) {
    val context = LocalContext.current
    val haptics = rememberHaptics()
    val hasCamera = remember { context.packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY) }
    var found by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf<String?>(null) }
    var shakes by remember { mutableStateOf(0) }
    LaunchedEffect(problem) { if (problem != null) { delay(3_000); problem = null } }
    fun handle(text: String) {
        if (found) return
        val link = PairingLink.parse(text)
        if (link != null && onLink(link)) {
            found = true
            haptics.play(HOHaptic.Tap)
        } else {
            problem = "That code is not a HandOver hub."
            shakes++
            haptics.play(HOHaptic.Error)
        }
    }
    ScannerScreen(
        cameraWorks = hasCamera, hasCamera = hasCamera, found = found, problem = problem, shakes = shakes,
        title = "Scan the hub's code",
        hint = "On the computer running HandOver, open http://localhost:8000 and click Show Code.",
        onPaste = {
            val clip = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clip.primaryClip?.getItemAt(0)?.coerceToText(context)?.toString()?.let(::handle)
        },
        onTyped = onTyped, onClose = onClose,
        camera = { QrCamera(::handle) },
    )
}

/**
 * The scanner page, stateless so previews and screenshots draw it without a camera
 * (SCREENS.md 3.1): forced dark, the viewfinder, title and hint at the top, Enter Address and
 * Paste at the bottom, a glass capsule for a bad code.
 */
@Composable
fun ScannerScreen(
    cameraWorks: Boolean,
    hasCamera: Boolean,
    found: Boolean,
    problem: String?,
    shakes: Int,
    title: String,
    hint: String,
    onPaste: () -> Unit,
    onTyped: () -> Unit,
    onClose: () -> Unit,
    typedLabel: String = "Enter Address",
    camera: @Composable () -> Unit = {},
) {
    val reduce = HandOver.reduceMotion
    val shake = remember { Animatable(0f) }
    LaunchedEffect(shakes) {
        if (shakes == 0 || reduce) return@LaunchedEffect
        repeat(2) { shake.animateTo(8f, tween(50)); shake.animateTo(-8f, tween(100)); shake.animateTo(0f, tween(50)) }
    }
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (cameraWorks) camera()
        Box(Modifier.fillMaxSize().graphicsLayer { translationX = shake.value * density }) { Viewfinder(cameraWorks, found) }
        Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(bottom = HOSpace.l), horizontalAlignment = Alignment.CenterHorizontally) {
            Column(Modifier.padding(horizontal = HOSpace.xxl).padding(top = 72.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                Text(title, style = HandOver.type.stepTitle, color = Color.White, textAlign = TextAlign.Center)
                Text(hint, style = HandOver.type.callout, color = Color.White.copy(alpha = 0.7f), textAlign = TextAlign.Center)
            }
            Spacer(Modifier.weight(1f))
            Column(Modifier.padding(horizontal = HOSpace.xl), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                if (problem != null) {
                    Row(Modifier.glass().padding(horizontal = 14.dp, vertical = 9.dp).semantics { liveRegion = LiveRegionMode.Polite }, verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Rounded.Warning, null, tint = Color.White, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(problem, style = HandOver.type.footnote.copy(fontWeight = FontWeight.Medium), color = Color.White)
                    }
                }
                if (!cameraWorks) {
                    Text(
                        if (!hasCamera) "No camera here. Enter the address instead." else "HandOver cannot use the camera. Allow it in Settings, or enter the address.",
                        style = HandOver.type.footnote, color = Color.White.copy(alpha = 0.7f), textAlign = TextAlign.Center,
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                    HOButton(typedLabel, onTyped, kind = ButtonKind.Glass, size = ButtonSize.Large)
                    HOButton("Paste", onPaste, kind = ButtonKind.Glass, size = ButtonSize.Large, icon = Icons.Outlined.ContentPaste)
                }
            }
        }
        Box(Modifier.align(Alignment.TopEnd).statusBarsPadding().padding(horizontal = HOSpace.s, vertical = HOSpace.xs)) {
            Box(
                Modifier.size(HOSize.touch).clickable(onClickLabel = "Cancel", onClick = onClose),
                contentAlignment = Alignment.Center,
            ) {
                Box(Modifier.size(40.dp).glass(), contentAlignment = Alignment.Center) { Icon(Icons.Rounded.Close, "Cancel", tint = Color.White) }
            }
        }
    }
}

/** Enter Address (SCREENS.md 3.2) with the Recent section above the field (3.4). */
@Composable
fun TypedAddressScreen(
    text: String,
    onText: (String) -> Unit,
    recent: List<RecentHub>,
    onConnect: () -> Unit,
    onPick: (RecentHub) -> Unit,
    onRemove: (RecentHub) -> Unit,
    onBack: () -> Unit,
    now: Long = System.currentTimeMillis(),
    currentAddress: String? = null,
) {
    val valid = PairingLink.isTypedAddress(text)
    var removing by remember { mutableStateOf<RecentHub?>(null) }
    Column(Modifier.fillMaxSize().paper().imePadding()) {
        PushedBar("Enter Address", onBack)
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(top = HOSpace.s, bottom = HOSpace.xl),
            verticalArrangement = Arrangement.spacedBy(HOSpace.xl),
        ) {
            if (recent.isNotEmpty()) {
                FormSection("Recent") {
                    FormGroup {
                        recent.forEach { hub ->
                            row { HubRow(hub, hub.address == currentAddress, now, onClick = { onPick(hub) }, onRemove = { removing = hub }) }
                        }
                    }
                }
            }
            FormSection("Hub address", footer = "Find it on the hub computer. HandOver uses port 8000 unless you set another.") {
                HOField(
                    text, onText, "192.168.1.20:8000",
                    style = HandOver.type.code.copy(fontSize = HandOver.type.body.fontSize),
                    keyboard = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false, capitalization = KeyboardCapitalization.None, imeAction = ImeAction.Go),
                    actions = KeyboardActions(onGo = { if (valid) onConnect() }),
                    label = "Hub address",
                )
            }
        }
        PrimaryButton("Connect", onConnect, enabled = valid, fullWidth = true, modifier = Modifier.navigationBarsPadding().padding(HOSpace.l))
    }
    removing?.let { hub ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("Remove ${hub.title}?") },
            text = { Text("This device forgets the address. Your lessons stay on the hub.") },
            confirmButton = { TextButton({ onRemove(hub); removing = null }) { Text("Remove", color = HandOver.colors.bad) } },
            dismissButton = { TextButton({ removing = null }) { Text("Cancel") } },
        )
    }
}

/** A hub row (DESIGN.md 3.10): tile, name, "Connected" or "Last connected ...", checkmark when active. */
@Composable
fun HubRow(hub: RecentHub, active: Boolean, now: Long, onClick: () -> Unit, onRemove: (() -> Unit)? = null) {
    val c = HandOver.colors
    Row(
        Modifier.fillMaxWidth().heightIn(min = 60.dp).pressRow(onClick = onClick).padding(start = HOSpace.l, end = HOSpace.xs, top = HOSpace.s, bottom = HOSpace.s),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SymbolTile(Icons.Outlined.Dns, size = 36.dp)
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(hub.title, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1)
            Text(if (active) "Connected" else "Last connected ${relative(hub.lastConnected, now)}", style = HandOver.type.footnote, color = c.ink2)
        }
        if (active) Icon(Icons.Rounded.Check, "Current hub", tint = c.accentInk, modifier = Modifier.size(20.dp))
        if (onRemove != null) {
            Box(Modifier.size(HOSize.touch).clip(CircleShape).clickable(onClickLabel = "Remove ${hub.title}", onClick = onRemove), contentAlignment = Alignment.Center) {
                Icon(Icons.Rounded.Close, "Remove ${hub.title}", tint = c.ink3, modifier = Modifier.size(18.dp))
            }
        }
    }
}

/** "just now", "5 minutes ago", "2 hours ago", "3 days ago". */
fun relative(then: Long, now: Long): String {
    val s = ((now - then) / 1000).coerceAtLeast(0)
    fun plural(n: Long, unit: String) = "$n $unit${if (n == 1L) "" else "s"} ago"
    return when {
        s < 60 -> "just now"
        s < 3_600 -> plural(s / 60, "minute")
        s < 86_400 -> plural(s / 3_600, "hour")
        else -> plural(s / 86_400, "day")
    }
}

/** Connecting, connected, not a hub, unreachable (SCREENS.md 3.3 and 25.3). */
@Composable
fun ConnectStatusScreen(state: ConnectState, onCancel: () -> Unit, onRetry: () -> Unit, onEdit: () -> Unit) {
    val c = HandOver.colors
    val reduce = HandOver.reduceMotion
    Box(Modifier.fillMaxSize().paper().statusBarsPadding().navigationBarsPadding()) {
        AnimatedContent(
            state, label = "connect",
            contentKey = { it::class },
            transitionSpec = { fadeIn(tween(if (reduce) 150 else 250)) togetherWith fadeOut(tween(if (reduce) 150 else 250)) },
        ) { s ->
            Column(Modifier.fillMaxSize().padding(horizontal = HOSpace.xl).padding(bottom = HOSpace.l), horizontalAlignment = Alignment.CenterHorizontally) {
                Spacer(Modifier.weight(1f))
                Box(Modifier.height(72.dp), contentAlignment = Alignment.Center) {
                    when (s) {
                        is ConnectState.Connecting -> CircularProgressIndicator(color = c.ink2, strokeWidth = 3.dp, modifier = Modifier.size(40.dp))
                        is ConnectState.Connected -> SuccessCheck()
                        is ConnectState.NotAHub -> Icon(Icons.AutoMirrored.Outlined.HelpOutline, null, tint = c.caution, modifier = Modifier.size(56.dp))
                        is ConnectState.Unreachable -> Icon(Icons.Outlined.WifiOff, null, tint = c.caution, modifier = Modifier.size(56.dp))
                    }
                }
                Spacer(Modifier.height(HOSpace.l))
                val (title, message) = when (s) {
                    is ConnectState.Connecting -> "Connecting to ${s.title}" to "Checking that a HandOver hub is there."
                    is ConnectState.Connected -> "Connected to ${s.title}" to when (s.lessons) {
                        0 -> "No lessons on this hub yet."
                        1 -> "1 lesson on this hub."
                        else -> "${s.lessons} lessons on this hub."
                    }
                    is ConnectState.NotAHub -> "No hub at that address" to "Something answered, but it is not HandOver. Check the address and port."
                    is ConnectState.Unreachable -> "Cannot reach ${s.host}" to s.reason
                }
                Text(title, style = HandOver.type.stepTitle, color = c.ink, textAlign = TextAlign.Center, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
                Spacer(Modifier.height(HOSpace.s))
                Text(message, style = HandOver.type.callout, color = c.ink2, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 340.dp))
                if (s is ConnectState.Unreachable) {
                    Spacer(Modifier.height(HOSpace.xl))
                    Column(Modifier.widthIn(max = 360.dp).card(HORadius.control).padding(HOSpace.m), verticalArrangement = Arrangement.spacedBy(HOSpace.xs)) {
                        Text("Same Wi-Fi?", style = HandOver.type.headline, color = c.ink)
                        Text("Make sure this device and the hub are on the same network, and that HandOver is running on the hub computer.", style = HandOver.type.footnote, color = c.ink2)
                    }
                }
                Spacer(Modifier.weight(1.3f))
                when (s) {
                    is ConnectState.Connecting -> QuietButton("Cancel", onCancel, size = ButtonSize.Regular)
                    is ConnectState.Connected -> Spacer(Modifier.height(HOSize.controlLarge))
                    else -> Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                        PrimaryButton("Try Again", onRetry, fullWidth = true)
                        SecondaryButton("Edit Address", onEdit, size = ButtonSize.Large, modifier = Modifier.fillMaxWidth())
                    }
                }
            }
        }
    }
}

/** The connected check: scales in with a spring once, or fades with Reduce Motion (Android's stand-in for the iOS draw-on). */
@Composable
fun SuccessCheck(size: androidx.compose.ui.unit.Dp = 64.dp) {
    val reduce = HandOver.reduceMotion
    val scale = remember { Animatable(if (reduce) 1f else 0.6f) }
    val alpha = remember { Animatable(0f) }
    LaunchedEffect(Unit) {
        launch { alpha.animateTo(1f, tween(if (reduce) 150 else 180)) }
        if (!reduce) scale.animateTo(1f, androidx.compose.animation.core.spring(0.55f, 380f))
    }
    Icon(
        Icons.Rounded.CheckCircle, null, tint = HandOver.colors.good,
        modifier = Modifier.size(size).graphicsLayer { scaleX = scale.value; scaleY = scale.value; this.alpha = alpha.value },
    )
}

/** Pairing as a button in the first-run page: the QR symbol. */
val ScanIcon get() = Icons.Rounded.QrCodeScanner
