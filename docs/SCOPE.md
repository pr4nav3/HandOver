# HandOver scope decision (Founder, Sat 2026-11-14)

Red-team attack ids S1 to S11 refer to docs/research/red-team.md. Hours are AI-assisted planning sizes, not promises.

## 1. Thesis and hook
- Thesis: the expert does the task once on camera; HandOver turns that take into a lesson that plays their own clip for each step and moves on only when the learner's camera shows the step is done.
- Hook: "Last year 3Docs won here by making manuals interactive. We got rid of the manual. An expert does the job once, and the lesson watches the next person do it."
- Never say "first", "only", or a training-time savings figure. Say "one take" only if true. Name DeepSight and Retrocausal only with market.md sources.

## 2. Features

### MUST (about 37 h)
1. Core loop on real Gemini: confirm model ids, run `check.py --time` 20 calls on hotspot, pre-cut bike lesson. 2 h, server. S4, S11.
2. Motion gate before every Gemini call (call when still and changed since last check, heartbeat every 6 s); latency on screen. 1.5 h, server. S4, S7.
3. Local OpenCV offline check plus circuit breaker (Gemini off 30 s after 3 errors or any 429); badge "Offline check". 4 h, server. S4, S2.
4. `reason` field in check result (max 8 words), shown in badge only when confidence >= 0.7. 1.5 h, server + web. S6.
5. Step 5 flip catch: after 5 s settled "no", compare live vs refs k-1, k, k+1. "Still step 4: flip it over" shown and spoken; matching a later step jumps ahead with "You're ahead". 3 h, server + web. S5, S6, S7.
6. Reference frame quality: stillest hands-free frame from last 15% of each clip; step 1 manual "camera sees paper" handshake; questions by shape and seam count, not color. 2 h, server. S5.
7. Honest learn states: camera disconnected (last frame dimmed), checks off, "Replay" banner whenever replay feeds frames, recording dot. 1.5 h, web. S2, S4, S10.
8. QR pairing: GET /api/info returns LAN addresses; learn screen shows QR, address text, device name once connected. 2 h, server + web. S1, S2.
9. iPhone app (Swift, xcodegen): phone camera or Ray-Ban glasses source, auto fallback to phone; pairs by QR; joins /ws/ui for step title, Next button, haptic on verified; NSAllowsLocalNetworking + NSLocalNetworkUsageDescription. 6 h, iOS. S3, S1.
10. Android app (Kotlin, CameraX): phone camera, same QR, remote and haptic; cleartext config. 5 h, Android. S1.
11. Mac desktop app: PyInstaller .app with bundled ffmpeg; starts server, opens learn screen in browser, shows QR. 3 h, Mac. S11.
12. Windows desktop app: PyInstaller .exe built on GitHub Actions windows-latest; smoke test starts exe, polls /api/lessons, runs replay against /ws/camera, checks a step advances. 3 h, Windows CI. S1, S11.
13. Replay hotkey plus two recordings: clean full fold and deliberate skipped flip. 1 h, server + web. S2, S5.
14. Privacy line backed by code: learn frames are checked then discarded, never written to disk. 0.5 h. S10.

### SHOULD (only after every MUST passes its gate)
- End screen: your time vs expert per step, camera-checked steps, mistakes caught, strip of verified frames. 3 h, web. S6.
- Check self-test at teach time: each question vs own frame (yes) and previous frame (no); green/amber/red per step; suggest manual. 2 h, server. S5.
- .handover export/import; Mac lesson opens on Windows server; covered in CI smoke test. 2 h, server. S1.
- Spoken hints via browser TTS, keyboard keys, aria-live, caption size control. 2 h, web.
- Safety warnings and tools list from narration (bike). 2 h, server + web.

### STRETCH
- Android glasses source (needs real Android phone and glasses). 4 h.
- Translated caption tracks. 2 h.
- Timeline editor drag and rename. 5 h.
- Printable one-page guide. 2 h.
- .dmg and Inno Setup installers. 2 h.

### CUT
- Hand ghost, multiple learners, Gemini Live API, ask-the-expert chat, voice cloning (fake), mDNS (QR replaces it), Tauri/Electron, Mica, re-record single step, accounts, cloud deploy, gemini-3.1-pro-preview (costs money). Voice "next" off by default; enable only in a quiet booth (S8).

## 3. Platform scope
- iPhone: native capture and remote app; glasses if 8 PM gate passes; Safari /capture fallback. Verified by hand on the user's phone.
- Android: native phone-camera capture and remote. Verified by hand only on a real phone; otherwise "built in CI, run in emulator", labeled.
- Mac: .app runs server and learn screen, unsigned (right-click Open). Verified by hand.
- Windows: .exe built and smoke tested in CI. With a Windows laptop: Edge learn screen against the Mac server, and run the .exe once. Otherwise "Windows: CI built and smoke tested, not tested on hardware".
- Web: learn, teach, library in Chrome, Safari, Firefox (voice Chrome only). /capture for any phone.
- Every-OS proof: Mac server takes the iPhone app (or glasses) as camera; Android app and a judge's phone (via QR) show the same step at once; Next on one phone updates every screen; Windows joins as a learn screen if present. Show only actually connected pairs; list tested pairs on one slide.
- CI-only, labeled: Windows .exe (unless hardware), iOS unsigned compile, Android APK without phone, export/import round trip.

## 4. Must-not-fail demo
1. Mac server on own hotspot (backup hotspot ready). Bike lesson pre-cut. Teach timeline, click a clip.
2. Judge folds on black board under desk lamp, iPhone app on chest mount (glasses only if gates passed). Clips advance by camera.
3. Judge skips the flip on purpose: "Still step 4: flip it over".
4. Finish, end screen, every-OS beat.
- Fallback ladder: camera glasses, iPhone app, Safari /capture, replay with "Replay" banner. Gemini down: local check automatically, badge says so. Wi-Fi: hotspot, backup hotspot.
- Fully offline: Mac alone at localhost (camera allowed on localhost without HTTPS), USB or Continuity Camera pointing down, local check, Next always works. Last resort: pre-recorded demo video introduced as a recording.

## 5. Go/no-go gates
- Sat 6:00 PM: real Gemini check benchmarked (latency, project limits). Median > 2.5 s: check every 2 s and require 1 confident yes plus local agreement.
- Sat 8:00 PM: glasses stream via iPhone app, else glasses out of the demo and never claimed.
- Sat 10:00 PM: real Android phone streaming, else Android labeled emulator only. Mac .app launches cleanly.
- Sun 12:30 AM: full fold end to end on real Gemini with iPhone app, local check works with Wi-Fi off. Else stop SHOULD work; both devs fix the loop.
- Sun 1:30 AM: feature freeze.
- Sun 8:00 AM: venue-light rehearsal; planted flip catch 20 tries, need 18+. Else step 5 manual.
- Sun 9:30 AM: CI green on web, Mac, Windows, iOS, Android; slide and Devpost labels final.
- Sun 10:30 AM: code freeze, tag, GitHub release.
- Sun 11:30 AM: Devpost submitted. 12:00 to 1:00 PM setup and two run-throughs. Judging 1:00 to 2:30 PM.

## 6. Humans only
- [ ] Two Gemini projects and keys (rehearsal, demo); read limits on AI Studio rate-limit page.
- [ ] Meta AI app Developer Mode, glasses updated and charged, pairing.
- [ ] Trust mkcert root on iPhone; allow free Apple ID signing on the phone.
- [ ] Borrow a real Android phone (USB debugging on); a Windows laptop if possible.
- [ ] Record takes: bike (one take), fortune teller, clean replay, skipped-flip replay.
- [ ] Props: 10+ duo-color kami, pre-folded examples, paper cups, black foam board, desk lamp, chest mount, earbuds, chargers, power strip.
- [ ] Set up and test both hotspots with every device.
- [ ] Decide whether the GitHub repo goes public (free CI minutes on Windows and Mac).
- [ ] Confirm prize tracks on MadHacks Discord.
- [ ] 8 AM venue rehearsal; submit Devpost; pitch and ask a judge to fold.

## Unconfirmed
Model ids and free-tier limits; check latency; venue Wi-Fi client isolation; Android Chrome user-cert trust; windows-latest CI free for this repo; Android/Windows hardware availability.
