package com.handover.app.ui.library

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.shell.PlaceholderScreen

/** Placeholder. See README.md in this package for what belongs here and who owns it. */
@Composable
fun LibraryScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier) {
    PlaceholderScreen(Icons.Outlined.VideoLibrary, "Library", "Lessons on the hub appear here.", modifier)
}
