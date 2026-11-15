package com.handover.app

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.handover.app.core.AccountSession
import com.handover.app.core.AppViewModel
import com.handover.app.ui.onboarding.HomeFirst
import com.handover.app.ui.onboarding.OnboardingFlow
import com.handover.app.ui.onboarding.OnboardingStore
import com.handover.app.ui.pairing.RecentHubs
import com.handover.app.ui.settings.SettingsStore
import com.handover.app.ui.settings.SharedKeyValue
import com.handover.app.ui.shell.AppLink
import com.handover.app.ui.shell.AppShell
import com.handover.app.ui.shell.Destination
import com.handover.app.ui.shell.ShellRequest
import com.handover.app.ui.theme.HandOverAppTheme
import com.handover.app.ui.theme.LocalHapticsEnabled
import com.meta.wearable.dat.core.Wearables

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels { AppViewModel.Factory }

    /** What the newest handover:// link asked the shell to open; cleared once the shell opens it. */
    private val request = mutableStateOf<ShellRequest?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        AccountSession.install(this)
        // A handover:// link acts at launch; a rotation must not act on it again.
        if (savedInstanceState == null) openLink(intent)
        val onboarding = OnboardingStore.get(this)
        val settings = SettingsStore.get(this)
        setContent {
            val state by vm.state.collectAsStateWithLifecycle()
            val progress by onboarding.progress.collectAsState()
            val prefs by settings.settings.collectAsState()
            HandOverAppTheme {
                CompositionLocalProvider(LocalHapticsEnabled provides prefs.haptics) {
                    if (!progress.finished) {
                        OnboardingFlow(state, vm, onFinish = {})
                    } else {
                        AppShell(
                            state, vm,
                            initial = if (progress.role == HomeFirst.Teach) Destination.Teach else Destination.Home,
                            request = request.value,
                            onRequestHandled = { request.value = null },
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        openLink(intent)
    }

    /**
     * Routes a handover:// link (AppLink): a hub address connects (and is remembered with the name the
     * link gave), an org invite opens Join, and the Meta AI app's return after glasses registration goes
     * to the Wearables toolkit and then Camera Mode, never to connect.
     */
    private fun openLink(intent: Intent?) {
        val data = intent?.data ?: return
        if (!data.scheme.equals(AppLink.SCHEME, ignoreCase = true)) return
        when (val link = AppLink.route(data.toString())) {
            is AppLink.Connect -> {
                RecentHubs(SharedKeyValue(this, "handover_hubs")).remember(link.target)
                vm.connect(link.target.hub.display)
            }
            is AppLink.Join -> {
                link.target?.let { target ->
                    RecentHubs(SharedKeyValue(this, "handover_hubs")).remember(target)
                    if (vm.state.value.hub != target.hub) vm.connect(target.hub.display)
                }
                request.value = ShellRequest.Join(link.code)
            }
            AppLink.Glasses -> {
                handleWearablesReturn(intent)
                request.value = ShellRequest.Glasses
            }
            null -> Unit
        }
    }

    /**
     * The Android form of the toolkit's handleUrl: Wearables reads the registration result from the
     * intent and continues the flow. Initializing here covers a process the system restarted while the
     * person was in the Meta AI app (initialize again is a harmless failure).
     */
    private fun handleWearablesReturn(intent: Intent) {
        runCatching {
            Wearables.initialize(applicationContext)
            Wearables.handleIntent(intent) { registration -> registration.continueRegistration(this) }
        }.onFailure { Log.w("HandOver", "glasses return link not handled: ${it.javaClass.simpleName}") }
    }
}
