package com.handover.app.ui.learn

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.School
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import com.handover.app.core.AppState
import com.handover.app.core.AppViewModel
import com.handover.app.ui.shell.PlaceholderScreen

/** Placeholder. See README.md in this package for what belongs here and who owns it. */
@Composable
fun LearnScreen(state: AppState, vm: AppViewModel, modifier: Modifier = Modifier) {
    PlaceholderScreen(Icons.Outlined.School, "Learn", if (state.session?.lessonId != null) "Step ${state.session.step + 1} of ${state.session.total}" else "Pick a lesson to start learning.", modifier)
}
