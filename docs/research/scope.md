# HandOver scope call (founder, Sat 2026-11-14 afternoon)

Final. Hacking ends 12:00 PM Sunday, judging 1:00 to 2:30 PM. Dev A owns the hub, the desktop apps, the Android app and CI. Dev B owns the web UI, the iPhone app and the glasses. Red-team attacks (S1 to S11) are from docs/research/red-team.md.

## 1. Thesis
- **Thesis:** One narrated take by an expert becomes a lesson that plays their own clip for each step and moves on only when the learner's camera shows the step is done.
- **Hook:** "Experts teach the same task fifty times. With HandOver they do it once." Then the judge skips the flip and the screen says so.
- **Differentiation (honest):** Others turn video into documents (Dozuki, VSight) or need a fixed station camera and labeled cycles (Retrocausal). HandOver closes the loop from one take: no labeling, no headset required, any phone with any laptop. We do not say "first" or "only", and we quote no time savings.

## 2. Features
Format: feature, hours for one dev with an AI agent, platforms, attack it answers.

### MUST
- **Core loop on real Gemini.** Run the check benchmark, measure latency and limits, fix any model id drift. 1 h, hub. S4, S11.
- **Two real lessons.** One take each of the fortune teller and the bike, recorded and cut by the pipeline, timestamps fixed by hand if needed. 2 h, both humans. S6, S11.
- **Clean reference frames.** Use the sharpest, stillest frame in the last 15% of each clip instead of the literal last frame. Step 1 becomes manual. 1.5 h, hub. S5.
- **Mistake catch and jump ahead.** After 5 s of settled "no", compare the live frame with steps k-1, k and k+1. If it still matches k-1, show "Looks like you skipped the flip" plus a short `reason`. If it matches k+1, advance with "You're ahead". Amber banner, spoken with speechSynthesis, phone haptic. 3 h hub, 1.5 h web. S5, S6, S7.
- **Motion gate.** Check only once the frame has settled and changed since the last check, plus a heartbeat every 6 s. 1.5 h, hub. S4.
- **Offline check and circuit breaker.** OpenCV paper mask, histogram, shape and edge score against every reference. After 3 errors or any 429, use local checks only for 30 s and show an "Offline check" badge. Local checks also run the mistake catch. 3 h, hub (Mac arm64 and Windows x64 wheels). S2, S4.
- **QR pairing.** `GET /api/info` returns LAN IPs. The learn screen shows "Use your phone as the camera" with a QR code and the address in text. Native apps get `ws://ip:8000`, browsers get `https://ip:8443/capture`. 0.5 h hub, 1 h web. S1, S2.
- **Honest live states.** Camera connected or lost, checks on, offline or off, latency in small text. Next always works. 1 h, web. S2, S4.
- **Lesson package.** `.handover` zip with a manifest; export and import endpoints with path checks; buttons in the library. 2 h hub, 0.5 h web. S1.
- **Spectator view.** The learn page in a phone browser shows a read-only mirror, using the existing `/ws/ui` broadcast. 1 h, web. S1.
- **iPhone app.** SwiftUI, scan QR, rear camera JPEG at 1 fps over WebSocket, status, step title, Next, haptics, screen kept awake. Plist keys for local network and ATS. 4 h, iOS. S1, S3.
- **Android app.** Kotlin, Material 3, scan QR, CameraX at 1 fps over OkHttp WebSocket, cleartext config, Next. 4 h, Android. S1.
- **Desktop apps.** PyInstaller hub with bundled ffmpeg and the built web app: Mac .app in a .dmg, Windows .exe. It starts the hub, opens the learn screen in the default browser, and adds a Windows firewall rule for Private networks. 4 h, Mac and Windows. S1, S11.
- **CI.** Web build; Mac and Windows build plus a smoke test (start the app, import a Mac-made package, replay a fold to `/ws/camera`, assert the step advances); Android assembleDebug; iOS compile without signing. Artifacts go on a GitHub release. 3 h Dev A, 1 h Dev B. S1.
- **Replay hotkey and backup video.** One key runs replay, labeled "Recording" on screen. 1 h, web. S2.
- **Privacy line.** Recording dot on the phone apps and capture page. "Frames are checked, then discarded" on screen and on a slide. 0.5 h, all. S10.

### SHOULD
- Ray-Ban Meta source in the iPhone app (DAT 1.0.1, Developer Mode). 3 h, iOS. S3.
- Done screen: your time vs the expert's per step, steps checked by camera, mistakes caught, all from real events. 2 h, web. S6.
- Check self-test at teach time: each question against its own frame (yes) and the previous frame (no), with a green or amber badge per step. 2 h, hub and web. S5.
- Keyboard and accessibility pack: Space, arrows, R, C, F; aria-live step announcements; reduced motion. 1.5 h, web.
- Safety warnings and tools list from the narration (bike). 2 h, hub and web. S6.
- "Why" and slow replay. 1 h, web. S6.

### STRETCH
- Glasses source in the Android app. 4 h, Android.
- Filmstrip of the learner's verified frames on the Done screen. 1.5 h, web.
- Translated caption tracks. 2 h, hub.
- Review editor with drag handles. 5 h, web.
- `/record` page for phone upload of takes. 1.5 h, web.
- Printable one-page guide. 2 h, web.

### CUT
- Tauri or Electron shells, mDNS discovery, paid code signing.
- Hand ghost, multiple learners, Live API, chat, voice cloning, accounts, cloud deploy, offline service worker.
- gemini-3.1-pro-preview (no free tier).
- Naming DeepSight (search-only source), any "first" claim, any time-savings number.
- Teaching live over venue Wi-Fi.

## 3. Platforms
- **iPhone:** native app as camera and remote, glasses source if the 9 PM gate passes. Capture page in Safari as backup. Verifiable on the Mac with the iPhone (free signing); CI compiles only.
- **Android:** native app as camera and remote. Chrome capture page through cloudflared as backup. The emulator with the Mac webcam proves the stream; a real Android phone is needed for real camera, permission and LAN behavior.
- **Mac:** .dmg hub app. Fully verifiable here, light and dark, keyboard.
- **Windows:** .exe hub app. CI only: build, import of a Mac-made package, replay advance. Firewall, SmartScreen and Edge playback need a real Windows laptop; without one we say "built and smoke-tested in CI, not tested by hand".
- **Web:** learn, teach, library and spectator in Chrome, Safari, Firefox and Edge. Voice "next" is Chrome or Edge only and off by default.
- **Proof of "every OS with every OS":** one shared contract (JPEG over WebSocket plus REST) and one portable package. Live: an iPhone app and an Android phone each pair by QR and drive the Mac hub, while phone browsers mirror the step. In CI: a package made on the Mac plays and advances on the Windows hub. A slide shows the matrix with each pair marked tested live, CI only or untested.

## 4. Must-not-fail demo path
1. Mac hub on our own phone hotspot, certs pre-trusted, every lesson already on disk.
2. Teach screen: the bike lesson made from one take, lesson.json beside the timeline.
3. The judge folds under the iPhone app on a stand. Clips advance on camera.
4. The judge skips the flip on purpose. The banner and voice catch it. They fix it, and the lesson continues to the finished fortune teller.
5. An Android phone scans the QR and takes over as the camera; phone browsers mirror the step. Then export the package and show the green Windows CI run.

**Fallbacks, in order:** glasses, then iPhone app, then capture page, then replay labeled "Recording". Gemini down: breaker to "Offline check", then Next. Hotspot down: second hotspot, then localhost replay. Everything down: backup video, said out loud.

## 5. Go/no-go gates
- **Sat 6:00 PM:** 20 real checks with median latency under 2 s, limits read; fortune-teller take cut. No-go: wider motion gate and 3 yes to advance.
- **Sat 8:00 PM:** iPhone app streams to the hub by QR on the device; Android emulator streams; Mac .app launches. No-go on Android: APK from CI only, and Android Chrome capture in the demo.
- **Sat 9:00 PM:** glasses round trip on iOS. No-go: glasses leave the demo and the pitch.
- **Sat 11:30 PM:** skipped-flip replay caught 18 of 20 times by Gemini, and local scores separate steps 4, 5 and 6. No-go: plant a mistake that fails reliably.
- **Sun 2:00 AM:** all CI jobs green, including the Windows smoke test. No-go: drop Windows from the live claim and keep "built in CI" only if the build passes.
- **Sun 8:00 AM:** feature freeze. Rehearse under venue lights and record the pass count.
- **Sun 10:00 AM:** Devpost draft with real screenshots; backup video recorded.
- **Sun 11:30 AM:** Devpost submitted, release tagged with artifacts.
- **Sun 12:00 to 1:00 PM:** setup, three full rehearsals.
