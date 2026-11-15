package com.handover.app.ui.onboarding

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.VideoCall
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.QrCodeScanner
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.account.AccountSupport
import com.handover.app.ui.account.AvatarHue
import com.handover.app.ui.account.FormPage
import com.handover.app.ui.account.JoinOrgPage
import com.handover.app.ui.account.OwnerSetupPage
import com.handover.app.ui.account.PersonAvatar
import com.handover.app.ui.account.SignInPage
import com.handover.app.ui.account.rememberAccounts
import com.handover.app.ui.components.BadgeState
import com.handover.app.ui.components.ButtonKind
import com.handover.app.ui.components.ButtonSize
import com.handover.app.ui.components.HOButton
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.PrimaryButton
import com.handover.app.ui.components.QuietButton
import com.handover.app.ui.components.SecondaryButton
import com.handover.app.ui.components.StatusBadge
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.pairing.PairingFlow
import com.handover.app.ui.pairing.PairingStart
import com.handover.app.ui.pairing.rememberRecentHubs
import com.handover.app.ui.settings.Segmented
import com.handover.app.ui.settings.SymbolTile
import com.handover.app.ui.settings.ThemeCard
import com.handover.app.ui.theme.Appearance
import com.handover.app.ui.theme.HORadius
import com.handover.app.ui.theme.HOSpace
import com.handover.app.ui.theme.HandOver
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.Hairline
import com.handover.app.ui.theme.ThemeCatalog
import com.handover.app.ui.theme.ThemeSpec
import com.handover.app.ui.theme.paper
import com.handover.app.ui.theme.rememberThemeStore
import androidx.compose.foundation.isSystemInDarkTheme

/**
 * First launch, from the welcome pages to Home (SCREENS.md 25). The step shown is always the first
 * one not done, so quitting mid-flow resumes there. Everything before the theme step draws in the
 * Default theme; the theme step re-themes live. [onFinish] runs when the person reaches Home.
 */
@Composable
fun OnboardingFlow(state: AppState, vm: AppViewModel, onFinish: () -> Unit) {
    val context = LocalContext.current
    val store = remember { OnboardingStore.get(context) }
    val progress by store.progress.collectAsState()
    val accounts = rememberAccounts()
    val account by accounts.state.collectAsState()
    val recent = rememberRecentHubs()
    LaunchedEffect(state.hub) { accounts.attach(state.hub) }
    var newAccount by remember { mutableStateOf(false) }
    var connectPage by remember { mutableStateOf<PairingStart?>(null) }
    val hub = HubFacts(
        connected = state.hub != null && account.support != AccountSupport.Unknown,
        accounts = account.support,
        setupNeeded = account.setupNeeded,
        signedIn = account.signedIn,
        orgCount = account.orgs?.size,
        newAccount = newAccount,
    )
    val step = OnboardingPlan.current(progress, hub)
    LaunchedEffect(step) { if (step == null) { store.update { it.copy(finished = true) }; onFinish() } }
    if (step == null) return
    val hubName = recent.nameOf(state.hub?.display) ?: state.hub?.host ?: "your hub"
    val label = OnboardingPlan.label(step, progress, hub)
    val reduce = HandOver.reduceMotion

    // Before the theme step, the Default theme in the system appearance (SCREENS.md 25.1).
    val body: @Composable () -> Unit = {
        AnimatedContent(
            step, label = "onboarding",
            transitionSpec = {
                if (reduce) fadeIn(tween(150)) togetherWith fadeOut(tween(150))
                else (slideInHorizontally(tween(300)) { 24 * it / 412 } + fadeIn(tween(300))) togetherWith fadeOut(tween(200))
            },
        ) { s ->
            when (s) {
                OnboardingStep.Welcome -> WelcomePages(onDone = { store.update { it.copy(welcomeSeen = true) } })
                OnboardingStep.Connect -> {
                    val page = connectPage
                    if (page == null) ConnectPage(label, onScan = { connectPage = PairingStart.Scan }, onTyped = { connectPage = PairingStart.Typed })
                    else {
                        BackHandler { connectPage = null }
                        PairingFlow(vm, page, onClose = { connectPage = null }, onConnected = { _, _ -> connectPage = null })
                    }
                }
                OnboardingStep.OwnerSetup -> Page { OwnerSetupPage(hubName, account, onCreate = { n, p -> accounts.setupOwner(n, p) { newAccount = true } }, stepLabel = label) }
                OnboardingStep.SignIn -> Page { SignInPage(hubName, account, onSignIn = { n, p -> accounts.signIn(n, p) }, stepLabel = label) }
                OnboardingStep.Profile -> Page {
                    ProfileStep(account.user?.name ?: "", progress.avatarHue, label,
                        onPick = { h -> store.update { it.copy(avatarHue = h) } },
                        onDone = { store.update { it.copy(profileDone = true) } })
                }
                OnboardingStep.Join -> Page {
                    JoinOrgPage(
                        accounts, null, onJoined = { store.update { it.copy(joinDone = true) } }, onBack = {},
                        showBar = true, title = label ?: "Join", notNow = { store.update { it.copy(joinDone = true) } },
                    )
                }
                OnboardingStep.Role -> Page {
                    RoleStep(progress.role, label, onPick = { r -> store.update { it.copy(role = r) } }, onDone = { store.update { it.copy(roleDone = true) } })
                }
                OnboardingStep.Theme -> ThemeStep(label, onDone = { store.update { it.copy(themeDone = true, finished = true) } })
            }
        }
    }
    if (step == OnboardingStep.Theme) body() else HandOverTheme(ThemeCatalog.system, dark = isSystemInDarkTheme()) { body() }
}

/** The paper surface with safe-area padding every step page uses. */
@Composable
private fun Page(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize().paper().statusBarsPadding()) { content() }
}

/** Connect to your hub (SCREENS.md 25.3, from section 2). */
@Composable
fun ConnectPage(stepLabel: String?, onScan: () -> Unit, onTyped: () -> Unit) {
    val c = HandOver.colors
    Column(
        Modifier.fillMaxSize().paper().statusBarsPadding().navigationBarsPadding().padding(HOSpace.l),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (stepLabel != null) Text(stepLabel, style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.padding(top = HOSpace.s))
        Spacer(Modifier.weight(1f))
        HubMark()
        Spacer(Modifier.height(HOSpace.xl))
        Text("Connect to your hub", style = HandOver.type.display, color = c.ink, textAlign = TextAlign.Center)
        Spacer(Modifier.height(HOSpace.s))
        Text(
            "The hub is HandOver running on a computer near you. It keeps your lessons.",
            style = HandOver.type.body, color = c.ink2, textAlign = TextAlign.Center, modifier = Modifier.widthIn(max = 340.dp),
        )
        Spacer(Modifier.weight(1.2f))
        Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(HOSpace.s), horizontalAlignment = Alignment.CenterHorizontally) {
            HOButton("Connect to a Hub", onScan, Modifier.fillMaxWidth(), kind = ButtonKind.Primary, size = ButtonSize.Large, icon = Icons.Rounded.QrCodeScanner)
            SecondaryButton("Enter Address", onTyped, Modifier.fillMaxWidth(), size = ButtonSize.Large)
        }
    }
}

/** A calm mark for the connect page: a laptop pane with a phone beside it, drawn from shapes in theme roles. */
@Composable
private fun HubMark() {
    val c = HandOver.colors
    Row(verticalAlignment = Alignment.Bottom, modifier = Modifier.clearAndSetSemantics { }) {
        Box(Modifier.size(120.dp, 76.dp).clip(RoundedCornerShape(10.dp)).background(c.stage).border(Hairline, c.line, RoundedCornerShape(10.dp)).padding(5.dp)) {
            Image(painterResource(SampleFrames[3]), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize().clip(RoundedCornerShape(6.dp)))
        }
        Spacer(Modifier.width(HOSpace.m))
        Box(Modifier.size(38.dp, 66.dp).clip(RoundedCornerShape(9.dp)).background(c.raised).border(Hairline, c.lineStrong, RoundedCornerShape(9.dp)), contentAlignment = Alignment.Center) {
            Icon(Icons.Rounded.QrCodeScanner, null, tint = c.accent, modifier = Modifier.size(22.dp))
        }
    }
}

/**
 * Your profile color (SCREENS.md 25.5, narrowed). The hub cannot store pictures yet, so photo
 * choice is left out rather than kept on this phone where nobody else would see it.
 */
@Composable
fun ProfileStep(name: String, hue: AvatarHue?, stepLabel: String?, onPick: (AvatarHue) -> Unit, onDone: () -> Unit) {
    val chosen = hue ?: AvatarHue.forName(name)
    val haptics = rememberHaptics()
    FormPage(
        "Pick your color", "Your initials show on this color in HandOver on this device.", "Continue", true, onDone,
        stepLabel = stepLabel, secondary = { QuietButton("Not Now", onDone, size = ButtonSize.Regular) },
    ) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(HOSpace.xl)) {
            PersonAvatar(name.ifBlank { "?" }, 96.dp, hue = chosen)
            Row(horizontalArrangement = Arrangement.spacedBy(HOSpace.xs)) {
                AvatarHue.entries.forEach { h ->
                    val ink = Color(if (HandOver.colors.isDark) h.dark else h.light)
                    Box(
                        Modifier.size(44.dp).clip(CircleShape).clickable(role = Role.RadioButton) { haptics.play(HOHaptic.Tap); onPick(h) }
                            .clearAndSetSemantics { contentDescription = h.title; selected = h == chosen; role = Role.RadioButton },
                        contentAlignment = Alignment.Center,
                    ) {
                        Box(
                            Modifier.size(32.dp).then(if (h == chosen) Modifier.border(2.dp, HandOver.colors.ink, CircleShape).padding(4.dp) else Modifier)
                                .background(ink, CircleShape),
                        )
                    }
                }
            }
        }
    }
}

/** What brings you here? (SCREENS.md 25.7). Changes only what Home shows first. */
@Composable
fun RoleStep(role: HomeFirst?, stepLabel: String?, onPick: (HomeFirst) -> Unit, onDone: () -> Unit) {
    FormPage(
        "What brings you here?", "This only changes what Home shows first. You can do both anytime.", "Continue", role != null, onDone,
        stepLabel = stepLabel, secondary = { QuietButton("Not Now", onDone, size = ButtonSize.Regular) },
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(HOSpace.m)) {
            RoleCard(Icons.Outlined.School, "I Want to Learn", "Lessons to take and where you left off.", role == HomeFirst.Learn) { onPick(HomeFirst.Learn) }
            RoleCard(Icons.Outlined.VideoCall, "I Want to Teach", "Record a task and turn it into a lesson.", role == HomeFirst.Teach) { onPick(HomeFirst.Teach) }
            RoleCard(null, "Both", null, role == HomeFirst.Both) { onPick(HomeFirst.Both) }
        }
    }
}

@Composable
private fun RoleCard(icon: ImageVector?, title: String, line: String?, selected: Boolean, onClick: () -> Unit) {
    val c = HandOver.colors
    val haptics = rememberHaptics()
    val shape = RoundedCornerShape(HORadius.card)
    Row(
        Modifier.fillMaxWidth().heightIn(min = if (icon != null) 76.dp else 56.dp).clip(shape)
            .background(if (selected) c.accentSoft else c.raised)
            .border(if (selected) 1.5.dp else Hairline, if (selected) c.accent else c.line, shape)
            .clickable(role = Role.RadioButton) { haptics.play(HOHaptic.Tap); onClick() }
            .clearAndSetSemantics { contentDescription = listOfNotNull(title, line).joinToString(". "); this.selected = selected; role = Role.RadioButton }
            .padding(horizontal = HOSpace.l, vertical = HOSpace.m),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            SymbolTile(icon, size = 40.dp)
            Spacer(Modifier.width(HOSpace.m))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = HandOver.type.headline, color = if (selected) c.accentInk else c.ink)
            if (line != null) Text(line, style = HandOver.type.callout, color = c.ink2)
        }
        if (selected) Icon(Icons.Rounded.CheckCircle, null, tint = c.accentInk, modifier = Modifier.size(24.dp))
    }
}

/**
 * Pick a look (SCREENS.md 25.9): a live miniature Learn screen in the highlighted theme, the
 * Appearance control and a row of the 14 theme cards. Picking applies to the whole app at once.
 */
@Composable
fun ThemeStep(stepLabel: String?, onDone: () -> Unit) {
    val themes = rememberThemeStore()
    val choice by themes.choice
    val haptics = rememberHaptics()
    val systemDark = isSystemInDarkTheme()
    HandOverTheme(choice.spec, dark = choice.spec.isDark(systemDark, choice.appearance)) {
        val c = HandOver.colors
        val list = rememberLazyListState(ThemeCatalog.all.indexOf(choice.spec).coerceAtLeast(0))
        Column(Modifier.fillMaxSize().paper().statusBarsPadding().navigationBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(horizontal = HOSpace.l, vertical = HOSpace.s), verticalAlignment = Alignment.CenterVertically) {
                if (stepLabel != null) Text(stepLabel, style = HandOver.type.footnote, color = c.ink2, modifier = Modifier.weight(1f)) else Spacer(Modifier.weight(1f))
                QuietButton("Keep Default", { themes.select(ThemeCatalog.system); onDone() }, size = ButtonSize.Regular)
            }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                Column(Modifier.padding(horizontal = HOSpace.l)) {
                    Text("Pick a look", style = HandOver.type.display, color = c.ink)
                    Spacer(Modifier.height(HOSpace.xs))
                    Text("You can change it anytime in Settings.", style = HandOver.type.body, color = c.ink2)
                    Spacer(Modifier.height(HOSpace.l))
                    LearnPreview()
                    Spacer(Modifier.height(HOSpace.l))
                    Segmented(Appearance.entries, choice.appearance, { it.title }, themes::setAppearance)
                }
                Spacer(Modifier.height(HOSpace.l))
                LazyRow(state = list, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = HOSpace.l), horizontalArrangement = Arrangement.spacedBy(HOSpace.m)) {
                    itemsIndexed(ThemeCatalog.all) { _, t ->
                        ThemeCard(t, t.id == choice.spec.id, Modifier.width(150.dp)) { themes.select(t) }
                    }
                }
            }
            PrimaryButton("Start Using HandOver", { haptics.play(HOHaptic.Success); onDone() }, fullWidth = true, haptic = null, modifier = Modifier.padding(HOSpace.l))
        }
    }
}

/** A miniature Learn screen with real components: progress, the step 4 frame with a caption, the title, the badge, Next. */
@Composable
private fun LearnPreview() {
    val c = HandOver.colors
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(HORadius.panel)).background(c.raised).border(Hairline, c.line, RoundedCornerShape(HORadius.panel)).padding(HOSpace.m)
            .clearAndSetSemantics { contentDescription = "Preview of a lesson in this theme" },
        verticalArrangement = Arrangement.spacedBy(HOSpace.s),
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
            repeat(8) { i -> Box(Modifier.weight(1f).height(4.dp).background(if (i < 3) c.accent.copy(alpha = 0.5f) else if (i == 3) c.accent else c.well, CircleShape)) }
        }
        Box(Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(HORadius.control)).background(c.stage)) {
            Image(painterResource(SampleFrames[3]), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            // The sample lesson is rendered without narration, so its captions are empty and none is shown.
        }
        Text("Step 4 of 8", style = HandOver.type.caption, color = c.ink2)
        Text(SampleStep4, style = HandOver.type.headline, color = c.ink)
        Row(verticalAlignment = Alignment.CenterVertically) {
            StatusBadge(BadgeState.Watching)
            Spacer(Modifier.weight(1f))
            Box(Modifier.background(c.accent, RoundedCornerShape(HORadius.control)).padding(horizontal = HOSpace.l, vertical = HOSpace.s)) {
                Text("Next", style = HandOver.type.callout, color = c.onAccent)
            }
        }
    }
}
