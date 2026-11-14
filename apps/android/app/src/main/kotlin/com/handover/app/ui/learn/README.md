# Learn screen

Status: placeholder. Future owner: the Learn screen builder, assigned by the lead. Until then, nobody else edits this package.

What belongs here: the step player: the clip for `state.currentStep` (URL from `vm.lessonFile(step.clip)`), captions, the live picture from `vm.frame`, status badges from `state.session.status`, "Checks off, use Next" when `check_offline`, the mistake banner from `state.session.mistake` (dismiss with `vm.dismissMistake()`), the "Recording" banner when `state.session.isRecording`, next and back through `vm.next()` and `vm.back()` (they carry the from-guard), preloading `next_clip`, and the chime on `vm.events` advances with reason camera.

Build against:
- `AppState` (core/AppState.kt) for everything to draw. Read it with `vm.state.collectAsStateWithLifecycle()` higher up; the shell passes it in.
- `AppViewModel` (core/AppViewModel.kt) for every action. Screens never call the hub directly.
- `HandOverTheme` and `HandOver.colors` (ui/theme) for color and type. No hard-coded colors.

Keep `LearnScreen(state, vm, modifier)` as the entry point; the shell (ui/shell/AppShell.kt) calls it.
