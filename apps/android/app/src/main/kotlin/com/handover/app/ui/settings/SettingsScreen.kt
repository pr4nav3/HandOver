package com.handover.app.ui.settings

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ClosedCaption
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.FormatSize
import androidx.compose.material.icons.outlined.GraphicEq
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.Palette
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.RecordVoiceOver
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material.icons.outlined.Timer
import androidx.compose.material.icons.outlined.Vibration
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.core.SocketPhase
import com.handover.app.ui.account.AccountScreen
import com.handover.app.ui.account.AccountSupport
import com.handover.app.ui.account.rememberAccounts
import com.handover.app.ui.components.StatusDot
import com.handover.app.ui.onboarding.PermissionAsk
import com.handover.app.ui.onboarding.PermissionGate
import com.handover.app.ui.onboarding.has
import com.handover.app.ui.pairing.HubRow
import com.handover.app.ui.pairing.PairingFlow
import com.handover.app.ui.pairing.PairingStart
import com.handover.app.ui.pairing.RecentHub
import com.handover.app.ui.pairing.rememberRecentHubs
import com.handover.app.ui.theme.Appearance
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.LocalHapticsEnabled
import com.handover.app.ui.theme.ThemeSpec
import com.handover.app.ui.theme.paper
import com.handover.app.ui.theme.rememberThemeStore

/** Pages inside Settings. */
enum class SettingsPage { Main, Hub, Theme, About, Licenses, Connect, Account, VoicePermission }

/**
 * Settings (SCREENS.md 17): Hub, Appearance, Learn, Camera, Account (only on hubs with accounts)
 * and About. Every change is saved at once. The theme and Appearance go through ui/theme's
 * ThemeStore, so the whole app redraws in the new theme.
 */
@Composable
fun SettingsScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier, onCameraMode: (() -> Unit)? = null) {
    val context = LocalContext.current
    val store = remember { SettingsStore.get(context) }
    val settings by store.settings.collectAsState()
    val themes = rememberThemeStore()
    val choice by themes.choice
    val recent = rememberRecentHubs()
    val hubs by recent.hubs.collectAsState()
    val accounts = rememberAccounts()
    val account by accounts.state.collectAsState()
    androidx.compose.runtime.LaunchedEffect(state.hub) { accounts.attach(state.hub) }
    var page by rememberSaveable { mutableStateOf(SettingsPage.Main) }
    BackHandler(page != SettingsPage.Main) { page = if (page == SettingsPage.Licenses) SettingsPage.About else SettingsPage.Main }

    CompositionLocalProvider(LocalHapticsEnabled provides settings.haptics) {
        Box(modifier.fillMaxSize().paper()) {
            when (page) {
                SettingsPage.Main -> SettingsMain(
                    SettingsUi(
                        hubTitle = state.hub?.let { recent.nameOf(it.display) ?: it.host },
                        hubAddress = state.hub?.display,
                        connected = state.connection.phase == SocketPhase.Open,
                        recent = hubs.filter { it.address != state.hub?.display },
                        themeName = choice.spec.name,
                        settings = settings,
                        accounts = account.support == AccountSupport.Available,
                        accountLine = account.user?.let { "${it.name}, ${it.roleTitle}" } ?: if (account.setupNeeded) "Set up the hub owner" else "Not signed in",
                        version = versionName(context),
                        voiceAvailable = VoiceNextListener.isAvailable(context),
                        appearance = choice.appearance,
                    ),
                    onHub = { page = SettingsPage.Hub },
                    onConnect = { page = SettingsPage.Connect },
                    onPickRecent = { vm.connect(it.address) },
                    onRemoveRecent = { recent.remove(it.address) },
                    onTheme = { page = SettingsPage.Theme },
                    onAppearance = themes::setAppearance,
                    onChange = { change -> store.update(change) },
                    onVoiceNext = { on ->
                        if (on && !context.has(PermissionAsk.Speech.permission)) page = SettingsPage.VoicePermission
                        else store.update { it.copy(voiceNext = on) }
                    },
                    onAccount = { page = SettingsPage.Account },
                    onAbout = { page = SettingsPage.About },
                    onCameraMode = onCameraMode?.takeIf { state.hub != null },
                )
                SettingsPage.Hub -> HubDetails(
                    state, recent.nameOf(state.hub?.display),
                    onReconnect = vm::reconnect,
                    onForget = {
                        state.hub?.let { recent.remove(it.display) }
                        vm.disconnect()
                        page = SettingsPage.Main
                    },
                    onBack = { page = SettingsPage.Main },
                )
                SettingsPage.Theme -> Column(Modifier.fillMaxSize()) {
                    PushedBar("Theme", { page = SettingsPage.Main })
                    Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(top = HOSpace.s, bottom = HOSpace.xxl)) {
                        ThemePicker(choice.spec, choice.appearance, themes::select, themes::setAppearance)
                    }
                }
                SettingsPage.About -> AboutPage(versionName(context), onLicenses = { page = SettingsPage.Licenses }, onBack = { page = SettingsPage.Main })
                SettingsPage.Licenses -> LicensesPage { page = SettingsPage.About }
                SettingsPage.Connect -> PairingFlow(vm, PairingStart.Scan, onClose = { page = SettingsPage.Main }, onConnected = { _, _ -> page = SettingsPage.Main })
                SettingsPage.Account -> AccountScreen(state, onBack = { page = SettingsPage.Main })
                SettingsPage.VoicePermission -> PermissionGate(PermissionAsk.Speech, onDecline = { page = SettingsPage.Main }) {
                    androidx.compose.runtime.LaunchedEffect(Unit) {
                        store.update { it.copy(voiceNext = true) }
                        page = SettingsPage.Main
                    }
                }
            }
        }
    }
}

/** What the main Settings page draws. Plain values so previews and screenshots need no hub. */
data class SettingsUi(
    val hubTitle: String?,
    val hubAddress: String?,
    val connected: Boolean,
    val recent: List<RecentHub>,
    val themeName: String,
    val settings: AppSettings,
    val accounts: Boolean,
    val accountLine: String,
    val version: String,
    val voiceAvailable: Boolean,
    val appearance: Appearance = Appearance.System,
)

@Composable
fun SettingsMain(
    ui: SettingsUi,
    onHub: () -> Unit,
    onConnect: () -> Unit,
    onPickRecent: (RecentHub) -> Unit,
    onRemoveRecent: (RecentHub) -> Unit,
    onTheme: () -> Unit,
    onAppearance: (Appearance) -> Unit,
    onChange: ((AppSettings) -> AppSettings) -> Unit,
    onVoiceNext: (Boolean) -> Unit,
    onAccount: () -> Unit,
    onAbout: () -> Unit,
    now: Long = System.currentTimeMillis(),
    /** Opens Be the Camera (this phone, or the glasses through it, as the hub's camera). Null hides the row. */
    onCameraMode: (() -> Unit)? = null,
) {
    val s = ui.settings
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).statusBarsPadding().padding(bottom = HOSpace.xxl)) {
        LargeTitle("Settings")
        Column(Modifier.padding(horizontal = HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
            FormSection("Hub") {
                FormGroup {
                    if (ui.hubTitle != null) row {
                        SettingsRow(ui.hubTitle, Icons.Outlined.Dns, subtitle = if (ui.connected) "Connected" else "Reconnecting", chevron = true, onClick = onHub)
                    }
                    row { SettingsRow(if (ui.hubTitle == null) "Connect to a Hub" else "Connect to Another Hub", Icons.Outlined.QrCodeScanner, accent = true, onClick = onConnect) }
                }
            }
            if (ui.recent.isNotEmpty()) {
                FormSection("Recent") {
                    FormGroup { ui.recent.forEach { h -> row { HubRow(h, false, now, onClick = { onPickRecent(h) }, onRemove = { onRemoveRecent(h) }) } } }
                }
            }
            FormSection("Appearance", footer = "Themes with one look keep it.") {
                FormGroup {
                    row { SettingsRow("Theme", Icons.Outlined.Palette, value = ui.themeName, chevron = true, onClick = onTheme) }
                    row {
                        Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = HOSpace.l, vertical = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
                            SymbolTile(Icons.Outlined.LightMode)
                            Spacer(Modifier.width(HOSpace.m))
                            Segmented(Appearance.entries, ui.appearance, { it.title }, onAppearance, Modifier.weight(1f))
                        }
                    }
                }
            }
            FormSection("Learn") {
                FormGroup {
                    row { ToggleRow("Captions", Icons.Outlined.ClosedCaption, s.captions, { v -> onChange { it.copy(captions = v) } }) }
                    row { CaptionSizeRow(s.captionSize) { v -> onChange { it.copy(captionSize = v) } } }
                    row { ToggleRow("Haptics", Icons.Outlined.Vibration, s.haptics, { v -> onChange { it.copy(haptics = v) } }) }
                    row { ToggleRow("Step Results", Icons.Outlined.Timer, s.stepResults, { v -> onChange { it.copy(stepResults = v) } }) }
                    row { ToggleRow("Speak Mistakes", Icons.Outlined.RecordVoiceOver, s.speakMistakes, { v -> onChange { it.copy(speakMistakes = v) } }) }
                }
            }
            FormSection(
                null,
                footer = if (ui.voiceAvailable) "Listens for \"next\" and \"back\" while a lesson is open. Ignores the expert's clip while it plays. Turn it off in a noisy room."
                else "Speech recognition is not available on this phone.",
            ) {
                FormGroup { row { ToggleRow("Voice Next", Icons.Outlined.GraphicEq, s.voiceNext && ui.voiceAvailable, onVoiceNext, enabled = ui.voiceAvailable) } }
            }
            FormSection("Camera") {
                FormGroup {
                    row {
                        MenuValueRow("Camera", Icons.Outlined.PhotoCamera, if (s.useGlasses) "Glasses" else s.cameraFacing.title, listOf("Back", "Front", "Glasses")) { i ->
                            onChange { if (i == 2) it.copy(useGlasses = true) else it.copy(useGlasses = false, cameraFacing = CameraFacing.entries[i]) }
                        }
                    }
                    if (onCameraMode != null) row { SettingsRow("Be the Camera", Icons.Outlined.Videocam, subtitle = "Point this phone at someone's hands so the hub can check their steps", chevron = true, onClick = onCameraMode) }
                }
            }
            if (ui.accounts) {
                FormSection("Account") {
                    FormGroup { row { SettingsRow("Account", Icons.Outlined.Person, subtitle = ui.accountLine, chevron = true, onClick = onAccount) } }
                }
            }
            FormSection("About") {
                FormGroup { row { SettingsRow("About HandOver", Icons.Outlined.Info, value = ui.version, chevron = true, onClick = onAbout) } }
            }
        }
    }
}

/** Caption Size with a live preview line on a black bar (SCREENS.md 17). */
@Composable
private fun CaptionSizeRow(size: CaptionSize, onPick: (CaptionSize) -> Unit) {
    Column {
        MenuValueRow("Caption Size", Icons.Outlined.FormatSize, size.title, CaptionSize.entries.map { it.title }) { onPick(CaptionSize.entries[it]) }
        val base = HandOver.type.captionText
        Box(
            Modifier.fillMaxWidth().padding(start = HOSpace.l, end = HOSpace.l, bottom = HOSpace.m)
                .background(HandOver.colors.captionFill, RoundedCornerShape(HORadius.small)).padding(horizontal = HOSpace.m, vertical = HOSpace.s),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "Fold the top corner down to meet the center.",
                style = base.copy(fontSize = base.fontSize * size.scale, lineHeight = base.lineHeight * size.scale),
                color = HandOver.colors.captionInk, textAlign = TextAlign.Center, maxLines = 2,
            )
        }
    }
}

@Composable
private fun MenuValueRow(title: String, icon: androidx.compose.ui.graphics.vector.ImageVector, value: String, options: List<String>, onPick: (Int) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        SettingsRow(title, icon, value = value, chevron = true, onClick = { open = true })
        DropdownMenu(open, { open = false }, modifier = Modifier.align(Alignment.TopEnd)) {
            options.forEachIndexed { i, o -> DropdownMenuItem({ Text(o) }, { open = false; onPick(i) }) }
        }
    }
}

/** Hub details (SCREENS.md 17): address with Copy, status, checks, Reconnect Now, Remove This Hub. */
@Composable
fun HubDetails(state: AppState, name: String?, onReconnect: () -> Unit, onForget: () -> Unit, onBack: () -> Unit) {
    val c = HandOver.colors
    val context = LocalContext.current
    var confirm by remember { mutableStateOf(false) }
    val title = name ?: state.hub?.host ?: "Hub"
    val connected = state.connection.phase == SocketPhase.Open
    val checks = state.session?.let { s ->
        when {
            s.checkOffline -> "Off: " + when (s.checkOfflineReason) {
                com.handover.app.core.OfflineReason.NoKey -> "no check key"
                com.handover.app.core.OfflineReason.RateLimited -> "too many requests"
                com.handover.app.core.OfflineReason.Budget -> "spending limit reached"
                else -> "checks are failing"
            }
            s.checkMode == "mock" -> "Simulated checks"
            else -> "Camera checks"
        }
    }
    Column(Modifier.fillMaxSize()) {
        PushedBar(title, onBack)
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(top = HOSpace.s, bottom = HOSpace.xxl), verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
            FormGroup {
                row {
                    SettingsRow("Address", null, value = state.hub?.display, trailing = {
                        TextButton({
                            (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Hub address", state.hub?.display))
                        }) { androidx.compose.material3.Icon(Icons.Outlined.ContentCopy, "Copy address", tint = c.accentInk, modifier = Modifier.size(18.dp)) }
                    })
                }
                row {
                    SettingsRow("Status", null, trailing = {
                        StatusDot(if (connected) c.good else c.caution)
                        Spacer(Modifier.width(HOSpace.s))
                        Text(if (connected) "Connected" else "Reconnecting", style = HandOver.type.body, color = c.ink2)
                    })
                }
                if (checks != null) row { SettingsRow("Checks", null, value = checks) }
                row { SettingsRow("Reconnect Now", null, accent = true, onClick = onReconnect) }
            }
            FormGroup { row { SettingsRow("Remove This Hub", null, destructive = true, onClick = { confirm = true }) } }
        }
    }
    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Remove $title?") },
            text = { Text("This device forgets the address. Your lessons stay on the hub.") },
            confirmButton = { TextButton({ confirm = false; onForget() }) { Text("Remove", color = c.bad) } },
            dismissButton = { TextButton({ confirm = false }) { Text("Cancel") } },
        )
    }
}

@Composable
fun AboutPage(version: String, onLicenses: () -> Unit, onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        PushedBar("About", onBack)
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(top = HOSpace.s, bottom = HOSpace.xxl), verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
            FormGroup { row { SettingsRow("Version", null, value = version) } }
            FormSection("Privacy") {
                FormGroup {
                    row {
                        Row(Modifier.fillMaxWidth().padding(HOSpace.l), verticalAlignment = Alignment.Top) {
                            SymbolTile(Icons.Outlined.Shield)
                            Spacer(Modifier.width(HOSpace.m))
                            Text(
                                "The hub never saves your camera frames. Checks send frames to the hub's check service and nothing is kept.",
                                style = HandOver.type.callout, color = HandOver.colors.ink2,
                            )
                        }
                    }
                }
            }
            FormGroup { row { SettingsRow("Open Source Licenses", Icons.Outlined.Description, chevron = true, onClick = onLicenses) } }
        }
    }
}

/** The Apache License 2.0 libraries in this app. The Meta toolkit has its own license, listed apart. */
val OpenSourceLibraries = listOf(
    "Kotlin and kotlinx (coroutines, serialization)" to "JetBrains",
    "Jetpack Compose and Material 3" to "Google, the Android Open Source Project",
    "AndroidX Core, Activity, Lifecycle" to "Google, the Android Open Source Project",
    "CameraX" to "Google, the Android Open Source Project",
    "Media3 ExoPlayer" to "Google, the Android Open Source Project",
    "Material Symbols icons" to "Google",
    "OkHttp and Okio" to "Square",
    "ZXing (QR codes)" to "ZXing authors",
)

@Composable
fun LicensesPage(onBack: () -> Unit) {
    Column(Modifier.fillMaxSize()) {
        PushedBar("Open Source Licenses", onBack)
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(top = HOSpace.s, bottom = HOSpace.xxl), verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
            FormSection(null, footer = "Each is used under the Apache License, Version 2.0: https://www.apache.org/licenses/LICENSE-2.0") {
                FormGroup { OpenSourceLibraries.forEach { (name, by) -> row { SettingsRow(name, null, subtitle = by) } } }
            }
            FormSection(null, footer = "Used under the Meta Wearables Device Access Toolkit license: https://github.com/facebook/meta-wearables-dat-android/blob/main/LICENSE") {
                FormGroup { row { SettingsRow("Meta Wearables Device Access Toolkit 1.0.1", null, subtitle = "Meta Platforms") } }
            }
        }
    }
}

fun versionName(context: Context): String =
    runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull() ?: "0.1.0"
