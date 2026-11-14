package com.handover.app.ui.shell

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PhotoCamera
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.VideoLibrary
import androidx.compose.material.icons.outlined.Videocam
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.camera.CameraScreen
import com.handover.app.ui.learn.LearnScreen
import com.handover.app.ui.library.LibraryScreen
import com.handover.app.ui.settings.SettingsScreen
import com.handover.app.ui.teach.TeachScreen

/** The app's top-level places, in navigation order. */
enum class Destination(val label: String, val icon: ImageVector) {
    Library("Library", Icons.Outlined.VideoLibrary),
    Learn("Learn", Icons.Outlined.School),
    Teach("Teach", Icons.Outlined.Videocam),
    Camera("Camera", Icons.Outlined.PhotoCamera),
    Settings("Settings", Icons.Outlined.Settings),
}

/** Below this width the app uses a bottom bar; at or above it (tablets, unfolded foldables), a side rail. */
private val RailMinWidth = 600.dp

/**
 * The frame around every screen: a bottom navigation bar on phones and a navigation rail on wider
 * screens. Each screen gets the app state and the ViewModel and owns everything inside its area.
 */
@Composable
fun AppShell(state: AppState, vm: AppViewModel, initial: Destination = Destination.Library) {
    var current by rememberSaveable { mutableStateOf(initial) }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val wide = maxWidth >= RailMinWidth
        if (wide) {
            Scaffold { padding ->
                Row(Modifier.fillMaxSize().padding(padding)) {
                    NavigationRail {
                        Destination.entries.forEach { d ->
                            NavigationRailItem(
                                selected = d == current,
                                onClick = { current = d },
                                icon = { Icon(d.icon, contentDescription = null) },
                                label = { Text(d.label) },
                            )
                        }
                    }
                    Box(Modifier.weight(1f).fillMaxSize()) { Screen(current, state, vm) }
                }
            }
        } else {
            Scaffold(
                bottomBar = {
                    NavigationBar {
                        Destination.entries.forEach { d ->
                            NavigationBarItem(
                                selected = d == current,
                                onClick = { current = d },
                                icon = { Icon(d.icon, contentDescription = null) },
                                label = { Text(d.label) },
                            )
                        }
                    }
                },
            ) { padding ->
                Box(Modifier.fillMaxSize().padding(padding)) { Screen(current, state, vm) }
            }
        }
    }
}

@Composable
private fun Screen(destination: Destination, state: AppState, vm: AppViewModel) = when (destination) {
    Destination.Library -> LibraryScreen(state, vm)
    Destination.Learn -> LearnScreen(state, vm)
    Destination.Teach -> TeachScreen(state, vm)
    Destination.Camera -> CameraScreen(state, vm)
    Destination.Settings -> SettingsScreen(state, vm)
}
