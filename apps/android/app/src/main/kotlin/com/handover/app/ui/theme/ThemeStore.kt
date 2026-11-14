package com.handover.app.ui.theme

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.core.content.edit

@Immutable
data class ThemeChoice(val spec: ThemeSpec = ThemeCatalog.system, val appearance: Appearance = Appearance.System)

/** Where the choice is kept. An interface so tests and previews use memory. */
interface ThemePrefs {
    var themeId: String?
    var appearance: String?
}

/** The same SharedPreferences file core's SharedHubPrefs uses ("handover"), with its own keys. */
class SharedThemePrefs(context: Context) : ThemePrefs {
    private val prefs = context.applicationContext.getSharedPreferences("handover", Context.MODE_PRIVATE)
    override var themeId: String?
        get() = prefs.getString(KEY_THEME, null)
        set(value) = prefs.edit { putString(KEY_THEME, value) }
    override var appearance: String?
        get() = prefs.getString(KEY_APPEARANCE, null)
        set(value) = prefs.edit { putString(KEY_APPEARANCE, value) }

    private companion object {
        const val KEY_THEME = "theme"
        const val KEY_APPEARANCE = "appearance"
    }
}

class MemoryThemePrefs(override var themeId: String? = null, override var appearance: String? = null) : ThemePrefs

/** The persisted theme and Appearance, observable from Compose. Picking applies at once. */
class ThemeStore(private val prefs: ThemePrefs) {
    private val _choice: MutableState<ThemeChoice> = mutableStateOf(ThemeChoice(ThemeSpec.from(prefs.themeId), Appearance.from(prefs.appearance)))
    val choice: State<ThemeChoice> get() = _choice

    fun select(spec: ThemeSpec) {
        prefs.themeId = spec.id
        _choice.value = _choice.value.copy(spec = spec)
    }

    fun setAppearance(appearance: Appearance) {
        prefs.appearance = appearance.id
        _choice.value = _choice.value.copy(appearance = appearance)
    }

    companion object {
        @Volatile private var shared: ThemeStore? = null

        /** One store per process, so Settings and the app root see the same choice. */
        fun get(context: Context): ThemeStore =
            shared ?: synchronized(this) { shared ?: ThemeStore(SharedThemePrefs(context)).also { shared = it } }
    }
}

@Composable
fun rememberThemeStore(): ThemeStore {
    if (LocalInspectionMode.current) return remember { ThemeStore(MemoryThemePrefs()) }
    val context = LocalContext.current
    return remember(context) { ThemeStore.get(context) }
}
