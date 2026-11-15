# Camera

Owner: the Camera feature builder (assigned by the lead). Until then, ask the lead before editing.

- Replace the placeholder `CameraView.swift`; keep the type name, since `Sources/App/AppSection.swift` shows it in the shell.
- Read and change app state only through `AppModel` (`@Environment(AppModel.self)`); see `Sources/Core`.
- Previews: `.environment(AppModel.preview())`, or `AppModel.preview(playing: true)` to watch the scripted run.
- Put new files for this feature in this folder. Changes to `Sources/Core` or `Sources/App` go through the lead.

## Ray-Ban Meta live camera checklist

The glasses path is wired as:

`Ray-Ban Meta -> iPhone (MWDAT 1.0.1) -> /ws/camera -> hub YOU pane -> step checker`

Before starting:

- Meta AI app V292 or newer, glasses firmware V128 or newer.
- Glasses paired to the iPhone and Developer Mode enabled in Meta AI.
- iPhone and laptop on the same network.
- Hub running on the laptop and reachable from the iPhone at `http://<laptop-ip>:8000`.

Run it:

1. From `apps/apple`, run `xcodegen generate` and open `HandOver.xcodeproj`.
2. Select the `HandOver` scheme and the connected iPhone, choose the available Personal Team, then Run.
3. In the Mac app, choose Meta Glasses and show its pairing code.
4. Scan the code with the iPhone Camera app. HandOver connects to the hub and opens Meta Glasses automatically.
5. Approve the Meta AI handoff and camera permission if prompted, then tap **Start glasses camera**.
6. Confirm a moving preview on the phone and frames in the laptop's **YOU** pane for 60 seconds. Perform one origami step and confirm the camera checker advances it.

If QR pairing is unavailable, enter `<laptop-ip>:8000` in the iPhone app and open **Be the Camera** manually. The phone screen reports the incoming frame rate, resolution, and which camera the hub considers active. If connection fails with `CAPABILITY_DENIED`, capture the full message; that indicates a Meta server-side capability gate rather than a hub transport failure.

The software path is covered by the iOS build/tests and hub camera contract tests. A real-glasses run is still required before claiming hardware validation.
