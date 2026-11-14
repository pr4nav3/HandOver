# Camera Mode

The phone, or the learner's Ray-Ban Meta glasses through the phone, as the hub's camera (SCREENS.md 10).

- `CameraScreen(state, vm, modifier, onClose)`: entry point. Camera pre-prompt, then Camera Mode.
- `CameraModeContent`: the stateless layout (screenshots use it).
- `FramePipeline`, `FrameGate`, `FpsMeter`: upright, long side 960, JPEG 70, about 1 fps, and the real sent rate.
- Glasses: `ui/glasses` (Meta Wearables Device Access Toolkit 1.0.1). Frames go through the same gate into core's `CameraSocket` with source "glasses".
