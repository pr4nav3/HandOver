# Install and connect HandOver

HandOver currently ships as a development prototype. The Mac/PC runs the local hub; desktop, phone, tablet, browser, and wearable camera clients connect to that hub on the same network. There is no hosted HandOver service to sign into.

## Choose what to install

| You want to… | Install |
| --- | --- |
| Run the complete local system | The repository, Python hub dependencies, and one desktop or browser client |
| Use the iPhone camera | The Apple app on the iPhone, built with Xcode |
| Use Ray-Ban Meta video | The Apple app plus Meta AI, Developer Mode, and paired glasses |
| Use an Android camera | The Android app, built with Gradle or installed from a published APK |
| Try the lesson without hardware | Only the hub and the checked-in replay fixture |

The public download page is [handover.sohamaggarwal.com/install](https://handover.sohamaggarwal.com/install). Release files are unsigned development builds unless a release explicitly says otherwise.

## 1. Start the local hub

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+, npm, and ffmpeg.

```sh
git clone https://github.com/pr4nav3/HandOver.git
cd HandOver

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r server/requirements.lock
npm --prefix web ci
npm --prefix web run build
scripts/run_server.sh
```

The terminal prints two important addresses:

- `http://localhost:8000` for the computer running the hub.
- `http://<laptop-ip>:8000` for native apps on the same network.

Keep that terminal open. The hub owns the active lesson and keeps every screen in sync.

For an offline first run, replace the final command with:

```sh
HANDOVER_CHECK=mock HANDOVER_NO_NETWORK=1 scripts/run_server.sh
```

Mock mode exercises the workflow without judging the camera image. Real checks require either `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` in a local `.env` file.

## 2. Mac desktop app

### Downloaded development build

Download the current Mac disk image from the [install page](https://handover.sohamaggarwal.com/install), drag HandOver to Applications, and open it. If macOS blocks the unsigned build, open **System Settings → Privacy & Security** and choose **Open Anyway** for HandOver.

The desktop app is a client of the local hub. During development it can reuse a hub already running on port 8000 or start the hub from a HandOver checkout it can locate. A downloaded app without a local checkout should connect to a hub that is already running.

### Build the Tauri desktop app

Requirements: the Rust toolchain, Node.js 20+, and the platform packages listed in [apps/desktop/README.md](../apps/desktop/README.md).

```sh
npm --prefix apps/desktop/ui ci
npm --prefix apps/desktop/ui run build
cd apps/desktop/app
../ui/node_modules/.bin/tauri build --bundles app
```

The macOS application lands under `apps/desktop/target/release/bundle/macos/`.

## 3. iPhone, iPad, or native Mac app

Requirements: macOS, Xcode 26.4 or later, XcodeGen, and an Apple ID added to Xcode. The project targets iOS 18 and macOS 15. A free Personal Team is sufficient for a development install; free-team builds normally need renewal after seven days.

```sh
brew install xcodegen
cd apps/apple
xcodegen generate
open HandOver.xcodeproj
```

In Xcode:

1. Select the **HandOver** target, then **Signing & Capabilities**.
2. Turn on **Automatically manage signing** and choose your Team.
3. If `com.soham109.handover` is unavailable to your team, change `PRODUCT_BUNDLE_IDENTIFIER` in `project.yml` to a unique reverse-domain identifier, regenerate the project, and reopen it.
4. Plug in and unlock the iPhone, trust the Mac when asked, and enable iPhone Developer Mode if Xcode requests it.
5. Choose the physical iPhone as the destination and press **Run**.

The app is not distributed through the App Store or TestFlight. Do not download an arbitrary IPA: iOS will not install it without matching signing and provisioning.

## 4. Android

Requirements: Android Studio or JDK 17 plus the Android SDK used by the Gradle project. The app supports Android 10 (API 29) or later; the checked-in debug build targets 64-bit ARM phones.

```sh
cd apps/android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

A published APK can be opened directly on the phone after allowing that browser or file manager to install unknown apps. Development APKs are not Play Store releases and are not suitable for managed production deployment.

## 5. Pair a phone with the hub

1. Put the phone and hub computer on the same Wi-Fi network or phone hotspot.
2. Start the hub and open the desktop app.
3. Choose **Pair a Phone** on the computer and scan its code with the HandOver phone app.
4. Confirm that both screens name the same hub before choosing a camera.
5. Select **iPhone Camera**, **Android Camera**, or **Meta Glasses**, then start the lesson.

If scanning does not connect, enter the LAN address printed by `scripts/run_server.sh`, including `http://` and port `8000`, in the phone's Hub setting. Opening that address in the phone browser is a quick network check: if it does not load, the app cannot reach it either.

## 6. Ray-Ban Meta camera through iPhone

The glasses path uses Meta's Wearables Device Access Toolkit 1.0.1 inside the iPhone app. It is a developer-preview workflow, not a store integration. The repository currently uses app ID and client token `0` for Developer Mode.

For this pinned toolkit, use Meta AI V292 or later and glasses firmware V128 or later. Meta may raise these requirements; when the toolkit reports an update requirement, follow that explicit result instead of retrying an outdated build.

Before opening HandOver:

1. Pair the glasses with this iPhone in Meta AI and confirm they are connected.
2. Update Meta AI and the glasses firmware when the app offers an update.
3. In Meta AI, open **Settings → App Info** and tap the version five times if Developer Mode is hidden.
4. Return to the glasses settings and turn **Developer Mode** on.
5. Open the glasses' hinges and keep the glasses near the iPhone.

Then in HandOver:

1. Connect to the hub.
2. Open the camera choice and select **Meta Glasses**.
3. Tap **Connect Meta Glasses**.
4. Complete registration or camera approval in Meta AI, then return to HandOver.
5. Wait for the glasses preview and the hub-connected state before starting the lesson.

For spoken guidance through the glasses, select the Ray-Ban output in iPhone Control Center before the lesson. The camera connection and the iPhone audio route are separate Bluetooth decisions, so a working glasses preview does not by itself prove that audio is routed there.

The physical evidence recorded for this repository is one signed iPhone development setup with Ray-Ban Meta Gen 2. Treat other phone, firmware, and glasses combinations as unvalidated until they complete the same sustained run.

## 7. Browser camera

The learner UI works at `http://<laptop-ip>:8000`, but mobile browsers require a secure context before they expose the camera. On macOS:

```sh
scripts/certs.sh
scripts/run_server.sh
```

Follow the script's instructions to install and trust the local certificate authority on the phone, then open the printed `https://<laptop-ip>:8443/capture` address. Native phone apps do not need this browser certificate flow.

## Verify the installation

Before testing a real course, confirm these checkpoints in order:

1. The hub opens locally and lists the bundled lessons.
2. The phone opens the hub's LAN address.
3. The desktop and phone show the same selected lesson and step.
4. The learner view receives fresh frames for at least 60 seconds.
5. **Pause**, **Replay**, **Back**, **Next**, and **End lesson** all work, and End stops clip and speech audio.
6. A mock or replay run completes before enabling paid model checks.
7. A glasses run shows a live preview before any completion claim is recorded.

If any checkpoint fails, stop there and use [troubleshooting.md](troubleshooting.md). The full evidence checklist is in [validation.md](validation.md).
