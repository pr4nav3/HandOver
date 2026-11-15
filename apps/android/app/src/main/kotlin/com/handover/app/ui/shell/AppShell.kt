package com.handover.app.ui.shell

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Groups
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.account.AccountPage
import com.handover.app.ui.account.AccountScreen
import com.handover.app.ui.account.AccountState
import com.handover.app.ui.account.AccountSupport
import com.handover.app.ui.account.rememberAccounts
import com.handover.app.ui.camera.CameraScreen
import com.handover.app.ui.learn.LearnScreen
import com.handover.app.ui.library.LibraryScreen
import com.handover.app.ui.settings.SettingsScreen
import com.handover.app.ui.start.CameraChoice
import com.handover.app.ui.start.CameraChoiceSheet
import com.handover.app.ui.start.LessonPickerSheet
import com.handover.app.ui.start.StartFlow
import com.handover.app.ui.teach.TeachScreen
import com.handover.app.ui.theme.HandOver

/** The app's top-level places, in navigation order (SCREENS.md 1, with Learn and Settings as tabs on Android). */
enum class Destination(val label: String, val icon: ImageVector, val short: String = label) {
    Home("Home", Icons.Outlined.Home),
    Learn("Learn", Icons.Outlined.School),
    Teach("Teach", Icons.Outlined.Videocam),
    // "Orgs" in the bottom bar so it fits on a 360 dp phone; the full word on the rail and for TalkBack.
    Organizations("Organizations", Icons.Outlined.Groups, short = "Orgs"),
    Settings("Settings", Icons.Outlined.Settings),
}

/** Start [lessonId] at [step], or with a null id, only change the camera. */
private data class StartRequest(val lessonId: String?, val step: Int = 0)

/** Something a handover:// link asked the shell to open. */
sealed interface ShellRequest {
    /** An org invite: open Organizations at Join with this code. */
    data class Join(val code: String) : ShellRequest

    /**
     * The Meta AI app returned after glasses registration. With glasses as the lesson camera the person
     * stays where they were (the start sheet or Learn picks up the new state); otherwise Be the Camera
     * opens, where the glasses card lives.
     */
    data object Glasses : ShellRequest
}

/** Below this width the app uses a bottom bar; at or above it (tablets, unfolded foldables), a side rail. */
private val RailMinWidth = 600.dp

/**
 * Which tabs this person sees (SCREENS.md 24): Teach only for people who can make lessons, and
 * Organizations only on hubs with accounts. Pure, so the rule is tested without a screen.
 */
object ShellTabs {
    fun visible(account: AccountState, forceOrgs: Boolean = false): List<Destination> = Destination.entries.filter { d ->
        when (d) {
            Destination.Teach -> canTeach(account)
            Destination.Organizations -> forceOrgs || account.support == AccountSupport.Available
            else -> true
        }
    }

    /**
     * Hubs without accounts: everyone teaches. With accounts: the hub owner, hub teachers, and admins or
     * teachers of an org. Signed out on an open hub (auth optional) may still make a legacy lesson.
     */
    fun canTeach(account: AccountState): Boolean {
        if (account.support != AccountSupport.Available) return true
        val user = account.user ?: return !account.authRequired
        if (user.role == "owner" || user.role == "teacher") return true
        return account.orgs.orEmpty().any { it.role == "org_admin" || it.role == "teacher" } || account.capabilities.canTeachIn.isNotEmpty()
    }
}

/**
 * The frame around every screen: a bottom navigation bar on phones and a navigation rail on wider
 * screens. Each screen gets the app state and the ViewModel and owns everything inside its area.
 * Be the Camera opens over everything as a full-screen cover (from Home, Settings or the glasses return link).
 *
 * The start flow lives here so Home, lesson detail, the Learn tab and Teach share it: Start asks how
 * HandOver should see your hands the first time (the camera sheet), then picks the lesson on the hub
 * and shows Learn once the hub confirms it.
 */
@Composable
fun AppShell(
    state: AppState,
    vm: AppViewModel,
    initial: Destination = Destination.Home,
    request: ShellRequest? = null,
    onRequestHandled: () -> Unit = {},
) {
    var current by rememberSaveable { mutableStateOf(initial) }
    var cameraOpen by rememberSaveable { mutableStateOf(false) }
    // Not saved across rotation on purpose: the join page uses the code as soon as it shows, so a
    // recreated screen must not send it twice. Cleared when the person leaves Organizations.
    var joinCode by remember { mutableStateOf<String?>(null) }
    // Bumped on each join link so the Organizations page restarts at Join even for the same code.
    var joinNonce by remember { mutableIntStateOf(0) }
    val accounts = rememberAccounts()
    val account by accounts.state.collectAsState()
    LaunchedEffect(state.hub) { accounts.attach(state.hub) }

    val context = LocalContext.current
    var choice by remember { mutableStateOf(CameraChoice.load(context)) }
    var sheetFor by remember { mutableStateOf<StartRequest?>(null) }
    var picking by remember { mutableStateOf(false) }
    var pending by remember { mutableStateOf<Pair<String, Int>?>(null) }
    val session = state.session

    // Learn opens once the hub has the lesson this phone asked for, then the step (Continue) is applied.
    LaunchedEffect(session?.lessonId, session?.step) {
        val target = pending ?: return@LaunchedEffect
        if (session?.lessonId == target.first) {
            if (target.second > 0 && session.step != target.second) vm.goto(target.second)
            pending = null
            current = Destination.Learn
        }
    }

    fun go(id: String, step: Int) {
        if (session?.lessonId == id) {
            vm.resumeLesson()
            if (step != session.step) vm.goto(step)
            current = Destination.Learn
        } else {
            pending = id to step
            vm.selectLesson(id)
        }
    }

    fun requestStart(id: String, step: Int) {
        if (StartFlow.mustAsk(choice)) sheetFor = StartRequest(id, step) else go(id, step)
    }

    val changeCamera = { sheetFor = StartRequest(null) }

    LaunchedEffect(request) {
        when (request) {
            is ShellRequest.Join -> {
                joinCode = request.code
                joinNonce++
                current = Destination.Organizations
            }
            ShellRequest.Glasses -> if (choice != CameraChoice.Glasses) cameraOpen = true
            null -> return@LaunchedEffect
        }
        onRequestHandled()
    }

    val tabs = ShellTabs.visible(account, forceOrgs = joinCode != null)
    // A tab that went away (signed out, or the role changed) falls back to Home.
    val shown = if (current in tabs) current else Destination.Home

    if (cameraOpen) {
        BackHandler { cameraOpen = false }
        CameraScreen(state, vm, Modifier.fillMaxSize(), onClose = { cameraOpen = false })
        return
    }

    AppShellFrame(tabs, shown, onSelect = { d -> if (d != Destination.Organizations) joinCode = null; current = d }) {
        when (shown) {
            Destination.Home -> LibraryScreen(
                state, vm,
                onStart = { id, step -> requestStart(id, step) },
                onTeach = if (Destination.Teach in tabs) ({ current = Destination.Teach }) else null,
                onLearn = { if (state.lessonRunning) current = Destination.Learn else picking = true },
                onBeTheCamera = { cameraOpen = true },
                camera = choice,
                onChangeCamera = changeCamera,
            )
            Destination.Learn -> LearnScreen(
                state, vm,
                camera = choice,
                onEnd = { vm.endLesson(); current = Destination.Home },
                onPickLesson = { picking = true },
                onChangeCamera = changeCamera,
            )
            Destination.Teach -> TeachScreen(state, vm, onStartLesson = { current = Destination.Learn })
            Destination.Organizations -> key(joinNonce) {
                AccountScreen(state, start = joinCode?.let { AccountPage.Join(it) } ?: AccountPage.Orgs)
            }
            Destination.Settings -> SettingsScreen(state, vm, onCameraMode = { cameraOpen = true })
        }
    }

    if (picking) {
        LaunchedEffect(Unit) { vm.refreshLessons() }
        LessonPickerSheet(state.lessons, state.lessonsLoading, onPick = { l -> picking = false; requestStart(l.id, 0) }, onDismiss = { picking = false })
    }
    sheetFor?.let { req ->
        CameraChoiceSheet(
            hub = state.hub,
            current = choice,
            confirm = if (req.lessonId != null) "Start Lesson" else "Done",
            onConfirm = { picked ->
                CameraChoice.save(context, picked)
                choice = picked
                sheetFor = null
                req.lessonId?.let { go(it, req.step) }
            },
            onDismiss = { sheetFor = null },
        )
    }
}

/**
 * The navigation chrome alone, stateless, so screenshot tests draw it with any content: a bottom
 * bar below [RailMinWidth], a rail at or above it. The content area consumes the bars' insets, so a
 * screen's own statusBarsPadding does not double up.
 */
@Composable
fun AppShellFrame(
    tabs: List<Destination>,
    current: Destination,
    onSelect: (Destination) -> Unit,
    content: @Composable () -> Unit,
) {
    val c = HandOver.colors
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val wide = maxWidth >= RailMinWidth
        if (wide) {
            Scaffold(containerColor = c.paper) { padding ->
                Row(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding)) {
                    NavigationRail(containerColor = c.paper) {
                        tabs.forEach { d ->
                            NavigationRailItem(
                                selected = d == current,
                                onClick = { onSelect(d) },
                                icon = { Icon(d.icon, contentDescription = null) },
                                label = { Text(d.label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                colors = NavigationRailItemDefaults.colors(
                                    selectedIconColor = c.accentInk, selectedTextColor = c.accentInk, indicatorColor = c.accentSoft,
                                    unselectedIconColor = c.ink2, unselectedTextColor = c.ink2,
                                ),
                            )
                        }
                    }
                    Box(Modifier.weight(1f).fillMaxSize()) { content() }
                }
            }
        } else {
            Scaffold(
                containerColor = c.paper,
                bottomBar = {
                    NavigationBar(containerColor = c.raised) {
                        tabs.forEach { d ->
                            NavigationBarItem(
                                selected = d == current,
                                onClick = { onSelect(d) },
                                icon = { Icon(d.icon, contentDescription = null) },
                                modifier = Modifier.semantics { contentDescription = d.label },
                                // The short label ("Orgs") so five tabs fit on a 360 dp phone without cutting a word.
                                label = { Text(d.short, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                colors = NavigationBarItemDefaults.colors(
                                    selectedIconColor = c.accentInk, selectedTextColor = c.accentInk, indicatorColor = c.accentSoft,
                                    unselectedIconColor = c.ink2, unselectedTextColor = c.ink2,
                                ),
                            )
                        }
                    }
                },
            ) { padding ->
                Box(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding)) { content() }
            }
        }
    }
}
