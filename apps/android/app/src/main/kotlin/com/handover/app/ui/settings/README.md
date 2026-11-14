# Settings screen

Status: placeholder. Future owner: the Settings screen builder, assigned by the lead. Until then, nobody else edits this package.

What belongs here: the hub address field and QR scan, both feeding `vm.connect(raw)` (parsed by `HubUrl`), the connection status from `state.connection`, the check mode from `state.session.checkMode`, the theme picker over `ThemeSpec`, and about and licenses.

Build against:
- `AppState` (core/AppState.kt) for everything to draw. Read it with `vm.state.collectAsStateWithLifecycle()` higher up; the shell passes it in.
- `AppViewModel` (core/AppViewModel.kt) for every action. Screens never call the hub directly.
- `HandOverTheme` and `HandOver.colors` (ui/theme) for color and type. No hard-coded colors.

Keep `SettingsScreen(state, vm, modifier)` as the entry point; the shell (ui/shell/AppShell.kt) calls it.
