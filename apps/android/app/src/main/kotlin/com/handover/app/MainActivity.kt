package com.handover.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.handover.app.core.AppViewModel
import com.handover.app.core.HubUrl
import com.handover.app.ui.shell.AppShell
import com.handover.app.ui.theme.HandOverTheme
import com.handover.app.ui.theme.ThemeSpec

class MainActivity : ComponentActivity() {
    private val vm: AppViewModel by viewModels { AppViewModel.Factory }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // A handover:// link connects at launch; a rotation must not reconnect.
        if (savedInstanceState == null) openLink(intent)
        setContent {
            val state by vm.state.collectAsStateWithLifecycle()
            HandOverTheme(ThemeSpec.Default) {
                AppShell(state, vm)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        openLink(intent)
    }

    private fun openLink(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme == HubUrl.SCHEME) vm.connect(data.toString())
    }
}
