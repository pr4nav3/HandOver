# HandOver desktop (Windows and Linux)

The HandOver app for Windows and Linux, buildable on macOS for development. It pairs with a hub on the local network and has every desktop screen in `apps/design/SCREENS.md`: onboarding, Home, Browse All, lesson detail, Learn, Done with score and rating, Teach with honest processing, the course editor, Organizations, Profile and Settings.

## Architecture

The same stack as Vibeflux's Windows app (`vibeflux/windows`): a Tauri 2 window around a Rust core, with a plain TypeScript UI (Vite, no framework).

| Folder | What it is |
| --- | --- |
| `core/` | The engine crate, no UI: hub addresses, pairing, the `/ws/ui` protocol (`protocol.rs`), the connection thread with reconnects (`socket.rs`, `backoff.rs`), lesson files with range requests and a small cache (`http.rs`), the library, accounts and organizations routes with this device's sign-in token (`api.rs`), recent hubs and settings (`store.rs`), and the theme catalog (`themes.rs`). Tests in `core/tests`. |
| `app/` | The Tauri shell: one command, `call`, that hands every UI request to the engine; the `hub` URL scheme for lesson media and the live frame; the native file picker; notifications; `--hub` and `--lesson` launch options. |
| `ui/` | The window: `src/main.ts` (navigation pane and routing) and one module per screen in `src/views/`. |
| `core/src/phone.rs`, `core/src/camera.rs` | Pairing a phone (the `handover://connect?hub=` link from the hub's `/api/hub-info`, or this computer's LAN address on older hubs, and its QR as SVG) and this computer's webcam as a `/ws/camera` sender that keeps only the newest unsent frame. |
| `core/src/bin/devserver.rs` | The development bridge: the same commands and events over HTTP on 127.0.0.1, so the UI can be worked on and screenshotted in a browser against a real hub. |

### Why Tauri, and not a native widget toolkit

- It is what Vibeflux uses for Windows, so the two apps share their build, signing and release path.
- Learn needs reliable video: step clips that loop, captions from WebVTT, range requests for seeking. A webview's `<video>` and `<track>` do this on every platform (WebView2 on Windows, WebKitGTK on Linux, WKWebView on macOS). Native Rust toolkits have no maintained cross-platform video and caption path.
- The window is still a native client, not a wrapper around the hub's web page. All network traffic goes through the Rust core: the UI never opens a socket or fetches from the hub itself, so the content security policy only allows the app's own `ipc` and `hub` schemes.

### How data flows

- **A viewer of the hub, built against CONTRACT.md Revision 6:** the hub owns lessons, checks, state and the learner session. The app runs no checks and keeps no lesson files; it reads `GET /api/lessons` and `GET /api/lessons/{id}`, refetches the lesson when `state.rev` changes, and adds `?v=<rev>` to clip, caption and frame URLs. Readers ignore unknown fields.
- **Commands:** the UI calls `call(cmd, args)`; the engine answers JSON. Library routes go through one command, `api`, restricted to `/api/...` paths and four methods. The sign-in token stays in the core: it is taken out of sign-in answers, stored per hub in `tokens.json` (mode 600), and added to each request.
- **Events:** the engine pushes `link` (connection state), `state`, `advance`, `mistake`, `error`, `frame` (a counter; the JPEG itself is served by the `hub` scheme), `camera` (this computer's webcam link) and `upload` (bytes sent).
- **Live camera, smooth at up to 15 fps:** `ui/src/frames.ts`. Each `frame` event is offered to a newest-only pump: one fetch and `createImageBitmap` decode at a time, frames that arrive meanwhile collapse into the newest, and drawing waits for `requestAnimationFrame` on a canvas. No object URLs are made.
- **This computer as the camera:** `getUserMedia` at about 12 fps (CONTRACT.md 6), scaled to a long side of 640, JPEG quality 0.55, one frame in flight. The window sends raw bytes with the `camera_frame` command (no JSON); the core sends hello (`source: browser`) and the newest frame over `/ws/camera`. The preview comes straight from the `<video>`; the hub's echo of it is ignored. On macOS the app's `Info.plist` carries the camera usage text.
- **Camera choice:** "How should HandOver see your hands?" (this computer, a phone, Meta glasses, the last marked Experimental) is asked before the first lesson, kept on this device, and shown as a Camera row with Change on the lesson page and in Settings.
- **End:** Learn always has End (Close when no lesson). Mid-lesson it asks first, then sends `end_lesson`, and the hub unloads the lesson for every screen. A lesson ended elsewhere shows "No lesson running" with Pick a Lesson.
- **Media:** `hub://localhost/lessons/...` (`http://hub.localhost/...` on Windows) is fetched from the paired hub. Small files are kept in memory after the first fetch, so a looping clip is fetched once and every range the player asks for is answered locally. Only lesson files and `/__frame` are reachable.
- **Reconnects:** one thread per hub. Back-off 0.4 s doubling to 5 s (the web app's curve). Close 1011 reconnects at once, 1013 backs off slowly, 4000 stops ("Another window took over"). 30 s without a message (three missed hub pings) counts as dead. Commands sent while down wait in a queue of 20. The window says "Reconnecting" only after 1.5 s down, shows the camera placeholder instead of a frozen frame, disables Next and Back, and re-selects its lesson once per connection if the hub restarted without it.
- **Feature detection:** `GET /api/me` decides whether the hub has accounts and the library. Without it, the app works as today's web app: the lesson list, Learn and Teach through `POST /api/lesson`, progress kept on this device.

### Screens (SCREENS.md sections)

| Screen | Notes |
| --- | --- |
| Onboarding (25) | Four welcome pages with the bundled sample lesson (`ui/public/sample`, rendered, labeled as such), Connect with recent hubs and the 3.3 result states, owner setup or sign in, avatar color, join with a code, role, theme with a live preview. |
| Home (21) | A dismissible "How it works" card in 3 steps, Learn a Lesson and Teach a Lesson, Pair a Phone, the lesson running on the hub with Open, then Continue Learning (this device), Your Lessons, one block per organization, Everyone on This Hub. Empty sections are left out. |
| Browse All (5) | Search, and chips for Everyone, Mine, Shared with Me and each organization. |
| Lesson detail (6) | Cover, description, meta, safety and tools, Start or Continue, rating summary, the step list with this device's last results. |
| Learn (7) | Live camera fitted to the frame's own shape. A wide frame leaves room under it for "When this step is done": the step's reference frame and its check question. Right column: the clip with captions, the step title, the mistake card, the course step list, and the badge with Back and Next at the bottom. Step result moments, chime, checks-off reasons (7.8), Recording chip for replays, camera lost state (the last frame dimmed until a camera is back), the mistake card spoken once with the system voice. |
| Done (8, 9, 20) | Score from section 20 (checked, pace, clean), best and weakest step, the tip rules, the per-step time bars, Practice Step and Start Over. The rating sheet is offered once after 2 s when the hub allows this person to rate. |
| Teach (11, 13) | Choose a File (native picker), title and organization, upload with real bytes sent, then only the stages the hub reports, its message verbatim, and the error copy from 13. |
| Editor (14, 15) | Step list, the full video with a timeline whose boundaries drag (recut on release), split at the playhead, merge, delete, rename, check type, check question, common mistake, lesson details, undo and redo from the hub, and the publish sheet with organizations and Unlisted. |
| Organizations (22) | List with invitations, join with a code, create, the org page with lessons and members, invite codes and invites by username, role changes, remove, leave, delete. |
| Profile (4.3) and Settings (17) | Progress from this device's finished runs. Settings: Appearance (System, Light, Dark; dark by default because Learn is video first), the 14 themes in their four groups with search, lesson options, hub address and status, "Model sees every 0.5 / 1 / 2 s" (`set_check_interval`, shown when the hub sends `check_interval_s`), account, keyboard. |

The header never shows the hub's address; the pane shows "Connected" with a dot, and the address is in its tooltip and in Settings.

### Themes

`core/build.rs` embeds `apps/design/THEMES.md` at compile time and `themes.rs` reads its Catalog table and each theme's Role table (paper, raised, well, ink, ink2, ink3, line, lineStrong, accent, onAccent, accentInk, good, caution, bad, idle, grain), filling roles a theme leaves out from the file's Rules defaults. All 14 themes come through; `cargo test` checks them against the file. Without the file the app ships one built-in theme with a light and a dark look. With the system's Increase Contrast on, the High Contrast values are used in the current appearance. Grain themes draw a fine noise at the theme's own amount.

## Build and run on macOS (development)

```
cd apps/desktop/ui && npm ci && npm run build
npm test                                   # newest-frame pump, Node's own test runner
cd .. && cargo build && cargo test
cargo run -p app --features custom-protocol -- --hub 127.0.0.1:8099
```

`--features custom-protocol` serves the built UI from inside the binary (the Tauri CLI turns it on for `tauri build`). `HANDOVER_DESKTOP_HOME` moves the app's data folder, for tests and demos.

Against a real hub in mock mode, from the repo root:

```
HANDOVER_PORT=8099 HANDOVER_HTTPS_PORT=8100 HANDOVER_CERTS=/nonexistent HANDOVER_CHECK=mock HANDOVER_NO_NETWORK=1 .venv/bin/python -m server.main
HANDOVER_TEST_HUB=127.0.0.1:8099 cargo test --test live_hub      # from apps/desktop
```

The UI in a browser, on the same engine:

```
DEVSERVER_HUB=127.0.0.1:8099 cargo run -p handover-core --features devserver --bin devserver
```

Then open http://127.0.0.1:5176. `DEVSERVER_PICK=<video path>` stands in for the native file picker.

## Build on Windows

Needs the Rust toolchain from `rust-toolchain.toml`, Node 20 or newer, and the Visual Studio C++ build tools. WebView2 ships with Windows 10 and 11; the installer bootstraps it otherwise.

```
cd apps\desktop\ui && npm ci && npm run build
cd ..\app && ..\ui\node_modules\.bin\tauri build
```

Or `cargo build --release --target x86_64-pc-windows-msvc --features custom-protocol` for the bare executable. Installers land in `apps\desktop\target\release\bundle\nsis` and `\msi`, unsigned.

## Build on Linux

```
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev librsvg2-dev libssl-dev libdbus-1-dev pkg-config
cd apps/desktop/ui && npm ci && npm run build
cd ../app && ../ui/node_modules/.bin/tauri build
```

Bundles (`.deb`, `.AppImage`) land in `apps/desktop/target/release/bundle`.

## What CI would do

A matrix job on `windows-latest` and `ubuntu-22.04` (plus `macos-latest` for the core):

1. Install the pinned toolchain (`rust-toolchain.toml`), Node 20, and on Ubuntu the packages above.
2. `npm ci && npm run build` in `ui/` (this also type-checks).
3. `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, `cargo test`.
4. `tauri build` and upload the bundles as artifacts.
5. Optionally start the hub in mock mode and run `HANDOVER_TEST_HUB=127.0.0.1:8099 cargo test --test live_hub`.

The workflow file belongs in the repo's `.github/workflows/`, outside this folder.

## Hub notes

- The library routes (`server/routes_library.py`) are not wired into `server/main.py` yet. The app detects that and falls back to the plain lesson flow. To test the full app, the router has to be included as `server/docs/library.md` describes.
- Hub needs from SCREENS.md that the app does not invent: a hub name (the host stands in, and is only shown in Settings and the connect result), sign up (accounts are made by the hub owner), avatar photos, per-step voiceover and self-test buttons in the editor, and run history per account (this device keeps its own).
