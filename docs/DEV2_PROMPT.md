# Developer 2 autonomous work prompt (HandOver clients)

Paste everything below the line into a Claude Code session opened in this repo on Developer 2's Mac. It is written to the agent.

---

You are Developer 2 on HandOver. Work on your own for many hours until every item below is done and verified, or honestly marked as not done. Developer 1 (hub, AI checks, packaging, CI) works in parallel on another Mac. The lead owns the plan.

## 1. Mission (read this first)

- HandOver: an expert does a task once on camera while narrating. The hub cuts that take into steps and plays the expert's own clip for each step. It moves on only when the learner's camera shows the step is done.
- The hub is one Python FastAPI server on a laptop (Mac or Windows). It holds lessons, runs checks and serves the web app at `http://<ip>:8000/`.
- You own every client: the web app (learn, teach, connect, spectator), `capture.html`, a new `join.html`, the iPhone app, the Android app, the icon, and the submission docs.
- All clients talk to the hub over one wire contract, `docs/CONTRACT_V2.md`. That contract is the reason any phone works with any laptop. Never invent fields.
- Demo: a judge folds an origami fortune teller under a phone camera; clips advance as each fold is seen; skipping the flip at step 5 makes the screen say so. Then an Android phone takes over as camera and a judge's phone mirrors the screen.
- Hacking ends **12:00 PM Sunday 2026-11-15**. Feature freeze 8:00 AM Sunday. Contract freeze 6:00 AM Sunday. Glasses go/no-go 8:00 PM Saturday.
- Quality bar: Apple-native, calm, honest. Nothing on screen may claim something the code does not do.

Read before writing code, in this order:
1. `docs/PLAN.md` (milestones, sync points, matrix; if its times differ from this prompt, PLAN.md wins)
2. `docs/CONTRACT_V2.md` (authoritative interface)
3. `docs/research/architecture.md` sections 4, 5, 10, 12, 13
4. `docs/research/design.md` (screens, strings, tokens)
5. `docs/RESEARCH_GLASSES_GEMINI.md` (iOS glasses toolkit APIs, verified) and `docs/research/glasses.md` (Android toolkit, phone camera, fallback)
6. `docs/IDEAS.md`, `docs/SPEC.md`, `docs/research/judging.md`
7. Code: `web/src/*`, `web/mock/mock-server.mjs`, `web/e2e/*.mjs`, `server/static/capture.html`, `server/main.py` (read only, to see what the hub sends today)

## 2. Paths

You may edit only:
- `web/**`
- `server/static/**` (`capture.html`, new `join.html`)
- `apps/ios/**` (including `apps/ios/ci.sh`)
- `apps/android/**` (including `apps/android/ci.sh`)
- `assets/icon/**`
- `docs/TESTED.md`, `docs/DEVPOST.md`, `docs/pitch/**`
- `docs/DECISIONS_DEV2.md`: yours alone

Never edit: `server/*.py`, `scripts/**`, `packaging/**`, `.github/workflows/**`, `lessons/**`, `CONTRACT.md`, `docs/CONTRACT_V2.md`, `README.md`, `.gitignore`, `docs/PLAN.md`, `docs/IDEAS.md`, `docs/SPEC.md`, `docs/research/**`, `docs/DEV1_PROMPT.md`. To change any of these, write the exact text you need under `## Requests for Developer 1` in `docs/DECISIONS_DEV2.md` and list it in your next status update so the human relays it. Keep working on something else meanwhile.

## 3. Contract you consume and send

Status is from CONTRACT_V2: **EXISTS** = in the hub today, rely on it. **NEW** = not built yet; assume nothing until Developer 1 says it is merged on `main`.

### 3.1 Web app (viewer, teach)
| Item | Exact fields | Status |
|---|---|---|
| `GET /api/lessons` | `[{id, title, steps}]` | EXISTS |
| `GET /api/lessons/{id}` | lesson.json: `id, title, video, steps[]`; step `n, title, start, end, clip, captions, ref_frame, check_type ("camera"/"manual"), check_question, prerequisites` | EXISTS |
| Step extras | `ref_time`, `common_mistake`, `mistake_question` (P1); `i18n` (P2) | NEW |
| `POST /api/lesson`, `GET /api/jobs/{job}` | multipart `file`, `title`, `id`; job `status` one of `queued, normalizing, extracting, cutting, done, error`, `message`, `id` | EXISTS |
| `POST /api/lessons/{id}/recut` | optional full lesson body; returns new lesson.json | EXISTS |
| `GET /lessons/{id}/<path>` | clips, captions, frames; append `?v=<rev>` | EXISTS |
| `GET /api/info` | `contract`, `version`, `hub_id`, `name`, `os`, `ports.http`, `ports.https` (null without certs), `urls.local`, `urls.lan[]`, `urls.join[]`, `urls.capture[]`, `check.mode`, `check.model`, `check.has_key`, `check.offline`, `check.offline_reason` | NEW P0 |
| `GET /api/qr?text=<url>` | `image/svg+xml` | NEW P0 |
| `GET /join?hub=<id>` | serves your `server/static/join.html` | NEW P0 |
| `GET /api/lessons/{id}/export[?video=0]`, `POST /api/lessons/import` | zip download; import returns `{id, title, steps, renamed}` | NEW (S-P) |
| `DELETE /api/lessons/{id}` | `{deleted}` | NEW P1 |
| `PUT /api/settings` | body `{gemini_key}`, localhost only, returns `{has_key, mode}` | NEW P1 |
| `/ws/ui` send | `{"type":"select_lesson","id"}`, `{"type":"next","reason":"button"/"voice","from":int}`, `{"type":"back","from":int}`, `{"type":"goto","step":int}` | EXISTS |
| `/ws/ui` send | `{"type":"dismiss_mistake"}` | NEW P1 |
| `/ws/ui?frames=0` | no binary frames to this client | NEW P1 |
| `/ws/ui` receive `state` | `lesson_id, rev, step, total, status ("watching","checking","verified","manual","done"), last_check {done, confidence, latency_ms}, camera_connected` | EXISTS |
| `state` additions | `camera {camera_id, name, platform, source}`, `cameras` (P0); `last_check.source`, `last_check.reason`, `check_source`, `check_offline`, `check_offline_reason ("no_key","rate_limited","errors")`, `mistake` (P1) | NEW |
| `advance` | `{from, to, reason ("camera","button","voice","timer")}`; chime only on `camera` | EXISTS |
| `mistake` | `{step, kind ("behind","ahead"), looks_like, message, confidence, source}` | NEW P1 |
| `error` | `{message}`; exact strings, e.g. `no lesson selected` | EXISTS |
| binary | newest live JPEG, at most 4 per second | EXISTS |

### 3.2 Cameras (iOS app, Android app, capture.html) on `/ws/camera`
| Item | Exact fields | Status |
|---|---|---|
| binary JPEG | starts `FF D8`, about 1 fps, long side 640 to 1280 | EXISTS |
| `hello` (first message, resend on every source switch and reconnect) | `{"type":"hello","device_id","name","platform":"ios"/"android"/"web","source":"glasses"/"phone"/"browser","model","app_version"}`. `device_id` stable per install (UUID in app storage, localStorage for capture.html), 1 to 64 chars; `name` 1 to 40 chars | NEW P0 |
| `welcome` | `{camera_id, active, hub {hub_id, name, version, contract}}` | NEW P0 |
| `camera_status` | `{active}` | NEW P0 |
| close code 4000 `replaced` | never auto-reconnect on 4000 | NEW P0 |
| `state`, `advance`, `mistake`, `error` on the camera socket | same as `/ws/ui` | NEW P1 |
| send `next` / `back` | `{"type":"next","reason":"button","from":int}`, `{"type":"back","from":int}`, only after hello | NEW P1 |
| Join URL forms to accept | `handover://connect?host=&port=&hub=`; any `http(s)://host[:port]/...` (port 8000 when absent; if a query `http=<port>` exists, use it); typed `host` or `host:port` | NEW P0 |

### 3.3 Rules while a NEW feature is not built
- **Feature-detect, never assume.** `/api/info` 404 or failed: treat as contract 1, show the address from `location.host`, hide the QR. Field absent from `state`: hide that UI. No `welcome` within 2 s of hello: keep streaming plain JPEGs and hide Next and Back on the phone.
- **Mock it in `web/mock/mock-server.mjs` first.** Add every NEW item there exactly as CONTRACT_V2 words it (field names, error strings), plus test hooks like the existing `/mock/*` ones (for example `/mock/mistake?kind=behind`, `/mock/offline?reason=rate_limited`, `/mock/camera?source=file`). The mock QR may be a placeholder SVG labeled "mock".
- **Never fake it in the real UI.** No placeholder QR, offline badge, mistake banner, or camera name unless the real hub sent it. Screenshots for Devpost come from the real hub only.
- Fix mock drift you find (example: the mock sends `No lesson selected`; the contract says `no lesson selected`).

## 4. Milestones, in order

Each has a definition of done (DoD) and the exact check. Post a short status line after each: finished, running, left. Never give time estimates.

Common checks, referred to by name below:
- **BUILD**: `cd web && npm run build` passes with no TypeScript errors.
- **SHOTS** (mock): from `web/`, start `PORT=8011 MOCK_AUTO=0 node mock/mock-server.mjs` and `VITE_API_TARGET=http://localhost:8011 npx vite --port 5175` in the background, run `APP=http://localhost:5175 MOCK=http://localhost:8011 node e2e/screenshots.mjs`, then stop both. Open and look at every PNG in `web/screenshots/` that changed. Extend the script with a shot and a check for every new state you add.
- **REAL** (hub): repo root, `HANDOVER_CHECK=mock scripts/run_server.sh` and `.venv/bin/python -m server.replay lessons/demo-v1/norm.mp4 --loop --select demo-v1` in the background; from `web/`, `npx vite --port 5173` then `node e2e/real-server.mjs`. Once the hub serves the dist (M2 merged), also `npm run build` then `APP=http://localhost:8000 node e2e/real-server.mjs`. Look at the screenshots. Stop every process you started.
- **WATCH**: `.venv/bin/python scripts/smoke.py watch --base http://<hub ip>:8000` (exists after Developer 1's M3) prints every `state`, `advance`, `mistake`.
- **IOS**: load check (section 8), then `cd apps/ios && xcodegen generate && xcodebuild -project HandOverCapture.xcodeproj -scheme HandOverCapture -destination 'generic/platform=iOS Simulator' build`, then `./ci.sh` (unsigned device build, what CI runs). Build only; do not boot a simulator (it has no camera).
- **IOS-DEVICE**: when the human has connected and unlocked the iPhone: `xcrun devicectl list devices` for its id, then `xcodebuild -project HandOverCapture.xcodeproj -scheme HandOverCapture -destination 'platform=iOS,id=<id>' -allowProvisioningUpdates DEVELOPMENT_TEAM=V8PCS2UL23 build`, then `xcrun devicectl device install app --device <id> <path to built .app>`. If Xcode on this Mac is not signed in to the Apple ID for team V8PCS2UL23, ask the human to sign in (Xcode > Settings > Accounts). Never handle passwords.
- **ANDROID**: load check, then `cd apps/android && ./gradlew assembleDebug` (needs JDK 17 and the Android SDK). Ask the human before installing the Android SDK, a JDK, Gradle or an emulator image. If declined, CI builds the APK regardless: push and confirm the `android` job with `gh run list --limit 3`.

If `.venv` is missing: `python3.12 -m venv .venv && .venv/bin/pip install -r server/requirements.lock`. If ffmpeg is missing, ask the human once and use the mock meanwhile.

| # | Milestone | Definition of done | Check |
|---|---|---|---|
| D0 | Setup | Branch `dev2/clients` from `main`; all read-first docs read; `docs/DECISIONS_DEV2.md` exists | `git status` clean on the branch |
| W1 | Web served by the hub; mock mirrors V2 | Only relative URLs, works from `http://<ip>:8000/` with no Vite proxy; `api.ts` types gain every V2 field as optional; mock has `/api/info`, `/api/qr`, hello and welcome on `/ws/camera`, `camera`, `cameras`, `check_*`, `mistake`, `dismiss_mistake`, `frames=0` | BUILD, SHOTS, REAL (both forms once the hub serves the dist) |
| W8a | iPhone app skeleton streams the phone camera | xcodegen project, typed address, plain JPEG frames at 1 fps to today's hub (no hello needed) | IOS; IOS-DEVICE when the phone is connected: live frames visible on the learn screen |
| **Sync 1, 4:30 PM** | Contract smoke | Your side: BUILD and REAL pass against Developer 1's latest `main` | REAL |
| W8b | iPhone app complete (spec in section 5) | hello, welcome, `camera_status`, step title, Next and Back, haptics, `handover://connect`, QR link from join.html, plist keys, `apps/ios/ci.sh` | IOS, IOS-DEVICE, WATCH shows `camera.platform: "ios"` |
| W4 | capture.html | sends hello (`platform:"web"`, `source:"browser"`, `name:"iPhone Safari"` or similar), recording dot, idle notice on `camera_status`, no reconnect on close 4000 | REAL with capture.html open in Chrome on `http://localhost:8000/capture` (localhost counts as secure); iPhone Safari over https with mkcert if certs exist |
| W2 | Connect panel | QR from `/api/qr` of `urls.join[0]`, address in plain text under it, "Wrong network?" picker over `urls.lan`, camera name in the top bar from `state.camera.name`, "iPhone connected" when the first frame arrives | BUILD, SHOTS, REAL; scan the QR with the real iPhone |
| **Sync 2, 6:30 PM** | First live loop, iPhone app | Real iPhone on the hotspot, typed address; WATCH shows `camera.platform: "ios"`, one `advance` reason `camera`; Next on the phone gives `advance` reason `button` on every screen | WATCH. On fail: use capture.html for later syncs while fixing |
| S-G | Glasses source in the iPhone app, time-boxed 6:30 to 8:00 PM | Spec in section 5.2; auto fallback to the phone camera works | IOS-DEVICE with glasses |
| **Sync 3, 8:00 PM** | Glasses gate | Glasses frames reach the hub for 60 s with no gap over 5 s; `camera.source: "glasses"`; one camera advance on demo-v1 | WATCH. On fail: glasses stay in code behind the toggle and leave the demo, pitch and Devpost |
| W5 | Honest live states | Camera lost: last frame dimmed to 40%, "Camera disconnected. Reconnect your phone, or keep going with Next." "Offline check" badge with reason text when `check_offline`; check source and latency in small text; "Recording" banner whenever `camera.source == "file"`; `last_check.reason` shown only at confidence 0.7 or more; privacy line only after Developer 1's M15 test is merged | BUILD, SHOTS (one shot per state), REAL with replay (banner visible) |
| W6 | Mistake banner | Amber banner across the live view with `message`; spoken once with `speechSynthesis`; "You're ahead." for `kind:"ahead"`; buttons "Show step n" (`goto looks_like`) and "I'm fine" (`dismiss_mistake`); clears on step change; phone apps play a warning haptic | BUILD, SHOTS via mock hook; REAL once M9 lands |
| W3 | join.html | "Open in HandOver app" (`handover://connect?host=<location.hostname>&port=<location.port or 80>&hub=<hub>`); "Use this browser" only when `/api/info` has `ports.https`; "Just watch" to `/#/watch`; works with no JavaScript framework | Open `http://localhost:8000/join` in Chrome at 390x844 and 1440x900 (Playwright shot); tap each button on the real iPhone |
| **Sync 4, 10:00 PM** | Mac app and Android checkpoint | Your side: Android app builds (locally or in CI); iPhone app streams to the frozen Mac app if Developer 1 has it | ANDROID or CI; WATCH |
| A1 | Android app (formerly M13), spec in section 6 | Phone camera, hello, step title, Next and Back, haptics, `handover://connect` and typed address, cleartext config, `apps/android/ci.sh` | ANDROID; on a real phone or emulator WATCH shows `camera.platform: "android"`. No phone and no emulator: label "CI build only" |
| W7 | Spectator view | `#/watch`: read-only mirror on a phone browser (step title, step count, clip with captions, status badge, camera name, live frame when available); never sends next, back or goto | BUILD, SHOTS at 390x844, real iPhone Safari against the hub |
| W9 | App icon | `assets/icon/icon.svg` plus PNGs 16 to 1024, iOS AppIcon 1024, Android adaptive foreground and background; tell Developer 1 the paths | Look at every PNG |
| P1 | Learn screen polish | Fill the empty band in the right column (about 230 px at 1440x900) with an "Up next" preview (next step title and its `frames/NN.jpg`) or the expert's quote from the current caption; teach thumbnails use `lessonUrl(id, ref_frame, rev)` so they refresh after a recut | SHOTS at 1440x900 and 1920x1080, no empty band, no overflow; recut in REAL then confirm thumbnails change |
| S-D | Done screen from real events | Per-step learner time from observed `advance` timestamps vs the expert's clip length (`end - start`), steps checked by camera (count of `reason:"camera"`), mistakes caught (count of `mistake` messages). Nothing invented | SHOTS, REAL to done |
| **Sync 5, 12:00 AM** | Midnight full run | Real Gemini, iPhone app, fortune teller folded to done; planted skipped flip gives `mistake` `kind:"behind"` on screen and spoken; Wi-Fi off shows "Offline check" and the lesson still finishes | WATCH during the fold. On fail: stop SHOULD work, fix the loop with Developer 1 |
| A2 | QR scan in both apps (S-Q) | iOS: `AVCaptureMetadataOutput` `.qr`, no dependency. Android: ML Kit `barcode-scanning` (bundled model) on a CameraX analyzer. Both accept every URL form in 3.2 | IOS-DEVICE and ANDROID; scan the hub QR |
| S-A | Accessibility | Space or Right = Next, Left = Back, R replay clip, C captions, F full screen, 1 to 9 go to step; `aria-live` step announcements; `prefers-reduced-motion` turns motion into crossfades; visible 2 px focus ring; contrast of tokens checked and fixed to 4.5:1 | BUILD, SHOTS, keyboard-only walk in REAL |
| | Sleep 12:30 to 5:30 AM (human); the agent keeps going only on safe items: tests, screenshots, docs drafts | | |
| W10a | Screenshots for submission | Real-hub screenshots: learn mid-step, verified, mistake banner, teach timeline, connect QR, spectator on phone, iPhone app, Android app if real | Look at each |
| **Sync 7, 6:00 AM** | Contract freeze | No new contract asks after this | none |
| S-PB, S-T badge, S-K | Export and import buttons; self-test badge per step; Gemini key field | Each only when Developer 1's endpoint is on `main`; feature-detected | BUILD, SHOTS, REAL |
| W10b | Matrix tests | Every cell in PLAN.md section 7 that you can run, run and recorded | section 7 below |
| **Sync 8, 8:00 AM** | Feature freeze, venue-light rehearsal | Bug fixes only from here | WATCH during rehearsal |
| W10c | `docs/TESTED.md`, `docs/DEVPOST.md`, `docs/pitch/` | section 9 | dash and claim checks in section 9 |
| **Sync 9, 10:00 AM** | Devpost draft | Every device claim maps to a live or CI row in TESTED.md | section 9 commands print nothing |
| **Sync 10, 11:30 AM** | Submit (human) | | |

Later SHOULD items, only if every MUST above passed: S-W ("Why" narration and slow replay), S-F (target frame toggle, confidence ring), S-S web side. STRETCH: Android glasses source (section 6.2), filmstrip on the Done screen.

Drop order if behind at midnight: (1) Android becomes "APK built in CI, emulator only", labeled; (2) A2 QR scan drops (join.html covers it); (3) S-D shows only counts, no bars; (4) spectator reuses the learn layout read-only.

## 5. iPhone app spec (`apps/ios/`)

### 5.1 Base (W8)
- SwiftUI, xcodegen `project.yml`, target and scheme `HandOverCapture`, iOS 17.2+, bundle id `dev.handover.capture` (if the free team rejects it as taken, pick a unique suffix and record it in docs/DECISIONS_DEV2.md). Version 0.2.0.
- Screens per design.md: Connect (large title, Scan QR, Enter address, last hub remembered and auto-reconnected), Camera (preview, status dot, "Connected to {hub name}", step title and "Step n of N" from the hub, Next filled and Back plain, source picker "This iPhone" / "Ray-Ban Meta"), Source (glasses registration, permission, Developer Mode reminder).
- Phone camera: `AVCaptureSession` back camera 1280x720, `AVCaptureVideoDataOutput` with `alwaysDiscardsLateVideoFrames = true`, rotate upright (`videoRotationAngle`), encode JPEG quality 0.6, one frame per second.
- Socket: `URLSessionWebSocketTask` to `ws://<host>:<port>/ws/camera`. First message `hello`: `device_id` UUID kept in UserDefaults, `name` "iPhone" (or "Ray-Ban Meta via iPhone"), `platform:"ios"`, `source:"phone"` or `"glasses"`, `model` from `utsname` machine (for example `iPhone18,1`), `app_version` "0.2.0".
- Keep only the latest frame: if a send is pending, drop the new frame.
- Reconnect backoff 0.5, 1, 2, 4 s, capped at 5 s; resend hello with the same `device_id`; never reconnect after close code 4000.
- Receive `welcome`, `camera_status` ("Idle: another camera is active"), `state`, `advance`, `mistake`, `error`. Haptics: `UINotificationFeedbackGenerator` `.success` on `advance` reason `camera`, `.warning` on `mistake`.
- Next and Back send `{"type":"next","reason":"button","from":step}` and `{"type":"back","from":step}`; shown only after a `welcome` arrived.
- `UIApplication.shared.isIdleTimerDisabled = true` while streaming. Recording dot and the line "Live: frames go to {hub name}" while sending.
- URL scheme `handover`: route by host. `handover://connect?...` goes to pairing; anything else goes to `Wearables.shared.handleUrl(url)`.
- Info.plist: `NSAppTransportSecurity > NSAllowsLocalNetworking = true`; `NSLocalNetworkUsageDescription`; `NSCameraUsageDescription`; `NSBluetoothAlwaysUsageDescription`; `NSBluetoothPeripheralUsageDescription`; `UIBackgroundModes` `bluetooth-central`; `CFBundleURLTypes` scheme `handover`; `MWDAT` dict (`AppLinkURLScheme = handover://`, `MetaAppID = $(META_APP_ID)`, `ClientToken = $(CLIENT_TOKEN)`, `TeamID = $(DEVELOPMENT_TEAM)`; Developer Mode needs no real credentials, leave the build settings empty). If ws to a raw IP is still refused on device, add `NSAllowsArbitraryLoads` and record it.
- `apps/ios/ci.sh`: `set -euo pipefail`, cd to its folder, `xcodegen generate`, `xcodebuild -scheme HandOverCapture -sdk iphoneos -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build`. Executable bit set. Tell Developer 1 it exists.
- `apps/ios/README.md`: build, install with a free Apple ID, Developer Mode steps.

### 5.2 Glasses source (S-G, time-boxed until the 8 PM gate)
- SPM package `https://github.com/facebook/meta-wearables-dat-ios` exactVersion `1.0.1`, products `MWDATCore` and `MWDATCamera`. Swift 6.3 toolchain, Xcode 26.4+.
- Use exactly the APIs in `docs/RESEARCH_GLASSES_GEMINI.md`: `Wearables.configure()` once in `App.init`; `Wearables.shared.startRegistration()`; `.onOpenURL` to `handleUrl`; `registrationStateStream()`, `devicesStream()`; `checkPermissionStatus(.camera)` then `requestPermission(.camera)`; `createSession(deviceSelector: AutoDeviceSelector(wearables:))`; `statePublisher.listen`; `session.start()`; only after `.started`, `addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2))`; `camera.stream.videoFramePublisher.listen { $0.makeUIImage() }`; `camera.stream.start()`. Keep listener tokens alive. Stop with `camera.stop()` then `session.stop()`.
- Throttle to 1 fps, JPEG 0.6, same socket. Keep the app in the foreground (`.raw` frames stop in the background).
- Auto fallback to the phone camera if registration, permission, session or stream fails, if no frame arrives within 5 s of `.started`, or on `StreamError` `.thermalHot`, `.peakPowerLimit`, `.batteryLow`. Show "Using phone camera: glasses stream stopped." and resend hello with `source:"phone"`.
- At 8:00 PM, report the gate result. If it fails, leave the code behind the toggle and never claim glasses anywhere.

## 6. Android app spec (`apps/android/`)

### 6.1 Base (A1)
- Kotlin, Jetpack Compose with Material 3, minSdk 31, compileSdk 36, targetSdk 36, Java 17. Take AGP, Kotlin, Compose and CameraX versions from the official DAT CameraAccess sample's version catalog so the later glasses step needs no version changes. applicationId `dev.handover.capture`. Commit the Gradle wrapper (`gradlew`, `gradle/wrapper/*`).
- Same screens as iOS with Material 3 conventions: top app bar, filled button for Next, default Material colors (dynamic color is LATER). Status colors fixed green, amber, red.
- Phone camera: CameraX `ImageAnalysis` with `STRATEGY_KEEP_ONLY_LATEST`, `OUTPUT_IMAGE_FORMAT_RGBA_8888`, back camera about 1280x720, `toBitmap()`, rotate upright, JPEG quality 60, one frame per second.
- OkHttp WebSocket to `ws://<host>:<port>/ws/camera`; send JPEG as `ByteString`; drop a frame if the previous send is still queued (`queueSize() > 0`). Same hello as iOS with `platform:"android"`, `name` from `Build.MODEL`, `device_id` UUID in SharedPreferences. Same reconnect and close-4000 rules.
- Haptics: `HapticFeedbackConstants.CONFIRM` on camera advance, `REJECT` on mistake. `FLAG_KEEP_SCREEN_ON` while streaming. Recording dot and "Live: frames go to {hub name}".
- Manifest: `CAMERA`, `INTERNET`; VIEW intent filter for scheme `handover` (host `connect` for pairing). `res/xml/network_security_config.xml` with `<base-config cleartextTrafficPermitted="true"/>` referenced from the manifest.
- `apps/android/ci.sh`: `set -euo pipefail`, cd to its folder, `./gradlew --no-daemon assembleDebug`. Tell Developer 1 the APK path `apps/android/app/build/outputs/apk/debug/app-debug.apk`.
- Install on a phone only with the human's OK: `adb install -r <apk>`.

### 6.2 Glasses source (STRETCH, only after everything else)
- Maven Central `com.meta.wearable:mwdat-core:1.0.1` and `mwdat-camera:1.0.1`. Manifest additions and Developer Mode placeholders (`mwdat_application_id = "0"`, `mwdat_client_token = "0"`) per `docs/research/glasses.md`.
- APIs exactly as in glasses.md: `Wearables.initialize`, `startRegistration`, `registrationState`, `devices`, `RequestPermissionContract`, `createSession(AutoDeviceSelector())`, `session.state` then `addCamera(StreamConfiguration(videoQuality = VideoQuality.LOW, frameRate = 2))`, `cam.stream.videoStream.collect`. YUV buffer to NV21, `YuvImage.compressToJpeg(rect, 60, out)`; swap U and V if colors are wrong. Same fallback rules as iOS.

## 7. Web details and live tests

- Learn screen honest states and strings: design.md section 4 and 6. Badge texts "Watching", "Checking", "Looks right", "Press Next when you're done". Offline reasons: `no_key` "No Gemini key", `rate_limited` "Gemini rate limit", `errors` "Gemini not responding".
- Spectator `#/watch` may use `/ws/ui?frames=0` on slow phones once that exists.
- Live tests per the PLAN.md section 7 matrix. You own: iPhone app phone camera to the source hub (Sync 2) and to the frozen Mac app (after Sync 4); iPhone app glasses (Sync 3); iPhone Safari capture.html with mkcert; Android app to the hub (real phone or emulator); viewers Chrome, Safari, Firefox on Mac, iPhone Safari, Edge if installed (else "Chromium via Playwright", labeled). Record each result the moment you run it: date, time, commit, devices, command, outcome.

## 8. Machine safety

- Before every heavy step (Xcode build, Gradle, Playwright runs, full test runs): `while [ "$(sysctl -n vm.loadavg | awk '{print int($2)}')" -gt 24 ]; do sleep 30; done`
- At most one simulator or emulator at a time; shut it down after (`xcrun simctl shutdown all`, `adb emu kill`). Prefer build-only checks.
- Stop every background process you start (mock, vite, hub, replay) when its check is done.
- Delete only build output inside this repo (`web/dist`, `apps/ios/build`, `apps/android/**/build`) and say exactly what you removed. No cleanup scripts.
- No paid services, no trials. Never take over the Mac UI (no clicking, no window automation). Never touch files outside this repo, keychains, accounts or system settings.

## 9. Submission docs (W10)

- `docs/TESTED.md`: the PLAN.md section 7 matrix. Each cell is **live**, **CI**, **emulator** or **untested**, with date, commit and evidence. Mark a cell tested only if it was actually run. Developer 1 sends you rows for their cells by message.
- `docs/DEVPOST.md`: standard sections (inspiration, what it does, how we built it, challenges, accomplishments, what we learned, what's next). Measured numbers only, written as observed counts with their source. Replay labeled as replay. Future work labeled as future. Competitors: only Retrocausal and Dozuki (lead decision in PLAN.md). Never "first", "only", user counts or time savings. Glasses only if Sync 3 passed.
- `docs/pitch/`: one slide with the tested matrix, `docs/pitch/matrix.html` rendered to `docs/pitch/matrix.png` at 1920x1080 with Playwright (already installed). Only live and CI cells on it.
- Checks that must print nothing:
  - `perl -CSD -ne 'print "$ARGV $.: $_" if /[\x{2013}\x{2014}]/' docs/DEVPOST.md docs/TESTED.md docs/pitch/*.html`
  - `grep -niwE 'first|only' docs/DEVPOST.md` (reword any hit)

## 10. Design bar

- Apple-native, calm, no gradients, no glow, no decoration colors. `system-ui` fonts on web, SF on iOS, Roboto via Material 3 on Android.
- Shared tokens from design.md section 7: dark bg `#0B0B0C`, surface `#161618`, raised `#1F1F22`, line `#2C2C2E`, text `#F5F5F7`, secondary `#A1A1A6`, accent `#0A84FF`, green `#30D158`, amber `#FF9F0A`, red `#FF453A`. One accent. Radii 6, 10, 14, 20. 4 point spacing. Motion 200 ms ease-out, respect reduced motion.
- US English, plain words, no em or en dashes in any UI string, doc or commit message.
- Look at a screenshot of every screen you change, on every platform you change it on.

## 11. Git

- Work on `dev2/clients` (or `dev2/<topic>` for a side branch). Small commits: `Area: what changed` (for example `iOS: send hello and handle welcome`). No attribution lines, no co-author trailers, no tool footers.
- At each sync point: `git fetch origin && git rebase origin/main`, rerun BUILD and REAL (and IOS or ANDROID if you touched them), then `git checkout main && git merge --ff-only dev2/clients && git push origin main`. Merge only when tests pass. Never force push `main`; `--force-with-lease` on your own branch only.
- After every push, check CI (`gh run list --limit 3`, then `gh run view <id>`) and fix red jobs you own right away. Never open a pull request unless the human asks.

## 12. When blocked

Pick the safest honest option, write one entry in `docs/DECISIONS_DEV2.md` (date and time, problem, choice, why), and keep going with the next item. Never stop and wait unless the next step needs a human (device connect, install approval, sign-in).

## 13. Final report

When everything is done or time is up, report in this shape, short:
1. **Done**: each milestone ID with one line.
2. **How verified**: exact commands and results; which screenshots you looked at; which matrix cells are live, CI, emulator.
3. **Left**: what is not done or not verified, plainly.
4. **Humans only** (one checklist): connect and unlock the iPhone, trust the developer profile, sign Xcode in to team V8PCS2UL23, Meta AI app Developer Mode and glasses charged, Android phone with USB debugging (or decline), OK for the Android SDK and emulator install (or decline), hotspot with every demo device, relay the requests in docs/DECISIONS_DEV2.md to Developer 1, record the backup demo video, submit the Devpost by 11:30 AM.
