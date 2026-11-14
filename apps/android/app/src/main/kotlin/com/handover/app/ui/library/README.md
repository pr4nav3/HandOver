# Library screen

Status: placeholder. Future owner: the Library screen builder, assigned by the lead. Until then, nobody else edits this package.

What belongs here: the lesson list from `state.lessons` (refresh with `vm.refreshLessons()`), choosing a lesson with `vm.selectLesson(id)`, and delete. Empty, loading and not-connected states.

Build against:
- `AppState` (core/AppState.kt) for everything to draw. Read it with `vm.state.collectAsStateWithLifecycle()` higher up; the shell passes it in.
- `AppViewModel` (core/AppViewModel.kt) for every action. Screens never call the hub directly.
- `HandOverTheme` and `HandOver.colors` (ui/theme) for color and type. No hard-coded colors.

Keep `LibraryScreen(state, vm, modifier)` as the entry point; the shell (ui/shell/AppShell.kt) calls it.
