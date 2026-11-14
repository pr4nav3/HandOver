# HandOver architecture (2026-11-14)

Architecture lead. Read: docs/SPEC.md, docs/SCOPE.md, docs/research/scope.md, docs/ARCHITECTURE.md (parallel session; reconciled in section 16), CONTRACT.md, docs/RESEARCH_GLASSES_GEMINI.md, every file in docs/research/, server/*.py, server/static/capture.html, web/src/*. The precise wire contract is docs/CONTRACT_V2.md. This file explains the shape, the reasons, and who builds what.

Hacking ends 12:00 PM Sunday 2026-11-15. Two developers, each driving an AI coding agent.

## 1. Answer

The platforms research is right on the core. Keep it:
- One Python hub (FastAPI) is the only server. It runs on the laptop, Mac or Windows. It holds lessons, runs checks, and serves the web app.
- The web app is the only learn and teach UI, on every OS.
- Native Swift iOS and native Kotlin Android apps are thin camera clients. Sources: Meta glasses (DAT 1.0.1) or the phone camera.
- capture.html is the no-install camera.
- Every device talks to the hub over the same HTTP and WebSocket contract. That one contract is why any phone works with any laptop.

Ten changes, each with its reason:

| # | Change | Reason |
|---|---|---|
| 1 | The desktop app shows a small native control window (tkinter): hub name, URL, QR, Open, Quit. `--headless` skips the window. | A windowless PyInstaller .app cannot be quit from the Dock, because the Dock sends a Cocoa quit event that a plain Python process never handles. On Windows a stray console window confuses users. CI needs headless anyway. |
| 2 | The QR encodes `http://<ip>:8000/join`, not `https://<ip>:8443/capture`. | Desktop builds have no trusted certificate, so an https QR fails on every installed copy. The join page offers "Open in HandOver app" (`handover://connect?...`) and, when certs exist, "Use this browser" to the https capture page. One QR works for all three camera types. |
| 3 | mDNS is a stretch goal (both scope docs cut it). If built, the TXT record carries the hub's IPs and contract version, and apps probe `GET /api/info` on each IP. | QR plus a typed address cover every case. If mDNS is added, this keeps the logic the same on iOS and Android. |
| 4 | A frozen app keeps its data in a per-user folder, not next to the code. | `REPO = Path(__file__).parent.parent` resolves inside the read-only .app bundle or a temp folder once frozen. Lessons, uploads, the key and certs would be lost or unwritable. |
| 5 | Finish the Windows and frozen-app fixes before packaging (section 9.1). | The parallel session already fixed the signal handler, utf-8 writes and upload ids. Still open: ffmpeg lookup, data folder, stdout under `--windowed`, recut keeping fields. |
| 6 | PyInstaller `onedir`, not `onefile`. | Faster start (nothing to unpack each launch), fewer antivirus false positives on Windows (inferred), and Inno Setup installs a folder anyway. |
| 7 | Mac first launch: System Settings > Privacy & Security > Open Anyway, not right-click Open. | I believe macOS 15 removed the Control-click bypass for unsigned apps (inferred, test on this Mac with a quarantined dmg). |
| 8 | The Mac hub's Info.plist declares NSLocalNetworkUsageDescription and NSBonjourServices. | macOS 15+ asks for Local Network permission for apps that use the LAN, and mDNS advertising may trigger it (inferred). |
| 9 | CI calls build scripts owned by the client developer (`apps/ios/ci.sh`, `apps/android/ci.sh`). | Developer 1 owns the workflow file and Developer 2 owns the app projects. Neither edits the other's files. |
| 10 | The hub renders QR codes (`GET /api/qr`, Python `segno`, BSD license, no dependencies). | Neither the web app nor the native apps need a QR library. One small, pure-Python dependency. |

Skip Tauri and Electron this weekend, as the research said: Chrome Web Speech fails inside embedded webviews (inferred from bug reports), and Rust plus sidecar setup is time the deadline does not have.

## 2. Components and processes

| Component | Runs on | Process | Talks to |
|---|---|---|---|
| Hub (`server/`) | The Mac or Windows laptop. Linux works from source. | One OS process. Main thread: control window (or headless wait). Background thread: one asyncio loop running uvicorn http 8000 and, when certs exist, https 8443, plus the engine loops and mDNS. Teach jobs run in worker threads. ffmpeg runs as child processes. | Gemini API over HTTPS. Every client over the LAN. |
| Web app (`web/`, built to `web/dist`) | Any browser. Served by the hub at `/`. | Browser tab. | Hub `/api/*`, `/lessons/*`, `/ws/ui`. |
| capture.html (`server/static/`) | Any phone browser over https 8443 (needs a trusted cert). | Browser tab. | Hub `/ws/camera` (wss). |
| join.html (`server/static/`, new) | Any phone browser over http 8000. | Browser tab. | Links only: `handover://connect`, https capture. |
| iOS app (`apps/ios/`) | iPhone, iOS 17.2+. | Foreground app with the screen kept awake. | Hub `/ws/camera` (ws), `/api/info`. Glasses over Bluetooth and Wi-Fi through the Meta AI app. |
| Android app (`apps/android/`) | Android phone, minSdk 31 (DAT sample). | Foreground activity, FLAG_KEEP_SCREEN_ON. | Same as iOS. |
| Replay (`server/replay.py`) | Any machine with Python and ffmpeg. | CLI. | Hub `/ws/camera`, `/ws/ui`. |

Inside the hub, one global Engine (EXISTS) holds the session: lesson, step, done flag, latest frame, check state. All `/ws/ui` clients see the same state. One learner per hub. Do not claim multi-learner.

Check loop (EXISTS, changed in V2): one check in flight, always on the newest frame, results from a previous step are ignored (the `version` counter).

## 3. Network topology

```
                 Gemini API (internet, optional: local fallback when down)
                          |
   Glasses --BT/Wi-Fi--> iPhone or Android app --ws:8000/ws/camera--+
   Phone camera -------> iPhone or Android app --ws:8000/ws/camera--+
   Any phone browser --> capture.html ----------wss:8443/ws/camera--+--> HUB (Mac or Windows laptop)
   replay.py ---------------------------------- ws:8000/ws/camera--+     serves web at http://<ip>:8000/
                                                                         |
   Laptop browser (learn screen) <--------- http/ws:8000 /ws/ui --------+
   Projector, judge phone, 2nd laptop <---- http/ws:8000 /ws/ui --------+  (all in sync)
```

- The hub is the only stateful node. Cameras only send. Viewers send commands (next, back, goto, select) and receive state.
- Multiple viewers stay in sync. Each `/ws/ui` client gets every `state`, `advance` and `mistake` message (broadcast EXISTS). Clip playback position is local to each viewer and is not synced. Only the step is.
- Multiple cameras: the newest active camera wins (CONTRACT_V2 section 6.3). Today the hub checks the newest frame from any camera, mixing views. Other cameras stay connected and idle. The UI shows which device is streaming.
- Lesson moves between hubs: `.handover` export from hub A, import on hub B (section 6). This is how "made on a Mac, hosted on Windows" works.

Network to use at the venue, in order:
1. The laptop joins a phone's personal hotspot. An iPhone hotspot hands out 172.20.10.x. Every demo device joins the same hotspot.
2. Venue Wi-Fi, only after it is tested. University Wi-Fi often blocks devices from reaching each other (client isolation, inferred for UW).
3. Last resort for the browser camera: a `cloudflared tunnel --url http://localhost:8000` quick tunnel (free, no account, URL changes each start; WebSocket through it is inferred, test it).

## 4. Discovery and pairing

Three ways in. QR and typed address are P0 on every client; mDNS is a stretch goal (both scope docs cut it). No single one is a dependency.

| Method | How | When it fails |
|---|---|---|
| QR | Hub shows a QR of `http://<lan-ip>:8000/join?hub=<hub_id>` in the control window and in the web app's Connect screen (image from `GET /api/qr`). System camera: opens join.html, which offers "Open in HandOver app" (`handover://connect?host=<ip>&port=8000`) and "Use this browser" (`https://<ip>:8443/capture`, shown only when the hub has certs). In-app scanner: parse host and port out of any URL. | Wrong IP when the laptop has several networks. The Connect screen lists every LAN URL from `/api/info` and has a picker ("Wrong network?"). |
| mDNS (stretch, P2) | Hub registers `_handover._tcp.local.` on port 8000 with python-zeroconf (Windows wheels exist, verified by the research). TXT: `v=2`, `id=<hub_id>`, `name=<hub name>`, `ips=<comma list>`, `https=<port or 0>`. iOS: `NWBrowser(for: .bonjour(type: "_handover._tcp", domain: nil))`. Android: `NsdManager.discoverServices("_handover._tcp", PROTOCOL_DNS_SD)`, then resolve for TXT. The app probes `GET http://<ip>:8000/api/info` for each IP in `ips` (1.5 s timeout) and keeps the first that answers. | Hotspots and some Wi-Fi drop multicast (Android hotspots especially; iPhone hotspot behavior unverified). Windows firewall may block UDP 5353 inbound (inferred). Never rely on it alone. |
| Manual | The app's "Enter address" field takes `192.168.1.20` or `192.168.1.20:8000`. The hub shows its address in plain text under the QR. | Never, if the network allows device-to-device traffic. |

LAN IP choice on the hub: list IPv4 addresses with `ifaddr` (already a zeroconf dependency). Drop loopback, 169.254.x.x, and interface names that look like VPN or virtual (`utun`, `awdl`, `llw`, `bridge`, `vEthernet`, `docker`, `vmnet`, `Tailscale`). Sort: private ranges first (192.168, 172.16 to 31, 10). Report all of them.

No pairing code this weekend. Anyone on the same network can stream or press Next. That is acceptable for a demo on our own hotspot, and the pitch says so if asked. A pair code would add a failure point in the live swap.

Custom scheme: both apps already register `handover://` for the Meta AI callback. Route by URL host: `handover://connect?...` goes to pairing, and everything else goes to `Wearables.handleUrl` / the DAT handler.

## 5. Transport

- HTTP and WebSocket on 8000 for everything (EXISTS). Native apps and replay use plain `ws://`.
  - iOS: Info.plist `NSAllowsLocalNetworking = true`, `NSLocalNetworkUsageDescription`, `NSBonjourServices = [_handover._tcp]`. If ws to a raw IP is still refused on device, add `NSAllowsArbitraryLoads` for the hackathon build (inferred, test on device).
  - Android: `res/xml/network_security_config.xml` with `<base-config cleartextTrafficPermitted="true"/>`. A base config is needed because the hub IP is not known in advance (verified by the research).
- HTTPS on 8443 only for capture.html, because getUserMedia needs a secure context (verified by the research). It is served only when `certs/cert.pem` and `certs/key.pem` exist (EXISTS, `scripts/certs.sh` with mkcert). Both ports share one process and one session (EXISTS).
- Desktop installers do not generate certificates. The no-install browser camera on an installed hub means mkcert on that laptop, the cloudflared tunnel, or Android Chrome's "insecure origins treated as secure" flag. Native apps are the main path. That keeps the installer free of a certificate story we cannot test on Windows.
- Frames: JPEG, about 1 fps, long side up to 1280. The hub scales them to 640 for the check and 960 for viewers (EXISTS). Viewers get at most 4 frames per second, dropped when they fall behind (EXISTS).

## 6. Lesson package (`.handover`)

A lesson is a folder with relative paths, so it already moves between OSes. The package is that folder in a zip.

```
fortune-teller-v1.handover   (zip, videos stored uncompressed, text deflated)
  manifest.json      {"format":"handover-lesson","format_version":1,"app_version":"0.2.0",
                      "created_at":"2026-11-14T21:03:00Z","lesson_id":"fortune-teller-v1",
                      "title":"Fold a fortune teller","includes_video":true,"hub_os":"macos"}
  lesson.json
  extraction.json    (optional; holds the transcript that recut needs for captions)
  clips/NN.mp4
  captions/NN.vtt    (+ captions/NN.<lang>.vtt when translated)
  frames/NN.jpg
  audio/NN.<lang>.m4a (optional, pre-generated speech)
  norm.mp4           (optional, ?video=0 omits it; without it recut is unavailable)
```

- `GET /api/lessons/{id}/export[?video=0]` streams the zip. `POST /api/lessons/import` (multipart `file`) unpacks it.
- Import safety: forward-slash relative names only, no `..`, no absolute paths or drive letters, no symlinks, at most 2000 entries, size cap. Unpack into a temp folder inside the lessons root, check every path that lesson.json references, then rename into place. Never overwrite: an id clash gets `-2`, `-3` and so on, and lesson.json's `id` is rewritten to match.
- Clips are already H.264 and AAC (normalize EXISTS), so a Mac-made lesson plays in Edge and Chrome on Windows.
- Optional later: `POST /api/lessons/import` with JSON `{"url": "http://<other hub>:8000/api/lessons/<id>/export"}` so one hub pulls from another over the LAN. It is in the contract as optional (P2).

## 7. The layered check

Order per frame, all on the hub:

```
frame -> [1 motion gate] -> [2 Gemini flash-lite, 3 s timeout] -> debouncer (2 yes >= 0.8) -> advance
                                   | 3 errors or any 429
                                   v
                           [3 circuit breaker: open 30 s] -> [4 OpenCV local check] -> debouncer (3 in a row)
          after 5 s of settled "no": [5 multiple-choice mistake check] -> mistake message
```

1. Motion gate (new, `server/gate.py`). 160x90 gray, 5x5 blur, absdiff against the previous frame. Motion = fraction of pixels with diff > 25. Hold while motion > 2%. Check only when motion < 0.5% for 2 frames and the frame differs > 3% from the last checked frame. Heartbeat check every 6 s regardless. The research expects 3 to 5 times fewer calls (an estimate; measure it). `HANDOVER_GATE=0` turns it off.
2. Gemini `gemini-3.5-flash-lite`, two images plus the question, low media resolution, minimal thinking (EXISTS). Timeout default goes from 8 s to 3 s (`HANDOVER_CHECK_TIMEOUT`).
3. Circuit breaker (new). Opens after 3 consecutive errors or timeouts, or any 429. While open (30 s, `HANDOVER_BREAKER_SECONDS`), only the local check runs, and state shows `check_offline: true` with a reason. After 30 s, one Gemini try: success closes the breaker, failure reopens it. No key at startup means local only, with reason `no_key`.
4. OpenCV local check (new, `server/local_check.py`, `opencv-python-headless` plus numpy; wheels exist for macOS arm64 and Windows amd64, verified by the research). Paper mask from Otsu on HSV V, largest contour. Score against every step reference: 0.5 histogram correlation + 0.3 (1 - matchShapes) + 0.2 edge density similarity. A pass is when the current step scores best with a lead >= 0.1 and histogram correlation >= 0.75. 3 in a row to advance. It is tuned for bright paper on a dark mat only. On anything else it answers `unsure`, and Next always works. When Gemini is up, the local score is a veto only: Gemini yes x2 advances unless local strongly names another step (lead > 0.2).
5. Mistake check (new, `server/mistake.py`). On a camera step k, after 5 s of settled consecutive "no", one Gemini call with references k-1, k and k+1 (labeled A, B, C; ends dropped) plus the live frame. Answer `{"match":"A|B|C|none","confidence":0..1}`. While the breaker is open, the local scores against the same three references stand in (research scope: local checks also run the mistake catch). At most one mistake call per 10 s per step. `mistake_question`, when set, is added to the prompt as a hint.
   - Match A with confidence >= 0.7: the learner is behind. The hub sends the step's `common_mistake` text, or "This still looks like step {k}." when that text is empty. The step does not move.
   - Match C: the learner is ahead. Both scope docs want a jump ahead, so the hub confirms with one normal check of step k+1 and, on a confident yes, sends `mistake` kind `ahead` ("You're ahead.") and advances two steps. No confirmation, no jump.
   - The check result also gains a short `reason` (up to 8 words, SCOPE MUST 4). The UI shows it only at confidence >= 0.7.
6. Mock (EXISTS): `HANDOVER_CHECK=mock` passes after N seconds, with no network and no gate.

`HANDOVER_CHECK` accepts `gemini` (default, falls back to local), `local` (never calls Gemini) and `mock`.

Teach-time reference frames (new, `teach.py`): when a step has `ref_time`, grab that frame of norm.mp4 instead of the clip's last frame. Recut must keep every step field it does not rewrite (today `cut()` rebuilds steps from scratch and drops unknown fields: fix this before adding fields).

## 8. Translations and speech (P2, only if P0 and P1 are done)

- Built ahead of time, never live. `POST /api/lessons/{id}/translate {"languages":["es","hi"],"speech":false}` starts a job (same job API as upload).
- One flash-lite call per language translates step titles and caption cues. Output: `captions/NN.<lang>.vtt` and `steps[i].i18n.<lang>.title` in lesson.json.
- Speech (if `speech:true`): `gemini-3.8-flash-lite-tts` through `client.interactions.create` (in SDK 3.3, never run, verify first). WAV converted to `audio/NN.<lang>.m4a` with ffmpeg. Browser `speechSynthesis` is the backup.
- The language choice is client-side only (caption track plus audio element). No WebSocket change.
- Never a fake expert voice. The expert's own clip audio stays the instruction.

## 9. Desktop packaging

### 9.1 Code fixes the packaging depends on (Developer 1, before the first build)
Already done by the parallel session (seen in server/ at revision 2): `add_signal_handler` falls back to `signal.signal` on Windows; teach.py reads and writes utf-8; an upload `id` is cleaned with `sanitize_id` before checking, so the returned id matches the folder; recut builds in `.recut_tmp/` and swaps; check timeout default is 3 s; uploads are capped at 2 GB.

Still open:
- The launcher runs the hub off the main thread (Tk owns it on Mac). Signal handlers cannot be installed there. Expose `start_hub()` and `stop_hub()` that skip signal setup when not on the main thread.
- With `--windowed` or `console=False`, `sys.stdout` and `sys.stderr` are None, and logging setup can crash (inferred, from docs/ARCHITECTURE.md). The launcher sends both to `<data>/logs/hub.log` before importing `server.main`.
- `server.main` reads `HANDOVER_LESSONS` at import time, so the launcher sets the data env vars before importing it.
- One path module `server/paths.py`:
  - Data dir: `HANDOVER_DATA`, else frozen: macOS `~/Library/Application Support/HandOver`, Windows `%LOCALAPPDATA%\HandOver`. From source: the repo root (today's behavior). Holds `lessons/`, `uploads/`, `certs/`, `.env`, `hub.json` (hub_id, name).
  - `HANDOVER_LESSONS` still overrides the lessons folder (EXISTS).
  - ffmpeg lookup order: `HANDOVER_FFMPEG`, then `sys._MEIPASS/ffmpeg[.exe]`, then `PATH`, then `/opt/homebrew/bin/ffmpeg`. ffprobe: `HANDOVER_FFPROBE`, then the same folder as the ffmpeg found, then the same order. teach.py's `_bin()` (PATH, then Homebrew) grows the first two steps, and replay.py, which still calls bare `"ffmpeg"`, uses it too.
  - Web dist: `HANDOVER_WEB_DIST`, then `sys._MEIPASS/web/dist`, then `<repo>/web/dist`.
- Recut keeps unknown fields: `cut()` still builds each step dict from scratch, so `ref_time`, `common_mistake` and the rest would be lost. Merge the old step's fields (matched by position) under the rewritten ones.
- Seed lessons: on first frozen run with an empty lessons folder, copy bundled sample lessons in.

### 9.2 Launcher (`server/launcher.py`)
- Starts the hub thread, waits for `/api/info`, opens `http://localhost:8000/` in the default browser (`HANDOVER_OPEN_BROWSER=0` to skip). Recommend Chrome in the UI copy for voice.
- tkinter window: hub name, LAN URL, QR (PhotoImage from segno PNG), buttons Open, Copy address, Quit. On Mac, Tk must own the main thread, so the hub runs in the background thread.
- `--headless`: no window, runs until SIGTERM or `POST /api/shutdown` (localhost only). If tkinter fails to import, fall back to headless plus the web app's Quit item.
- tkinter ships in python-build-standalone builds (what uv installs) and PyInstaller supports it (inferred, the first CI build proves it).

### 9.3 PyInstaller (`packaging/handover.spec`)
- `onedir`. Mac: `BUNDLE` to `HandOver.app`, `windowed`. Windows: `console=False`, `HandOver.exe`.
- datas: `web/dist` to `web/dist`, `server/static` to `server/static`, seed lessons, ffmpeg and ffprobe binaries plus their license text.
- `collect_submodules("uvicorn")`, `collect_submodules("zeroconf")`, `collect_all("google.genai")` (lazy imports inside functions are usually found, but the smoke test is the proof).
- Mac Info.plist additions: `NSLocalNetworkUsageDescription`, `NSBonjourServices = ["_handover._tcp"]`, `CFBundleShortVersionString`.
- Keep faster-whisper out of the bundle (size). Transcripts come from Gemini.

### 9.4 ffmpeg
- Windows: gyan.dev "essentials" static build (GPLv3, verified by the research), fetched in CI by `packaging/ffmpeg/fetch.ps1`, checked against a pinned SHA256.
- Mac: static arm64 build (evermeet.cx or osxexperts), fetched by `packaging/ffmpeg/fetch.sh`, pinned SHA256. Homebrew ffmpeg is not relocatable.
- Shipped as separate executables called through subprocess. License file and source link in the bundle.

### 9.5 Installers and first run
- Mac: `packaging/mac/make-dmg.sh`: ad hoc `codesign --force --deep -s -` (including the bundled ffmpeg), then `hdiutil create -format UDZO`. arm64 only; say so on the download.
  - First launch from a downloaded dmg: System Settings > Privacy & Security > Open Anyway (section 1, row 7). Or `xattr -dr com.apple.quarantine /Applications/HandOver.app`.
  - macOS application firewall is off by default. If it is on, it asks once per build because ad hoc signatures change (inferred).
- Windows: `packaging/windows/handover.iss` (Inno Setup): install to Program Files (admin), Start menu shortcut, `[Run]` adds a firewall rule by program, removed on uninstall:
  `netsh advfirewall firewall add rule name="HandOver" dir=in action=allow program="{app}\HandOver.exe" enable=yes profile=private,public`
  - Public is included because Windows often classes hotspots as Public (inferred). The rule allows only this program.
  - Without the installer (zip), Windows Defender Firewall prompts on first listen. The user must tick both Private and Public.
  - SmartScreen: "More info" then "Run anyway" (unsigned). Paid signing is out of scope.

## 10. Native apps

Same four screens on both, per design.md:

| Screen | Contents |
|---|---|
| Connect | List of hubs found by mDNS (name, IP). Buttons: Scan QR, Enter address. Last hub remembered and auto-reconnected. |
| Camera | Live preview. Status dot ("Connected to {hub name}", "Lost connection. Trying again…"). Source toggle Glasses / This phone. Current step title and "Step n of N" from the hub. Next and Back buttons. Haptic on verified (success) and on mistake (warning). Screen kept awake. |
| Source | Glasses registration (Meta AI app round trip), camera permission, Developer Mode reminder. |
| Settings | Frame interval (0.5, 1, 2 s), device name sent in hello, about. |

- Connection: `ws://<hub>:8000/ws/camera`. First message is `hello` (CONTRACT_V2 section 6.1). Send one JPEG per interval and drop a frame if the previous send is still pending. Reconnect with backoff 0.5, 1, 2, 4 s, capped at 5 s. On reconnect, send hello again with the same `device_id` so the hub replaces the stale socket.
- The camera socket also carries `state`, `advance` and `mistake` text messages after hello (NEW), so the phone shows the step and plays haptics without a second socket. Next and Back from the phone go over the same socket.
- Discovery: QR and typed address (P0). NWBrowser (iOS) and NsdManager (Android) with the `/api/info` probe only if mDNS is built (stretch, section 4).
- QR: P0 is the system camera through join.html and `handover://connect` (no scanner code in the app). P1 is an in-app scanner: AVCaptureMetadataOutput `.qr` on iOS (no dependency), ML Kit `barcode-scanning` bundled on Android.
- Sources and auto fallback (glasses.md): start on Glasses if registered, else This phone. Switch to This phone automatically if registration, permission, session or stream fails, if no frame arrives within 5 s of STARTED, or on a critical stream error (thermal, battery). Show "Using phone camera: glasses stream stopped." Send a new hello with `source: "phone"` on every switch.
  - iOS glasses: `StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2)`, `makeUIImage()`, JPEG 0.6. Phone: AVCaptureSession back camera 1280x720.
  - Android glasses: VideoFrame YUV to NV21, `YuvImage.compressToJpeg(rect, 60, out)`. Swap U and V if colors are wrong (layout undocumented). Phone: CameraX ImageAnalysis KEEP_ONLY_LATEST, RGBA_8888, back camera.
- Glasses audio stays off. Audio plays on the laptop (HFP sounds like a phone call, per glasses.md).
- Hard go/no-go for glasses streaming at 8 PM Saturday (spec). After that, phone camera only.

## 11. CI (`.github/workflows/build.yml`, Developer 1)

| Job | Runner | Steps | Pass means |
|---|---|---|---|
| web | ubuntu-latest | Node 22, `npm ci`, `npm run build` in web/, upload `web-dist` | TypeScript compiles, Vite builds |
| hub-test | ubuntu-latest | Python 3.12, `pip install -r server/requirements.lock`, apt ffmpeg, `python -m server.test_check`, contract smoke (`scripts/smoke.py`): mock hub, build demo lesson, `/api/info`, export then import round trip, replay to `/ws/camera`, expect an `advance` with reason `camera` | Contract behaves end to end |
| hub-mac | macos-latest (arm64) | download `web-dist`, `fetch.sh`, pyinstaller, ad hoc sign, dmg, run `HandOver.app/Contents/MacOS/HandOver --headless` with `HANDOVER_CHECK=mock`, same smoke | The frozen app starts and serves the contract |
| hub-win | windows-latest | download `web-dist`, `fetch.ps1`, pyinstaller, `choco install innosetup -y` (not guaranteed on the image, issue #11644), `iscc`, run `HandOver.exe --headless`, same smoke in PowerShell | The frozen exe starts on Windows, finds ffmpeg, cuts a lesson, advances |
| android | ubuntu-latest | setup-java 17 (temurin), `apps/android/ci.sh` (`./gradlew assembleDebug`), upload apk | App compiles with DAT 1.0.1 from Maven Central |
| ios | macos-latest | `brew install xcodegen`, `apps/ios/ci.sh` (`xcodegen generate && xcodebuild -scheme HandOverCapture -sdk iphoneos -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build`) | App compiles with DAT 1.0.1 (needs Xcode 26.4+ on the image; pin with `xcode-select` if the default is older, inferred) |
| release | on tag `v*` | attach dmg, Windows installer, apk to a GitHub release | Artifacts downloadable |

- Free on a public repo. On a private repo, minutes are limited and macOS minutes count at a multiplier, so keep it public or keep Mac jobs to pushes on main (inferred from GitHub's billing page, check before relying on it). No paid runners.
- Smoke runs with `HANDOVER_CHECK=mock` so CI never calls Gemini.

## 12. What can be verified where

| Item | This Mac | CI | Real device only |
|---|---|---|---|
| Hub from source, all endpoints, export and import, mock and local checks | yes | yes (ubuntu) | |
| Gemini check latency and accuracy | yes (with key, own project) | no (mock only) | venue network |
| Web app in Chrome, Safari, Firefox; screenshots | yes | build only | |
| Mac .app and dmg, Gatekeeper and firewall prompts | yes | build plus headless smoke | |
| Windows exe and installer | no | build plus headless smoke | Windows laptop: firewall prompt, SmartScreen, Edge playback, Web Speech |
| iOS app compiles | yes (Xcode) | yes, unsigned | |
| iOS app streams the phone camera | no (the Simulator has no camera) | no | iPhone with free signing |
| Glasses to iOS app | no | no | iPhone + glasses + Meta AI app in Developer Mode |
| Android app compiles | yes if the Android SDK is installed (unknown) | yes | |
| Android phone camera to hub | emulator with the Mac webcam (inferred) | no | Android phone |
| Glasses to Android app | no | no | Android phone + glasses |
| mDNS across devices, hotspot multicast | partly (Mac to iPhone) | no | every device pair on the venue network |
| capture.html over https | yes (mkcert, iPhone) | no | Android Chrome cert trust |

The pitch names only the device pairs actually shown. Windows ships as "CI green and smoke tested, not tried by hand" unless someone brings a Windows laptop.

## 13. Repo layout and owners

Developer 1 = hub (server, AI checks, teach, packaging, desktop installers, CI). Developer 2 = clients (web UI, iOS app, Android app, capture.html, join.html). No file has two owners.

| Path | Owner | Notes |
|---|---|---|
| `server/main.py`, `check.py`, `teach.py`, `replay.py`, `test_check.py`, `__init__.py` | Dev 1 | EXISTS |
| `server/paths.py`, `discovery.py`, `package.py`, `gate.py`, `local_check.py`, `mistake.py`, `translate.py`, `launcher.py` | Dev 1 | NEW |
| `server/tests/` | Dev 1 | NEW, pytest-free plain asserts like test_check |
| `server/requirements.txt`, `server/requirements.lock` | Dev 1 | adds zeroconf, segno, opencv-python-headless, numpy, pyinstaller (build only) |
| `server/static/capture.html`, `server/static/join.html` | Dev 2 | lives under server/ but Dev 1 never edits it; Dev 1 only serves it |
| `scripts/*.sh`, `scripts/smoke.py` | Dev 1 | |
| `packaging/**` | Dev 1 | spec, mac dmg script, Inno Setup, ffmpeg fetchers, licenses |
| `.github/workflows/**` | Dev 1 | calls `apps/*/ci.sh` and web npm scripts; never edits them |
| `lessons/` (sample lessons) | Dev 1 | |
| `CONTRACT.md` | Dev 1 | add one line at top: "Superseded by docs/CONTRACT_V2.md" |
| `docs/CONTRACT_V2.md` | Dev 1 | shared, see change process |
| `README.md`, `.gitignore` | Dev 1 | shared, see change process |
| `web/**` (src, mock, e2e, package.json, vite config, index.html, tsconfig) | Dev 2 | `web/mock/mock-server.mjs` must mirror CONTRACT_V2 |
| `apps/ios/**` (project.yml, Sources, Info.plist, README.md, ci.sh) | Dev 2 | NEW |
| `apps/android/**` (Gradle wrapper, app module, network_security_config.xml, README.md, ci.sh) | Dev 2 | NEW |
| `assets/icon/` (one SVG plus exported PNGs) | Dev 2 | Dev 1 reads it for the .app, .exe and installer icons |
| `docs/SPEC.md`, `docs/research/**` | lead | read-only for both devs |

Change process for shared files (`docs/CONTRACT_V2.md`, `README.md`, `.gitignore`):
1. Dev 2 asks Dev 1 in one message with the exact text to change (field name, type, which side sends it).
2. Dev 1 edits the file, bumps the `Revision` line at the top of CONTRACT_V2, commits, and tells Dev 2 the commit.
3. Additive and optional changes: Dev 1 decides alone. A rename, removal or type change needs both humans to agree, and lands with the hub and client changes in the same hour.
4. Contract freeze at 6:00 AM Sunday. After that, bug fixes only.

Branches: each developer works in their own git worktree and branch (`hub/*`, `client/*`). Merge to main after `npm run build` and `python -m server.test_check` pass.

## 14. Order of work

P0 means the demo needs it. P1 makes the demo safer. P2 only if everything above is done.

| Pri | Dev 1 (hub) | Dev 2 (clients) |
|---|---|---|
| P0 | open 9.1 fixes; serve web dist at `/`; `/api/info`; `/api/qr`; hello and active camera; state camera fields; `/join` route; export and import; launcher; PyInstaller Mac and Windows; CI web, hub-test, hub-mac, hub-win, android, ios | Web serves from the hub (no Vite proxy needed in prod); Connect screen with QR and LAN URL picker; camera name in the top bar; "Replay" banner when `state.camera.source == "file"`; export and import buttons; capture.html hello; join.html; Android app phone camera plus manual IP; iOS app phone camera plus manual IP, glasses if the gate passes |
| P1 (SCOPE MUST for the check) | motion gate; circuit breaker; local OpenCV check; `check_source` and offline badge state; `reason`; mistake check and jump ahead; clean reference frames (`ref_time`); recut keeps fields; settings key endpoint | Offline badge; `reason` in the badge; mistake banner, spoken, phone haptic; in-app QR scanner; settings key screen |
| P2 | mDNS; translate and speech jobs; import from URL; Inno Setup and dmg polish | mDNS browse in both apps; language picker; speech playback |

## 15. Unverified (carry into testing)
- tkinter inside the frozen app on macOS 26 and Windows.
- PyInstaller collecting google-genai, zeroconf and uvicorn without extra hooks.
- macOS Local Network prompt for the hub app; Gatekeeper "Open Anyway" flow on this Mac.
- ws to a raw IP from iOS with only NSAllowsLocalNetworking.
- mDNS over an iPhone hotspot and an Android hotspot.
- Windows firewall rule by program on a Public network; SmartScreen; Edge Web Speech.
- Inno Setup availability on windows-latest.
- Xcode version on the macos-latest image versus DAT's Xcode 26.4+ need.
- All check numbers: latency, gate call reduction, local check thresholds, mistake check accuracy.
- TTS through `client.interactions.create`.

## 16. Reconciliation with the parallel session's docs

docs/SCOPE.md and docs/research/scope.md (founder scope calls) and docs/ARCHITECTURE.md describe the same system. Where they differ, this file and CONTRACT_V2 decide as follows.

| Topic | Other docs | Decision here | Reason |
|---|---|---|---|
| Contract file | ARCHITECTURE.md points to `docs/CONTRACT_V2.md` with its own field names | CONTRACT_V2.md as written now is the one contract. ARCHITECTURE.md's names that differ (`/api/hub`, `/api/pair/qr.png`, `state.cameras[]` array, `checks_available`, `check_mode`, `alert`, `HANDOVER_ZEROCONF`) are replaced by `/api/info`, `/api/qr`, `state.camera` + `state.cameras` (count), `check_offline` + `check_source`, `mistake`, `HANDOVER_MDNS` | One name per thing. `/api/info` is what both scope docs name. The lead asked for a `mistake` message |
| mDNS | Both scope docs: CUT. ARCHITECTURE.md: built | Stretch (P2), contract kept so it can be added without changes | Founder decision. QR plus a typed address are enough |
| QR content | ARCHITECTURE.md: `https://<ip>:8443/capture?pair=<code>&http=8000`, http fallback when no certs | `http://<ip>:8000/join?hub=<id>`. Native apps still accept the ARCHITECTURE.md form (host from the URL, port from `http` when present) | Installed hubs have no trusted cert, so an https QR fails there. The join page works either way |
| Pairing code | ARCHITECTURE.md: 4 digits, sent but not enforced | None | Unenforced, it protects nothing and adds a field to type |
| Self-signed cert in the frozen app | ARCHITECTURE.md: generate with `cryptography` (flagged risky) | Do not generate. https only with mkcert certs | New dependency, and iOS may still refuse wss on an untrusted cert (inferred). Native apps are the phone path |
| Web dist location | ARCHITECTURE.md: copy to `server/static/app/` | Look up `HANDOVER_WEB_DIST`, then the bundle, then `web/dist` | No build output inside a folder owned by the client developer |
| Multiple cameras | ARCHITECTURE.md: newest frame from any camera is checked (EXISTS) | Newest active camera wins; others idle | With two cameras, mixed frames make the check flip between views |
| Mistake catch | SCOPE: matching a later step jumps ahead | Adopted, with a confirming check of step k+1 first | Jump ahead is in both scope docs. The confirmation stops one bad match from skipping two steps |
| `reason` field | SCOPE MUST 4 | Added as `last_check.reason` | Founder MUST |
| Mac first open | SCOPE: right-click Open | System Settings > Privacy & Security > Open Anyway (ARCHITECTURE.md agrees) | macOS 15 removed the Control-click bypass (inferred, test) |
| Owners | research/scope.md: Dev A owns hub, desktop, Android, CI; Dev B owns web, iPhone, glasses | Lead's split: Dev 1 hub, packaging, CI; Dev 2 web, iOS, Android, capture | The lead's instruction for this document. If the humans prefer the scope.md split, move `apps/android/**` and its `ci.sh` to Dev 1 in the table in section 13. Nothing else changes |
| Feature tiers | SCOPE MUST includes motion gate, breaker, local check, mistake catch | Those are P1 here only because P0 is the cross-platform plumbing they sit on. Both are needed for the demo | Same content, ordered by dependency |
| Gates | SCOPE: glasses at 8 PM; research scope: 9 PM | Use docs/SCOPE.md times; the humans pick one | Not an architecture decision |

