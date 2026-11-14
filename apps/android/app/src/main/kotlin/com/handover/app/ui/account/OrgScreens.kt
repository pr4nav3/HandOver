package com.handover.app.ui.account

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import androidx.activity.compose.BackHandler
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.MovieFilter
import androidx.compose.material.icons.outlined.PersonAdd
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.handover.app.core.HubUrl
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.EmptyState
import com.handover.app.ui.components.HOCard
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.Pill
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.QuietButton
import com.handover.app.ui.components.SecondaryButton
import com.handover.app.ui.components.Tone
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.onboarding.PermissionAsk
import com.handover.app.ui.onboarding.PermissionGate
import com.handover.app.ui.pairing.InviteCode
import com.handover.app.ui.pairing.PairingLink
import com.handover.app.ui.pairing.QrCamera
import com.handover.app.ui.pairing.ScannerScreen
import com.handover.app.ui.settings.FormGroup
import com.handover.app.ui.settings.FormSection
import com.handover.app.ui.settings.HOField
import com.handover.app.ui.settings.PushedBar
import com.handover.app.ui.settings.Segmented
import com.handover.app.ui.settings.SettingsRow
import com.handover.app.ui.settings.pressRow
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.paper
import kotlinx.coroutines.launch

// SCREENS.md section 22. Every action is shown only when the session allows it (section 24).

/** An org row (DESIGN.md 3.24): avatar 44, name, meta, role badge above Member. */
@Composable
fun OrgRow(org: Org, onClick: () -> Unit) {
    val c = HandOver.colors
    Row(Modifier.fillMaxWidth().heightIn(min = 68.dp).pressRow(onClick = onClick).padding(horizontal = HOSpace.l, vertical = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
        OrgAvatar(org.name, 44.dp)
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(org.name, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1)
            orgMeta(org)?.let { Text(it, style = HandOver.type.callout, color = c.ink2) }
        }
        org.myRole?.takeIf { it != OrgRole.Member }?.let { Pill(it.title, Tone.Accent) }
    }
}

/** "4 lessons, 12 members", leaving out what the hub did not send. */
fun orgMeta(org: Org): String? = listOfNotNull(
    org.lessons?.let { "$it lesson${if (it == 1) "" else "s"}" },
    org.members?.let { "$it member${if (it == 1) "" else "s"}" },
).joinToString(", ").ifEmpty { null }

/** My organizations (22.1). */
@Composable
fun OrgsListPage(orgs: List<Org>, canCreate: Boolean, onJoin: () -> Unit, onCreate: () -> Unit, onOpen: (Org) -> Unit, onBack: (() -> Unit)?) {
    Column(Modifier.fillMaxSize().paper()) {
        PushedBar("Organizations", onBack) {
            TextButton(onJoin) { Icon(Icons.Outlined.QrCodeScanner, null, tint = HandOver.colors.accentInk, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(6.dp)); Text("Join", color = HandOver.colors.accentInk) }
            if (canCreate) TextButton(onCreate, modifier = Modifier.semantics { contentDescription = "New Organization" }) { Icon(Icons.Outlined.Add, null, tint = HandOver.colors.accentInk) }
        }
        if (orgs.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                EmptyState(
                    "No organizations yet",
                    if (canCreate) "Organizations group people and lessons, like a team or a class." else "Ask an admin for an invite code, then join here.",
                    icon = Icons.Outlined.Groups,
                ) {
                    PrimaryButton("Join with a Code", onJoin)
                    if (canCreate) SecondaryButton("Create Organization", onCreate, size = ButtonSize.Large)
                }
            }
        } else {
            Column(Modifier.verticalScroll(rememberScrollState()).padding(HOSpace.l)) {
                FormGroup { orgs.sortedBy { it.name.lowercase() }.forEach { o -> row { OrgRow(o) { onOpen(o) } } } }
            }
        }
    }
}

/** New Organization (22.2). */
@Composable
fun CreateOrgPage(state: AccountState, onCreate: (String, String) -> Unit, onBack: () -> Unit) {
    var name by remember { mutableStateOf("") }
    var about by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().paper()) {
        PushedBar("New Organization", onBack)
        FormPage(
            "New Organization", null, "Create", name.trim().length in 2..40 && !state.busy, { onCreate(name, about) }, busy = state.busy,
            footer = "You become the admin. You can invite people next.",
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
                Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { OrgAvatar(name.ifBlank { "?" }, 72.dp) }
                FormSection("Name") { HOField(name, { name = it.take(40) }, "Bike Shop Crew", keyboard = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next), label = "Name") }
                FormSection("About", footer = "Optional.") { HOField(about, { about = it.take(200) }, "What this group learns together.", label = "About") }
                FieldError(state.error)
            }
        }
    }
}

/** What the join page is doing. */
sealed interface JoinStep {
    data object Form : JoinStep
    data object Checking : JoinStep
    data class Preview(val code: String, val preview: InvitePreview) : JoinStep
    data class Failed(val message: String) : JoinStep
}

/** Join with a code (22.3, 25.6): type it or scan it, then the welcome card. */
@Composable
fun JoinOrgPage(
    model: AccountModel,
    initialCode: String?,
    onJoined: (Org) -> Unit,
    onBack: () -> Unit,
    onOtherHub: ((PairingLink.Join) -> Unit)? = null,
    title: String = "Join with a Code",
    showBar: Boolean = true,
    notNow: (() -> Unit)? = null,
) {
    val scope = rememberCoroutineScope()
    val haptics = rememberHaptics()
    val state by model.state.collectAsState()
    var mode by remember { mutableStateOf("Type Code") }
    var code by remember { mutableStateOf(initialCode?.let(InviteCode::grouped).orEmpty()) }
    var step by remember { mutableStateOf<JoinStep>(JoinStep.Form) }
    var shakes by remember { mutableStateOf(0) }

    fun check(raw: String) {
        val normalized = InviteCode.normalize(raw) ?: run { step = JoinStep.Failed("That code does not work. Check it with the admin."); shakes++; haptics.play(HOHaptic.Error); return }
        step = JoinStep.Checking
        scope.launch {
            model.previewInvite(normalized).fold(
                { step = JoinStep.Preview(normalized, it) },
                { e -> step = JoinStep.Failed(AccountModel.inviteError(e.cause as? java.io.IOException ?: java.io.IOException(e.message))); shakes++; haptics.play(HOHaptic.Error) },
            )
        }
    }
    LaunchedEffect(initialCode) { if (initialCode != null) check(initialCode) }
    BackHandler(mode == "Scan QR" || step is JoinStep.Preview) { if (step is JoinStep.Preview) step = JoinStep.Form else mode = "Type Code" }

    if (mode == "Scan QR" && step !is JoinStep.Preview) {
        PermissionGate(PermissionAsk.Camera, onDecline = { mode = "Type Code" }) {
            var problem by remember { mutableStateOf<String?>(null) }
            ScannerScreen(
                cameraWorks = true, hasCamera = true, found = false, problem = problem, shakes = shakes,
                title = "Scan the invite code", hint = "Ask an admin to show the code from the organization's page.",
                onPaste = {}, onTyped = { mode = "Type Code" }, onClose = { mode = "Type Code" }, typedLabel = "Type Code",
                camera = {
                    QrCamera({ text ->
                        when (val link = PairingLink.parse(text)) {
                            is PairingLink.Join -> if (link.target != null && onOtherHub != null) onOtherHub(link) else { mode = "Type Code"; code = InviteCode.grouped(link.code); check(link.code) }
                            else -> InviteCode.normalize(text)?.takeIf { text.length <= 40 }?.let { mode = "Type Code"; code = InviteCode.grouped(it); check(it) }
                                ?: run { problem = "That is not an invite code."; shakes++; haptics.play(HOHaptic.Error) }
                        }
                    })
                },
            )
        }
        return
    }

    Column(Modifier.fillMaxSize().paper()) {
        if (showBar) PushedBar(title, onBack) { if (notNow != null) TextButton(notNow) { Text("Not Now", color = HandOver.colors.ink) } }
        when (val s = step) {
            is JoinStep.Preview -> OrgWelcomeCard(
                s.preview, busy = state.busy, error = state.error,
                onJoin = { model.acceptInvite(s.code) { org -> haptics.play(HOHaptic.Success); onJoined(org) } },
                onOpen = { onJoined(s.preview.org) },
                onDifferent = { step = JoinStep.Form; code = "" },
            )
            else -> FormPage(
                "Join your team", "If someone gave you an invite code, enter it or scan it. You can do this later from Organizations.",
                "Join", (InviteCode.normalize(code)?.length ?: 0) >= 8 && s != JoinStep.Checking, { check(code) }, busy = s == JoinStep.Checking,
                secondary = { SecondaryButton("Scan QR Code", { mode = "Scan QR" }, size = ButtonSize.Large, icon = Icons.Outlined.QrCodeScanner, modifier = Modifier.fillMaxWidth()) },
            ) {
                Column(rememberShake(shakes.takeIf { it > 0 }), verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                    FormSection("Invite code") {
                        HOField(
                            code, { v -> code = v.uppercase().filter { it.isLetterOrDigit() || it == ' ' || it == '-' }.take(40) }, "K7QM 2XPA",
                            style = HandOver.type.code.copy(fontSize = 20.sp, letterSpacing = 2.sp),
                            keyboard = KeyboardOptions(capitalization = KeyboardCapitalization.Characters, autoCorrectEnabled = false, imeAction = ImeAction.Go),
                            error = s is JoinStep.Failed, label = "Invite code",
                        )
                        FieldError((s as? JoinStep.Failed)?.message)
                    }
                }
            }
        }
    }
}

/** The welcome card (25.6): org avatar 72, name, members, real lessons only, the role. */
@Composable
fun OrgWelcomeCard(preview: InvitePreview, busy: Boolean, error: String?, onJoin: () -> Unit, onOpen: () -> Unit, onDifferent: () -> Unit, lessons: List<OrgLesson> = emptyList()) {
    val c = HandOver.colors
    val org = preview.org
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(HOSpace.l)) {
            HOCard(padding = HOSpace.xl) {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                    OrgAvatar(org.name, 72.dp)
                    Spacer(Modifier.size(HOSpace.xs))
                    Text(org.name, style = HandOver.type.display, color = c.ink, textAlign = TextAlign.Center)
                    org.members?.let { Text("$it member${if (it == 1) "" else "s"}", style = HandOver.type.callout, color = c.ink2) }
                    org.about?.takeIf { it.isNotBlank() }?.let { Text(it, style = HandOver.type.body, color = c.ink2, textAlign = TextAlign.Center, maxLines = 3) }
                }
                Spacer(Modifier.size(HOSpace.l))
                Text("Lessons in ${org.name}", style = HandOver.type.section, color = c.ink2)
                Spacer(Modifier.size(HOSpace.s))
                if (lessons.isEmpty()) Text("No lessons here yet.", style = HandOver.type.callout, color = c.ink2)
                else lessons.take(3).forEach { l -> Text("${l.title}, ${l.steps} steps", style = HandOver.type.body, color = c.ink, modifier = Modifier.padding(vertical = 2.dp)) }
                Spacer(Modifier.size(HOSpace.l))
                Text(
                    if (preview.alreadyMember) "You are already in ${org.name}." else "You join as ${OrgRole.from(preview.role).title}.",
                    style = HandOver.type.bodyMedium, color = c.ink,
                )
            }
            FieldError(error)
        }
        Column(Modifier.fillMaxWidth().padding(HOSpace.l), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
            if (preview.alreadyMember) PrimaryButton("Open", onOpen, fullWidth = true)
            else PrimaryButton("Join ${org.name}", onJoin, enabled = !busy, fullWidth = true, haptic = null)
            QuietButton("Use a Different Code", onDifferent, size = ButtonSize.Regular)
        }
    }
}

/** The org page (22.4) with Lessons and Members, and admin actions only for admins. */
@Composable
fun OrgDetailPage(
    page: OrgPage,
    me: HubUser?,
    onInvite: () -> Unit,
    onSetRole: (OrgMember, OrgRole) -> Unit,
    onRemove: (OrgMember) -> Unit,
    onLeave: () -> Unit,
    onBack: () -> Unit,
) {
    val c = HandOver.colors
    val org = page.org
    val admin = org.isAdmin
    val admins = page.members.count { it.orgRole == OrgRole.Admin }
    val lastAdmin = admin && admins <= 1
    var tab by remember { mutableStateOf("Lessons") }
    var confirmLeave by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<OrgMember?>(null) }
    Column(Modifier.fillMaxSize().paper()) {
        PushedBar(org.name, onBack)
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(bottom = HOSpace.xxl), verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                OrgAvatar(org.name, 72.dp)
                Text(org.name, style = HandOver.type.display, color = c.ink, textAlign = TextAlign.Center)
                org.about?.takeIf { it.isNotBlank() }?.let { Text(it, style = HandOver.type.body, color = c.ink2, textAlign = TextAlign.Center, maxLines = 3) }
                orgMeta(org.copy(members = org.members ?: page.members.size.takeIf { it > 0 }, lessons = org.lessons ?: page.lessons.size))?.let {
                    Text(it, style = HandOver.type.callout, color = c.ink2)
                }
            }
            if (admin) SecondaryButton("Invite", onInvite, size = ButtonSize.Large, icon = Icons.Outlined.PersonAdd, modifier = Modifier.fillMaxWidth())
            Segmented(listOf("Lessons", "Members"), tab, { it }, { tab = it })
            if (tab == "Lessons") {
                if (page.lessons.isEmpty()) {
                    HOCard {
                        EmptyState(
                            "No lessons yet",
                            if (org.myRole == OrgRole.Member) "When teachers publish here, lessons show up in this list." else "Make the first lesson for ${org.name}.",
                            icon = Icons.Outlined.MovieFilter,
                        )
                    }
                } else FormGroup { page.lessons.forEach { l -> row { SettingsRow(l.title.ifBlank { l.id }, null, subtitle = "${l.steps} steps") } } }
            } else {
                OrgRole.entries.forEach { role ->
                    val group = page.members.filter { it.orgRole == role }
                    if (group.isNotEmpty()) {
                        FormSection(
                            when (role) { OrgRole.Admin -> "Admins"; OrgRole.Teacher -> "Teachers"; OrgRole.Member -> "Members" },
                            footer = if (role == OrgRole.Admin && admin && admins <= 1) "Every organization needs at least one admin." else null,
                        ) {
                            FormGroup {
                                group.forEach { m ->
                                    row {
                                        val isMe = m.userId == me?.id
                                        val canManage = admin && !isMe && !(m.orgRole == OrgRole.Admin && admins <= 1)
                                        MemberRow(m, isMe, canManage, onSetRole = { onSetRole(m, it) }, onRemove = { removing = m })
                                    }
                                }
                            }
                        }
                    }
                }
            }
            FormGroup {
                row {
                    if (lastAdmin) SettingsRow("Make Someone Admin to Leave", Icons.AutoMirrored.Outlined.Logout, onClick = { tab = "Members" })
                    else SettingsRow("Leave Organization", Icons.AutoMirrored.Outlined.Logout, destructive = true, onClick = { confirmLeave = true })
                }
            }
        }
    }
    if (confirmLeave) {
        AlertDialog(
            onDismissRequest = { confirmLeave = false },
            title = { Text("Leave ${org.name}?") },
            text = { Text("You lose access to its lessons. Your progress stays on the hub.") },
            confirmButton = { TextButton({ confirmLeave = false; onLeave() }) { Text("Leave", color = c.bad) } },
            dismissButton = { TextButton({ confirmLeave = false }) { Text("Cancel") } },
        )
    }
    removing?.let { m ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("Remove ${m.name} from ${org.name}?") },
            text = { Text("They lose access to this organization's lessons. Lessons they made stay in the org.") },
            confirmButton = { TextButton({ removing = null; onRemove(m) }) { Text("Remove", color = c.bad) } },
            dismissButton = { TextButton({ removing = null }) { Text("Cancel") } },
        )
    }
}

/** A member row (DESIGN.md 3.26). Admins get a role menu; others see plain text. */
@Composable
fun MemberRow(m: OrgMember, isMe: Boolean, canManage: Boolean, onSetRole: (OrgRole) -> Unit, onRemove: () -> Unit) {
    val c = HandOver.colors
    var menu by remember { mutableStateOf(false) }
    Row(Modifier.fillMaxWidth().heightIn(min = 60.dp).padding(start = HOSpace.l, end = HOSpace.s, top = HOSpace.s, bottom = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
        PersonAvatar(m.name, 36.dp)
        Spacer(Modifier.width(HOSpace.m))
        Column(Modifier.weight(1f)) {
            Text(if (isMe) "${m.name} (You)" else m.name, style = HandOver.type.bodyMedium, color = c.ink, maxLines = 1)
            m.username?.let { Text("@$it", style = HandOver.type.callout, color = c.ink2) }
        }
        if (canManage) {
            Box {
                TextButton({ menu = true }) {
                    Text(m.orgRole.title, color = c.accentInk)
                    Icon(Icons.Rounded.ExpandMore, null, tint = c.accentInk, modifier = Modifier.size(18.dp))
                }
                DropdownMenu(menu, { menu = false }) {
                    OrgRole.entries.forEach { r -> DropdownMenuItem({ Text(r.title) }, { menu = false; if (r != m.orgRole) onSetRole(r) }) }
                    DropdownMenuItem({ Text("Remove", color = c.bad) }, { menu = false; onRemove() })
                }
            }
        } else Text(m.orgRole.title, style = HandOver.type.callout, color = c.ink2, modifier = Modifier.padding(end = HOSpace.s))
    }
}

/** Invite to <org> (22.5), Invite Code half: the new code form and active codes. */
@Composable
fun InvitePage(org: Org, invites: List<OrgInvite>, hub: HubUrl?, hubName: String?, onCreate: (OrgRole, Int?, Int?) -> Unit, onRevoke: (OrgInvite) -> Unit, busy: Boolean, error: String?, onBack: () -> Unit) {
    var role by remember { mutableStateOf(OrgRole.Member) }
    var expiry by remember { mutableStateOf(Expiry.Week) }
    var uses by remember { mutableStateOf(Uses.NoLimit) }
    var revoking by remember { mutableStateOf<OrgInvite?>(null) }
    val active = invites.filter { !it.expired }
    Column(Modifier.fillMaxSize().paper()) {
        PushedBar("Invite to ${org.name}", onBack)
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(bottom = HOSpace.xxl), verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
            FormSection("New Code") {
                FormGroup {
                    row { MenuRow("Joins as", role.title, OrgRole.entries.map { it.title }) { i -> role = OrgRole.entries[i] } }
                    row { MenuRow("Expires", expiry.title, Expiry.entries.map { it.title }) { i -> expiry = Expiry.entries[i] } }
                    row { MenuRow("Uses", uses.title, Uses.entries.map { it.title }) { i -> uses = Uses.entries[i] } }
                }
                Spacer(Modifier.size(HOSpace.xs))
                PrimaryButton("Create Code", { onCreate(role, expiry.hours, uses.count) }, enabled = !busy, fullWidth = true)
                FieldError(error)
            }
            if (active.isNotEmpty()) {
                FormSection("Active Codes") {
                    Column(verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                        active.forEach { inv -> InviteCodeCard(inv, org, hub, hubName, onRevoke = { revoking = inv }) }
                    }
                }
            }
        }
    }
    revoking?.let { inv ->
        AlertDialog(
            onDismissRequest = { revoking = null },
            title = { Text("Revoke this code?") },
            text = { Text("People who already joined stay in the org. The code stops working now.") },
            confirmButton = { TextButton({ revoking = null; onRevoke(inv) }) { Text("Revoke Code", color = HandOver.colors.bad) } },
            dismissButton = { TextButton({ revoking = null }) { Text("Cancel") } },
        )
    }
}

enum class Expiry(val title: String, val hours: Int?) { Hour("In 1 Hour", 1), Day("In 1 Day", 24), Week("In 7 Days", 168), Month("In 30 Days", 720), Never("Never", null) }
enum class Uses(val title: String, val count: Int?) { One("1", 1), Ten("10", 10), Fifty("50", 50), NoLimit("No Limit", null) }

@Composable
private fun MenuRow(title: String, value: String, options: List<String>, onPick: (Int) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        SettingsRow(title, null, value = value, trailing = { Icon(Icons.Rounded.ExpandMore, null, tint = HandOver.colors.ink3, modifier = Modifier.size(20.dp)) }, onClick = { open = true })
        DropdownMenu(open, { open = false }, modifier = Modifier.align(Alignment.TopEnd)) {
            options.forEachIndexed { i, o -> DropdownMenuItem({ Text(o) }, { open = false; onPick(i) }) }
        }
    }
}

/** The `handover://join` link for a code, with this hub's address so it works from anywhere. */
fun joinLink(code: String, hub: HubUrl?, hubName: String?): String {
    val b = StringBuilder("handover://join?code=").append(code)
    if (hub != null) {
        b.append("&host=").append(hub.host).append("&port=").append(hub.port)
        if (hub.secure) b.append("&secure=1")
    }
    hubName?.let { b.append("&name=").append(java.net.URLEncoder.encode(it, "UTF-8").replace("+", "%20")) }
    return b.toString()
}

/** The invite code card (DESIGN.md 3.25): code in groups of four, QR below, meta, Share, Copy, Revoke. */
@Composable
fun InviteCodeCard(inv: OrgInvite, org: Org, hub: HubUrl?, hubName: String?, onRevoke: () -> Unit) {
    val c = HandOver.colors
    val context = LocalContext.current
    val link = joinLink(inv.code, hub, hubName)
    HOCard {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
            SelectionContainer {
                Text(
                    InviteCode.grouped(inv.code), style = HandOver.type.code.copy(fontSize = 22.sp, letterSpacing = 3.sp),
                    color = if (inv.expired) c.ink3 else c.ink, textDecoration = if (inv.expired) TextDecoration.LineThrough else null,
                    modifier = Modifier.semantics { contentDescription = InviteCode.spoken(inv.code) },
                )
            }
            if (!inv.expired) QrImage(link, 160.dp)
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Joins as ${OrgRole.from(inv.role).title}", style = HandOver.type.callout, color = c.ink2)
                Text(inv.expires?.let { "Expires ${it.replace('T', ' ').take(16)}" } ?: "Never expires", style = HandOver.type.callout, color = c.ink2)
                Text("Used ${inv.uses} time${if (inv.uses == 1) "" else "s"}" + (inv.maxUses?.let { ", ${(it - inv.uses).coerceAtLeast(0)} uses left" } ?: ""), style = HandOver.type.callout, color = c.ink2)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.s)) {
                SecondaryButton("Share", {
                    val text = "Join ${org.name} on HandOver: ${InviteCode.grouped(inv.code)}. Or open $link."
                    context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), null))
                }, icon = Icons.Outlined.Share)
                SecondaryButton("Copy", {
                    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("Invite code", inv.code))
                }, icon = Icons.Outlined.ContentCopy)
                com.handover.app.ui.components.HOButton("Revoke", onRevoke, kind = com.handover.app.ui.components.ButtonKind.Destructive, size = ButtonSize.Regular)
            }
        }
    }
}
