# HandOver design system

The visual and interaction rules for every HandOver app: iPhone, iPad, Mac, Android and Windows. Colors per theme are in [THEMES.md](THEMES.md). Every screen, string and state is in [SCREENS.md](SCREENS.md).

Sources. Most patterns here come from two apps that already work this way. Each section names the file it borrows from.
- Vibeflux, iPhone: `vibeflux/iOS/AgentDeckViewer/Design/DeckTokens.swift`, `DeckComponents.swift`, `Views/*`. Mac and shared: `vibeflux/Sources/Design/DeckThemeCatalog.swift`, `DeckWorkViews.swift`. Android: `vibeflux/android/app/src/main/kotlin/com/soham109/agentdeck/ui/theme/DeckTheme.kt`. Windows: `vibeflux/windows/ui/src/themes.ts`.
- Glasspad: `glasspad/Packages/GlasspadKit/Sources/GlasspadKit/Theme/ThemeCatalog.swift`, `ThemeGrain.swift`, `glasspad/Apps/iOS/Sources/Design/Glass.swift`, `Grain.swift`, `glasspad/docs/brand/voice.md`.
- HandOver today: `web/src/Learn.tsx`, `web/src/Teach.tsx`, `web/src/styles.css`, `CONTRACT.md`, `server/docs/*`.

Scope note. `docs/PLAN.md` lists Android, Windows and QR pairing as cut for the hackathon build. This spec covers them because the lead asked for the full product. Builders should treat Android and Windows sections as the target for after the demo. Features that need hub endpoints that do not exist yet are marked **Needs hub** with the missing piece named (see the last section of SCREENS.md).

---

## 1. Principles

1. **The two videos are the interface.** The expert's clip and the learner's camera take the space. Everything else is small, quiet and at the edges.
2. **One accent per screen.** One filled primary button at most. Status uses the tone colors (good, caution, bad), never the accent. Borrowed from `DeckButtonStyle` ("`.primary` is the accent fill, one per screen"), `DeckComponents.swift`.
3. **Say what is true.** A badge never claims a check that did not run. Simulated checks say so. Stats on the done screen and in Insights come only from real events. Empty states show no numbers at all, never zeros dressed up as data.
4. **Calm surfaces.** Flat paper, raised cards with a half-point hairline, sunken wells. No gradients, no glow, no colored shadows, no blur blobs. Shadows only on things that float (toasts, the PiP tile). From `DeckShadow` and `deckFloating`, `DeckTokens.swift` and `DeckComponents.swift`.
5. **Glass only for floating controls.** Liquid Glass (iOS 26 and macOS 26) is for controls that sit on top of video: the close button, the badge over the camera, the recording controls, the PiP tile's frame. Never for cards, lists or the video itself. From `deckGlassCapsule` in `DeckComponents.swift` and `glassCapsule` in Glasspad's `Glass.swift` ("never for the trackpad surface itself").
6. **Native first.** System font, system controls, system sheets, system navigation. A HandOver screen should look like it came with the platform.
7. **Plain words.** Buttons are one to three words in Title Case. Messages are one sentence, two at most: what happened, then what to do. US spelling. No em dashes or en dashes anywhere. No time estimates. From `glasspad/docs/brand/voice.md`.
8. **Still things stay still.** Status dots do not pulse or breathe. The words say what is happening. From `DeckStatusDot` ("Nothing breathes or glows"), `DeckComponents.swift`.
9. **Show only what this person can do.** Actions the person's role does not allow are left out, not shown disabled. No grayed-out Teach, Invite, Publish or Remove buttons, and no lock icons on them. Disabled is only for actions the person can take once something is ready, like Next before a lesson loads or Send before a star is picked. Rules in SCREENS.md section 24.

---

## 2. Tokens

Names are shared across platforms. Swift: `HOColor.paper`, `HOSpace.l`. Kotlin: `HO.colors.paper`, `HOSpace.l`. Windows and web: `--ho-paper`, `--ho-space-l`.

### 2.1 Color roles

Same role set as Vibeflux (`DeckThemeTokens` in `DeckThemeCatalog.swift`), plus four HandOver roles for video. Values per theme in THEMES.md.

| Role | Use | Contrast rule |
|---|---|---|
| `paper` | Surface behind everything; carries the grain in grain themes | |
| `raised` | Cards, rows, sheets, the step list | |
| `well` | Sunken areas: segmented tracks, timeline track, pressed rows, text field fill inside cards | |
| `ink` | Primary text and symbols | 4.5:1 on paper, raised, well, washes |
| `ink2` | Secondary text: step count, times, captions under titles, section headers | 4.5:1 on paper, raised, well |
| `ink3` | Placeholders, disabled, quiet symbols. Never information | 3:1 on paper and raised |
| `line` | Hairlines and card edges | |
| `lineStrong` | Field edges, the selected segment, timeline boundaries | |
| `accent` | Fill of the one primary button, selection, progress fill for the current step, toggles | 3:1 on paper, raised, well |
| `onAccent` | Text and symbols on accent | 4.5:1 on accent |
| `accentInk` | Accent as text: links, "Checking" badge text, selected row text | 4.5:1 on surfaces and on accentSoft |
| `accentSoft` | Accent wash (12% light, 16% dark): selected rows, Checking badge | |
| `good` | Verified, done, connected, camera-checked | 4.5:1 on surfaces and its wash |
| `caution` | Mistake card, checks off, budget reached, simulated checks, camera lost | 4.5:1 on surfaces and its wash |
| `bad` | Errors, failed upload, destructive buttons, delete | 4.5:1 on surfaces and its wash |
| `idle` | Watching dot, offline dots | 3:1 on surfaces |
| `stage` | Behind video and letterbox bars. `#000000` in every theme | |
| `captionFill` | Caption bar behind text over video. `#000000` at 72% in every theme | |
| `captionInk` | Caption text. `#FFFFFF` in every theme. 9.2:1 even over a white frame (72% black over white composites to `#474747`) | |
| `record` | Recording dot, timer pill fill, shutter inner when recording. `#D70015` in every theme. White text on it is 5.4:1 | |

Washes: one strength, `tone.alpha(0.12)` light and `0.16` dark (Vibeflux `washAlpha`; Android rounds to 30/255 and 40/255 as `DeckTheme.kt` does). Hover `ink` at 5% light, white at 6% dark. Press `ink` at 9% light, white at 10% dark.

Why the video roles are fixed: video is watched against black on every platform (Photos, the Camera app, QuickTime). A cream letterbox around a clip looks like a mistake, and captions must read on any frame.

### 2.2 Type

System font everywhere. Every iOS and Mac style is a Dynamic Type text style, so it scales. From `DeckFont`, `DeckTokens.swift`.

| Token | iOS and Mac style | Size at default | Weight | Use |
|---|---|---|---|---|
| `largeTitle` | `.largeTitle` | 34 | bold, tracking -0.4 | Library and Settings titles (navigation large title) |
| `display` | `.title` | 28 | semibold, tracking -0.3 | Empty state titles, Done title, the one big number |
| `stepTitle` | `.title2` | 22 | semibold, tracking -0.2 | Current step title in Learn |
| `title` | `.title3` | 20 | semibold, tracking -0.3 | Sheet titles, card titles in content |
| `headline` | `.headline` | 17 | semibold | Lesson row titles, mistake card message |
| `body` | `.body` | 17 | regular | Body text, list rows |
| `bodyMedium` | `.body` | 17 | medium | Row titles, toast text |
| `callout` | `.subheadline` | 15 | regular | Secondary lines, empty state messages |
| `section` | `.footnote` | 13 | semibold, in `ink2` | Section headers |
| `footnote` | `.footnote` | 13 | regular | Check reason, latency, hints |
| `caption` | `.caption` | 12 | regular | Timestamps, counts |
| `badge` | `.caption` | 12 | medium | Badges, chips |
| `captionText` | `.body` scaled by the Caption Size setting | 17 at Medium | semibold | Captions over video |
| `numeral` | `.system(.title, design: .rounded)` | 28 | semibold, monospaced digits | Done stats, the Library duration chip, Insights numbers |
| `timer` | `.system(.headline).monospacedDigit()` | 17 | semibold | Recording timer pill. SF Pro, not Rounded, like the Camera app |
| `code` | `.system(.footnote, design: .monospaced)` | 13 | regular | Hub address, lesson id |

SF Rounded is used only for numerals that are read at a glance (done stats, Insights, duration chips, step number in the step list tile). Everything else is SF Pro. Captions use SF Pro semibold because it holds up over moving video.

Caption Size setting: Small 0.85x, Medium 1.0x, Large 1.25x, Extra Large 1.5x of `.body`, then Dynamic Type on top. Maximum 2 lines; longer cues wrap to 2 and shrink to 0.85x before truncating.

Android maps the same tokens to sp with the sizes above (`DeckType.Default` in `DeckTheme.kt`), system font (Roboto or the phone's own). Windows uses Segoe UI Variable with the same sizes in px; Rounded numerals become Segoe UI Variable Display semibold with tabular figures.

### 2.3 Spacing

From `DeckSpace`, `DeckTokens.swift` (same on Android in dp).

| Token | Points |
|---|---|
| `xxs` | 2 |
| `xs` | 4 |
| `s` | 8 |
| `m` | 12 |
| `l` | 16 (screen margin on iPhone, card padding) |
| `xl` | 24 (screen margin on iPad and Mac, between sections) |
| `xxl` | 32 |
| `xxxl` | 48 |

Gap between the two video panes: `m` (12) on iPhone, `l` (16) on iPad and Mac. Between video and step title: `m`.

### 2.4 Sizes

From `DeckSize`, `DeckTokens.swift`.

| Token | Points |
|---|---|
| `touch` | 44, the smallest hit area on iOS and Mac touch surfaces (48 dp on Android, 40 epx on Windows with pointer, 44 with touch) |
| `controlSmall` | 32 |
| `control` | 44 |
| `controlLarge` | 52 (Next, Record, Make Course) |
| `iconButton` | 36 visible, inside a 44 hit area |
| `badge` | 22 minimum height, grows with type |
| `dot` | 9, scales with type |
| `tile` | 32 symbol tile |
| `shutter` | 72 outer ring, 60 inner (Camera app proportions) |
| `pip` | iPhone portrait PiP tile: 30% of screen width, aspect of the learner camera, minimum 112 wide |

### 2.5 Radii

Continuous corners everywhere. From `DeckRadius`, `DeckTokens.swift`.

| Token | Points | Use |
|---|---|---|
| `small` | 8 | Chips, timeline segments, thumbnails in the step list |
| `control` | 12 | Buttons, fields, rows, segmented control, mistake card on iPhone |
| `card` | 18 | Cards, video panes on iPhone |
| `panel` | 24 | Sheets content panels, floating glass panels, video panes on iPad and Mac |
| `pip` | 16 | The PiP tile |
| `capsule` | half height | Badges, toasts, timer pill |

### 2.6 Lines, materials and shadows

- Hairline: 0.5 pt in `line` (0.6 dp on Android, 1 px on Windows at 100% scale). From `DeckLine`.
- Card: `raised` fill plus hairline. Grain themes draw grain on `paper` only; `raised` is opaque so text on cards never sits on noise.
- Glass: `glassEffect(.regular, in: .capsule)` on iOS 26 and macOS 26 for floating controls over video; `.regularMaterial` plus hairline before 26. Group neighboring glass controls with `GlassEffectContainer(spacing: 20)`. From `deckGlassCapsule`, `deckGlassPanel` (`DeckComponents.swift`) and `glassGroup` (Glasspad `Glass.swift`).
- Over video, glass controls force the dark color scheme so their content reads on any frame. From `CameraDark` in `PairingView.swift`.
- Floating shadow (toasts, PiP tile, dragged step): two layers. Light: near `#141414` 6% radius 1 y 1, far `#141414` 16% radius 16 y 10. Dark: near black 30%, far black 45%. From `DeckShadow.floating`.
- Segmented control raised segment: black 6% radius 2 y 1 in light, none in dark.
- Nothing else has a shadow.

### 2.7 Grain

Grain themes put a still noise tile on `paper`. Two proven methods exist; HandOver uses the Vibeflux one because it overlays any color and is shared by four platforms.

- Method (from `DeckGrain.texture(.grain, ...)`, `DeckThemeCatalog.swift`, and `DeckGrain` in `DeckTheme.kt`): a 128 x 128 px tile, SplitMix64 seeded with `0x6465636B67726169`. Per pixel `n = (r1 + r2 + r3) / 3 - 0.5`; draw white (lift) when `n > 0`, black (dip) otherwise, at alpha `abs(n) * 2 * amount * 2.2`, clamped to 0 to 1. Drawn once, tiled, never animated.
- Glasspad's alternative (`ThemeGrain.swift`, `Grain.swift`): a 256 px tile baked into the surface color at the screen's pixel density, one grain about half a point. Use it only if a builder needs grain baked into a pattern color (UIKit `patternImage`).
- Contrast is checked on the paper lifted and dipped by `amount` (the worst grain pixel), as `contrastProblems()` does.
- Grain is never drawn over video, sheets, the camera viewfinder or `raised`.

### 2.8 Motion

From `DeckMotion`, `DeckTokens.swift` (springs measured in Glasspad).

| Token | Value | Use |
|---|---|---|
| `panel` | spring response 0.38, damping 0.82 | Sheets, mistake card in and out, toasts, onboarding |
| `layout` | spring response 0.34, damping 0.86 | Progress segments filling, PiP snapping to a corner, timeline boundary release, reorder |
| `snappy` | `.snappy(duration: 0.25)` | Badge label changes, small state changes |
| `press` | ease out 0.12 s | Button press: scale 0.98, primary fill to 82% |
| `clip` | ease in out 0.20 s | Cross-fade between step clips |
| `shutter` | spring response 0.30, damping 0.80 | Shutter circle to rounded square and back |
| `reduced` | ease in out 0.15 s | What every animation becomes with Reduce Motion |

Rules:
- Reduce Motion: nothing moves or scales. Every change cross-fades in 0.15 s or happens at once. The shutter changes shape without morphing. The PiP jumps to its corner. Symbol bounce effects are off.
- The Verified symbol plays `.symbolEffect(.bounce)` once (from the pairing done state, `PairingView.swift`).
- Shake on a bad QR code or wrong passcode: 8 pt sideways, 2 cycles (`Shake` in `PairingView.swift`). Off with Reduce Motion; the error text still appears.
- No looping animations except the clip itself and the activity spinner.

---

## 3. Components

Every component lists its states. Exact strings are in SCREENS.md; the strings below are the canonical ones the components show.

### 3.1 Status badge

A capsule: dot, then label. `badge` type, padding 8 horizontal 3 vertical, wash fill of its tone, text in the tone's text color. From `DeckBadge` and `DeckTone`, `DeckComponents.swift` and `DeckTokens.swift`. Sits on the paper in the controls area; over video it becomes a glass capsule with white text and the dot in the tone color.

| Hub state | Label | Dot and text tone | SF Symbol (shown at accessibility sizes instead of the dot) | VoiceOver |
|---|---|---|---|---|
| `watching`, camera step, camera live | Watching | idle dot, `ink2` text, `well` fill | `eye` | "Status: watching for this step" |
| `checking` | Checking | `accentInk` on `accentSoft` | `viewfinder` | "Status: checking" |
| `verified` | Verified | `good` on good wash | `checkmark.circle.fill` | "Status: verified" |
| `manual` or step `check_type` manual | Tap Next when done | neutral | `hand.tap` | "Status: manual step. Tap Next when done" |
| `done` | Done | `good` | `checkmark.seal.fill` | "Status: lesson done" |
| `check_offline` true | Checks off, use Next | `caution` | `exclamationmark.triangle` | "Status: checks off. Use Next" |
| check mode is mock | Simulated checks | `caution` | `testtube.2` | "Status: simulated checks, not real" |
| camera step, no camera | No camera | idle | `video.slash` | "Status: no camera connected" |

Rules:
- Precedence (matches CONTRACT 5 plus client rules): done, then verified (also while the client holds the 1.8 s flash after a camera `advance`, as `Learn.tsx` does), then manual, then checks off, then simulated, then no camera, then checking, then watching.
- `checking` is already delayed 1.5 s by the hub (proposal P13). Once shown, hold it at least 0.6 s so it never flickers.
- Simulated checks needs the check mode from the hub. **Needs hub**: `check_mode` in `state`, or `GET /api/health` (proposal P25). Until then the badge cannot show it, and must not guess.
- Beside the badge, one `footnote` line in `ink2`: "Last check 0.9 s" while watching with a live camera, or the reason for checks off. Below it, the check reason in `ink2` only when `last_check.done == "no"` and confidence is 0.7 or more (rule from CONTRACT 7 and `Learn.tsx`).
- Label changes use `snappy` with `.contentTransition(.opacity)`.
- Announce changes with `.accessibilityLiveRegion` politeness polite (web `aria-live="polite"`).

### 3.2 Mistake card

Shown when `state.mistake` is set for the current step, or a `mistake` message arrives. Caution wash fill over `raised`, 0.5 pt hairline in `caution` at 40%, `control` radius (iPhone) or `card` radius (iPad, Mac). Leading symbol `exclamationmark.triangle.fill` in `caution`.

Layout: symbol, message (`headline`, `ink`, up to 3 lines), then a row of two quiet buttons (`controlSmall` height).

| Kind | Message (from the hub, verbatim) | Buttons |
|---|---|---|
| `behind` | the step's `common_mistake`, or "This still looks like step 4." | Show Step 4 (goes to `looks_like`), I'm Fine (sends `dismiss_mistake`) |
| `ahead` | "You're ahead." | OK (local dismiss; the hub has already advanced) |

States: entering (slides down from under the progress bar with `panel`, or fades with Reduce Motion), shown, dismissing (fades 0.15 s), replaced (cross-fade when a new message arrives). It is cleared automatically on step change. Plays the warning haptic once on entering. Spoken aloud when Voice Prompts is on (Settings), as the web does with `speechSynthesis`. VoiceOver: `.accessibilityAddTraits(.isStaticText)`, announced with `AccessibilityNotification.Announcement`, label "Mistake. <message>".

The current segment of the step progress bar turns `caution` while a `behind` mistake is shown (from `Learn.tsx`, class `mistake`).

### 3.3 Step progress bar

A row of equal segments at the top of Learn, one per step, 4 pt tall, 3 pt gaps, `small` radius ends. From `.progress` in `Learn.tsx` and `DeckProgressBar` (`DeckWorkViews.swift`).

| Segment | Fill |
|---|---|
| done | `good` |
| current | `accent` |
| current with a `behind` mistake | `caution` |
| upcoming | `well` |
| no lesson | one `well` segment |

Over 20 steps, segments become a single bar with the done portion filled and a tick for the current step. Fill changes animate with `layout`. VoiceOver: one element, "Progress, step 4 of 8", adjustable (swipe up or down goes to next or back only if the learner explicitly uses the rotor; it sends `goto`). Tapping a segment on iPad and Mac shows a menu "Go to Step N" (sends `goto`); on iPhone segments are not tappable (too small).

### 3.4 Clip player with caption bar

The expert's clip for the current step, looping, muted by default only if the device is on silent; otherwise audible.

- Pane: `stage` black fill, `card` radius on iPhone, `panel` on iPad and Mac. Video is aspect fit, centered. Letterbox bars are part of the black pane.
- Captions: drawn by the app, not the system, so size and position are controlled. Bottom center, inset `m` from the pane edge. `captionFill` capsule-ish rectangle (`small` radius), padding 8 by 4, `captionText` style in `captionInk`, center aligned, max 2 lines. Cues come from `captions/NN.vtt`.
- Above the caption, nothing else. Clip controls appear on tap (see below) and hide after 3 s.
- Controls on tap (glass capsule, top right of the pane): Replay (`gobackward`), Mute or Unmute (`speaker.wave.2` / `speaker.slash`), Captions On or Off (`captions.bubble`). Each 44 pt hit area.
- States: loading (black pane, small `ProgressView` in white at center after 0.5 s), playing, paused (only when the app is in the background or on the done screen), error (black pane, `exclamationmark.triangle` in white 60%, "Clip did not load." and a Try Again quiet button), no lesson (black pane, "No lesson selected").
- Step change: cross-fade with `clip` (0.2 s). The pane never changes size between steps unless the aspect changes; when it does, it animates with `layout`.
- URLs carry `?v=<rev>` (CONTRACT 5). Reload only when the clip URL changes, never on other redraws (from `Learn.tsx`).
- VoiceOver: "Expert clip for step 4, playing". Captions are also exposed as the element's value so VoiceOver can read the current line.

### 3.5 Live view with letterboxing

The learner's camera: either this device's camera preview, or the hub's forwarded frames (on Mac and iPad when another device is the camera).

- Pane: same shape as the clip pane. Aspect fit on `stage`, never cropped, so what the learner sees is what the check sees.
- Source chip, top left, glass capsule: symbol plus name. `iphone` "This iPhone", `eyeglasses` "Glasses", `video` camera name from `state.camera.name`, `film` "Recording" (when `camera.source == "file"`, in `caution`, with the `record` dot; from `.rec` in `Learn.tsx`).
- States:
  - live: frames updating.
  - waiting: black pane, `video` symbol in white 40%, "Waiting for camera", and the hint "Open HandOver on your phone and tap Be the Camera." in white 60%.
  - lost: the last frame stays, dimmed to 40%, with "Camera lost. Keep going with Next." in a caption-style bar (from `Learn.tsx`).
  - reconnecting to hub: placeholder, never a frozen frame (from `Learn.tsx`: "A frozen frame while the socket is down would mislead").
  - permission denied (own camera): see SCREENS.md, Camera access.
- The own-camera preview is mirrored only when using the front camera, and the frames sent to the hub are never mirrored.
- VoiceOver: "Your camera, live" or "Your camera, lost".

### 3.6 PiP tile (iPhone portrait Learn)

The smaller of the two videos floats over the larger one, like FaceTime.

- Size `pip` (30% width), `pip` radius, floating shadow, 0.5 pt white 20% hairline.
- Tap: swaps which video is large, with `layout` (a matched geometry swap). Reduce Motion: cross-fade.
- Drag: follows the finger, then snaps to the nearest of four corners on release with `layout`, keeping `l` inset from the safe area and clear of the controls tray. Velocity carries it toward the corner it was thrown at.
- Long press: menu with Swap, Hide Preview. Hidden state leaves a 44 pt glass button at the corner, `pip.exit` symbol, label "Show Preview".
- Corner and which video is large persist per device.
- VoiceOver: the tile is a button "Your camera, small. Double tap to swap." with custom actions Swap, Move to Top Left, Move to Top Right, Move to Bottom Left, Move to Bottom Right, Hide.

### 3.7 Buttons

From `DeckButtonStyle` and `DeckIconButtonStyle`, `DeckComponents.swift`.

| Kind | Fill | Text | Edge | Use |
|---|---|---|---|---|
| primary | `accent` (82% pressed) | `onAccent` | none | One per screen: Next, Start Lesson, Make Course, Publish, Connect |
| secondary | `raised` (`well` pressed) | `ink` | hairline | Back, Try Again, Choose Video |
| quiet | none (`pressed` wash) | `ink` | none | Card actions, I'm Fine, Show Step 4 |
| destructive | `raised` | `bad` | hairline | Delete Lesson, Remove Hub |
| icon | `raised` circle 36 | `ink` | hairline | Toolbar-free spots |
| glass | Liquid Glass capsule | white | none | Anything over video |

Sizes: small 32 high, regular 44, large 52 (large radius 16). Labels wrap to 2 lines at large type; small labels shrink to 0.85x. Pressed: scale 0.98 (off with Reduce Motion), `press` timing. Disabled: `well` fill, `ink3` text (quiet buttons stay clear). Keyboard focus: 2 pt `accent` ring at 55%, 2 pt outside the shape (`deckFocusRing`).

Next button: primary, large, full width of the controls tray on iPhone, at least 160 wide elsewhere. Label "Next". On the last step "Finish". Disabled with no lesson and on Done. Hint under it on Mac and iPad with a keyboard: "or press Right Arrow" in `caption`, `ink2`; with Voice Next on and listening: "or say next".

Back button: secondary, large, symbol `chevron.left` plus "Back". Hidden on step 1.

### 3.8 Shutter (record)

Camera app proportions. 72 pt white ring (4 pt stroke), inner shape 60 pt.

| State | Inner shape | Notes |
|---|---|---|
| ready | `record` red circle, 60 pt | |
| pressed | circle scales to 0.92 | `press` |
| recording | red rounded square 28 pt, radius 6 | morphs with `shutter` spring; Reduce Motion swaps shape instantly |
| finishing | square, ring shows a `ProgressView` | while the file closes |
| disabled | gray `#8E8E93` circle | no source, no permission, or glasses too hot |

VoiceOver: "Record" or "Stop recording", trait button. Hardware: Volume Up and Volume Down also start and stop (Camera app behavior, `AVCaptureEventInteraction` on iOS 17.2 and later). Space on iPad and Mac.

### 3.9 Timer pill and waveform

- Timer pill: `record` capsule, white `timer` text "00:42", 8 by 4 padding, at top center. Hidden when not recording. Blinks nothing; the dot left of the text is solid white.
- Waveform: under the timer while recording, 120 x 24 pt. 24 bars, 3 pt wide, 2 pt gap, white at 90%, heights from microphone RMS at 20 updates per second, smoothed. Silent for 3 s shows the line "No sound. Check the mic." in white 70% under it. With Reduce Motion the waveform becomes a single level bar that changes width at 4 updates per second.
- VoiceOver: timer exposed as "Recording, 42 seconds", updated every 10 s, not every second.

### 3.10 List rows

From `WorkspaceRow`, `MacRow`, `SettingsLabel`, `DeckRowButtonStyle` (`Components.swift`, `SettingsView.swift`, `DeckComponents.swift`).

- Lesson row: cover thumbnail 64 x 40 (`small` radius, `stage` fill behind), title (`bodyMedium`, 2 lines), meta line (`callout`, `ink2`): "8 steps, 3:12". Trailing: progress ring 20 pt in `accent` when in progress, or `checkmark.circle.fill` in `good` when completed. Padding `l` horizontal, `m` vertical. Minimum height 64.
- Settings row: symbol tile (30) plus title, trailing value in `ink2`, chevron for navigation.
- Hub row: `desktopcomputer` tile, name, subtitle "Connected" or "Last connected 2 hours ago", trailing checkmark in `accentInk` when active.
- Step row (editor): 1-based number tile (Rounded), thumbnail 72 x 40, title, meta "0:42 to 1:03, Camera check" or "Manual". Selected: `accentSoft` fill, `accentInk` number.
- Pressed: `pressed` wash. Selected: `accentSoft`. At accessibility sizes, meta moves below and wraps; thumbnails hide on iPhone.
- Swipe actions (iOS): trailing destructive only where deletion exists.

### 3.11 Empty and error states

Centered: symbol (`largeTitle` light, `ink2` or the tone), title (`title`), message (`callout`, `ink2`, max width 320), optional actions with `s` above. From `DeckEmptyState`, `DeckComponents.swift`.

Loading variant: large `ProgressView` instead of the symbol, title only, shown after 0.5 s of waiting (never flash a spinner for a fast load).

Error copy pattern: title says what happened, message says what to do. Always offer the one action that fixes it.

### 3.12 Banners

A slim card under the navigation bar for ongoing conditions (hub reconnecting, checks off, budget reached, simulated checks). From `ConnectionBanner`, `RootView.swift`. Symbol in the tone color, one `footnote` line in `ink2` (up to 3 lines), optional small secondary button. `raised` with hairline, `control` radius, inset `l`. Enters with `move(edge: .top)` plus opacity. One banner at a time; the highest severity wins (hub down, then budget, then checks off, then simulated).

### 3.13 Toasts

One line, floating at the bottom, leaves on its own after 4 s. From `DeckToast`, `DeckWorkViews.swift`. Capsule, `raised`, floating shadow, height 52. Optional tone symbol and one quiet action ("Undo"). Announced to VoiceOver. Slides up with `panel`, fades with Reduce Motion. Use for: "Lesson saved", "Copied address", "Step deleted" (Undo), "Published". Never for errors that need action (those are banners or alerts).

### 3.14 Sheets

System sheets. iPhone: `.presentationDetents([.medium, .large])` with the drag indicator for short content (connection details, publish), `.large` for forms. iPad and Mac: form sheets centered, 540 wide. Title inline, Done on the trailing side (`confirmationAction`), Cancel on the leading side when there are unsaved changes. From `ConnectionSheet`, `RootView.swift`. Confirmation of destructive actions uses `confirmationDialog` with the action named ("Delete Lesson"), never "OK".

### 3.15 Segmented control

Sunken `well` track, raised selected segment with hairline, sliding with `layout` (instant with Reduce Motion). At accessibility sizes, segments with symbols show symbols only. From `DeckSegmented`, `DeckComponents.swift`. Use for: source switcher (Phone, Glasses), visibility, library filters.

### 3.16 Fields

`raised` fill, `lineStrong` hairline, turning `accent` 1 pt while focused. Optional leading symbol in `ink3`. From `DeckFieldStyle`. Hub address field uses `code` type, URL keyboard, no autocorrect or autocapitalize.

### 3.17 Glasses card

Used in Record and Camera mode. `raised` card. Leading `eyeglasses` tile. Title "Ray-Ban Meta". A status line with a dot. Two meters when the SDK reports them: battery (`battery.75` family symbols) and thermal (`thermometer.medium`). Primary or secondary action depending on state. States and copy are in SCREENS.md, Glasses states.

Honesty rule: the DAT 1.0.1 notes in `docs/RESEARCH_GLASSES_GEMINI.md` confirm only `StreamError.batteryLow`, `.thermalHot` and `.peakPowerLimit`. If the SDK gives no battery percentage, show no percentage; show "Battery low" only when that error arrives. Same for heat: "Too hot" only from `.thermalHot`.

### 3.18 Timeline

Teach and the editor. From `.timeline` in `Teach.tsx`.

- Track: `well`, 44 pt tall (touch), `small` radius.
- Segments: one per step, filled with the step hue (step hues below), 1 pt `paper` gap between. The step number sits in a small `raised` pill (16 pt tall, `badge` type, `ink` text) at the segment's leading edge, so the label contrast is always ink on raised, whatever the hue. Segments narrower than the pill hide the number (it stays in VoiceOver and the tooltip). Selected segment: 2 pt `ink` outline.
- Playhead: 2 pt `ink` line with a 10 pt circle cap.
- Boundaries (editor only): 20 pt wide hit area centered on each boundary, a 4 x 24 pt `lineStrong` grip visible on hover or focus. Drag snaps to narration sentence edges (transcript segment starts and ends) within 0.4 s, with the selection haptic on each snap; hold Option (Mac) or drag with two fingers (iPad, iPhone) to place freely at 0.1 s. Minimum step length 0.5 s (teach cleans out shorter steps).
- Scale: start "00:00" and end time under the track in `caption`, `ink2`. Zoom with pinch or Command plus scroll; the track scrolls horizontally when zoomed.
- Step hues (light and dark, each reads as a fill under white or ink labels): `#4F78A8`, `#5E8B62`, `#A87A3E`, `#7E62A0`, `#A85E57`, `#3F8A86`, `#8C7E2E`, `#6268A8`. These replace the lighter web palette in `Teach.tsx` with deeper values so every segment reaches 3:1 as a mark against `well` in light themes (they are marks, not text; text is in the pill). Mono themes draw every segment in `ink2` at 35% with alternating `ink` 20% stripes and rely on numbers.

### 3.19 Step result moment

A small note after each finished step. It never blocks and never asks for anything.

- Glass capsule centered at the top of the clip pane (over video, dark scheme), `badge` type raised to `callout` semibold, symbol plus one line. Max width 90% of the pane.
- Appears on every forward step change caused by camera or Next (not by goto, not by Back). Enters with a 0.96 to 1 scale plus fade (`snappy`), stays, then fades. Total time on screen 1.5 s. Reduce Motion: fade only.
- Never stacks: a new one replaces the old one at once.
- Its haptic is the step change haptic in section 4 (success for camera, medium impact for Next). It adds no second haptic.
- Copy rules (exact strings in SCREENS.md, Learn, Step result moment): time from the client's per-step timer (as `Learn.tsx` counts it), expert time from the step's `end - start`. "Faster than the expert" only when your time is under 90% of the expert's. Within 10% says "about the expert's time". Slower says only the time, no judgment. No time is shown when the step was entered less than 1 s ago or the timer was interrupted by a hub disconnect.
- VoiceOver: announced with the same words, politeness polite.
- Off when Settings, Learn, Step Results is off.

### 3.20 Course step list

The vertical list of a lesson's steps with the learner's status. Used in Lesson detail, the Learn sidebar (iPad, Mac) and the Learn steps sheet (iPhone).

- Row: status symbol (20 pt), thumbnail 72 x 40 from `frames/NN.jpg` (`small` radius), step number and title (`bodyMedium`, 2 lines), meta (`callout`, `ink2`): "Expert 0:21". When done this run, adds "You 0:14".
- Status symbols:

| Learner status | Symbol | Tone | Word (VoiceOver and at accessibility sizes) |
|---|---|---|---|
| current | `play.circle.fill` | accent | Current |
| done by camera | `checkmark.circle.fill` | good | Checked by camera |
| done by hand | `hand.tap.fill` | neutral (`ink2`) | Marked done |
| skipped | `arrow.uturn.forward.circle` | caution | Skipped |
| not started | `circle` | `ink3` | Not started |

- Skipped means the learner moved past the step with goto, or the hub advanced from k to k+2 (an `ahead` mistake). Steps passed by an `ahead` advance show done by camera for step k and skipped for k+1 only if no check passed on k+1.
- Current row: `accentSoft` fill. Tap any row: jumps there (sends `goto`) after a confirm only when it would skip forward: "Skip to Step 6?" with Skip and Cancel.
- Header: progress ring and "3 of 8 done".

### 3.21 Progress ring and score ring

- Progress ring: 2 strokes, track `well`, fill `accent`, round caps, 4 pt stroke at 28 pt, 8 pt stroke at 96 pt. Center text: done count or percent in `numeral`. Animates with `layout`. Completed lessons: fill `good` and a check in the center.
- Score ring (Done screen): 120 pt, 10 pt stroke, fill in the tone of the label (Excellent `good`, Good `accent`, Keep practicing `caution`), center the score in `numeral` at `.largeTitle` size and the label under it in `callout`. With not enough data: track only, center shows "Not enough data" in `callout` `ink2`, no number.
- Fill animates once from 0 on appear over 0.6 s ease out; with Reduce Motion it appears filled.
- VoiceOver: "Score 82 of 100, good".

### 3.22 Time bar (you vs expert)

Per step on the Done screen. Two thin bars (6 pt, `small` radius) stacked 2 pt apart: Expert in `ink3`, You in `accent` (or `good` when faster). Both scaled to the longest time across the lesson. Times at the trailing end in `caption` with monospaced digits. Missing time: the You bar is absent and the text says "No time". VoiceOver: "Step 3. You 14 seconds, expert 21 seconds. Checked by camera. No mistakes."

### 3.23 Star rating

Five `star` and `star.fill` symbols, 32 pt each in a 44 pt hit area, `accent` when filled, `ink3` empty (Mono themes: `ink`). Tap sets, drag across scrubs with a `tap` haptic per star. VoiceOver: one adjustable element "Rating, 4 of 5 stars", swipe up or down to change. Read only variant in Insights at 14 pt with the average to one decimal.

### 3.24 Org tile and avatar

- Org avatar: rounded square (radius 28% of side, like `DeckSymbolTile`), sizes 28, 44, 72. Fill `accentSoft`, the first one or two letters of the org name in `accentInk`, SF Rounded semibold at 42% of the side. An uploaded org image replaces the letters (aspect fill, hairline edge). Mono themes: `well` fill, `ink` letters.
- Person avatar: circle, same sizes and letters rule, colored as in section 7.4. No photos are shown on public profiles unless the person uploaded one.
- Org row: avatar 44, name (`bodyMedium`), meta (`callout`, `ink2`): "<n> lessons, <m> members", trailing role badge ("Admin", "Teacher") only for roles above Member.
- Org card (Home, Explore): avatar 44, name, meta, 160 wide on iPhone in a horizontal row.

### 3.25 Invite code card

Shows an org invite code to admins.

- `raised` card. Code in `code` type at `.title2` size, letters spaced, grouped in fours ("K7QM 2XPA"), selectable. QR code (black on white, quiet zone 4 modules, 160 pt) beside it on iPad and Mac, below on iPhone. The QR stays black on white in every theme so every scanner reads it.
- Meta lines (`callout`, `ink2`): "Joins as Member", "Expires <date and time>" or "Never expires", "Used <n> times" and "<n> uses left" when capped.
- Actions: "Share" (system share sheet with the text and link), "Copy" (toast "Copied invite code"), overflow "Revoke" (destructive, with a confirmation).
- States: active, expired (code drawn in `ink3` and struck through, meta "Expired <date>", only Delete offered), revoked (removed from the list immediately, toast "Code revoked" with Undo for 4 s).
- VoiceOver reads the code one character at a time: "Invite code K 7 Q M 2 X P A".

### 3.26 Member row

Avatar 36, name (`bodyMedium`), username (`callout`, `ink2`, "@sam"), trailing role. Admins see the role as a menu (Admin, Teacher, Member) and a swipe action "Remove" (destructive). Other people see the role as plain text. The current person's row reads "You" after the name and cannot remove itself here; leaving the org is a separate "Leave Organization" action.

---

## 4. Haptics

iOS only (Android gets the closest `HapticFeedbackConstants`; Mac and Windows get none except Force Touch trackpad alignment on Mac for timeline snaps). The helper is Vibeflux's, verbatim (`Haptics` in `vibeflux/iOS/AgentDeckViewer/Views/Support.swift`):

```swift
enum Haptics {
    static func tap() { UISelectionFeedbackGenerator().selectionChanged() }
    static func soft() { UIImpactFeedbackGenerator(style: .soft).impactOccurred(intensity: 0.7) }
    static func success() { UINotificationFeedbackGenerator().notificationOccurred(.success) }
    static func warning() { UINotificationFeedbackGenerator().notificationOccurred(.warning) }
    static func error() { UINotificationFeedbackGenerator().notificationOccurred(.error) }
}
```

| Event | Haptic | Android | Source of the pattern |
|---|---|---|---|
| Any button tap that does something | `tap` | `CLOCK_TICK` | Vibeflux calls `Haptics.tap()` in every button action |
| Tab or segment change | `.sensoryFeedback(.selection)` | `SEGMENT_TICK` | `RootView.swift`, `AgentsView.swift` |
| Step verified by camera | `success`, once, on the `advance` with reason `camera` | `CONFIRM` | `PairingView.swift` done |
| Step change by Next, Back or goto | `.impact(weight: .medium)` | `CONTEXT_CLICK` | Vibeflux send (`PromptScreen.swift`) |
| Mistake card appears | `warning`, once per mistake | `REJECT` | Vibeflux stop (`PromptScreen.swift`) |
| Lesson done | `success` | `CONFIRM` | |
| Step result moment | none of its own; it rides on the step change haptic above | | |
| Rating star set | `tap` per star | `CLOCK_TICK` | |
| Invite code scanned or accepted, joined an org | `success` | `CONFIRM` | `PairingView.swift` done |
| Invite code invalid or expired | `error` plus shake | `REJECT` | `PairingView.swift` |
| Code revoked, member removed | `warning` | `REJECT` | `SettingsView.swift` remove |
| QR code found | `soft` | `CLOCK_TICK` | `PairingView.swift` `handle` |
| QR code or passcode wrong | `error` plus shake | `REJECT` | `PairingView.swift` |
| Paired or connected | `success` | `CONFIRM` | `PairingView.swift` |
| Hub connection lost while in front | `warning`, once until it is back | `REJECT` | `ConnectionFeedback.swift` |
| Hub connection restored after a loss | `success`, once | `CONFIRM` | `ConnectionFeedback.swift` |
| Record starts | `.impact(weight: .heavy)` | `LONG_PRESS` | Camera app |
| Record stops | `.impact(weight: .medium)` | `CONTEXT_CLICK` | Camera app |
| Timeline boundary snaps to a sentence edge | `tap` | `SEGMENT_FREQUENT_TICK` | |
| PiP lands in a corner | `soft` | `CLOCK_TICK` | |
| Destructive action confirmed | `warning` | `REJECT` | `SettingsView.swift` remove |
| Upload or course processing done | `success` | `CONFIRM` | |
| Upload or processing failed | `error` | `REJECT` | |

Rules (from `ConnectionFeedback.swift`):
- One haptic per real event the person can see. Never one per retry, per check, per `checking` flip or per state message.
- Nothing plays in the background, on the first connect after launch, during reconnect loops, or for the hub closing on purpose.
- Settings, Haptics off silences all of them. System "System Haptics" off is respected automatically.
- With the phone mounted as a camera, haptics still play but are not relied on: the learner is not holding it.

---

## 5. Accessibility

- **Dynamic Type** to AX5 on every screen. Layouts that would break switch: rows stack meta under titles; side by side Learn on iPhone landscape keeps both videos but the controls tray moves under them and scrolls; segmented controls go symbols only (`DeckSegmented`). Buttons grow to `min(scale, 1.6)` of their height (`DeckButtonBody`). Captions follow Caption Size times Dynamic Type, capped at 2 lines.
- **VoiceOver**: every control has a label; icon-only buttons always. Status dots are hidden; the status is in the row's label (`DeckStatusDot`). Rows combine children with one label, value and hint (`WorkspaceRow`). State changes the learner needs (verified, mistake, checks off, lesson done) are announced with `AccessibilityNotification.Announcement`. Order in Learn: step count and title, status badge, mistake card, Next, Back, expert clip, your camera, progress.
- **Reduce Motion**: see 2.8. Also stops the clip from auto-crossfading; it cuts.
- **Reduce Transparency**: glass becomes `raised` at 96% with hairline; caption fill becomes 90% black.
- **Increase Contrast**: switch to the High Contrast theme's values for the current appearance, hairlines to `lineStrong`.
- **Contrast**: text 4.5:1, marks and placeholders 3:1, everywhere, including on washes and grain extremes. High Contrast theme targets 7:1. Every theme in THEMES.md lists its measured ratios. Port Vibeflux's `DeckThemeContrastTests` (`contrastProblems()`) and run it on every theme in CI.
- **Color is never the only signal**: every status has a word and a symbol; timeline segments have numbers; Mono themes prove it.
- **Targets**: 44 x 44 pt minimum on iOS and Mac touch, 48 dp on Android, 40 epx pointer and 44 touch on Windows. The PiP tile, timeline boundaries and progress segments meet it with invisible padding.
- **Keyboard** (iPad and Mac, also Windows): Right Arrow or Space for Next, Left Arrow for Back (same as `Learn.tsx`), R to replay the clip, M to mute, C for captions, Command Z and Shift Command Z in the editor, Command S does nothing (autosave) but shows "Saved". Full keyboard access focus ring on every control.
- **Captions** on by default. Respect the system "Closed Captions + SDH" setting as on.
- **Voice Next** (listen for "next" and "back") is off by default and stays off until the learner turns it on (`docs/PLAN.md`, `Learn.tsx`). It ignores speech while the clip is audible.
- **Camera mode** keeps the screen awake (`isIdleTimerDisabled`) and dims to 30% brightness after 30 s idle, restoring on touch.

---

## 6. Platforms

One product, native on each. Same tokens, same strings, same states. Only navigation and controls change.

### 6.1 iPhone

- Navigation: `TabView` with up to four tabs: Home (`house`), Organizations (`person.3`), Teach (`video.badge.plus`, only for people who can teach somewhere), Profile (`person.crop.circle`). Library is the Browse All screen inside Home (SCREENS.md section 21). On a hub without accounts: Home, Teach, Profile. Settings sits behind the gear at the top left of every tab (Vibeflux `SettingsButton`, `RootView.swift`), the hub pill at the top right only when something is off (Vibeflux `ConnectionPill`: "Connected is silent, like Mail").
- Learn and Record and Camera mode are full screen covers (no tab bar).
- Portrait Learn: clip large, live preview as PiP (3.6). Landscape: side by side.
- One hand: the controls tray (badge, mistake card, Back, Next) lives in the bottom third, above the home indicator.
- Liquid Glass tab bar and toolbars come from the system on iOS 26.

### 6.2 iPad

- `NavigationSplitView`: sidebar (Home, Browse All, Teach, Insights, Profile, Settings; then an "Organizations" section listing each org with its avatar, and "New Organization" for people who may create one), content, detail.
- Learn: side by side at any width over 700 pt; in Split View or Slide Over under 700 pt it uses the iPhone portrait layout with PiP.
- Editor: three columns: step list, timeline and preview, inspector.
- Pointer: hover highlights (`.hoverEffect(.highlight)`, Glasspad `KeyCapStyle`), boundary grips appear on hover.
- Keyboard shortcuts as in section 5, listed in the Command key overlay.

### 6.3 Mac

- SwiftUI app, `NavigationSplitView` with a source list sidebar (same items as iPad), unified toolbar.
- Learn window: sidebar shows the lesson's steps (number, title, status symbol) and can be collapsed; the detail shows live view and clip side by side, step title and controls under them. Toolbar: lesson title, status badge (as a toolbar item), Voice Next toggle (`mic`), Captions toggle, Full Screen. Minimum window 900 x 600.
- Editor window: toolbar has Undo, Redo, Split, Merge, Test Question, draft status, Publish (primary).
- Menus: File (New Lesson from Video, Record Take, Open Hub Address), Edit (Undo, Redo, Split Step, Merge with Next, Delete Step), Lesson (Next Step, Previous Step, Replay Clip, Captions, Mute), View (Show Sidebar, Swap Videos), Window, Help.
- Settings in the standard Settings window (Command comma) with tabs: Hub, Appearance, Learn, Account, About.
- Mac can be the camera only with a connected camera (Continuity Camera included); it lists cameras by name.

### 6.4 Android (Material 3 mapping)

Mapping copied from Vibeflux `DeckColors.material()` in `DeckTheme.kt`:

| Material role | HandOver role |
|---|---|
| primary, onPrimary | accent, onAccent |
| primaryContainer, onPrimaryContainer | accentSoft, accentInk |
| secondary, onSecondary | ink2, paper |
| tertiary | accent |
| background, onBackground | paper, ink |
| surface, onSurface | raised, ink |
| surfaceVariant, onSurfaceVariant | well, ink2 |
| surfaceContainerLowest to High | raised |
| surfaceContainerHighest, surfaceDim | well |
| outline, outlineVariant | lineStrong, line |
| error, onError | bad, white |
| inverseSurface, inverseOnSurface | ink, paper |
| scrim | black 32% |

- Navigation: `NavigationBar` (Library, Teach, Profile) on phones; `NavigationRail` on medium width; `PermanentNavigationDrawer` on expanded.
- Top app bar: `TopAppBar` (small) with the gear as a navigation icon slot replaced by Settings in the overflow on phones.
- Sheets: `ModalBottomSheet`. Dialogs: `AlertDialog` with named actions.
- Buttons: primary is `Button` (filled), secondary `OutlinedButton`, quiet `TextButton`. Shapes use the radii above, not Material's default full pill, so it matches.
- A "Dynamic" theme option takes the accent from the wallpaper and falls back to Default if it fails the contrast check (`AgentDeckTheme` in `DeckTheme.kt`).
- Grain: the same tile via `DeckGrain.pixels`.
- Back: system back gesture goes Back a screen, never Back a step (stepping back is the Back button only).
- Camera: CameraX; the PiP tile uses the same rules.

### 6.5 Windows (Fluent mapping)

| Fluent | HandOver |
|---|---|
| Backdrop | Mica on the window, but with `paper` drawn opaque on content so themes stay true |
| AccentFillColorDefault | accent |
| TextOnAccentFillColorPrimary | onAccent |
| TextFillColorPrimary, Secondary, Tertiary | ink, ink2, ink3 |
| CardBackgroundFillColorDefault | raised |
| ControlFillColorSecondary | well |
| CardStrokeColorDefault, ControlStrokeColorDefault | line, lineStrong |
| SystemFillColorSuccess, Caution, Critical | good, caution, bad |
| Corner radius ControlCornerRadius, OverlayCornerRadius | 4 is Fluent default; HandOver uses 8 for controls and 12 for cards, a deliberate match to the other apps |
| Typography | Segoe UI Variable: Title 28, Subtitle 20, Body Strong 14, Body 14, Caption 12 (scaled from the iOS sizes by 14/17 so density feels native) |

- Navigation: `NavigationView` left pane (Home, Browse All, Organizations, Teach, Insights, Profile), Settings at the pane foot (Fluent convention).
- Title bar: custom, with the hub pill on the right.
- Learn: same as Mac (side by side, step list in the pane). Keyboard as section 5.
- Theme data: generated from the shared catalog as Vibeflux does for `windows/ui/src/themes.ts` (`DeckThemeExport`). Never hand edit colors on Windows.

### 6.6 What stays the same everywhere

Strings, state names, status precedence, haptic events (where hardware allows), the two-pane Learn idea, the controls order (badge, mistake card, Back, Next), the theme catalog and its ids, and the rule that every number shown came from a real event.

---

## 7. Onboarding

Screens and copy are in SCREENS.md section 25. This section sets how onboarding looks and moves. The aim is restraint: one idea per page, one moving thing at a time, nothing that loops for attention.

### 7.1 Page anatomy

| Part | Spec |
|---|---|
| Illustration area | Top 55% of the safe height on iPhone (max 360 pt), 1.3x on iPad, 300 pt tall on Mac. Centered, no frame, no background shape behind it |
| Title | `display`, centered, `ink`, up to 2 lines, `xl` below the illustration |
| Line | `body`, `ink2`, centered, max width 340, `s` below the title |
| Primary | `controlLarge`, full width with `l` margins, `l` above the bottom safe area |
| Page dots | system page indicator, `ink3` and `ink` |
| Step label | "Step 2 of 5" in `footnote`, `ink2`, `m` above the title |
| Background | flat `paper`, no grain, no gradient, until the Theme step applies the chosen theme |

### 7.2 Illustration style

- Built from SF Symbols at `.light` or `.regular` weight and simple rounded rectangles with continuous corners, drawn in theme roles only: `stage` panes, `raised` cards with hairlines, `accent` for the one highlighted thing, `good` for success. Two colors plus neutrals per illustration at most.
- Real content where content appears: frames and one clip from `lessons/synthetic-fortune-teller-v1`, labeled "Sample lesson, rendered". Real HandOver components (timeline, badge, score ring) rather than drawings of them.
- No people, no hands, no stock photos, no emoji, no confetti, no sparkles, no gradients, no glow.
- No numbers unless they come from the sample lesson (its 8 steps and 3 s spans). The score page shows an empty ring and bars without figures.
- Ships as SwiftUI views (vector, so they scale with Dynamic Type and themes). Android draws the same views in Compose; Windows uses the same layouts in XAML. No Lottie and no video except the one sample clip.

### 7.3 Motion

All values are exact. Every animation plays once per appearance of the page and never loops, except the sample clip and the waveform symbol on page 1 while it is visible.

| Moment | Animation | Curve and duration |
|---|---|---|
| Page content on first appear | Illustration fades in, text fades in 0.08 s later | ease out 0.30 s each |
| Swipe between welcome pages | System paging. Illustration offset at 0.6x of the page offset (parallax), text at 1.0x | follows the finger; release uses the system page spring |
| Page 1 waveform | `.symbolEffect(.variableColor.iterative)` on `waveform` | system symbol effect timing, stops when the page is off screen |
| Page 1 panel to page 2 tile | `matchedGeometryEffect` from the clip panel to step tile 1 | spring response 0.50, damping 0.86 |
| Page 2 timeline fill | Each segment grows from width 0 to its span, left to right | ease out 0.35 s per segment, starts staggered 0.12 s |
| Page 2 tile to page 3 pane | `matchedGeometryEffect` from tile 3 to the right pane | spring response 0.50, damping 0.86 |
| Page 3 badge | Watching to Verified after a 1.2 s delay, label `.contentTransition(.opacity)`, symbol `.bounce` once | `snappy` 0.25 s |
| Page 4 score ring | Trim from 0 to 0.70 | ease out 0.60 s, after 0.20 s delay |
| Page 4 bars | Each grows from 0 | ease out 0.25 s, staggered 0.08 s |
| Scanner code found | Corner brackets inset to 86%, color to `good` | spring response 0.34, damping 0.86 |
| Scanner to connecting | Cross-fade | ease in out 0.25 s |
| Connected check | `.symbolEffect(.drawOn)` on iOS 26 and macOS 26, `.bounce` before | system timing; `success` haptic on the first frame |
| Connected hold | Then advances by itself | 1.2 s hold, then 0.30 s cross-fade |
| Step to step (after the welcome pages) | Push: new page slides in 24 pt from trailing with fade; old fades | spring response 0.38, damping 0.82 (`panel`) |
| Invite code field to org welcome card | `matchedGeometryEffect` | spring response 0.40, damping 0.86 |
| Role card select | Fill and edge change | `snappy` 0.25 s |
| Avatar color change | Fill cross-fade | `snappy` 0.25 s |
| Passcode strength bar | Segments fill or empty | ease out 0.20 s |
| Theme preview change | Cross-fade of the preview and the screen | ease in out 0.20 s |
| Finish into Home | Cross-fade, Home content rises 12 pt | ease in out 0.35 s plus `panel` spring for the rise |

Reduce Motion: no parallax, no matched geometry moves, no growing segments or ring draw, no bounce or draw-on. Every change becomes a 0.15 s cross-fade (`reduced`), and content appears in its final state. The sample clip shows its first frame as a still image with a Play button (`play.circle`, VoiceOver "Play sample clip"). Haptics still play.

Low Power Mode: the sample clip shows as a still frame, as with Reduce Motion. Everything else plays.

### 7.4 Avatar

- Initials: first letter of the first two words of the name (one letter for one word), SF Rounded semibold at 40% of the diameter.
- Color: the person picks one of 8 hues. The default is picked from a hash of the username so it stays the same across devices. Fill is the hue's wash (12% light, 16% dark, over `raised`), letters are the hue.

| Name | Light | Dark |
|---|---|---|
| Blue | `#3249B8` | `#8AA8FF` |
| Teal | `#0A6570` | `#5CCFD9` |
| Violet | `#6E3FB0` | `#C4A1FF` |
| Berry | `#A02C6A` | `#FF8CC6` |
| Olive | `#56620C` | `#C8D46A` |
| Slate | `#4D5868` | `#AEB8C6` |
| Rust | `#963C22` | `#F0A07E` |
| Green | `#345C3D` | `#9CCB9F` |

The first six are Vibeflux's role hues (`lightRoles`, `darkRoles` in `DeckThemeCatalog.swift`), which its contrast test checks as text on their own wash at 4.5:1. Rust and Green are Clay's and Sage's accent text colors; add them to the ported contrast test before shipping. Mono themes ignore the hue: `well` fill, `ink` letters.
- Photo: circle crop, hairline edge in `line`, shown wherever the avatar appears. Stored on the hub (**Needs hub**), never uploaded anywhere else.
- Sizes: 28 (rows), 36 (member rows), 56 (Profile header), 72 (public profile), 96 (onboarding preview).

### 7.5 Passcode strength meter

Three segments, each 4 pt tall, 4 pt apart, `small` radius, track `well`. Fill tone by level: 1 `caution`, 2 `accent`, 3 `good`. The line under it uses `footnote` in `ink2` (never color alone). VoiceOver reads it as part of the field's value: "Passcode, hard to guess". Rules and copy are in SCREENS.md 25.4. The meter describes how easy the passcode is to guess. It does not promise security.

### 7.6 Platform notes

- iPhone: portrait only during onboarding. System page style with dots.
- iPad: same content in a 600 x 720 card on `paper`, larger illustrations, keyboard arrows move pages.
- Mac: a fixed 720 x 560 window, Back and Continue buttons instead of swiping, Return triggers the primary, Escape goes Back.
- Android: Compose `HorizontalPager`, shared element transitions for the matched geometry moves, `AnimatedVectorDrawable` versions of the symbol effects, durations and curves as above (`FastOutSlowInEasing` stands in for ease out, spring stiffness about 400 and damping ratio 0.86 for the springs).
- Windows: a 760 x 600 window, Back and Continue, connected animations for matched geometry, durations as above, no haptics.
