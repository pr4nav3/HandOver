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
import com.handover.app.ui.teach.TeachScreen
import com.handover.app.ui.theme.HandOver

/** The app's top-level places, in navigation order (SCREENS.md 1, with Learn and Settings as tabs on Android). */
enum class Destination(val label: String, val icon: ImageVector) {
    Home("Home", Icons.Outlined.Home),
    Learn("Learn", Icons.Outlined.School),
    Teach("Teach", Icons.Outlined.Videocam),
    Organizations("Organizations", Icons.Outlined.Groups),
    Settings("Settings", Icons.Outlined.Settings),
}

/** Something a handover:// link asked the shell to open. */
sealed interface ShellRequest {
    /** An org invite: open Organizations at Join with this code. */
    data class Join(val code: String) : ShellRequest

    /** The Meta AI app returned after glasses registration: open Camera Mode, where the glasses card lives. */
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
 * Camera Mode opens over everything as a full-screen cover (from Settings or the glasses return link).
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

    LaunchedEffect(request) {
        when (request) {
            is ShellRequest.Join -> {
                joinCode = request.code
                joinNonce++
                current = Destination.Organizations
            }
            ShellRequest.Glasses -> cameraOpen = true
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
            Destination.Home -> LibraryScreen(state, vm, onStartLesson = { current = Destination.Learn }, onTeach = { current = Destination.Teach })
            Destination.Learn -> LearnScreen(state, vm)
            Destination.Teach -> TeachScreen(state, vm, onStartLesson = { current = Destination.Learn })
            Destination.Organizations -> key(joinNonce) {
                AccountScreen(state, start = joinCode?.let { AccountPage.Join(it) } ?: AccountPage.Orgs)
            }
            Destination.Settings -> SettingsScreen(state, vm, onCameraMode = { cameraOpen = true })
        }
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
                                // "Organizations" is the longest label; it stays on one line and ellipsizes on narrow phones.
                                label = { Text(d.label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
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
