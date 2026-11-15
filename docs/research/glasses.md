# Glasses (Android and iOS), audio, phone camera fallback (2026-11-14)

iOS toolkit APIs: see ../RESEARCH_GLASSES_GEMINI.md.

## Android toolkit (verified)
- github.com/facebook/meta-wearables-dat-android, 1.0.1 (2026-10-09), developer preview, Maven Central (no token). Samples: CameraAccess, BirdSpotter, DisplayAccess.
- Deps: group com.meta.wearable: mwdat-core, mwdat-camera (also speech, mockdevice, display, inputs, motion). mavenCentral() only.
- CameraAccess: minSdk 31, compileSdk 36, targetSdk 36, Java 17.
- Manifest: BLUETOOTH, BLUETOOTH_CONNECT, CAMERA, INTERNET, RECORD_AUDIO, MODIFY_AUDIO_SETTINGS (optional FOREGROUND_SERVICE, FOREGROUND_SERVICE_CONNECTED_DEVICE, WAKE_LOCK). meta-data com.meta.wearable.mwdat.APPLICATION_ID = ${mwdat_application_id}, com.meta.wearable.mwdat.CLIENT_TOKEN = ${mwdat_client_token}. VIEW intent-filter with scheme `handover` (Meta AI app callback).
- Developer Mode: manifestPlaceholders mwdat_application_id = "0", mwdat_client_token = "0"; Developer Mode on in Meta AI app.
- 1.0.0 HEVC buffer corruption freeze fixed in 1.0.1. Pin 1.0.1. Camera streaming "experimental".
```kotlin
Wearables.initialize(context)
Wearables.startRegistration(activity)
Wearables.registrationState.collect { }; Wearables.devices.collect { }
Wearables.checkPermissionStatus(Permission.CAMERA)
registerForActivityResult(Wearables.RequestPermissionContract()) { } // launch(Permission.CAMERA)
Wearables.createSession(AutoDeviceSelector()).onSuccess { s -> s.start() }
session.state.collect { if (it == DeviceSessionState.STARTED) startCamera(session) }
session.addCamera(StreamConfiguration(videoQuality = VideoQuality.LOW, frameRate = 2))
  .onSuccess { cam -> cam.start(); cam.stream.videoStream.collect { f -> handle(f) } }
// errorStream; stop: camera.stop(); session.stop(). Stopped session cannot restart: create new.
```
- Frame: default decoded, VideoFrame.buffer raw YUV. Leave compressVideo off; build NV21 and YuvImage(...).compressToJpeg(rect, 60, out). YUV layout (I420 vs NV21) undocumented: test on device, swap U/V if colors wrong.

## Glasses audio
- Plain Bluetooth, no toolkit calls. A2DP play only; HFP two-way 16/8 kHz mono; HFP disables A2DP. Set HFP before camera stream or audio route fails silently.
- Android: TYPE_BLUETOOTH_SCO device, MODE_IN_COMMUNICATION, setCommunicationDevice, before session.start(). SpeechRecognizer for "next" (inferred it follows comm device).
- iOS: .playback (A2DP) or .playAndRecord with .allowBluetoothHFP; SFSpeechRecognizer.
- Recommendation: keep audio on the laptop; HFP sounds like a phone call.

## Phone fallback and one Android app
- Android cleartext: res/xml/network_security_config.xml `<base-config cleartextTrafficPermitted="true"/>`.
- iOS: NSAllowsLocalNetworking, NSLocalNetworkUsageDescription.
- One Android app: "Glasses" and "Phone" sources, FLAG_KEEP_SCREEN_ON; OkHttp WebSocket to ws://<ip>:8000/ws/camera, JPEG ByteString max 1 fps, drop if previous send pending. Phone path CameraX ImageAnalysis KEEP_ONLY_LATEST RGBA_8888, toBitmap, JPEG 60, back camera ~1280x720. Auto fallback to phone if registration/permission/session/stream fails, no frame within 5 s of STARTED, or CRITICAL_STREAM_ERROR. Last resort capture.html or replay.

## Open
- YUV layout; mwdat-speech API names; min Meta AI app version on Android.
