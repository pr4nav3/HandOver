# Developer 2 autonomous work prompt (HandOver clients)

Humans, before pasting: `main` is pushed from the lead Mac to `https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer` (see DEV1_PROMPT.md). On Developer 2's Mac, `git clone https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer.git` and open the session in that clone.

Paste everything below the line into a Claude Code session opened in that clone on Developer 2's Mac. It is written to the agent.

---

You are Developer 2 on HandOver. Work on your own for many hours until every item below is done and verified, or honestly marked as not done. Developer 1 (hub, AI checks, packaging, CI) works in parallel on another Mac. The lead owns the plan.

## 1. Mission (read this first)

- HandOver: an expert does a task once on camera while narrating. The hub cuts that take into steps and plays the expert's own clip for each step. It moves on only when the learner's camera shows the step is done.
- The hub is one Python FastAPI server on a laptop (Mac or Windows). It holds lessons, runs checks and serves the web app at `http://<ip>:8000/`.
- You own every client: the web app (learn, teach, connect, spectator), `capture.html`, a new `join.html`, the iPhone app, the Android app, the icon, and the submission docs.
- All clients talk to the hub over one wire contract, `docs/CONTRACT_V2.md`. That contract is the reason any phone works with any laptop. Never invent fields.
- Demo: a judge folds an origami fortune teller under a phone camera; clips advance as each fold is seen; leaving the paper unflipped at step 5 makes the screen say "Flip it over first." Then an Android phone takes over as camera and a judge's phone mirrors the screen.
- Fixed times (Sunday 2026-11-15 unless noted): glasses go/no-go 8:00 PM Saturday, contract freeze 6:00 AM, feature freeze 8:00 AM, code freeze 10:30 AM, submit 11:30 AM, hacking ends 12:00 PM, judging 1:00 PM.
- **Late start rule:** if you start after a sync's clock time, run that sync as soon as both sides' milestones for it are merged, in order. Never skip a sync.
- Quality bar: Apple-native, calm, honest. Nothing on screen may claim something the code does not do.

Read before writing code, in this order:
1. `docs/PLAN.md` (milestones, sync points, gates, matrix; **PLAN.md wins on times and drop order**)
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
- `apps/ios/**` (including `apps/ios/ci.sh` and `apps/ios/.gitignore`)
- `apps/android/**` (including `apps/android/ci.sh` and `apps/android/.gitignore`)
- `assets/icon/**`
- `docs/TESTED.md`, `docs/DEVPOST.md`, `docs/pitch/**`
- `docs/DECISIONS_DEV2.md`: yours alone

Never edit: `server/*.py`, `server/tests/**`, `server/requirements.*`, `scripts/**`, `packaging/**`, `.github/workflows/**`, `lessons/**`, `CONTRACT.md`, `docs/CONTRACT_V2.md`, `README.md`, `.gitignore`, `docs/PLAN.md`, `docs/IDEAS.md`, `docs/SPEC.md`, `docs/research/**`, `docs/DEV1_PROMPT.md`, `docs/DECISIONS_DEV1.md`, `docs/REVIEW_FIXES.md`, this file. To change any of these, write the exact text you need under `## Requests for Developer 1` in `docs/DECISIONS_DEV2.md` and list it in your next status update so the human relays it. Keep working on something else meanwhile.

App gitignores (first commit that creates each app): `apps/android/.gitignore` with `.gradle/`, `build/`, `local.properties`, `*.apk`; `apps/ios/.gitignore` with `build/`, `*.xcodeproj/` (xcodegen makes it), `DerivedData/`.

## 3. Contract you consume and send

Status is from CONTRACT_V2: **EXISTS** = in the hub today, rely on it. **NEW** = not built yet; assume nothing until Developer 1 says it is merged on `main`.

### 3.1 Web app (viewer, teach)
| Item | Exact fields | Status |
|---|---|---|
| `GET /api/lessons` | `[{id, title, steps}]` | EXISTS |
| `GET /api/lessons/{id}` | lesson.json: `id, title, video, steps[]`; step `n, title, start, end, clip, captions, ref_frame, check_type ("camera"/"manual"), check_question, prerequisites` | EXISTS |
| Step extras | `ref_time`, `common_mistake`, `mistake_question` (P1); `self_test {own, prev, ok}` or null (P2, S-T); `i18n` (P2) | NEW |
| Top-level extras | `safety: string[]`, `tools: string[]` (P2, S-S) | NEW |
| `POST /api/lesson`, `GET /api/jobs/{job}` | multipart `file`, `title`, `id`; job `status` one of `queued, normalizing, extracting, cutting, done, error`, `message`, `id` | EXISTS |
| `POST /api/lessons/{id}/recut` | optional full lesson body; returns new lesson.json | EXISTS |
| `GET /lessons/{id}/<path>` | clips, captions, frames; append `?v=<rev>` | EXISTS |
| `GET /api/info` | `contract`, `version`, `hub_id`, `name`, `os`, `ports.http`, `ports.https` (null without certs), `urls.local`, `urls.lan[]`, `urls.join[]`, `urls.capture[]`, `check.mode`, `check.model`, `check.has_key`, `check.offline`, `check.offline_reason` | NEW P0 |
| `GET /api/qr?text=<url>` | `image/svg+xml` | NEW P0 |
| `GET /join?hub=<id>` | serves your `server/static/join.html`; 404 `join page not installed` when the file is missing | NEW P0 |
| `GET /api/lessons/{id}/export[?video=0]`, `POST /api/lessons/import` | zip download; import returns `{id, title, steps, renamed}` | NEW P1 (S-P, SHOULD) |
| `DELETE /api/lessons/{id}` | `{deleted}` | NEW P1 |
| `PUT /api/settings` | body `{gemini_key}`, localhost only, returns `{has_key, mode}` | NEW P1 |
| `/ws/ui` send | `{"type":"select_lesson","id"}`, `{"type":"next","reason":"button"/"voice","from":int}`, `{"type":"back","from":int}`, `{"type":"goto","step":int}` | EXISTS |
| `/ws/ui` send | `{"type":"dismiss_mistake"}` | NEW P1 |
| `/ws/ui?frames=0` | no binary frames to this client | NEW P1 |
| `/ws/ui` receive `state` | `lesson_id, rev, step, total, status ("watching","checking","verified","manual","done"), last_check {done, confidence, latency_ms}, camera_connected` | EXISTS |
| `rev` | increasing int, opaque: compare for change, never parse. It covers the active lesson only, so after recutting a lesson that is not active, Teach bumps a local counter for its cache-busting `?v=` | EXISTS |
| `state` additions | `camera {camera_id, name, platform, source}`, `cameras` (P0); `last_check.source`, `last_check.reason`, `check_source`, `check_offline`, `check_offline_reason ("no_key","rate_limited","errors")`, `mistake` (P1) | NEW |
| `advance` | `{from, to, reason ("camera","button","voice","timer")}`; chime only on `camera` | EXISTS |
| `mistake` | `{step, kind ("behind","ahead"), looks_like, message, confidence, source ("gemini","local","mock")}`; `mock` comes only from Dev 1's `HANDOVER_MOCK_MISTAKE` test hook | NEW P1 |
| `error` | `{message}`; exact strings, e.g. `no lesson selected` | EXISTS |
| binary | newest live JPEG, at most 4 per second | EXISTS |

### 3.2 Cameras (iOS app, Android app, capture.html) on `/ws/camera`
| Item | Exact fields | Status |
|---|---|---|
| binary JPEG | starts `FF D8`, about 1 fps, long side 640 to 1280 | EXISTS |
| `hello` (first message, resend on every source switch and reconnect) | `{"type":"hello","device_id","name","platform":"ios"/"android"/"web","source":"glasses"/"phone"/"browser","model","app_version"}`. `device_id` stable per install (UUID in app storage, localStorage for capture.html), 1 to 64 chars; `name` 1 to 40 chars. A repeat hello on the same socket updates the camera | NEW P0 |
| `welcome` | `{camera_id, active, hub {hub_id, name, version, contract}}` | NEW P0 |
| `camera_status` | `{active}` | NEW P0 |
| close code 4000 `replaced` | never auto-reconnect after 4000 on the current socket | NEW P0 |
| `state`, `advance`, `mistake`, `error` on the camera socket | same as `/ws/ui` | NEW P1 |
| send `next` / `back` | `{"type":"next","reason":"button","from":int}`, `{"type":"back","from":int}`, only after hello | NEW P1 |
| Join URL forms to accept | `handover://connect?host=&port=&hub=`; any `http(s)://host[:port]/...` (port 8000 when absent; if the URL has a query `http=<port>`, use it); typed `host` or `host:port` | NEW P0 |

### 3.3 Rules while a NEW feature is not built
- **Feature-detect, never assume.** `/api/info` 404 or failed: treat as contract 1, show the address from `location.host`, hide the QR. Field absent from `state`: hide that UI. No `welcome` within 2 s of hello: keep streaming plain JPEGs and hide Next and Back on the phone.
- **Mock it in `web/mock/mock-server.mjs` first.** Add every NEW item there exactly as CONTRACT_V2 words it (field names, error strings), plus test hooks like the existing `/mock/*` ones (for example `/mock/mistake?kind=behind`, `/mock/offline?reason=rate_limited`, `/mock/camera?source=file`). The mock QR may be a placeholder SVG labeled "mock".
- **Never fake it in the real UI.** No placeholder QR, offline badge, mistake banner, or camera name unless the real hub sent it. Screenshots for Devpost come from the real hub only; the mistake banner shot comes from a real Gemini run, never from the mock hook.
- Fix mock drift you find (example: the mock sends `No lesson selected`; the contract says `no lesson selected`).

## 4. Milestones, in order

Each has a definition of done (DoD) and the exact check. Post a short status line after each: finished, running, left. Never give time estimates.

**Setup (fresh clone).** Run once in the repo root; `uv` brings its own Python 3.12, so a missing `python3.12` does not matter:
```
uv venv --python 3.12 --python-preference only-managed .venv
uv pip install --python .venv/bin/python -r server/requirements.lock
npm --prefix web ci
```
Ask the human to create `.env` with the Gemini key by hand (never print it). If ffmpeg is missing, ask the human once and use the mock meanwhile. If both developers share one Mac, use a separate clone folder, run your hub with `HANDOVER_PORT=8100` and Vite with `VITE_API_TARGET=http://localhost:8100` (and replace 8000 with 8100 in the checks below).

Common checks, referred to by name below:
- **BUILD**: `cd web && npm run build` passes with no TypeScript errors.
- **SHOTS** (mock): from `web/`, start `PORT=8011 MOCK_AUTO=0 node mock/mock-server.mjs` and `VITE_API_TARGET=http://localhost:8011 npx vite --port 5175` in the background, run `APP=http://localhost:5175 MOCK=http://localhost:8011 node e2e/screenshots.mjs`, then stop both. Open and look at every PNG in `web/screenshots/` that changed. Extend the script with a shot and a check for every new state you add.
- **REAL** (hub; needs Google Chrome, Playwright uses channel `chrome`): repo root, `HANDOVER_CHECK=mock scripts/run_server.sh` and `.venv/bin/python -m server.replay lessons/demo-v1/norm.mp4 --loop --select demo-v1` in the background. Before Developer 1's M2 is merged: from `web/`, `npx vite --port 5173` then `node e2e/real-server.mjs`. Once the hub serves the dist (M2 merged): `npm run build` then `APP=http://localhost:8000 node e2e/real-server.mjs`. Look at the screenshots. Stop every process you started.
- **WATCH**: `.venv/bin/python scripts/smoke.py watch --base http://<hub ip>:8000` (exists after Developer 1's M3) prints every `state`, `advance`, `mistake`.
- **IOS**: load check (section 8), then `cd apps/ios && xcodegen generate && xcodebuild -project HandOverCapture.xcodeproj -scheme HandOverCapture -destination 'generic/platform=iOS Simulator' build`, then `./ci.sh` (unsigned device build, what CI runs). Build only; do not boot a simulator (it has no camera). If `xcodegen` is missing, ask the human before `brew install xcodegen`.
- **IOS-DEVICE**: when the human has connected and unlocked the iPhone: `xcrun devicectl list devices` for its id, then from `apps/ios/`:
  ```
  xcodebuild -project HandOverCapture.xcodeproj -scheme HandOverCapture -destination 'platform=iOS,id=<id>' -derivedDataPath build -allowProvisioningUpdates DEVELOPMENT_TEAM=$HANDOVER_TEAM build
  xcrun devicectl device install app --device <id> build/Build/Products/Debug-iphoneos/HandOverCapture.app
  ```
  `HANDOVER_TEAM` is the Personal Team ID of the Apple ID signed in to Xcode on this Mac (V8PCS2UL23 only if it is that account). Ask the human for it once and record it in `docs/DECISIONS_DEV2.md`. If Xcode is not signed in, ask the human to sign in (Xcode > Settings > Accounts). Never handle passwords.
- **ANDROID**: load check, then `cd apps/android && ./gradlew assembleDebug`. Toolchain setup, each install only with the human's OK (skip the command line tools if `sdkmanager` already exists):
  ```
  brew install --cask zulu@17
  export JAVA_HOME=$(/usr/libexec/java_home -v 17)
  brew install --cask android-commandlinetools
  export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
  yes | sdkmanager --licenses
  sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"
  brew install gradle
  cd apps/android && gradle wrapper --gradle-version <version from the CameraAccess sample>
  ```
  Write `apps/android/local.properties` with `sdk.dir=<ANDROID_HOME>` (gitignored). If the installs are declined, copy `gradlew` and `gradle/wrapper/*` from the CameraAccess sample and rely on CI. Pushes to `dev2/clients` run only the cheap `web` (and `hub-test`) jobs; `android` and `ios` run on `main` only. To build your branch on CI, run it by hand, sparingly: `gh workflow run build.yml --ref dev2/clients`, then `gh run list --branch dev2/clients --limit 1` (Developer 1 lands the minimal workflow before Sync 2).

| # | Milestone | Definition of done | Check |
|---|---|---|---|
| D0 | Setup | Fresh clone, branch `dev2/clients` from `main`, setup above done; all read-first docs read; `docs/DECISIONS_DEV2.md` exists | `git status` clean on the branch |
| W1 | Web served by the hub; mock mirrors V2 | Only relative URLs, works from `http://<ip>:8000/` with no Vite proxy; `api.ts` types gain every V2 field as optional; mock has `/api/info`, `/api/qr`, hello and welcome on `/ws/camera`, `camera`, `cameras`, `check_*`, `mistake`, `dismiss_mistake`, `frames=0` | BUILD, SHOTS, REAL (both forms once the hub serves the dist) |
| W8a | iPhone app skeleton streams the phone camera | xcodegen project, typed address, plain JPEG frames at 1 fps to today's hub (no hello needed) | IOS; IOS-DEVICE when the phone is connected: live frames visible on the learn screen |
| W3a | Minimal join.html, by Sync 1 | `server/static/join.html` committed: one self-contained file (inline CSS, JS and SVG, no external requests), shows the hub address and an "Open in HandOver app" link; W3 completes it | Open `http://localhost:8000/join` once M3 is merged |
| **Sync 1, 4:30 PM** | Contract smoke (M2, M3) | Your side: BUILD and REAL pass against Developer 1's latest `main`; W3a merged | REAL |
| W8b | iPhone app complete (spec in section 5) | hello, welcome, `camera_status`, step title, Next and Back, haptics, `handover://connect`, QR link from join.html, plist keys, `apps/ios/ci.sh` | IOS, IOS-DEVICE, WATCH shows `camera.platform: "ios"` |
| W4 | capture.html | sends hello (`platform:"web"`, `source:"browser"`, `name` from the user agent: "iPhone Safari", "Android Chrome", else "Browser"), recording dot, idle notice on `camera_status`, never reconnects after close 4000 on the current socket | REAL with capture.html open in Chrome on `http://localhost:8000/capture` (localhost counts as secure); iPhone Safari over https with mkcert if certs exist |
| W2 | Connect panel | QR from `/api/qr` of `urls.join[0]`, address in plain text under it, "Wrong network?" picker over `urls.lan`; top bar shows "{state.camera.name} connected" when `state.camera` exists, else "Camera connected" when the first frame arrives | BUILD, SHOTS, REAL; scan the QR with the real iPhone |
| **Sync 2, 6:30 PM** | First live loop, iPhone app | Real iPhone on the hotspot, typed address; WATCH shows `camera.platform: "ios"`, one `advance` reason `camera`; Next on the phone gives `advance` reason `button` on every screen | WATCH. On fail: S-G is dropped, the 6:30 to 8:00 slot goes to W8b, and capture.html is the camera for later syncs while fixing |
| S-G | Glasses source in the iPhone app, time-boxed 6:30 to 8:00 PM, only if Sync 2 passed | Spec in section 5.2; auto fallback to the phone camera works | IOS-DEVICE with glasses |
| **Sync 3, 8:00 PM** | Glasses gate and drop check | Glasses frames reach the hub for 60 s with no gap over 5 s; `camera.source: "glasses"`; one camera advance on demo-v1. If Sync 2 failed, record glasses as not shipped | WATCH. On fail: glasses stay in code behind the toggle and leave the demo, pitch and Devpost |
| W5 | Honest live states | Camera lost: last frame dimmed to 40%, "Camera disconnected. Reconnect your phone, or keep going with Next." "Offline check" badge with reason text when `check_offline`; check source and latency in small text; "Recording" banner whenever `camera.source == "file"`; `last_check.reason` shown only at confidence 0.7 or more; privacy line, exactly "The hub never saves your camera frames. Each check sends one frame to Gemini's API under Google's free-tier terms.", shown only after Developer 1's M15 test is merged | BUILD, SHOTS (one shot per state), REAL with replay (banner visible) |
| W6 | Mistake banner | Amber banner across the live view with `message`. Behind: buttons "Show step {looks_like + 1}" (`goto looks_like`) and "I'm fine" (`dismiss_mistake`); clears on step change. Ahead: "You're ahead." with only an "OK" button; it stays 4 s after the `mistake` message regardless of the states that follow (the jump's state arrives right after). Spoken once with `speechSynthesis` on `#/learn` only, never on `#/watch`. Phone apps play a warning haptic | BUILD, SHOTS via mock hook; REAL with `HANDOVER_MOCK_MISTAKE` once M9 lands |
| W3 | join.html complete | "Open in HandOver app" (`handover://connect?host=<location.hostname>&port=<location.port or 80>&hub=<hub>`); "Use this browser" only when `/api/info` has `ports.https`; "Just watch" to `/#/watch`; stays self-contained, no framework | Open `http://localhost:8000/join` in Chrome at 390x844 and 1440x900 (Playwright shot); tap each button on the real iPhone |
| **Sync 4, 10:00 PM** | Mac app checkpoint | Your side: iPhone app streams to the frozen Mac app if Developer 1 has it | WATCH |
| W11 | Android app (formerly M13), spec in section 6 | Phone camera, hello, step title, Next and Back, haptics, `handover://connect` and typed address, cleartext config, `apps/android/ci.sh` | ANDROID; on a real phone WATCH shows `camera.platform: "android"`; emulator runs labeled "emulator"; no phone: the CI APK, labeled "APK built in CI" |
| W7 | Spectator view | `#/watch`: read-only mirror on a phone browser (step title, step count, clip with captions, status badge, camera name, live frame when available); clips `muted` and `playsinline` with a "Tap for sound" control; never speaks; never sends next, back or goto | BUILD, SHOTS at 390x844, real iPhone Safari against the hub |
| W9 | App icon | `assets/icon/icon.svg` plus `assets/icon/icon-1024.png`, iOS AppIcon 1024, Android adaptive foreground and background; tell Developer 1 the paths (they make `.icns` and `.ico`) | Look at every PNG |
| **Sync 5, 12:00 AM** | Midnight full run | Real Gemini, iPhone app, fortune teller folded to done; planted skipped flip gives `mistake` `kind:"behind"` on screen and spoken; internet down with LAN up (the human turns off cellular data on the hotspot phone) shows "Offline check" and the lesson still finishes. Android: WATCH shows `camera.platform: "android"` when a phone exists, else the CI APK, labeled | WATCH during the fold. On fail: stop SHOULD work, fix the loop with Developer 1 |
| W12 | Learn polish | Fill the empty band in the right column (about 230 px at 1440x900) with an "Up next" preview (next step title and its `frames/NN.jpg`) or the expert's quote from the current caption; teach thumbnails use `lessonUrl(id, ref_frame, rev)` so they refresh after a recut, with a local counter for lessons that are not active | SHOTS at 1440x900 and 1920x1080, no empty band, no overflow; recut in REAL then confirm thumbnails change |
| | **SHOULD items start only after W1 to W12 pass** | | |
| S-A | Accessibility | Space or Right = Next, Left = Back, R replay clip, C captions, F full screen, 1 to 9 go to step; `aria-live` step announcements; `prefers-reduced-motion` turns motion into crossfades; visible 2 px focus ring; contrast of tokens checked and fixed to 4.5:1 | BUILD, SHOTS, keyboard-only walk in REAL |
| | Sleep 12:30 to 5:30 AM (human); the agent keeps going only on safe items: tests, screenshots, docs drafts | | |
| S-D | Done screen from real events | Per-step learner time from observed `advance` timestamps vs the expert's clip length (`end - start`), steps checked by camera (count of `reason:"camera"`), mistakes caught (count of `mistake` messages). Nothing invented | SHOTS, REAL to done |
| S-Q | QR scan in both apps | iOS: `AVCaptureMetadataOutput` `.qr`, no dependency. Android: ML Kit `barcode-scanning` (bundled model) on a CameraX analyzer. Both accept every URL form in 3.2 | IOS-DEVICE and ANDROID; scan the hub QR |
| W10a | Screenshots for submission | Real-hub screenshots: learn mid-step, verified, mistake banner (real Gemini run only), teach timeline, connect QR, spectator on phone, iPhone app, Android app if real | Look at each |
| **Sync 7, 6:00 AM** | Contract freeze | No new contract asks after this | none |
| S-PB, S-T badge, S-K | Export and import buttons; self-test badge per step from `self_test`; Gemini key field | Each only when Developer 1's endpoint or field is on `main`; feature-detected | BUILD, SHOTS, REAL |
| W10b | Matrix tests | Every cell in PLAN.md section 7 that you can run, run and recorded | section 7 below |
| **Sync 8, 8:00 AM** | Feature freeze, venue-light rehearsal | Bug fixes only from here | WATCH during rehearsal |
| V | Version bump, before 10:30 AM | `0.2.0` in `web/package.json`, the iOS project (`MARKETING_VERSION`) and Android `versionName` | BUILD, IOS, ANDROID or CI |
| W10c | `docs/TESTED.md`, `docs/DEVPOST.md`, `docs/pitch/` | section 9 | dash and claim checks in section 9 |
| **Sync 9, 10:00 AM** | Devpost draft | Every device claim maps to a live or CI row in TESTED.md | section 9 commands print nothing |
| **Sync 10, 11:30 AM** | Submit (human) | | |

Later SHOULD items, same rule (only after W1 to W12 pass): S-W ("Why" narration and slow replay), S-F (target frame toggle, confidence ring), S-S web side (`safety`, `tools`). STRETCH: Android glasses source (section 6.2), filmstrip on the Done screen.

Drop order if behind at midnight (same as PLAN.md section 3): (1) W11 becomes "APK built in CI, emulator only", labeled; (2) W12 waits; (3) W7 reuses the learn layout read-only; (4) W9 uses a plain placeholder mark. SHOULD items (S-Q, S-D and the rest) start only after W1 to W12 pass; if S-D has started, it shows counts only.

## 5. iPhone app spec (`apps/ios/`)

### 5.1 Base (W8)
- SwiftUI, xcodegen `project.yml`, target and scheme `HandOverCapture`, iOS 17.2+, bundle id `dev.handover.capture` (if the free team rejects it as taken, pick a unique suffix and record it in docs/DECISIONS_DEV2.md). Version 0.2.0. `DEVELOPMENT_TEAM` comes from `$HANDOVER_TEAM` (section 4, IOS-DEVICE); never hard-code a team.
- Screens per design.md: Connect (large title, Scan QR, Enter address, last hub remembered and auto-reconnected), Camera (preview, status dot, "Connected to {hub name}", step title and "Step n of N" from the hub, Next filled and Back plain, source picker "This iPhone" / "Ray-Ban Meta"), Source (glasses registration, permission, Developer Mode reminder).
- Phone camera: `AVCaptureSession` back camera 1280x720, `AVCaptureVideoDataOutput` with `alwaysDiscardsLateVideoFrames = true`, rotate upright (`videoRotationAngle`), encode JPEG quality 0.6, one frame per second.
- Socket: `URLSessionWebSocketTask` to `ws://<host>:<port>/ws/camera`. First message `hello`: `device_id` UUID kept in UserDefaults, `name` "iPhone" (or "Ray-Ban Meta via iPhone"), `platform:"ios"`, `source:"phone"` or `"glasses"`, `model` from `utsname` machine (for example `iPhone18,1`), `app_version` "0.2.0".
- Keep only the latest frame: if a send is pending, drop the new frame.
- Reconnect backoff 0.5, 1, 2, 4 s, capped at 5 s; resend hello with the same `device_id`. Never reconnect after close code 4000 on the current socket, and ignore close events from superseded sockets (an old task closing must not trigger a reconnect or change the screen).
- Receive `welcome`, `camera_status` ("Idle: another camera is active"), `state`, `advance`, `mistake`, `error`. Haptics: `UINotificationFeedbackGenerator` `.success` on `advance` reason `camera`, `.warning` on `mistake`.
- **Step title (no new contract field):** on a `state` whose `lesson_id` or `rev` differs from the last one seen, `GET /api/lessons/<lesson_id>` over http on the same host and port and keep the steps. Show `steps[state.step].title` and "Step n of N" (`state.step + 1`, `state.total`); show "Done" when `state.status == "done"`.
- Next and Back send `{"type":"next","reason":"button","from":state.step}` and `{"type":"back","from":state.step}` (the step from the latest `state`); shown only after a `welcome` arrived.
- `UIApplication.shared.isIdleTimerDisabled = true` while streaming. Recording dot and the line "Live: frames go to {hub name}" while sending.
- URL scheme `handover`: route by host. `handover://connect?...` goes to pairing; anything else goes to `Wearables.shared.handleUrl(url)`.
- Info.plist: `NSAppTransportSecurity > NSAllowsLocalNetworking = true`; `NSLocalNetworkUsageDescription`; `NSCameraUsageDescription`; `NSBluetoothAlwaysUsageDescription`; `NSBluetoothPeripheralUsageDescription`; `UIBackgroundModes` `bluetooth-central`; `CFBundleURLTypes` scheme `handover`; `MWDAT` dict (`AppLinkURLScheme = handover://`, `MetaAppID = $(META_APP_ID)`, `ClientToken = $(CLIENT_TOKEN)`, `TeamID = $(DEVELOPMENT_TEAM)`; Developer Mode needs no real credentials, leave the build settings empty). If ws to a raw IP is still refused on device, add `NSAllowsArbitraryLoads` and record it.
- `apps/ios/ci.sh`: `set -euo pipefail`, cd to its folder, `xcodegen generate`, `xcodebuild -scheme HandOverCapture -sdk iphoneos -destination 'generic/platform=iOS' -derivedDataPath build CODE_SIGNING_ALLOWED=NO build`. Executable bit set. Tell Developer 1 it exists.
- `apps/ios/README.md`: build, install with a free Apple ID, Developer Mode steps.

### 5.2 Glasses source (S-G, time-boxed until the 8 PM gate)
- SPM package `https://github.com/facebook/meta-wearables-dat-ios` exactVersion `1.0.1`, products `MWDATCore` and `MWDATCamera`. Swift 6.3 toolchain, Xcode 26.4+.
- Use exactly the APIs in `docs/RESEARCH_GLASSES_GEMINI.md`: `Wearables.configure()` once in `App.init`; `Wearables.shared.startRegistration()`; `.onOpenURL` to `handleUrl`; `registrationStateStream()`, `devicesStream()`; `checkPermissionStatus(.camera)` then `requestPermission(.camera)`; `createSession(deviceSelector: AutoDeviceSelector(wearables:))`; `statePublisher.listen`; `session.start()`; only after `.started`, `addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2))`; `camera.stream.videoFramePublisher.listen { $0.makeUIImage() }`; `camera.stream.start()`. Keep listener tokens alive. Stop with `camera.stop()` then `session.stop()`.
- Throttle to 1 fps, JPEG 0.6, same socket. Keep the app in the foreground (`.raw` frames stop in the background).
- Auto fallback to the phone camera if registration, permission, session or stream fails, if no frame arrives within 5 s of `.started`, or on `StreamError` `.thermalHot`, `.peakPowerLimit`, `.batteryLow`. Show "Using phone camera: glasses stream stopped." and resend hello with `source:"phone"`.
- At 8:00 PM, report the gate result. If it fails, leave the code behind the toggle and never claim glasses anywhere.

## 6. Android app spec (`apps/android/`)

### 6.1 Base (W11)
- Kotlin, Jetpack Compose with Material 3, minSdk 31, compileSdk 36, targetSdk 36, Java 17. Take AGP, Kotlin, Compose and CameraX versions from the official DAT CameraAccess sample's version catalog so the later glasses step needs no version changes. applicationId `dev.handover.capture`. Commit the Gradle wrapper (`gradlew`, `gradle/wrapper/*`). `versionName` 0.2.0.
- Same screens as iOS with Material 3 conventions: top app bar, filled button for Next, default Material colors (dynamic color is LATER). Status colors fixed green, amber, red.
- Phone camera: CameraX `ImageAnalysis` with `STRATEGY_KEEP_ONLY_LATEST`, `OUTPUT_IMAGE_FORMAT_RGBA_8888`, back camera about 1280x720, `toBitmap()`, rotate upright, JPEG quality 60, one frame per second.
- OkHttp WebSocket to `ws://<host>:<port>/ws/camera`; send JPEG as `ByteString`; drop a frame if the previous send is still queued (`queueSize() > 0`). Same hello as iOS with `platform:"android"`, `name` from `Build.MODEL`, `device_id` UUID in SharedPreferences. Same reconnect rules: never reconnect after close 4000 on the current socket, ignore close events from superseded sockets.
- Step title, "Step n of N", "Done" and the `from` of Next and Back: same rule as iOS 5.1 (`GET /api/lessons/<lesson_id>` when `lesson_id` or `rev` changes; `from: state.step`).
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
- Live tests per the PLAN.md section 7 matrix. You own: iPhone app phone camera to the source hub (Sync 2) and to the frozen Mac app (after Sync 4); iPhone app glasses (Sync 3); iPhone Safari capture.html with mkcert (the human OKs `brew install mkcert` and runs `scripts/certs.sh` on the hub Mac before 6:30 PM, again after a hotspot IP change); Android Chrome capture.html with the `chrome://flags/#unsafely-treat-insecure-origin-as-secure` exception for `http://<ip>:8000`, else a cloudflared tunnel only with the humans' OK (frames pass through Cloudflare); Android app to the hub (real phone, else emulator, else CI APK); viewers Chrome, Safari, Firefox on Mac, iPhone Safari, Edge live if installed, else untested (Playwright Chromium results are recorded under Chrome, not Edge). Record each result the moment you run it: date, time, commit, devices, command, outcome.

## 8. Machine safety

- Before every heavy step (Xcode build, Gradle, Playwright runs, full test runs):
  ```
  while [ "$(sysctl -n vm.loadavg | awk '{print int($2)}')" -gt "$(sysctl -n hw.ncpu)" ]; do sleep 30; done
  ```
- At most one simulator or emulator at a time; shut it down after (`xcrun simctl shutdown all`, `adb emu kill`). Prefer build-only checks.
- Stop every background process you start (mock, vite, hub, replay) when its check is done.
- Delete only build output inside this repo (`web/dist`, `apps/ios/build`, `apps/android/**/build`) and say exactly what you removed. No cleanup scripts.
- No paid services, no trials. Never take over the Mac UI (no clicking, no window automation). Never touch files outside this repo, keychains, accounts or system settings.

## 9. Submission docs (W10)

- `docs/TESTED.md`: the PLAN.md section 7 matrix. Each cell is **live**, **CI**, **emulator** or **untested**, with date, commit and evidence. Mark a cell tested only if it was actually run. Developer 1 sends you rows for their cells by message. A platform with only CI evidence reads "built and smoke tested in CI, not tested by hand".
- `docs/DEVPOST.md`: standard sections (inspiration, what it does, how we built it, challenges, accomplishments, what we learned, what's next). Measured numbers only, written as observed counts with their source. Replay labeled as replay. Future work labeled as future. Competitors: only Retrocausal and Dozuki (lead decision in PLAN.md). Never "first", "only", user counts or time savings. Glasses only if Sync 3 passed.
- `docs/pitch/`: one slide with the tested matrix, `docs/pitch/matrix.html` rendered to `docs/pitch/matrix.png` at 1920x1080 with Playwright (already installed). Only live and CI cells on it.
- Checks that must print nothing (reword any hit):
  ```
  perl -CSD -ne 'print "$ARGV $.: $_" if /[\x{2013}\x{2014}]/' docs/DEVPOST.md docs/TESTED.md docs/pitch/*.html
  grep -niwE 'first|only' docs/DEVPOST.md
  ```

## 10. Design bar

- Apple-native, calm, no gradients, no glow, no decoration colors. `system-ui` fonts on web, SF on iOS, Roboto via Material 3 on Android.
- Shared tokens from design.md section 7: dark bg `#0B0B0C`, surface `#161618`, raised `#1F1F22`, line `#2C2C2E`, text `#F5F5F7`, secondary `#A1A1A6`, accent `#0A84FF`, green `#30D158`, amber `#FF9F0A`, red `#FF453A`. One accent. Radii 6, 10, 14, 20. 4 point spacing. Motion 200 ms ease-out, respect reduced motion.
- US English, plain words, no em or en dashes in any UI string, doc or commit message.
- Look at a screenshot of every screen you change, on every platform you change it on.

## 11. Git

- Work in your own clone on `dev2/clients`. No worktrees. Small commits: `Area: what changed` (for example `iOS: send hello and handle welcome`). No attribution lines, no co-author trailers, no tool footers.
- **Merge gate** (all must pass, after the load check):
  ```
  .venv/bin/python -m server.test_server
  .venv/bin/python -m server.test_check
  .venv/bin/python -m server.tests                  # once Developer 1's M2 is merged
  npm --prefix web run build
  apps/ios/ci.sh                                    # only if you touched apps/ios
  apps/android/ci.sh                                # only if you touched apps/android
  git diff origin/main...HEAD | perl -CSD -ne 'print if /^\+.*[\x{2013}\x{2014}]/'   # must print nothing
  ```
  Also run REAL before a sync merge.
- **Merge to main** at each sync point:
  ```
  git fetch origin && git rebase origin/main
  # rerun the merge gate
  git push --force-with-lease origin dev2/clients
  git push origin dev2/clients:main
  ```
  If the push to `main` is rejected, fetch, rebase, rerun the gate and push again. Never force push `main`; `--force-with-lease` on your own branch only. A fix for a red CI job you own may merge outside syncs after the full gate.
- After every push, check CI (`gh run list --branch dev2/clients --limit 3` or `--branch main`, then `gh run view <id>`) and fix red jobs you own right away. Branch pushes run only `web` and `hub-test`; `ios` and `android` run on `main`, or on your branch only via `gh workflow run build.yml --ref dev2/clients`, used sparingly. Never open a pull request unless the human asks.

## 12. When blocked

Pick the safest honest option, write one entry in `docs/DECISIONS_DEV2.md` (date and time, problem, choice, why), and keep going with the next item. Never stop and wait unless the next step needs a human (device connect, install approval, sign-in).

## 13. Final report

When everything is done or time is up, report in this shape, short:
1. **Done**: each milestone ID with one line.
2. **How verified**: exact commands and results; which screenshots you looked at; which matrix cells are live, CI, emulator.
3. **Left**: what is not done or not verified, plainly.
4. **Humans only** (one checklist): connect and unlock the iPhone, trust the developer profile, give the Personal Team ID of the Apple ID signed in to Xcode, Meta AI app Developer Mode and glasses charged, Android phone with USB debugging (or decline), OK each Android toolchain install (or decline), OK mkcert and run `scripts/certs.sh`, hotspot with every demo device, turn off cellular data on the hotspot phone for the offline test, relay the requests in docs/DECISIONS_DEV2.md to Developer 1, record the backup demo video, submit the Devpost by 11:30 AM.
