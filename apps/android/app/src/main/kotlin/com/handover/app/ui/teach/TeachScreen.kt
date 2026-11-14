package com.handover.app.ui.teach

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.shell.PlaceholderScreen

/** Placeholder. See README.md in this package for what belongs here and who owns it. */
@Composable
fun TeachScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier) {
    PlaceholderScreen(Icons.Outlined.Videocam, "Teach", "Record or choose a video to make a lesson.", modifier)
}
