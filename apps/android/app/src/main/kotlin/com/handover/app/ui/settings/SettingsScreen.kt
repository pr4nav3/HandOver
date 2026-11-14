package com.handover.app.ui.settings

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.shell.PlaceholderScreen

/** Placeholder. See README.md in this package for what belongs here and who owns it. */
@Composable
fun SettingsScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier) {
    PlaceholderScreen(Icons.Outlined.Settings, "Settings", state.hub?.let { "Hub: ${it.display}" } ?: "Connect to a hub on your Wi-Fi.", modifier)
}
