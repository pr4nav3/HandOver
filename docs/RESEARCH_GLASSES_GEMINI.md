# Verified API notes: Meta glasses toolkit (iOS) and google-genai 3.3

Fetched 2026-11-14. "Verified" = read in official source today. "Inferred" = not confirmed.

## Meta Wearables Device Access Toolkit iOS 1.0.1
- Repo: github.com/meta/meta-wearables-dat-ios (facebook/... redirects). SPM exactVersion 1.0.1. Products: MWDATCore, MWDATCamera (also Display, Inputs, MockDevice, Motion, Speech). Import MWDATCore and MWDATCamera. iOS 17.2+, Xcode 26.4+, Swift 6.3+. Verified.
- xcodegen (inferred):
  ```yaml
  packages:
    MWDAT: { url: https://github.com/facebook/meta-wearables-dat-ios, exactVersion: 1.0.1 }
  # target dependencies: - package: MWDAT, product: MWDATCore / MWDATCamera
  ```
- Info.plist (from official CameraAccess sample): CFBundleURLTypes scheme (use `handover`); `MWDAT` dict with `AppLinkURLScheme = handover://`, `MetaAppID = $(META_APP_ID)`, `ClientToken = $(CLIENT_TOKEN)`, `TeamID = $(DEVELOPMENT_TEAM)` (Developer Mode needs no credentials); UIBackgroundModes bluetooth-central (sample also lists processing, audio, bluetooth-peripheral); NSBluetoothAlwaysUsageDescription, NSBluetoothPeripheralUsageDescription; NSLocalNetworkUsageDescription + NSBonjourServices. Add NSAppTransportSecurity > NSAllowsLocalNetworking = true for ws://<laptop IP> (inferred).
- Developer Mode: Meta AI app > Settings > App Info > tap App version 5 times > Developer Mode > Enable. It turns off after glasses firmware updates.
- Registration:
  ```swift
  try Wearables.configure()                     // once in App.init
  try await Wearables.shared.startRegistration()
  .onOpenURL { url in Task { _ = try? await Wearables.shared.handleUrl(url) } }
  for await s in wearables.registrationStateStream() { /* .registered */ }
  for await devices in wearables.devicesStream() { }
  if try await wearables.checkPermissionStatus(.camera) != .granted { _ = try await wearables.requestPermission(.camera) }
  ```
- Session and stream (verified against sample):
  ```swift
  let session = try wearables.createSession(deviceSelector: AutoDeviceSelector(wearables: wearables))
  session.statePublisher.listen { state in }    // idle, starting, started, paused, stopping, stopped
  try session.start()
  // only after state == .started:
  let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2) // 2/7/15/24/30; low 360x640
  guard let camera = try session.addCamera(config: config) else { return }
  let token = camera.stream.videoFramePublisher.listen { frame in guard let img = frame.makeUIImage() else { return } }
  camera.stream.start()
  // keep listener tokens alive (AnyListenerToken / ListenerTokenBag). Stop: camera.stop(); session.stop()
  ```
- `.raw` delivers frames only in the foreground. Backgrounding ends the session. Keep app open, isIdleTimerDisabled = true.
- Errors: DeviceSessionError, StreamError (.thermalHot, .peakPowerLimit, .batteryLow).

## google-genai 3.3.0 (installed source)
- SDK default API version is v1. Pass `HttpOptions(api_version="v1beta")`.
- `GenerateContentConfig(response_mime_type="application/json", response_json_schema=..., media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW, thinking_config=types.ThinkingConfig(thinking_level="minimal"))`.
- `Part.from_bytes(data=, mime_type=)`, `VideoMetadata(fps=)` range (0, 24].
- Async: `await client.aio.models.generate_content(...)`. Transport httpx2 (installed); nothing else needed.

## Models (aistudio.google.com/docs/models)
- gemini-3.8-flash stable; thinking low/medium/high only (no minimal). Free tier yes.
- gemini-3.5-flash-lite stable; thinking minimal (default)/low/medium/high. Free tier yes.
- gemini-3.1-pro-preview: preview, NO free tier. Do not use as a fallback without asking (costs money).
- Free-tier rate limits are not published per model; check aistudio.google.com/rate-limit.
