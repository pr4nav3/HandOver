# Glasses and phone recording: research notes (updated 2026-11-15)

Tags: [V] verified in Meta 1.0 reference, the official repo, or our compiled integration; [I] inferred, needs a device test.
The active MWDAT 1.0.1 integration is in `apps/apple/Sources/Features/Record/GlassesToolkit.swift`. A signed iPhone development build has completed registration and reached the live HandOver flow with Ray-Ban Meta Gen 2; sustained matrix coverage remains open.

## Transport and signing correction

- [V] The 1.0.1 path used here streams over Bluetooth Classic through the external-accessory protocol. It does not use the earlier Hotspot Configuration or Wi-Fi Info entitlement assumption.
- [V] The Bluetooth-only development configuration has signed with a free Personal Team and completed a Gen 2 live-flow run.
- [V] The app requests `.medium`, then `.low`, at 15 fps and measures the frames that actually arrive. The phone forwards newest-only JPEGs to the hub, so backpressure drops old frames instead of adding latency.
- [I] Open: repeat sustained sessions across the intended iPhone, Meta AI, firmware, and glasses matrix. One working development setup is not a distribution claim.

## Expert recording from the glasses
- [V] `StreamConfiguration(videoCodec:resolution:frameRate:)`; resolutions high 720x1280, medium 504x896, low 360x640; frame rates 2, 7, 15, 24, 30. `.raw` = decoded 420v buffers, foreground only. `.hvc1` = compressed HEVC CMSampleBuffers, foreground and background.
- [V] Audio (dev/beta only, needs Audio Streaming approval + `.microphone` permission): `StreamConfiguration(videoCodec:audioCodec:resolution:frameRate:)`, `AudioCodec.pcm(.rate48000, 1)`, `stream.audioFramePublisher`. Subscribe before `stream.start()`.
- Current implementation: a `.raw` stream at `.medium` or `.low`, 15 fps, written to HEVC with `AVAssetWriter`. Recording is video-only; the glasses microphone remains outside the validated permission path.
- Fallback: Gen 2 records up to 3K30 natively; import via `PhotosPicker(selection:matching: .videos)` (no photo permission needed).

## Registration UX
- `try Wearables.configure()` once in App.init; `.onOpenURL { Task { _ = try? await Wearables.shared.handleUrl($0) } }`.
- async throws: `startRegistration()`, `checkPermissionStatus(.camera)`, `requestPermission(.camera)`. sync throws: `createSession(deviceSelector:)`, `session.start()`.
- States via `registrationStateStream()`: `.unavailable`, `.available`, `.registering`, `.registered`. Errors: `RegistrationError.metaAINotInstalled`, `.configurationInvalid` (Developer Mode off).
- Developer Mode: Meta AI app > Settings > App Info > tap version 5 times. Turns off after firmware updates.
- Device: `devicesStream()`, `deviceForIdentifier`, fields `name`, `batteryLevel`, `chargingState`, `linkState`, `hingeState`, `donState`, `thermalLevel`.
- StreamError: `.thermalHot`, `.batteryLow`, `.peakPowerLimit`, `.hingesClosed`, `.permissionDenied`, `.deviceNotConnected`, `.timeout`, `.videoStreamingError`. DeviceSessionError: `.thermalCritical`, `.batteryCritical`, `.datAppOnTheGlassesUpdateRequired` (`openDATGlassesAppUpdate()`). A stopped session cannot restart.

## Learner streaming
- Glasses `.raw` tries `.medium`, then `.low`, at 15 fps. The common phone pipeline scales to a 640 px long side and sends at up to 15 fps; serious and critical thermal states reduce that to 4 and 2 fps.
- A one-slot latest-frame buffer replaces old frames while encoding or sending. JPEG uses one shared Metal-backed `CIContext`; no frame queue is allowed to build.

## Phone recording
- AVCaptureMovieFileOutput, `.hd1920x1080`, HEVC, SDR (`activeColorSpace = .sRGB`), stabilization `.cinematicExtended` or `.auto`, `RotationCoordinator` for orientation. Recording cannot survive a lock; uploads can.
- Camera-style UI: shutter morph (circle to rounded square, spring 0.3/0.8), red timer pill with `Text(timerInterval:)`, `.sensoryFeedback(.impact(weight: .medium))`, white blink skipped under Reduce Motion.

## macOS
- No MWDAT. Learner camera via Continuity Camera and `.deskViewCamera` (top-down desk view). Sandbox: camera, audio-input, network.client.

## Upload
- `POST /api/lesson` multipart (file, title, id), Content-Length required, 2 GB limit. Background URLSession needs a body file; start with a normal session + `beginBackgroundTask`, move to background session after a lock test.
- Info.plist additions: NSMicrophoneUsageDescription, NSBluetoothPeripheralUsageDescription.
