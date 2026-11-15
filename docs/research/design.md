# HandOver cross-platform design

Notes on how the hub, phones and native shells fit together on each platform.

**1. The model in one line**
- The laptop (Mac or Windows desktop app, or the browser at localhost:8000) is the hub. It holds the lessons, runs the checks and shows the learn screen.
- Phones (iPhone app, Android app, or the capture web page) are cameras and remotes. They all send JPEGs to `/ws/camera`.
- Every phone works with every laptop because the only link is HTTP/WS on the local network. The server code is the same on every OS.

**2. Screens per platform**
- Desktop, Mac and Windows (one shared web UI inside a native shell): Welcome, Gemini key, Connect a camera (QR), Lessons (library), New lesson, Making lesson (progress), Lesson editor, Learn (full screen), Done, Settings.
  - macOS: sidebar for Lessons and Settings, traffic lights inset in a unified toolbar, Learn enters native full screen.
  - Windows 11: Mica only as the window backdrop, never on controls. Caption buttons on the right, custom title bar showing the backdrop. Mica turns into a solid color when transparency is off or on battery saver, so the layout must not depend on it. Source: https://learn.microsoft.com/en-us/windows/apps/design/style/mica (verified).
  - Font: `system-ui` gives SF on Mac and Segoe UI Variable on Windows 11. MDN says `system-ui` is "the default user interface font on a given platform": https://developer.mozilla.org/en-US/docs/Web/CSS/font-family (verified). The Segoe UI Variable mapping is inferred.
- Web: the same screens as desktop, plus `/capture` for phones.
- iPhone app: Connect (scan QR), Camera (preview, status, step title, Next), Source (This iPhone or Ray-Ban Meta), Settings.
  - Large title on Connect, inline titles elsewhere. SF via the system font.
  - Haptics: success when a step is verified, warning when a mistake is caught (UINotificationFeedbackGenerator; inferred, the Apple HIG page did not render).
  - Keep the screen awake while streaming.
- Android app: the same four screens.
  - Material 3 top app bar, filled button for Next.
  - Dynamic color for app chrome. It exists from Android 12: https://developer.android.com/develop/ui/views/theming/dynamic-colors (verified).
  - Status colors stay fixed (green, amber, red) and are harmonized with the dynamic scheme (HarmonizedColors, same page).
- Capture web page, no app needed: one screen with a permission prompt, then preview, status line, Next, and a "Having trouble?" sheet.

**3. First run and pairing**
- Desktop first run has three steps.
  1. "Welcome to HandOver. Record a task once. Anyone can learn it from your clips."
  2. "Add your Gemini key." Field, then Continue. Secondary action: "Skip, use sample lessons."
  3. "Connect a camera." Big QR code, the URL in plain text under it, and a 4-digit code.
- The QR content is `https://<laptop-ip>:8443/capture?pair=4821`.
  - With no app installed, the system camera opens the capture page.
  - The native apps scan the same QR, read host and code, and stream to `ws://<ip>:8000/ws/camera`. Plain `ws` avoids the certificate step.
- If the laptop has more than one network, show "Wrong network?" with a picker of local IPs.
- When the first frame arrives, the desktop shows "iPhone connected" (device name), shows the live preview, and enables Continue.
- Certificate step on the web path: "Your phone may warn about the connection. Tap Show Details, then visit this website." iOS needs the mkcert root installed and trusted. Android Chrome trusting user CAs is inferred and must be tested.
- Native apps need iOS local network permission plus ATS local networking, and an Android cleartext config for the laptop IP. Both inferred, not tested.
- Moving lessons between OSes: "Export lesson" writes a zip of the lesson folder and "Import lesson" reads it. A Mac-made lesson then plays on a Windows hub. Clips are already H.264, so they play everywhere.

**4. Learn screen (dark, readable on a projector)**
- Layout:
  - Top bar: lesson title on the left, "Step 4 of 8" and the camera dot on the right.
  - Thin segmented progress bar under the top bar.
  - Left 60%: live view.
  - Right 40%: expert clip on loop with captions, step title (40 px) above it.
  - Bottom right: status badge and a large Next button with the hint "or say next".
- States: badge text, color, and what happens.
  - Watching: "Watching", grey dot.
  - Checking: "Checking", grey ring that turns slowly. No spinner glow.
  - Verified: "Looks right", green check. Chime plus phone haptic. The next clip starts after 600 ms.
  - Manual: "Press Next when you're done", grey outline. A camera icon with a slash shows the step is not checked.
  - Mistake caught: amber banner across the live view. "This looks like step 6. Did you skip the flip?" Buttons: "Show step 5" and "I'm fine".
  - Skip alert (spoken and shown): "Wait. Step 3 comes first: crease both diagonals."
  - Camera offline: "Camera disconnected. Reconnect your phone, or keep going with Next." The last frame stays, dimmed to 40%.
  - Checks offline (API down): "Checks are off right now. Use Next to move on." The badge is hidden. Replay still works.
- Done: "Done. You folded a fortune teller."
  - Stats table with three rows: your time vs the expert's time, steps checked by camera, mistakes caught.
  - Per-step bars: you vs expert.
  - Buttons: "Try again" (primary), "Back to lessons".
- Keyboard: Space or Right arrow = Next, Left arrow = Back, R = replay clip, C = captions, M = mute, F = full screen, 1 to 9 = go to step. Visible focus ring is 2 px in the accent color.
- Captions use `::cue` at 32 px, white on rgba(0,0,0,0.72).

**5. Teach flow**
- New lesson: drop zone "Drop a video, or choose a file", a Title field, and "Record from phone" (reuses the pairing QR).
- Making lesson: three rows with checks mapped to job status.
  - "Preparing video" (normalizing)
  - "Finding steps" (extracting)
  - "Cutting clips" (cutting)
  - Error text: "Couldn't make this lesson. {message}" with a Try again button.
- Lesson editor:
  - Player at the top.
  - Timeline under it, one segment per step. Segments alternate between two neutral tints; the selected step uses the accent. No rainbow.
  - Row of clip thumbnails (frames/NN.jpg). Clicking one plays that clip.
  - Step list. Each step has a title, start and end fields (MM:SS), a Camera or Manual switch, and a check question.
  - Buttons: "Re-cut clips" (calls recut), "Start lesson" (primary).

**6. Key strings (US English, no dashes)**
- "Next", "Back", "or say next", "Step {n} of {total}", "Watching", "Checking", "Looks right"
- "Camera connected", "Connecting…", "Scan with your phone's camera", "Or type this address", "Code {code}"
- Phone: "Point the camera at your hands", "Connected to {laptop}", "Lost connection. Trying again…"
- Library: "Lessons", "New lesson", "No lessons yet. Record a task once to make one."
- Settings: "Gemini key", "Chime", "Voice commands", "Camera source"

**7. Shared tokens (one product on every platform)**
- Color, dark (learn screen and dark mode):
  - bg #0B0B0C, surface #161618, raised #1F1F22, line #2C2C2E
  - text #F5F5F7, secondary #A1A1A6
  - accent #0A84FF, green #30D158, amber #FF9F0A, red #FF453A
- Color, light:
  - bg #FFFFFF, surface #F5F5F7, line #D2D2D7
  - text #1D1D1F, secondary #6E6E73
  - accent #007AFF, green #248A3D, amber #B25000, red #D70015
- Contrast: these pairs should clear 4.5:1 on their own backgrounds (estimated, not measured). Check with a contrast tool before shipping.
- One accent only. Green, amber and red are used only for state, never for decoration.
- Radii: 6 controls, 10 cards, 14 video panes, 20 sheets. Windows overrides: 4 controls and 8 windows (inferred from WinUI defaults).
- Spacing on a 4-point grid: 4, 8, 12, 16, 24, 32, 48, 64.
- Type scale for desktop and web, size/line height in px:
  - 13/18 caption, 15/22 body, 17/24 headline, 22/28 title, 28/34 large title
  - Learn screen: 20 counter, 32 captions, 40 step title, 24 Next label
  - Mobile body 17, iOS and Android native sizes.
- Motion: 200 ms ease-out. Respect reduced motion: no turning ring, crossfade instead.

**8. What can be verified from this Mac**
- Can verify: web and Mac app (screenshots in light and dark, keyboard); iPhone app on device with free signing. The iOS Simulator has no camera, so streaming needs a real device.
- Needs setup: Android emulator. It needs the free Android SDK, which is unknown to be installed. The emulator can feed the Mac webcam as its camera (inferred).
- Cannot verify here: the Windows app. Options are a free GitHub Actions windows-latest build (compiles only, inferred free for public repos) or Windows 11 ARM in UTM (heavy, and the Mac load rule applies). Windows UI and Mica stay unverified without a Windows machine. Phone to laptop pairing across OSes also needs the real devices.

**9. Contract additions this design needs**
- `status:"mistake"` with a `message` field, and a skip alert event.
- `pair` code check, plus a hello message from the phone carrying the device name.
- Export and import lesson endpoints.
- `checks_available` boolean in the state message.
- Per-step timing for the Done stats.