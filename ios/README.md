Compiles with Xcode on macOS against MWDAT 1.0.1; not yet run on a device.

# HandOver Camera (iPhone app, PLAN.md W8)

A small SwiftUI app that sends about one JPEG per second to the hub's `/ws/camera`
(CONTRACT.md section 6). It shows the current step and status, and has large Next and Back buttons.
The source is the phone's back camera (W8a), or Ray-Ban Meta glasses through the Meta Wearables
Device Access Toolkit 1.0.1 (W8b). If the glasses fail, the app switches to the phone camera on its own.

The app builds with zero warnings in the glasses and hub files. Every toolkit call lives in
`Sources/GlassesCameraSource.swift`, checked against the 1.0.1 swiftinterface files. Nothing has run on
an iPhone or the glasses yet.

## Files

| File | What it does |
|---|---|
| `project.yml` | xcodegen spec: target HandOverCamera, iOS 17.2, Swift 5 mode, `com.handover.camera`, DAT package from 1.0.1, Info.plist keys, portrait only |
| `Sources/HandOverCameraApp.swift` | `@main`; configures the toolkit and forwards `onOpenURL` callbacks from the Meta AI app |
| `Sources/FrameSource.swift` | `FrameSource` protocol, JPEG helper (long side 960, quality 0.6), 2 fps throttle, and the glasses stub for builds without the toolkit |
| `Sources/PhoneCameraSource.swift` | AVCaptureSession back camera, 1280x720, portrait, 1 frame/s |
| `Sources/GlassesCameraSource.swift` | All toolkit calls: 2 fps at `.low`, throttled to 2 fps. Falls back after 15 s without frames, or on any error |
| `Sources/HubClient.swift` | WebSocket client: hello, binary frames, next/back with `from`, state parsing, reconnect with backoff capped at 5 s, stops on close code 4000 |
| `Sources/ContentView.swift` | UI and `SessionController` (source switching, idle timer, scene phase) |

## Build (Mac)

1. `brew install xcodegen`
2. `cd ios && xcodegen generate`. This writes `HandOverCamera.xcodeproj` and `Supporting/Info.plist`. Both are gitignored; edit `project.yml` instead.
3. `open HandOverCamera.xcodeproj`. Wait for the package to resolve (File > Packages > Resolve Package Versions if it stalls).
4. Select the HandOverCamera target, then Signing & Capabilities. Tick "Automatically manage signing" and pick your free Personal Team. If the bundle id is taken, change it to something like `com.<you>.handover.camera`.
5. Plug in the iPhone and select it as the run destination. Press Run.
6. On the iPhone, turn on Settings > Privacy & Security > Developer Mode (needed once, and the phone restarts). Trust the developer under Settings > General > VPN & Device Management.
7. On first launch, allow Camera and Local Network. If Local Network is denied, the socket fails silently. Re-enable it in Settings > HandOver.

The toolkit needs Xcode 26.4 or later (Swift 6.3 tools). With an older Xcode, the package will not
resolve. In that case, use the fallback below.

## Use

- Run the hub on the Mac (`scripts/run_server.sh`). Both devices must be on the same Wi-Fi or hotspot.
- Enter the Mac's LAN address in the app, for example `192.168.1.20:8000`. A bare IP assumes port 8000. `ws://`, `wss://` and `http(s)://` URLs also work. The path defaults to `/ws/camera`.
- Pick Phone or Glasses, then tap Start. The screen stays awake while running. Leaving the app stops streaming; coming back restarts it.
- Next and Back stay disabled until the hub has sent a state with a lesson. Pick the lesson in the web app.
- If you see "Replaced", another connection with this phone's device id took over (close code 4000). The app does not reconnect on its own. Tap Start again.
- `wss://` to the hub's port 8443 only works if the phone trusts the mkcert root. Plain `ws://<ip>:8000` is the normal path.
- If iOS blocks `ws://<ip>` with an ATS error (-1022), `NSAllowsLocalNetworking` is not covering the address. For the demo, add `NSAllowsArbitraryLoads: true` under `NSAppTransportSecurity` in `project.yml` and regenerate.

## Glasses: Developer Mode in the Meta AI app

1. Pair the glasses in the Meta AI app (v254 or later). Update the glasses firmware first if it asks.
2. In the Meta AI app, open Settings > App Info and tap the version number 5 times. Turn on Developer Mode.
3. In HandOver, choose Glasses and tap Start. The first time, the app opens the Meta AI app for registration and camera permission. Approve, then return to HandOver. Streaming restarts when the app is back in front.
4. Developer Mode turns itself off after glasses firmware updates. Check it again right before the demo.
5. Keep HandOver in the foreground. Backgrounding the app ends the glasses session.

The app falls back to the phone camera, with an orange note, if no glasses frame arrives within 15 s
or the stream reports an error. Tap Start again (with Glasses selected) to retry.

## Building without the glasses toolkit (phone camera only)

The phone path does not depend on the toolkit. There are two ways to drop the glasses source, and either one leaves the
app building and working with the phone camera. In that build, choosing "Glasses" falls straight back to Phone.

**A. The package resolves, but `GlassesCameraSource.swift` does not compile.** In `project.yml`, change
`SWIFT_ACTIVE_COMPILATION_CONDITIONS: "$(inherited)"` to `"$(inherited) HANDOVER_NO_GLASSES"`, then run `xcodegen generate`.
The real class compiles out, and the stub in `FrameSource.swift` takes over. In Xcode only, you can instead add
`HANDOVER_NO_GLASSES` under Build Settings > Active Compilation Conditions.

**B. The package does not resolve (old Xcode, no network, or a bad tag).** In `project.yml`:
1. Delete the `packages:` block and the two `- package: MWDAT` dependency entries.
2. Optionally, exclude the file from the target by uncommenting
   `excludes: ["GlassesCameraSource.swift"]` under `sources:`.
3. Run `xcodegen generate`.

Without the package, `canImport(MWDATCore)` is false, so the stub is used automatically. The flag from A is not
needed, but setting it does no harm. If you exclude the file while keeping the package, you must also set the
flag from A, or `GlassesCameraSource` will be undefined.

In Xcode without xcodegen: select `GlassesCameraSource.swift`, untick HandOverCamera under Target Membership,
and remove the MWDATCore and MWDATCamera packages under the project's Package Dependencies.

## 8 PM glasses gate (docs/PLAN.md)

W8b (glasses) is time-boxed from 6:30 to 8:00. At **8:00 PM**, frames must reach the hub through this app for
**60 s with no gap over 5 s and one camera advance**. Otherwise, glasses leave the demo, the pitch and Devpost.
The phone camera (W8a) is the main path either way. The demo ladder is glasses, then this iPhone app, then Safari
`capture.html`, then replay.

## Checklist for the first device run

- Check the `MWDAT` Info.plist dictionary keys against the sample's Info.plist (only `AppLinkURLScheme` is set).
- Phone smoke test: Start with Phone selected. The hub log and the web app should show camera frames, and the
  frames counter should go up by about 1 per second.
