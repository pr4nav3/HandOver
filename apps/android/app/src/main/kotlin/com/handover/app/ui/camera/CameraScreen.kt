package com.handover.app.ui.camera

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.shell.PlaceholderScreen

/** Placeholder. See README.md in this package for what belongs here and who owns it. */
@Composable
fun CameraScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier) {
    PlaceholderScreen(Icons.Outlined.PhotoCamera, "Camera", "Use this phone as the hub's camera.", modifier)
}
