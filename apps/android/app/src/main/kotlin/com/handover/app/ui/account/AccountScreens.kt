package com.handover.app.ui.account

import android.content.Context
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.handover.app.core.AccountSession
import com.handover.app.core.HubClient
import com.handover.app.core.HubUser
import com.handover.app.core.CourseItem
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.EmptyState
import com.handover.app.ui.components.HOCard
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.Pill
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.Tone
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.settings.FormGroup
import com.handover.app.ui.settings.FormSection
import com.handover.app.ui.settings.HOField
import com.handover.app.ui.settings.SettingsRow
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

/** The app's one account session, so Settings, Profile and onboarding share it. */
object Accounts {
    @Volatile private var model: AccountModel? = null

    fun get(context: Context): AccountModel = model ?: synchronized(this) {
        model ?: AccountModel(
            AccountSession.apply { install(context) }.tokens,
            HubClient.sharedHttp,
            CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate),
        ).also { model = it }
    }
}

/** A shake for a wrong passcode: 8 dp sideways, 2 cycles; off with Reduce Motion (DESIGN.md 2.8). */
@Composable
fun rememberShake(trigger: Any?): Modifier {
    val reduce = HandOver.reduceMotion
    val x = remember { Animatable(0f) }
    LaunchedEffect(trigger) {
        if (trigger == null || reduce) return@LaunchedEffect
        repeat(2) { x.animateTo(8f, tween(50)); x.animateTo(-8f, tween(100)); x.animateTo(0f, tween(50)) }
    }
    return Modifier.graphicsLayer { translationX = x.value * density }
}

/** A secure passcode field with a show or hide eye. */
@Composable
fun PasscodeField(value: String, onChange: (String) -> Unit, placeholder: String, onDone: () -> Unit = {}, error: Boolean = false, imeAction: ImeAction = ImeAction.Done, maxLength: Int? = null) {
    var shown by remember { mutableStateOf(false) }
    HOField(
        value, { v -> onChange(if (maxLength != null) v.take(maxLength) else v) }, placeholder,
        visual = if (shown) VisualTransformation.None else PasswordVisualTransformation(),
        keyboard = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false, imeAction = imeAction),
        actions = KeyboardActions(onDone = { onDone() }, onNext = { onDone() }),
        error = error,
        trailing = {
            IconButton({ shown = !shown }) {
                Icon(if (shown) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (shown) "Hide passcode" else "Show passcode", tint = HandOver.colors.ink3)
            }
        },
    )
}

/** Error line under a field, in `bad` (SCREENS.md 4.1). */
@Composable
fun FieldError(text: String?) {
    if (text == null) return
    Text(text, style = HandOver.type.footnote, color = HandOver.colors.bad, modifier = Modifier.padding(horizontal = HOSpace.l).semantics { liveRegion = LiveRegionMode.Polite })
}

/** A centered page with a title, a line and a form, the primary button pinned to the bottom. */
@Composable
fun FormPage(
    title: String,
    line: String?,
    primary: String,
    primaryEnabled: Boolean,
    onPrimary: () -> Unit,
    busy: Boolean = false,
    stepLabel: String? = null,
    footer: String? = null,
    secondary: (@Composable () -> Unit)? = null,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val c = HandOver.colors
    Column(modifier.fillMaxSize().imePadding()) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(top = HOSpace.l, bottom = HOSpace.xl)) {
            if (stepLabel != null) {
                Text(stepLabel, style = HandOver.type.footnote, color = c.ink2)
                Spacer(Modifier.height(HOSpace.m))
            }
            Text(title, style = HandOver.type.display, color = c.ink)
            if (line != null) {
                Spacer(Modifier.height(HOSpace.s))
                Text(line, style = HandOver.type.body, color = c.ink2)
            }
            Spacer(Modifier.height(HOSpace.xl))
            content()
            if (footer != null) {
                Spacer(Modifier.height(HOSpace.l))
                Text(footer, style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(horizontal = HOSpace.xs))
            }
        }
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(HOSpace.l), verticalArrangement = Arrangement.spacedBy(HOSpace.s), horizontalAlignment = Alignment.CenterHorizontally) {
            if (busy) {
                Box(Modifier.fillMaxWidth().heightIn(min = 52.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = c.ink2, strokeWidth = 2.5.dp, modifier = Modifier.size(24.dp))
                }
            } else PrimaryButton(primary, onPrimary, enabled = primaryEnabled, fullWidth = true)
            secondary?.invoke()
        }
    }
}

/** Sign In (SCREENS.md 4.1). The hub accepts the display name; usernames come later. */
@Composable
fun SignInPage(hubName: String, state: AccountState, onSignIn: (String, String) -> Unit, modifier: Modifier = Modifier, stepLabel: String? = null) {
    var name by remember { mutableStateOf("") }
    var passcode by remember { mutableStateOf("") }
    val haptics = rememberHaptics()
    LaunchedEffect(state.error) { if (state.error != null) haptics.play(HOHaptic.Error) }
    val ok = name.isNotBlank() && passcode.length >= Passcode.MIN
    FormPage(
        "Sign In to $hubName", "Your account lives on this hub. There is no HandOver cloud account.",
        "Sign In", ok && !state.busy, { onSignIn(name, passcode) }, busy = state.busy, stepLabel = stepLabel,
        footer = "Passcodes stay on this hub. HandOver has no cloud account.", modifier = modifier,
    ) {
        Column(rememberShake(state.error), verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
            FormSection("Name") {
                HOField(name, { name = it }, "Sam Rivera", keyboard = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next), label = "Name")
            }
            FormSection("Passcode") {
                PasscodeField(passcode, { passcode = it }, "Passcode", onDone = { if (ok) onSignIn(name, passcode) }, error = state.error != null)
                FieldError(state.error)
            }
        }
    }
}

/**
 * First-run owner setup (SCREENS.md 4.5). The hub today takes a name and a passcode for its first
 * user; the hub name and sign up policy steps need hub support and are left out until it exists.
 */
@Composable
fun OwnerSetupPage(hubName: String, state: AccountState, onCreate: (String, String) -> Unit, modifier: Modifier = Modifier, stepLabel: String? = null) {
    var name by remember { mutableStateOf("") }
    var passcode by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf("") }
    var confirmTouched by remember { mutableStateOf(false) }
    val strength = Passcode.strength(passcode)
    val mismatch = confirmTouched && confirm.isNotEmpty() && confirm != passcode
    val ok = name.isNotBlank() && passcode.length >= Passcode.MIN && confirm == passcode
    FormPage(
        "Set up $hubName", "You are the first person here, so you become the hub owner. Owners manage accounts and organizations.",
        "Finish Setup", ok && !state.busy, { onCreate(name, passcode) }, busy = state.busy, stepLabel = stepLabel,
        footer = "Your account lives on this hub only.", modifier = modifier,
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.l)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                PersonAvatar(name.ifBlank { "?" }, 56.dp)
                Spacer(Modifier.width(HOSpace.m))
                Column(Modifier.weight(1f)) {
                    HOField(name, { name = it.take(40) }, "Sam Rivera", keyboard = KeyboardOptions(capitalization = KeyboardCapitalization.Words, imeAction = ImeAction.Next), label = "Name")
                }
            }
            Text("Shown on lessons you teach and in your organizations.", style = HandOver.type.footnote, color = HandOver.colors.ink2, modifier = Modifier.padding(horizontal = HOSpace.xs))
            FormSection("Passcode") {
                PasscodeField(passcode, { passcode = it }, "Passcode", imeAction = ImeAction.Next, maxLength = Passcode.MAX)
                StrengthMeter(strength, Modifier.padding(horizontal = HOSpace.xs))
            }
            FormSection("Confirm Passcode") {
                PasscodeField(confirm, { confirm = it; if (it.length >= passcode.length) confirmTouched = true }, "Confirm Passcode", error = mismatch, maxLength = Passcode.MAX,
                    onDone = { confirmTouched = true; if (ok) onCreate(name, passcode) })
                FieldError(if (mismatch) "Passcodes do not match." else state.error)
            }
        }
    }
}

/** Profile (SCREENS.md 4.3): header, progress from real runs only, orgs, sign out. */
@Composable
fun ProfilePage(
    hubName: String,
    state: AccountState,
    onSignOut: () -> Unit,
    onOrgs: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
    val c = HandOver.colors
    val user = state.user ?: return
    var confirm by remember { mutableStateOf(false) }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = HOSpace.l).padding(bottom = HOSpace.xxl), verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
        HOCard {
            Row(verticalAlignment = Alignment.CenterVertically) {
                PersonAvatar(user.name, 56.dp)
                Spacer(Modifier.width(HOSpace.m))
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(HOSpace.xs)) {
                    Text(user.name, style = HandOver.type.title, color = c.ink)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Pill(user.roleTitle, if (user.role == "learner") Tone.Neutral else Tone.Accent)
                        Spacer(Modifier.width(HOSpace.s))
                        Text(hubName, style = HandOver.type.callout, color = c.ink2)
                    }
                }
            }
        }
        FormSection("Progress") {
            val done = state.completed.size
            val runs = state.courses.sumOf { it.progress?.runs ?: 0 }
            if (runs == 0) {
                HOCard {
                    EmptyState("No progress yet", "Finish a lesson and your results show up here.", icon = Icons.Outlined.BarChart)
                }
            } else {
                HOCard {
                    Row(Modifier.fillMaxWidth()) {
                        Stat("Lessons done", done, Modifier.weight(1f))
                        Stat("Runs", runs, Modifier.weight(1f))
                        Stat("In progress", state.inProgress.size, Modifier.weight(1f))
                    }
                }
            }
        }
        if (state.completed.isNotEmpty()) {
            FormSection("Completed") {
                FormGroup {
                    state.completed.forEach { item ->
                        row {
                            SettingsRow(item.title.ifBlank { item.id }, null, subtitle = "${item.steps} steps", trailing = {
                                Icon(Icons.Rounded.CheckCircle, "Completed", tint = c.good, modifier = Modifier.size(20.dp))
                            })
                        }
                    }
                }
            }
        }
        if (state.inProgress.isNotEmpty()) {
            FormSection("In Progress") {
                FormGroup {
                    state.inProgress.forEach { item ->
                        val p = item.progress!!
                        row { SettingsRow(item.title.ifBlank { item.id }, null, subtitle = "Step ${p.lastStepsDone} of ${p.total}") }
                    }
                }
            }
        }
        if (onOrgs != null) {
            FormGroup { row { SettingsRow("Organizations", Icons.Outlined.Groups, value = state.orgs?.size?.takeIf { it > 0 }?.toString(), chevron = true, onClick = onOrgs) } }
        }
        FormGroup { row { SettingsRow("Sign Out", null, destructive = true, onClick = { confirm = true }) } }
    }
    if (confirm) {
        AlertDialog(
            onDismissRequest = { confirm = false },
            title = { Text("Sign out of $hubName?") },
            text = { Text("Your progress stays on the hub.") },
            confirmButton = { TextButton({ confirm = false; onSignOut() }) { Text("Sign Out", color = c.bad) } },
            dismissButton = { TextButton({ confirm = false }) { Text("Cancel") } },
        )
    }
}

@Composable
private fun Stat(label: String, value: Int, modifier: Modifier) {
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value.toString(), style = HandOver.type.numeral, color = HandOver.colors.ink)
        Text(label, style = HandOver.type.caption, color = HandOver.colors.ink2, textAlign = TextAlign.Center)
    }
}

/** Shown when the hub has no accounts (SCREENS.md 4: skip the section entirely; this explains why). */
@Composable
fun NoAccountsNote(modifier: Modifier = Modifier) {
    EmptyState(
        "No accounts on this hub", "Everyone on this hub shares one session, so there is nothing to sign in to.",
        modifier = modifier, icon = Icons.Outlined.Groups,
    )
}

@Composable
fun rememberAccounts(): AccountModel {
    val context = LocalContext.current
    return remember(context) { Accounts.get(context) }
}

/** Keeps the button row tidy when a secondary action sits under the primary. */
@Composable
fun SecondaryLink(text: String, onClick: () -> Unit) = com.handover.app.ui.components.QuietButton(text, onClick, size = ButtonSize.Regular)
