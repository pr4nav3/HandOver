# Camera screen

Status: placeholder. Future owner: the Camera screen builder, assigned by the lead. Until then, nobody else edits this package.

What belongs here: CameraX preview and JPEG frames at about 1 per second, long side 640 to 1280, sent with `vm.startCamera()?.sendFrame(jpeg)` (it drops frames while the last one is still sending), the active badge from `CameraSocket.active`, the step title from `CameraSocket.state`, next and back on the camera socket, the "replaced" state (close 4000, no auto-reconnect), and the camera permission request. Add the CameraX dependency here when building it.

Build against:
- `AppState` (core/AppState.kt) for everything to draw. Read it with `vm.state.collectAsStateWithLifecycle()` higher up; the shell passes it in.
- `AppViewModel` (core/AppViewModel.kt) for every action. Screens never call the hub directly.
- `HandOverTheme` and `HandOver.colors` (ui/theme) for color and type. No hard-coded colors.

Keep `CameraScreen(state, vm, modifier)` as the entry point; the shell (ui/shell/AppShell.kt) calls it.
