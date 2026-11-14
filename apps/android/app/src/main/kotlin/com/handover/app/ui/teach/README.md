# Teach screen

Status: placeholder. Future owner: the Teach screen builder, assigned by the lead. Until then, nobody else edits this package.

What belongs here: picking or recording a video and uploading it with `vm.upload(UploadSource, title)`, the progress in `state.upload` (bytes, then the job phases queued, normalizing, extracting, cutting, done), and errors in plain words.

Build against:
- `AppState` (core/AppState.kt) for everything to draw. Read it with `vm.state.collectAsStateWithLifecycle()` higher up; the shell passes it in.
- `AppViewModel` (core/AppViewModel.kt) for every action. Screens never call the hub directly.
- `HandOverTheme` and `HandOver.colors` (ui/theme) for color and type. No hard-coded colors.

Keep `TeachScreen(state, vm, modifier)` as the entry point; the shell (ui/shell/AppShell.kt) calls it.
