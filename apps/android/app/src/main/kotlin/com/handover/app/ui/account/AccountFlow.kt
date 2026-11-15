package com.handover.app.ui.account

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
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
import com.handover.app.core.AppState
import com.handover.app.core.Org
import com.handover.app.core.OrgInvite
import com.handover.app.core.OrgPage
import com.handover.app.ui.components.EmptyState
import com.handover.app.ui.components.HOHaptic
import com.handover.app.ui.components.rememberHaptics
import com.handover.app.ui.pairing.rememberRecentHubs
import com.handover.app.ui.settings.PushedBar
import com.handover.app.ui.theme.paper
import kotlinx.coroutines.launch

/** Pages inside the account area. */
sealed interface AccountPage {
    data object Home : AccountPage
    data object Orgs : AccountPage
    data object CreateOrg : AccountPage
    data class Join(val code: String? = null) : AccountPage
    data class OrgDetail(val id: String) : AccountPage
    data class Invite(val id: String) : AccountPage
}

/**
 * The account area (SCREENS.md 4 and 22), feature-detected: on a hub without /api/me it says so
 * and offers nothing; with accounts it shows owner setup, sign in or the profile, and the
 * organization pages when the hub has /api/orgs.
 */
@Composable
fun AccountScreen(
    state: AppState,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    start: AccountPage = AccountPage.Home,
) {
    val model = rememberAccounts()
    val account by model.state.collectAsState()
    val recent = rememberRecentHubs()
    val hub = state.hub
    val hubName = recent.nameOf(hub?.display) ?: hub?.host ?: "this hub"
    LaunchedEffect(hub) { model.attach(hub) }
    var page by remember(start) { mutableStateOf(start) }
    // The page Back stops at: the Organizations tab (start Orgs, or a join link) roots at the org list.
    val root = if (start is AccountPage.Join || start == AccountPage.Orgs) AccountPage.Orgs else AccountPage.Home
    var detail by remember { mutableStateOf<OrgPage?>(null) }
    val scope = rememberCoroutineScope()
    val haptics = rememberHaptics()

    fun open(id: String) {
        page = AccountPage.OrgDetail(id)
        detail = null
        scope.launch { model.org(id).onSuccess { detail = it } }
    }
    fun reload(id: String) = scope.launch { model.org(id).onSuccess { detail = it } }

    BackHandler(page != root) {
        page = when (val p = page) {
            is AccountPage.Invite -> AccountPage.OrgDetail(p.id)
            AccountPage.Orgs -> AccountPage.Home
            else -> AccountPage.Orgs
        }
    }

    // Organizations need a signed-in person on a hub with accounts; until then the tab shows the account page.
    val shown = if (root == AccountPage.Orgs && page != AccountPage.Home && !(account.signedIn && account.orgsSupported)) AccountPage.Home else page

    Column(modifier.fillMaxSize().paper()) {
        when (val p = shown) {
            AccountPage.Home -> {
                PushedBar(if (root == AccountPage.Orgs) "Organizations" else if (account.signedIn) "Profile" else "Account", onBack)
                when {
                    hub == null -> Centered { EmptyState("No hub connected", "Connect to a hub first.") }
                    account.support == AccountSupport.Unknown -> Centered { EmptyState("Checking the hub", null, loading = true) }
                    account.support == AccountSupport.None -> Centered { NoAccountsNote() }
                    account.setupNeeded -> OwnerSetupPage(hubName, account, onCreate = { n, pc -> model.setupOwner(n, pc) { haptics.play(HOHaptic.Success) } })
                    !account.signedIn -> SignInPage(hubName, account, onSignIn = { n, pc -> model.signIn(n, pc) { haptics.play(HOHaptic.Success) } })
                    else -> ProfilePage(hubName, account, onSignOut = model::signOut, onOrgs = if (account.orgsSupported) ({ page = AccountPage.Orgs }) else null)
                }
            }
            AccountPage.Orgs -> OrgsListPage(
                account.orgs.orEmpty(), account.capabilities.canCreateOrg,
                onJoin = { page = AccountPage.Join() }, onCreate = { page = AccountPage.CreateOrg }, onOpen = { open(it.id) },
                onBack = if (root == AccountPage.Orgs) null else ({ page = AccountPage.Home }),
                invites = account.invites,
                onAccept = { inv -> model.acceptInvite(inv) { org -> haptics.play(HOHaptic.Success); open(org.id) } },
                onDecline = { inv -> scope.launch { model.declineInvite(inv) } },
            )
            AccountPage.CreateOrg -> CreateOrgPage(account, onCreate = { n -> model.createOrg(n) { org -> haptics.play(HOHaptic.Success); open(org.id); page = AccountPage.Invite(org.id) } }, onBack = { page = AccountPage.Orgs })
            is AccountPage.Join -> JoinOrgPage(model, p.code, onJoined = { open(it.id) }, onBack = { page = AccountPage.Orgs })
            is AccountPage.OrgDetail -> {
                val d = detail
                if (d == null || d.org.id != p.id) {
                    PushedBar("Organization", { page = AccountPage.Orgs })
                    Centered { EmptyState("Loading", null, loading = true) }
                } else OrgDetailPage(
                    d, account.user,
                    onInvite = { page = AccountPage.Invite(p.id) },
                    onSetRole = { m, r -> scope.launch { model.setRole(p.id, m.userId, r); reload(p.id) } },
                    onRemove = { m -> scope.launch { model.removeMember(p.id, m.userId).onSuccess { haptics.play(HOHaptic.Warning) }; reload(p.id) } },
                    onLeave = { scope.launch { model.leave(p.id).onSuccess { page = AccountPage.Orgs } } },
                    onBack = { page = AccountPage.Orgs },
                )
            }
            is AccountPage.Invite -> {
                val d = detail
                var error by remember { mutableStateOf<String?>(null) }
                var fresh by remember(p.id) { mutableStateOf<OrgInvite?>(null) }
                var busy by remember { mutableStateOf(false) }
                InvitePage(
                    d?.org ?: Org(id = p.id, name = "Organization"), d?.invites.orEmpty(), hub, hubName,
                    onCreate = { role, hours, uses ->
                        busy = true
                        scope.launch {
                            model.createInvite(p.id, role, hours, uses).fold({ fresh = it; error = null; reload(p.id) }, { error = it.message })
                            busy = false
                        }
                    },
                    onRevoke = { inv ->
                        scope.launch {
                            model.revokeInvite(p.id, inv.id).onSuccess { haptics.play(HOHaptic.Warning); if (fresh?.id == inv.id) fresh = null }
                            reload(p.id)
                        }
                    },
                    busy = busy, error = error, onBack = { page = AccountPage.OrgDetail(p.id) }, fresh = fresh,
                )
            }
        }
    }
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { content() }
}
