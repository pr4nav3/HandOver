# Camera

Owner: the Camera feature builder (assigned by the lead). Until then, ask the lead before editing.

- Replace the placeholder `CameraView.swift`; keep the type name, since `Sources/App/AppSection.swift` shows it in the shell.
- Read and change app state only through `AppModel` (`@Environment(AppModel.self)`); see `Sources/Core`.
- Previews: `.environment(AppModel.preview())`, or `AppModel.preview(playing: true)` to watch the scripted run.
- Put new files for this feature in this folder. Changes to `Sources/Core` or `Sources/App` go through the lead.
