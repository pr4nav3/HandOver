# Cross-platform architecture research (2026-11-14)

## Recommendation
- Hub: one Python FastAPI server serving the built React app plus the REST/WS contract. Frozen with PyInstaller per OS. Every client speaks the same HTTP/WS contract; that is what makes every OS work with every other.
- Desktop (Mac, Windows): skip Tauri/Electron at first. Ship the PyInstaller app (Mac .app in .dmg, Windows .exe in Inno Setup installer). It starts the hub, opens the learn screen in the default browser, shows a QR code. Reason: Chrome Web Speech fails inside embedded webviews (Electron "network" error, WKWebView) (inferred from bug reports). Tauri 2 sidecar is the later upgrade (needs Rust, target-triple binary name; verified).
- Mobile: native Swift iOS and native Kotlin Android thin capture clients: glasses or phone camera, JPEG 1 fps, WebSocket to /ws/camera.
  - Meta Wearables DAT for Android exists (verified): github.com/facebook/meta-wearables-dat-android, Maven Central group com.meta.wearable, sample 1.0.1, developer preview, video streaming supported. Trust README (Maven Central) over older docs (GitHub Packages + token).
  - iOS DAT 1.0.1 SPM developer preview (verified). Flutter wrapper is third party; skip. RN/Capacitor have no official glasses support.
- Web: same Vite build served by the hub. Phone capture.html stays as fallback.

## Interop
- Lesson = folder with relative paths, so Mac-made lessons run on a Windows hub. Add GET /api/lessons/{id}/export (zip) and POST /api/lessons/import.
- Windows path hygiene: pathlib everywhere, ids [a-z0-9-], ffmpeg resolved from bundle (sys._MEIPASS), never assumed on PATH.
- Always normalize to H.264 (Windows browsers cannot play HEVC).

## Discovery and pairing
- mDNS: python zeroconf 0.154.0 (Python 3.11+, Windows wheels, verified). Hub registers `_handover._tcp` on 8000. Android NsdManager, iOS NWBrowser (iOS needs NSLocalNetworkUsageDescription + NSBonjourServices).
- Do not rely on .local in Android browsers (unreliable on Android 12, excluded on VPN). Use raw IPs.
- QR pairing: hub displays QR. Native apps get http://<ip>:8000; browsers get https://<ip>:8443/capture. Python `qrcode` package.
- getUserMedia needs HTTPS or localhost (MDN verified). Native apps avoid it. Browser fallback: mkcert root trusted on phone (iOS profile + full trust); last resort cloudflared quick tunnel.
- Android cleartext blocked by default (targetSdk 28+): network_security_config.xml `<base-config cleartextTrafficPermitted="true">` (verified).
- Windows firewall: first listen on 0.0.0.0 prompts; allow Private. Installer rule: `netsh advfirewall firewall add rule ... dir=in action=allow protocol=TCP localport=8000,8443` (inferred). Hotspots often classed Public.

## ffmpeg bundling
- Windows: gyan.dev essentials static GPLv3 (verified) or BtbN. Mac: static arm64 build (evermeet.cx / osxexperts) or CI build. Homebrew ffmpeg not relocatable.
- Ship as separate executable via subprocess, include license and source link.

## Verifiable from the Mac
- Mac app: yes.
- iOS: free Apple ID signing (7 day profiles, 3 apps per device). CI only compiles with CODE_SIGNING_ALLOWED=NO.
- Android: yes via command line tools, emulator, Gradle assembleDebug. Glasses need a real phone with Meta AI app; emulator only proves phone camera to WS.
- Windows: CI only. Smoke test on windows-latest: start exe, poll /api/lessons, run replay against /ws/camera. Firewall and SmartScreen unverifiable without hardware.

## Repo layout
- server/ (+ discovery.py zeroconf/QR, launcher.py start hub + open browser)
- web/ (build copied into server/static/app)
- apps/ios/ (xcodegen project.yml)
- apps/android/ (Gradle Kotlin, network_security_config.xml)
- packaging/ (handover.spec PyInstaller, mac/make-dmg.sh, windows/handover.iss Inno Setup, ffmpeg/fetch.{sh,ps1})
- .github/workflows/build.yml

## CI matrix (free on public repos)
- web ubuntu: npm ci && npm run build.
- mac macos-latest arm64: web dist, ffmpeg, uv, pyinstaller --windowed, ad hoc codesign, hdiutil dmg, smoke test.
- windows windows-latest: same, `choco install innosetup` (not guaranteed on image, issue #11644).
- android ubuntu: setup-java 17, ./gradlew assembleDebug, upload apk.
- ios macos: xcodegen && xcodebuild -sdk iphoneos CODE_SIGNING_ALLOWED=NO build.
- On tag: attach artifacts to a GitHub release.

## Risks
- Unsigned apps: Gatekeeper right-click Open; SmartScreen "Run anyway". Paid signing out of scope.
- PyInstaller size; keep faster-whisper optional.
- Web Speech needs Chrome and internet; Next button fallback.
- DAT developer preview on both OSes.
- Hotspot client isolation can block phone to laptop. Test the network early.
- No Windows hardware means Windows ships "CI green, untested by hand".

## Minimum viable per platform
- Mac: hub from source; dmg bonus. Web: Chrome learn/teach; capture.html over mkcert. iOS: native glasses capture app via free signing. Android: native Kotlin phone camera over cleartext ws; glasses if real device. Windows: CI installer passing replay smoke test; claim nothing beyond.
