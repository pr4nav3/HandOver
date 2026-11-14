# Glasses and phone recording: research notes (2026-11-14)

Tags: [V] verified in Meta 1.0 reference, the official repo, or Pranav's compiled code; [I] inferred, needs a device test.
The compiling MWDAT 1.0.1 integration is on branch soham/pranav-fixes (ios/Sources/GlassesCameraSource.swift).

## P0: entitlements and the Wi-Fi link (test first)
- [V] Camera streaming runs over a Wi-Fi network hosted by the glasses. Needs `com.apple.developer.networking.HotspotConfiguration` and `com.apple.developer.networking.wifi-info` entitlements plus Local Network permission. Without them the SDK connects over BLE but never streams.
- [V] The official CameraAccess sample entitlements: HotspotConfiguration true, wifi-info true, keychain-access-groups `$(AppIdentifierPrefix)$(CFBundleIdentifier)`. ios/project.yml has no entitlements file yet.
- [I] Risk: a free Apple ID (personal team) may not get the Hotspot capability, so frames never arrive. If Xcode refuses the capability, glasses streaming needs a paid Apple Developer team (costs money: ask the user). Fallback: record on the glasses natively and import from Photos.
- [I] Open: while on the glasses' Wi-Fi, can the phone still reach the laptop hub? Test early; USB Personal Hotspot is a fallback.

## Expert recording from the glasses
- [V] `StreamConfiguration(videoCodec:resolution:frameRate:)`; resolutions high 720x1280, medium 504x896, low 360x640; frame rates 2, 7, 15, 24, 30. `.raw` = decoded 420v buffers, foreground only. `.hvc1` = compressed HEVC CMSampleBuffers, foreground and background.
- [V] Audio (dev/beta only, needs Audio Streaming approval + `.microphone` permission): `StreamConfiguration(videoCodec:audioCodec:resolution:frameRate:)`, `AudioCodec.pcm(.rate48000, 1)`, `stream.audioFramePublisher`. Subscribe before `stream.start()`.
- Recommendation: `.hvc1`, `.high`, 30 fps (try 24), written to MP4 with AVAssetWriter passthrough (`outputSettings: nil`, `sourceFormatHint` from the first buffer). Retime buffers to the host clock; phone mic for audio if glasses audio is unavailable. [I] Expected bitrate about 450 to 600 kbps: soft but first-person.
- Fallback: Gen 2 records up to 3K30 natively; import via `PhotosPicker(selection:matching: .videos)` (no photo permission needed).

## Registration UX
- `try Wearables.configure()` once in App.init; `.onOpenURL { Task { _ = try? await Wearables.shared.handleUrl($0) } }`.
- async throws: `startRegistration()`, `checkPermissionStatus(.camera)`, `requestPermission(.camera)`. sync throws: `createSession(deviceSelector:)`, `session.start()`.
- States via `registrationStateStream()`: `.unavailable`, `.available`, `.registering`, `.registered`. Errors: `RegistrationError.metaAINotInstalled`, `.configurationInvalid` (Developer Mode off).
- Developer Mode: Meta AI app > Settings > App Info > tap version 5 times. Turns off after firmware updates.
- Device: `devicesStream()`, `deviceForIdentifier`, fields `name`, `batteryLevel`, `chargingState`, `linkState`, `hingeState`, `donState`, `thermalLevel`.
- StreamError: `.thermalHot`, `.batteryLow`, `.peakPowerLimit`, `.hingesClosed`, `.permissionDenied`, `.deviceNotConnected`, `.timeout`, `.videoStreamingError`. DeviceSessionError: `.thermalCritical`, `.batteryCritical`, `.datAppOnTheGlassesUpdateRequired` (`openDATGlassesAppUpdate()`). A stopped session cannot restart.

## Learner streaming
- Glasses `.raw` `.low` 2 fps throttled to 1 JPEG/s, send-when-idle. Keep a one-slot latest frame and send it the moment the previous send finishes.
- JPEG: shared Metal CIContext `jpegRepresentation(of:colorSpace:options:)` at quality 0.6 beats UIImage.jpegData. Keep `isIdleTimerDisabled = true`.

## Phone recording
- AVCaptureMovieFileOutput, `.hd1920x1080`, HEVC, SDR (`activeColorSpace = .sRGB`), stabilization `.cinematicExtended` or `.auto`, `RotationCoordinator` for orientation. Recording cannot survive a lock; uploads can.
- Camera-style UI: shutter morph (circle to rounded square, spring 0.3/0.8), red timer pill with `Text(timerInterval:)`, `.sensoryFeedback(.impact(weight: .medium))`, white blink skipped under Reduce Motion.

## macOS
- No MWDAT. Learner camera via Continuity Camera and `.deskViewCamera` (top-down desk view). Sandbox: camera, audio-input, network.client.

## Upload
- `POST /api/lesson` multipart (file, title, id), Content-Length required, 2 GB limit. Background URLSession needs a body file; start with a normal session + `beginBackgroundTask`, move to background session after a lock test.
- Info.plist additions: NSMicrophoneUsageDescription, NSBluetoothPeripheralUsageDescription.
