# HandOver screens

Every screen on every platform: layout, hierarchy, exact copy, states and transitions. Tokens and components are in [DESIGN.md](DESIGN.md); colors in [THEMES.md](THEMES.md).

Copy rules (from `glasspad/docs/brand/voice.md`): US English, plain words, Title Case for buttons, screen titles and Settings rows, sentence case for everything else. No em dashes or en dashes. No time estimates. An error says what happened, then what to do. Strings in quotes below are exact. `<angle brackets>` are filled from data. Hub messages (mistake text, server errors) are shown verbatim.

Wire facts come from `CONTRACT.md` (Revision 5) and `server/docs/contract-proposals.md`. Anything that needs a hub feature that does not exist yet is marked **Needs hub** and listed in section 19.

Contents
1. Navigation map
2. First run
3. Connect to a hub (QR, typed address, recent hubs)
4. Sign in and accounts
5. Library
6. Lesson detail and course view
7. Learn
8. Done
9. Rate this course
10. Camera mode
11. Teach home
12. Record a take (phone and glasses)
13. Make course (processing)
14. Course editor
15. Publish and access
16. Insights
17. Settings
18. Errors and banners
19. Hub needs
20. Score and stats rules

---

## 1. Navigation map

| Platform | Root |
|---|---|
| iPhone | Tabs: Library, Teach, Profile. Gear (Settings) top left on every tab; hub pill top right only when something is off. Learn, Record, Camera Mode open as full screen covers |
| iPad | `NavigationSplitView` sidebar: Library, Teach, Insights, Profile, Settings, then "Recent" lessons |
| Mac | Window with source list sidebar (same items), unified toolbar. Learn and the editor open in their own windows. Settings window via Command comma |
| Android | `NavigationBar` Library, Teach, Profile; rail or drawer on wide screens |
| Windows | `NavigationView` left pane; Settings at the pane foot |

Insights is inside Teach on iPhone and Android phones (a row per lesson), a top-level item elsewhere.

Who sees what (roles from section 15): learners see Library, Profile, Settings. Editors and owners also see Teach and Insights. With no accounts on the hub (section 4), everyone sees everything, as the web app does today.

---

## 2. First run

Pattern from Vibeflux `OnboardingView.swift`: the mark, one line, one primary and one secondary button, nothing else.

**Layout (iPhone)**: `paper` with grain if themed. Centered column, max width 520. Top spacer, app mark 88 pt (fades and scales from 0.9 on appear with `panel`, fade only with Reduce Motion), title, one line, spacer, buttons pinned to the bottom with `l` margins.

| Element | Copy |
|---|---|
| Title (`largeTitle`, tracking -0.3) | "HandOver" |
| Line (`body`, `ink2`) | "Learn a task from an expert's own video, one step at a time." |
| Primary, large, full width, symbol `qrcode.viewfinder` | "Connect to a Hub" |
| Secondary, large, full width | "Enter Address" |
| Footnote (`caption`, `ink3`) | "A hub is the HandOver server running on a computer near you." |

iPad: same, centered card 520 wide. Mac: a 560 x 520 window with the same content; primary is "Enter Address" (Macs rarely scan), secondary "Use This Mac as the Hub" only when a hub is detected on localhost:8000. Android and Windows: same as iPhone and Mac respectively.

Transitions: Connect to a Hub opens the scanner (full screen cover). Enter Address pushes Typed address.

---

## 3. Connect to a hub

### 3.1 QR scan

Pattern and behavior from Vibeflux `PairingView.swift`.

**Layout**: full-bleed camera, forced dark. A 280 pt rounded square window (radius 14% of its side) cut out of a 50% black dim. Close button top right, 44 pt glass circle, `xmark`. Title block near the top, paste and type fallbacks at the bottom.

| Element | Copy |
|---|---|
| Title (`title2` semibold, white) | "Scan the hub's code" |
| Hint (`subheadline`, white 70%) | "On the computer running HandOver, open http://localhost:8000 and click Show Code." |
| Bottom button (secondary glass) | "Enter Address" |
| Paste button (system `PasteButton`) | system label |
| Close, VoiceOver | "Cancel" |

What the QR carries: `handover://connect?host=<ip>&port=8000&name=<hub name>` (and `&https=8443` when certs exist). **Needs hub**: the hub page that shows this code (PLAN lists QR pairing as cut; the app side can ship first and also accept the plain `http://<ip>:8000` URL).

States:
- scanning: as above.
- found: frame shrinks to 86% with `panel`, `soft` haptic, announcement "Found <hub name>. Connecting." then Connecting.
- bad code: `error` haptic, frame shakes, glass capsule above the buttons: "That code is not a HandOver hub." Leaves after 3 s.
- no camera permission: dashed white 30% frame with a `qrcode` symbol, text "HandOver cannot use the camera. Allow it in Settings, or enter the address." Button "Open Settings" (secondary, large).
- no camera (Simulator, Mac without camera): text "No camera here. Enter the address instead."

### 3.2 Typed address

Navigation title "Enter Address" (inline). A grouped form.

| Element | Copy |
|---|---|
| Field label (section header) | "Hub address" |
| Placeholder (`code` type) | "192.168.1.20:8000" |
| Footer | "Find it on the hub computer. HandOver uses port 8000 unless you set another." |
| Primary, full width | "Connect" (disabled until the field parses as host or host:port) |

Parsing: accepts `192.168.1.20`, `192.168.1.20:8000`, `http://...`, `https://...:8443`, `hub.local`. Missing port means 8000. Missing scheme means http.

### 3.3 Connecting and result

Same screen family as Vibeflux pairing progress views.

| State | Symbol | Title | Message | Actions |
|---|---|---|---|---|
| connecting | spinner | "Connecting to <host>" | "Checking that a HandOver hub is there." | Cancel (quiet) |
| connected | `checkmark.circle.fill` good, bounce | "Connected to <hub name>" | "<n> lessons on this hub." or "No lessons on this hub yet." | closes itself after 1.2 s (Vibeflux) |
| not a hub | `questionmark.circle` caution | "No hub at that address" | "Something answered, but it is not HandOver. Check the address and port." | "Try Again" primary, "Edit Address" secondary |
| unreachable | `wifi.exclamationmark` caution | "Cannot reach <host>" | "Make sure this device and the hub are on the same Wi-Fi, and that the hub is running." | "Try Again", "Edit Address" |
| local network denied (iOS) | `lock` caution | "Local network is off for HandOver" | "Turn on Local Network for HandOver in Settings > Privacy & Security > Local Network." | "Open Settings" |

Check performed: `GET /api/lessons` returns a JSON array, or `GET /` returns `{"app":"HandOver",...}` or the web app. Hub name: **Needs hub** (a name in `/api/health`); until then the host is the name.

Haptics: `success` on connected, `error` on failure.

### 3.4 Recent hubs

Shown above the field on Typed address and as a section in Settings, Hub. List rows (DESIGN 3.10, hub row).

| Element | Copy |
|---|---|
| Section header | "Recent" |
| Row subtitle | "Connected" (current) / "Last connected <relative time>" |
| Swipe action | "Remove" (destructive) |
| Confirm dialog title | "Remove <hub name>?" |
| Confirm message | "This device forgets the address. Your lessons stay on the hub." |
| Confirm button | "Remove" |

Up to 5 hubs, newest first. Tap connects.

---

## 4. Sign in and accounts

**Needs hub** for all of section 4: accounts, sessions, roles, device approval and progress storage do not exist in `CONTRACT.md`. When a hub reports no accounts, the app skips this section entirely and works as today (one shared session).

### 4.1 Sign in

Shown after connecting when the hub requires accounts. Sheet on iPhone (large detent), centered card elsewhere.

| Element | Copy |
|---|---|
| Title | "Sign In to <hub name>" |
| Field label | "Name" |
| Field label | "Passcode" (secure, number pad allowed, 4 to 12 characters) |
| Primary | "Sign In" |
| Divider text | "or" |
| Secondary | "Ask the Hub Owner" |
| Footer | "Passcodes stay on this hub. HandOver has no cloud account." |

States: wrong passcode: field shakes, `error` haptic, text under the field in `bad`: "That name and passcode do not match." Too many tries: "Too many tries. Wait a minute, then try again." (no countdown estimate; the button re-enables when the hub allows).

### 4.2 Waiting for approval

After Ask the Hub Owner. Symbol `person.badge.clock`, title "Waiting for approval", message "Ask the person who runs this hub to approve <device name> in HandOver on the hub computer." Spinner with "Waiting for the hub". Button "Cancel". On approval: `success`, "Approved", closes. On decline: "The hub owner declined this device." Button "OK".

### 4.3 Profile

Tab on iPhone and Android, sidebar item elsewhere. Navigation title "Profile".

Sections:
1. Header card: initials circle 56 pt (`accentSoft` fill, `accentInk` letters), name (`title`), "Learner" / "Editor" / "Owner" badge, hub name (`callout`, `ink2`).
2. "Progress" (only real events; **Needs hub** for history across devices):
   - Stat row of up to three: "Lessons done" <n>, "Steps checked by camera" <n>, "Mistakes caught" <n>. Numbers in `numeral`.
   - Empty: symbol `chart.bar`, title "No progress yet", message "Finish a lesson and your results show up here."
3. "Completed" list: lesson rows with trailing "You 3:40, Expert 2:55" or "You 3:40" when the expert total is unknown. Tap opens that run's Done summary (read only).
4. "In Progress" list with progress rings; tap continues.
5. Buttons: "Sign Out" (destructive, with confirm "Sign out of <hub name>?", message "Your progress stays on the hub.").

No accounts on the hub: Profile shows only "This device" progress kept locally, with the footer "Progress is kept on this device because the hub has no accounts."

---

## 5. Library

Navigation title "Library" (large). Data: `GET /api/lessons` (id, title, step count). Cover, duration, description, visibility and owner are **Needs hub** fields; until then cover is the first step's `frames/01.jpg` and duration is the last step's `end` from the lesson file.

**Layout**
- Search field in the navigation bar drawer: placeholder "Search lessons".
- Filter segmented control under it: "Everyone", "Mine", "Shared with Me" (Mine and Shared need accounts; hidden without them).
- "Continue" section (only when there are in-progress lessons on this device or account): horizontal row of cards 260 x 200 on iPhone, grid on iPad and Mac. Card: cover 16:9 on `stage`, `card` radius; title (`headline`, 2 lines); meta "Step 4 of 8"; progress ring 28 pt top right over the cover in a glass circle. Tap: opens Learn at the saved step (sends `select_lesson` then `goto`).
- "All Lessons" section: iPhone list rows (DESIGN 3.10 lesson row); iPad grid of cards 3 to 4 columns; Mac grid with adjustable size. Card: cover, title, meta "<n> steps, <m:ss>", a "Draft" or "Unlisted" badge for owners. Completed: `checkmark.circle.fill` good on the cover corner.
- Pull to refresh (iOS, Android); Command R on Mac.

Context menu on a lesson (long press, right click): "Start", "Lesson Details", for editors "Edit", "Insights", for owners "Delete Lesson" (destructive, confirm "Delete <title>?", message "This removes the lesson and its clips from the hub. Learners lose access.", button "Delete Lesson"; sends `DELETE /api/lessons/{id}`).

States

| State | Symbol | Title | Message | Action |
|---|---|---|---|---|
| loading (after 0.5 s) | spinner | "Loading lessons" | | |
| no lessons, can teach | `film.stack` | "No lessons yet" | "Record a task once and HandOver turns it into steps." | "Make a Lesson" (primary, goes to Teach) |
| no lessons, learner | `film.stack` | "No lessons yet" | "When someone shares a lesson on this hub, it shows up here." | |
| no search results | `magnifyingglass` | "No results for \"<query>\"" | "Check the spelling or try fewer words." | |
| hub unreachable | see section 18 | | | |

---

## 6. Lesson detail and course view

Push from Library. Navigation title inline: lesson title.

**Layout (iPhone)**: scroll view.
1. Cover 16:9 on `stage`, `card` radius, inset `l`.
2. Title (`display`), description (`body`, `ink2`, up to 4 lines with "More"). **Needs hub** for description.
3. Meta row (`callout`, `ink2`): "<n> steps", "<m:ss> expert time", "<k> checked by camera" (count of `check_type == camera`). Separated by `s` spacing and small dots in `ink3`, not dashes.
4. Safety and tools, when present (`safety`, `tools` in lesson.json): a card "Before you start" with `exclamationmark.shield` rows for each safety line and a "Tools" line listing tools comma separated.
5. Primary large button: "Start Lesson", or "Continue at Step <n>" with secondary "Start Over" beside it.
6. Course view: section header "Steps" with progress ring and "<d> of <n> done" (DESIGN 3.20, 3.21). Rows per step with status from this device's latest run.
7. Rating summary when there are ratings: star row read only, "4.6 from 12 ratings". **Needs hub**.

iPad and Mac: two columns: cover, title, meta and Start on the left (360 wide); steps on the right.

Tap a step row: opens Learn at that step (`select_lesson`, then `goto`). If a run is in progress and the step is ahead of the current one: confirm "Skip to Step <n>?", message "Steps you skip are marked as skipped.", buttons "Skip" and "Cancel".

---

## 7. Learn

The core screen. Two videos at once: the expert's clip for the current step, and the learner's own camera.

### 7.1 Data and sockets

- On open: `select_lesson` (or keep the hub's current lesson if it matches), fetch `GET /api/lessons/{id}`, refetch when `rev` changes and add `?v=<rev>` to clip, caption and frame URLs (CONTRACT 5).
- The app always opens `/ws/ui` for `state`, `advance`, `mistake`, `error`, and to send `next` (`reason: "button"` or `"voice"`, with `from`), `back` (with `from`), `goto`, `dismiss_mistake`. **Needs hub (small)**: `/ws/ui?frames=0` so a phone that is also the camera does not download its own frames back.
- When this device is the camera, it also opens `/ws/camera`, sends `hello` (`platform: "ios"` or the platform, `source: "phone"` or `"glasses"`, `device_id`, `name`), and streams JPEG frames (section 10 rules). It shows its own camera preview locally at full frame rate, so the learner sees exactly what the laptop shows, only smoother.
- When another device is the camera, the live pane shows the binary frames from `/ws/ui`.
- Keep the screen awake while Learn is open.

### 7.2 Regions (all layouts)

1. Step progress bar (DESIGN 3.3), full width at the very top under the safe area.
2. Top bar: Close (`xmark`, glass on video layouts, plain elsewhere, VoiceOver "Close lesson"), lesson title (`headline`, 1 line), Steps button (`list.bullet`, VoiceOver "Steps"), More menu (`ellipsis.circle`): "Captions" toggle, "Mute Clip" toggle, "Voice Next" toggle, "Swap Videos", "Restart Lesson".
3. Expert clip pane (DESIGN 3.4).
4. Live view pane (DESIGN 3.5), or PiP tile (DESIGN 3.6).
5. Step info: "Step 4 of 8" (`footnote`, `ink2`), step title (`stepTitle`, up to 3 lines).
6. Mistake card slot (DESIGN 3.2), directly above the controls.
7. Controls tray: status badge with its meta line on the left; Back and Next on the right (Next is primary).

Close confirm (only when the run is mid-lesson): "Leave this lesson?", message "Your place is saved on this device.", buttons "Leave" and "Keep Going".

### 7.3 iPhone portrait

```
+----------------------------------+
| ==== ==== ==== ---- ---- ----    |  progress bar
| (x)   Fold a fortune teller  (=) |  top bar
| +------------------------------+ |
| |                              | |
| |       EXPERT CLIP (large)    | |  aspect fit, black
| |                    +-------+ | |
| |                    | YOU   | | |  PiP, draggable, tap to swap
| |   caption line     +-------+ | |
| +------------------------------+ |
| Step 4 of 8                      |
| Flip it over and fold the        |
| corners to the center            |
| +------------------------------+ |
| | ! Flip it over first.        | |  mistake card (when present)
| |   [Show Step 3]   [I'm Fine] | |
| +------------------------------+ |
| (o) Watching   [ < ] [  Next  ]  |  controls tray, bottom third
+----------------------------------+
```

- The clip pane takes the width minus `l` margins and as much height as is left after step info and controls, never less than 40% of the screen height. With a mistake card shown, the pane shrinks with `layout` rather than covering the card.
- PiP starts bottom right of the clip pane. Tap swaps (the learner's camera becomes large, the clip becomes the tile). Drag to any corner of the large pane.
- One hand: Next is a large primary button at the bottom right, 52 tall, at least half the width. Back is a 52 x 52 secondary square with `chevron.left`, VoiceOver "Back". Badge sits at the bottom left. The mistake card's buttons sit in the lower half too. Nothing the learner needs during a step is in the top half except Close.
- Captions sit at the bottom of whichever pane shows the clip. When the clip is the tile, captions move below the large pane as a caption bar on `stage`, full width, so they stay readable.
- Reachability: the Steps button also appears as a swipe up from the step info (sheet).

### 7.4 iPhone landscape

```
+--------------------------------------------------------------+
| ==== ==== ==== ---- ---- ----                                |
| +---------------------------+  +---------------------------+ |
| |                           |  |                           | |
| |       YOUR CAMERA         |  |       EXPERT CLIP         | |
| |                           |  |      caption line         | |
| +---------------------------+  +---------------------------+ |
| (x) Step 4 of 8: Flip it over...   (o) Watching  [<] [Next]  |
+--------------------------------------------------------------+
```

- Two equal panes side by side, gap `m`, live on the left and clip on the right (same order as the web app, `Learn.tsx`). Swap Videos in the More menu flips the order and is remembered.
- One row under them: Close, step count and title on one line (truncates at a word), badge, Back, Next. Next stays at the trailing edge under the right thumb.
- Mistake card floats over the bottom of the clip pane as a glass panel (dark scheme) with the same content, so the panes do not jump.
- No PiP in landscape.
- At accessibility type sizes the controls row wraps to two rows and the panes shrink.

### 7.5 iPad

- Full screen or wide Split View (700 pt and up): side by side like iPhone landscape, panes up to 16:9 each, the step info and controls in a band under them. The sidebar can show the course view (DESIGN 3.20) on the leading side when toggled with the Steps button; at 1100 pt and up it is open by default.
- Narrow Split View and Slide Over: iPhone portrait layout with PiP.
- Pointer: hover shows clip controls; Next shows a hover highlight.
- Keyboard: Right Arrow or Space Next, Left Arrow Back, R replay, M mute, C captions, S swap.

### 7.6 Mac

- Window with a collapsible sidebar listing the steps (course view rows, compact: number, title, status symbol). Detail: live and clip side by side at equal width, gap `l`, step info and controls under them. Window minimum 900 x 600; below 1000 wide the sidebar collapses.
- Toolbar: sidebar toggle, lesson title, status badge (toolbar item), spacer, Voice Next (`mic`, toggles, VoiceOver "Voice Next"), Captions (`captions.bubble`), Swap (`arrow.left.arrow.right`).
- Hint under Next: "or press Right Arrow" (or "or say next" while Voice Next listens).
- The Mac is usually the big screen in the room. Defaults there: Captions Large, clip audible.

### 7.7 Android and Windows

Android follows iPhone and iPad layouts exactly, with Material components (DESIGN 6.4). Windows follows Mac (DESIGN 6.5).

### 7.8 Status badge and meta copy

| Condition | Badge | Meta line (`footnote`, `ink2`) |
|---|---|---|
| watching, camera live | "Watching" | "Last check 0.9 s" (from `last_check.latency_ms`), and below it the reason when allowed, e.g. "seams still facing up" |
| checking | "Checking" | same as above |
| verified | "Verified" | none |
| manual step | "Tap Next when done" | none |
| done | "Done" | none |
| checks off, `no_key` | "Checks off, use Next" | "No check key on the hub." |
| checks off, `rate_limited` | "Checks off, use Next" | "Too many checks. Trying again soon." |
| checks off, `errors` | "Checks off, use Next" | "Checks failed. Trying again soon." |
| checks off, `budget` | "Checks off, use Next" | "Check spending limit reached." |
| simulated | "Simulated checks" | "Test mode. Steps pass on a timer." (**Needs hub**: check mode in state) |
| camera step, no camera | "No camera" | "Connect a camera to check steps." |

"Trying again soon" is honest: the breaker retries after `HANDOVER_BREAKER_SECONDS`; it states no duration.

### 7.9 Mistake card copy

| Kind | Message | Buttons |
|---|---|---|
| behind | hub text, e.g. "Flip it over first." or "This still looks like step 3." | "Show Step <looks_like + 1>", "I'm Fine" |
| ahead | "You're ahead." | "OK" |

"I'm Fine" sends `dismiss_mistake`. "Show Step N" sends `goto` with `looks_like`. The card is spoken aloud only when Settings, Learn, Speak Mistakes is on (default on for Mac, off for iPhone). `warning` haptic once.

### 7.10 Step result moment

DESIGN 3.19. Shown after every forward step change by camera or Next. 1.5 s, non-blocking.

| Case | Symbol | Copy |
|---|---|---|
| your time under 90% of expert | `hare` | "Nice. <t>, faster than the expert." |
| within 10% of expert | `checkmark` | "Done. <t>, about the expert's time." |
| slower | `checkmark` | "Done in <t>." |
| one or more mistakes fixed on this step | `checkmark` | "Done. <k> mistake fixed." / "Done. <k> mistakes fixed." (replaces the time line) |
| verified by camera, no time available | `checkmark.circle` | "Verified." |
| by Next, no time available | `checkmark` | "Done." |

`<t>` is "12 s" under a minute, else "1:05" (same formatting as `formatSecs` in `Learn.tsx`). "Mistake fixed" means a `behind` mistake was raised on this step and the step was then finished. Last step: no result moment; Done takes over.

### 7.11 Steps sheet (iPhone)

Opened by the Steps button or a swipe up on the step info. Medium and large detents. Title "Steps", Done button. Content: course view (DESIGN 3.20) for this run. Tap a row: `goto` (with the skip confirm when moving forward past unfinished steps), sheet closes.

### 7.12 States

| State | What shows |
|---|---|
| loading lesson | progress bar with one `well` segment, both panes black with spinners after 0.5 s |
| hub reconnecting | banner "Reconnecting to the hub." under the top bar, live pane shows the placeholder (never a frozen frame), clip keeps looping from cache, Next and Back disabled with VoiceOver hint "Waiting for the hub" |
| hub came back with no lesson | the app re-sends `select_lesson` once per connection (as `Learn.tsx` does); if that fails, the lesson picker sheet "Pick a lesson" with the Library list |
| replaced on another device | when `/ws/camera` closes with 4000: banner "Another device took over as the camera." Do not reconnect |
| camera lost | live pane dims the last frame with "Camera lost. Keep going with Next." |
| recording source | "Recording" chip in caution on the live pane |
| server error | toast with the hub text (e.g. "no lesson selected"), 4 s |

### 7.13 Transitions

- Step change: clip cross-fades (0.2 s); step title cross-fades; progress segment fills with `layout`; the result moment shows; haptic per DESIGN 4.
- Verified: badge turns good with the symbol bounce, holds while the hub holds `verified`, plus the client's 1.8 s flash after a camera `advance` (`Learn.tsx`), then the step changes.
- Done: when `status == done`, the clip pauses on its last frame and Done slides up as a full screen (sheet style on iPad and Mac) with `panel`.

---

## 8. Done

Every number on this screen comes from real events in this run: `advance` messages (from, to, reason), `state` changes with times measured on this device, and `mistake` messages. Rules in section 20. Missing data shows "Not enough data", never a made-up value.

**Layout (iPhone)**: scroll view on `paper`.

1. Score ring (DESIGN 3.21), centered. Under it the title (`display`): "Lesson complete". Under that (`callout`, `ink2`): the lesson title.
2. Stat row, three columns, `numeral` values with `caption` labels in `ink2`:
   - "Your time" <m:ss>. Missing: "Not enough data".
   - "Expert" <m:ss> (sum of step lengths).
   - "Checked by camera" <c of n>.
   Second row: "Marked done" <h>, "Mistakes caught" <k>, "Skipped" <s> (only when s > 0).
3. Best and weakest: two cards side by side (stacked at accessibility sizes).
   - "Best step": "Step <n>. <title>" and the reason, e.g. "Checked by camera in 9 s." 
   - "Practice this": "Step <n>. <title>" and the reason, e.g. "2 mistakes, 1:40 against 0:35."
   Shown only when at least 2 steps have complete data; otherwise one card "Not enough data to compare steps."
4. Tip card (`lightbulb` symbol, `raised`): one concrete sentence picked by rule (section 20.4).
5. "Steps" breakdown: one row per step: number, title (1 line), time bar (DESIGN 3.22), how it was completed (symbol and word from DESIGN 3.20), and "<k> mistakes" in `caution` when k > 0. Tap a row: "Practice Step <n>" action sheet.
6. Buttons: primary "Practice the Weakest Step" (sends `select_lesson` then `goto` to that step, starts a practice run that ends when that step is finished, then returns to this screen with that step's new result); secondary "Start Over" (`goto` 0, resets the run). Quiet "Back to Library".

iPad and Mac: two columns: score, stats, best and weakest, tip and buttons on the left (380 wide); breakdown on the right.

Score label copy:

| Score | Label | Ring tone |
|---|---|---|
| 85 to 100 | "Excellent" | good |
| 60 to 84 | "Good" | accent |
| 0 to 59 | "Keep practicing" | caution |
| not computable | "Not enough data" | track only, no number |

States: practice run return: a toast "Step <n>: <new time>, <how>." Hub disconnected while on Done: the summary stays (it is frozen at the moment of finishing, as `Learn.tsx` does), buttons disabled until reconnected.

Saving: the run summary is stored on the device. **Needs hub** for storing it per account and for Insights (learn events exist on the hub, proposal P26, but there is no read API).

After Done appears and the learner scrolls or 2 s pass, the rating prompt (section 9) slides up once.

---

## 9. Rate this course

Offered once per lesson per person, after Done. Skippable. Editable later from Lesson detail. **Needs hub** to store and read ratings.

Sheet, medium detent.

| Element | Copy |
|---|---|
| Title | "Rate this lesson" |
| Stars (DESIGN 3.23) | VoiceOver "Rating, <n> of 5 stars" |
| Field placeholder (optional, 500 characters) | "What helped or got in the way? (optional)" |
| Primary (enabled after a star is set) | "Send" |
| Quiet | "Not Now" |
| Footer | "The lesson's owner sees your rating and comment with your name." (without accounts: "with no name") |

After Send: toast "Thanks. Rating sent." `success` haptic. Not Now: never asked again for this lesson; Lesson detail shows "Rate This Lesson" (quiet) instead. Editing: Lesson detail shows "Your rating" with stars and "Edit".

---

## 10. Camera mode

The phone as the learner's camera, pointed at the work. From Learn (when no camera is connected the live pane offers "Use This iPhone") or Library toolbar "Be the Camera" (`video.circle`).

**Layout (iPhone, portrait or landscape)**: full-bleed camera preview, forced dark, aspect fill for the preview but a thin white 30% frame shows the exact area sent (aspect fit of the sent JPEG).

Top, glass capsules:
- Capture indicator: red `record` dot plus "Sending to <hub name>" while frames flow; "Paused" with a gray dot when not sending.
- Stats chip (tap to show or hide): "<f> fps, <w> x <h>" measured from frames actually sent in the last 5 s, and "Active camera" or "Standby" from `camera_status`.
- Source chip: `iphone` "iPhone back camera" / "iPhone front camera" / `eyeglasses` "Glasses". Tap opens the source menu.

Bottom, glass panel:
- Step title from the `state` the hub sends after hello: "Step 4 of 8: Flip it over" (2 lines).
- Status badge (same states as Learn).
- Next (primary glass prominent, large) and Back. They send `next` and `back` on `/ws/camera` with `from`.
- Lock button (`lock`): hides controls to stop accidental taps; tap and hold 1 s to unlock, VoiceOver "Unlock, double tap and hold".

Frame rules: about 1 frame per second (CONTRACT 6), long side 1280, JPEG quality 0.7, under 2 MB; never faster than 5 per second (proposal P16). Never mirrored. Frames are never saved on the phone.

States

| State | Copy |
|---|---|
| connecting | capsule "Connecting to <hub name>" with spinner |
| active | "Sending to <hub name>", stats "1.0 fps, 1280 x 720, Active camera" |
| standby (another camera active) | capsule "Standby", banner "Another camera is active. This one takes over if it stops." |
| replaced (close 4000) | full panel: `iphone.slash`, "Another device took over", "This iPhone stopped sending. Tap to send again.", button "Send Again" |
| no lesson | step area "No lesson started", hint "Start a lesson on any screen connected to this hub." |
| hub lost | capsule caution "Reconnecting", frames paused |
| thermal serious (iOS `thermalState >= .serious`) | banner "iPhone is warm. Sending fewer frames." and the rate drops to 0.5 fps |
| low power mode | banner "Low Power Mode is on. The screen dims to save power." |

Screen stays awake; after 30 s without touches it dims to 30% brightness (camera keeps running), any touch restores. Moving the app to the background stops sending (glasses frames only arrive in the foreground per the DAT notes); coming back resumes and re-sends hello.

Haptics: `success` when the hub verifies a step (from the `advance` with reason `camera`), `warning` on a mistake. The learner may not be holding the phone; the screen also flashes the badge.

---

## 11. Teach home

Tab "Teach" on iPhone and Android. Navigation title "Teach" (large). Only for editors and owners on hubs with accounts.

1. Three big option cards (stacked on iPhone, row of three on iPad and Mac). Each: symbol tile 44, title, one line.
   - `record.circle` "Record a Take": "Use this iPhone or your Ray-Ban Meta glasses. Talk through each step."
   - `photo.on.rectangle` "Choose from Photos": "Pick a video you already recorded."
   - `folder` "Choose from Files": "Pick a video from Files or a drive."
   On Mac: "Record a Take" (built-in or Continuity Camera), "Choose a File" (also accepts drag and drop onto the window: "Drop a video to make a lesson"), no Photos card unless Photos access is granted.
2. "Your Lessons" list: lesson rows with status badges "Draft", "Published", "Unlisted", "Processing" (spinner). Tap opens the course editor (Processing opens the processing view).
3. Empty: symbol `video.badge.plus`, "No lessons yet", "Record a task once while you talk through it. HandOver cuts it into steps."

Upload after picking (Photos or Files):
- Title sheet: field "Title" prefilled from the file name (`Teach.tsx` does the same), placeholder "Fold a fortune teller"; footer "One video of the whole task works best. Talk through each step as you do it." Primary "Make Course".
- Upload progress replaces the sheet content: file name, size ("214.3 MB"), a determinate bar from bytes sent, "Uploading <p>%", and Cancel. Errors from the hub shown verbatim, e.g. "video is larger than 2 GB", "too many jobs" (as "The hub is busy with other lessons. Try again when one finishes."), "lesson id already exists".
- Then the processing view (section 13).

---

## 12. Record a take

Native Camera app feel. Full screen cover, forced dark.

### 12.1 Layout (iPhone portrait; landscape rotates controls like the Camera app)

```
+----------------------------------+
| (x)      [ 00:42 ]        (bolt) |  close, timer pill, more
|           ||||||||                |  narration waveform
|                                  |
|          CAMERA PREVIEW          |
|      (phone camera or glasses)   |
|                                  |
| [ Glasses card, when relevant ]  |
|                                  |
|   [ iPhone | Glasses ]           |  source switcher
|                                  |
|  (thumb)     ( O )     (flip)    |  last take, shutter, flip camera
+----------------------------------+
```

- Preview: aspect fill on iPhone camera, aspect fit with `stage` bars for glasses (their frame is portrait 9:16 at low resolution per the DAT notes; never stretched).
- Close (`xmark`, glass, VoiceOver "Close"). While recording, Close asks "Stop and discard this take?" with "Discard" and "Keep Recording".
- Timer pill (DESIGN 3.9) appears when recording.
- Waveform under it (DESIGN 3.9) for the narration mic.
- Mic chip (glass, tap to change): `mic` "iPhone mic" or `eyeglasses` "Glasses mic" (when the glasses are connected as a Bluetooth audio input), from the current audio route.
- Source switcher (DESIGN 3.15): "iPhone" (`iphone`), "Glasses" (`eyeglasses`). Disabled while recording.
- Bottom row: last take thumbnail (opens the takes list for this session), shutter (DESIGN 3.8), flip camera (`arrow.triangle.2.circlepath.camera`, iPhone source only; hidden for glasses).
- Hint before the first recording (`footnote`, white 70%, above the switcher): "Say each step out loud as you do it. Pause between steps."

Recording rules:
- iPhone: 1080p at 30 fps, HEVC or H.264, audio AAC 48 kHz. The hub normalizes anyway (`server/docs/teach.md`).
- Glasses: frames from the DAT stream at the highest resolution and frame rate the SDK accepts (try 30 fps, then 24, then 15). The source chip shows what is actually arriving: "Glasses, <w> x <h>, <f> fps", measured, never the requested value. Frames are written with `AVAssetWriter` alongside the mic audio. The app must stay in front (DAT `.raw` frames stop in the background); the screen stays awake.
- Volume buttons start and stop. Haptics: heavy impact on start, medium on stop.
- On stop: shutter shows finishing, then a review sheet (12.4).

### 12.2 Glasses states

The glasses card (DESIGN 3.17) sits above the source switcher whenever Glasses is selected and the glasses are not streaming, and as a compact chip once streaming. Registration flow from `docs/RESEARCH_GLASSES_GEMINI.md` (DAT 1.0.1: `Wearables.configure`, `startRegistration`, the `handover://` callback, `registrationStateStream`, `devicesStream`, camera permission, session states idle, starting, started, paused, stopping, stopped).

| State | Card title and status | Action |
|---|---|---|
| not registered | "Ray-Ban Meta" / "Not connected to HandOver" and the line "HandOver asks the Meta AI app for access to your glasses camera." | primary "Connect Glasses" (starts registration, opens Meta AI) |
| Developer Mode off (registration fails with that cause) | "Turn on Developer Mode" / "In the Meta AI app: Settings > App Info, tap the version 5 times, then turn on Developer Mode." | "Open Meta AI", "Try Again" |
| waiting for Meta AI | "Waiting for Meta AI" / spinner "Approve HandOver in the Meta AI app." | "Cancel" |
| registered, no device | "Glasses not found" / "Put on your glasses and make sure they are connected to this iPhone." | "Try Again" |
| camera permission needed | "Allow camera access" / "The glasses need permission to share their camera with HandOver." | "Allow" |
| connecting (session starting) | "Connecting" / spinner | |
| streaming | compact chip "Glasses, 720 x 1280, 30 fps" with a good dot | |
| paused (session paused) | "Paused" / "The glasses paused the camera." | "Resume" |
| battery low (`StreamError.batteryLow`) | "Glasses battery low" / "Charge the glasses or switch to the iPhone camera." | "Use iPhone" |
| too hot (`StreamError.thermalHot`) | "Glasses too hot" / "Let them cool down, or switch to the iPhone camera." | "Use iPhone" |
| power limit (`StreamError.peakPowerLimit`) | "Glasses need a break" / "They hit a power limit. Try again, or switch to the iPhone camera." | "Try Again", "Use iPhone" |
| stream lost | "Glasses disconnected" | "Reconnect", "Use iPhone" |

Battery percentage and temperature meters appear only if the SDK reports values; otherwise only the error states above show (DESIGN 3.17).

Fallback during a recording: if the glasses stream fails while recording, the app keeps the take so far, shows a banner "Glasses stopped. Recording paused.", and offers "Continue on iPhone" (records the rest as a second part, joined in order; the hub supports several files joined with `--concat`, **Needs hub** for multi-file upload over HTTP) or "Stop". It never switches cameras silently.

### 12.3 Permissions

| Missing | Copy | Action |
|---|---|---|
| camera | "HandOver needs the camera to record a take." | "Open Settings" |
| microphone | "HandOver needs the microphone to record your narration. Steps are found from what you say." | "Open Settings", "Record Without Sound" (shows a warning: "Without narration, HandOver can only guess the steps.") |
| Bluetooth (glasses) | "Allow Bluetooth so HandOver can reach your glasses." | "Open Settings" |

### 12.4 Review take

Sheet over the recorder. Plays the take (system player). Title field (prefilled "Lesson <date>"). Buttons: primary "Make Course", secondary "Record Again" (discards after confirm "Discard this take?"), quiet "Save to Photos". Takes list (from the thumbnail): each take with duration, a checkbox to include, reorder handles; "Make Course" with several selected joins them in order (**Needs hub** multi-file).

---

## 13. Make course (processing)

After upload. Honest per-stage progress: a stage only shows as done when the hub says so; a percentage only shows when the hub reports one.

**Layout**: centered column on iPhone, card 520 wide elsewhere. Title (`title`): the lesson title. Under it the stage list:

| Stage (hub `status`) | Row text while active | Done text |
|---|---|---|
| upload (client) | "Uploading <p>%" | "Uploaded" |
| `queued` | "Waiting for the hub" | |
| `normalizing` | "Preparing video" | "Video prepared" |
| `transcribing` (**Needs hub**) | "Transcribing narration" | "Narration transcribed" |
| `extracting` | "Finding steps" | "<n> steps found" (from the finished lesson) |
| `cutting` | "Cutting clips" | "Clips cut" |
| `voiceover` (**Needs hub**) | "Writing voiceover" | "Voiceover added" or "No voiceover needed" |
| `done` | | |

Rows: status symbol (spinner when active, `checkmark.circle.fill` good when done, `circle` `ink3` when not reached), text (`body`), optional determinate bar when the hub sends progress. The hub today reports only `queued`, `normalizing`, `extracting`, `cutting`, `done`, `error` plus a free `message`; until it reports more, the app shows only those rows, and shows the hub's `message` under the active row in `footnote` `ink2` when it is not empty. No invented percentages, no time estimate.

Footer: "You can leave this screen. The hub keeps working." Button "Done" (closes; the lesson shows as Processing in Teach).

Finished: `success` haptic, title "Your lesson is ready", buttons primary "Review Steps" (opens the editor), secondary "Try It as a Learner" (opens Learn).

Errors:
- job `error`: `error` haptic, the stage row turns `bad` with `xmark.circle.fill`, message the hub's text verbatim, buttons "Try Again" (re-uploads) and "Done".
- job not found (404, the hub restarted): "The hub restarted and lost this job. Upload the video again." (copy from `Teach.tsx`).
- lost contact for 30 polls: "Lost contact with the hub. Check that it is running, then upload again." (`Teach.tsx`).

---

## 14. Course editor

iPad and Mac first-class, iPhone usable. Opens from Teach, Library (Edit) or the processing view.

Saved data: lesson.json via recut (`POST /api/lessons/{id}/recut` with a full lesson object). Recut keeps unknown fields under the planned rule (proposal P7). Captions editing, per-step voiceover, cover, description, split, merge, reorder, self-test per question, drafts and autosave need hub support; each is marked.

### 14.1 Layout

**Mac and iPad (three columns)**
- Left: step list (DESIGN 3.10 step row), 280 wide. Footer buttons: "Split" (`scissors`), "Merge" (`arrow.triangle.merge`), "Delete" (`trash`).
- Center: player (the full video, or the selected step's clip with captions) on `stage`, and the timeline (DESIGN 3.18) under it, full width of the column. Under the timeline, a transcript strip showing sentences as chips aligned to time; the chip under the playhead is highlighted.
- Right: inspector for the selected step, 320 wide, in grouped sections.
- Toolbar: Undo (`arrow.uturn.backward`), Redo (`arrow.uturn.forward`), draft status, "Preview" (opens Learn on this lesson), "Publish" (primary).

**iPhone**
- Top: player 16:9. Under it the timeline. Under that the step list. Tapping a step opens the inspector as a sheet (large detent). Toolbar: Undo, Redo, More (Preview, Lesson Details, Delete Lesson), Publish (primary text button).
- Boundary dragging works with one finger on the 20 pt grips; the track zooms with pinch.

### 14.2 Lesson details

Mac: a "Details" section above the step list (or a sheet from More on iPhone). **Needs hub** for cover and description.

| Field | Copy |
|---|---|
| Cover | image well 16:9, "Choose Cover", menu: "Use a Step Frame" (grid of `frames/NN.jpg`), "Choose Photo", "Remove" |
| Title | "Title", placeholder "Fold a fortune teller" |
| Description | "Description", placeholder "What learners will make, and what they need." (300 characters) |
| Safety | list of lines, "Add Safety Note" (from `safety`) |
| Tools | list, "Add Tool" (from `tools`) |

### 14.3 Step inspector

Sections in order:

1. **Title**: field "Step title", placeholder "Fold the corners to the center". Footer "Short and doable. Start with a verb."
2. **Time**: "Start" and "End" (`MM:SS.s`, monospaced), stepper buttons of 0.1 s; "Length 0:21". Changes here move the timeline boundaries and vice versa.
3. **How it is checked**: segmented "Camera" (`viewfinder`) / "Manual" (`hand.tap`). Step 1 shows a note when Camera: "Step 1 is often better as Manual: the camera has nothing to compare to yet."
   - Camera: field "Check question", placeholder "Is the paper folded into a small square with four flaps?", footer "Ask about shape and folds you can see, not color." (M8 guidance).
   - Reference frame: the `frames/NN.jpg` image with "Change Frame" (scrub within the step to pick; writes `ref_time`).
   - **Test This Question** (secondary, `checkmark.seal`): runs the self-test for this step (**Needs hub**: an HTTP endpoint for the CLI `--self-test` per step). Result card with two rows:
     - "On this step's frame" with "Yes" in good or "No" or "Unsure" in caution. Expected: Yes.
     - "On the previous step's frame" with the answer. Expected: No.
     - Summary: "Works. The question tells this step apart." (both as expected) or "Might misfire. Try a more specific question, or make this step Manual." with a quiet button "Make Manual". If the result came from mock checks, a caution line: "Simulated check. This result does not test the question."
     - Stored result from the lesson (`self_test`) shows on open with "Last tested" and its answers.
4. **Common mistake**: field "What do people get wrong here?", placeholder "Flip it over first.", footer "Shown and spoken when the learner is still on the step before." (`common_mistake`).
5. **Captions**: list of cues for this step: time (monospaced) and text field each. "Add Line" at the playhead; swipe to delete. Footer "Captions show under the expert's clip." **Needs hub** (write `captions/NN.vtt`).
6. **Voiceover**: status "Voiceover on" / "Original sound". Voice picker (menu of the hub's Kokoro voices, default "af_heart" shown by its readable name). Buttons "Regenerate" (rewrites and re-speaks this step), "Remove" (back to the original audio; the hub keeps originals for undo, `server/voice.py`). **Needs hub** per-step HTTP control and a voice list endpoint (today voiceover runs per lesson from the CLI).
7. **Delete Step** (destructive) with confirm "Delete Step <n>?", message "Its time joins the step before it." (so the video stays contiguous, as teach requires).

### 14.4 Timeline editing

- Drag a boundary: the two neighbors resize; snaps to transcript sentence edges within 0.4 s with a `tap` haptic; free placement with Option held (Mac) or a two-finger drag (touch). A floating label shows the time "01:14.5" while dragging.
- Split: at the playhead, "Split" makes two steps; the new step gets the title "<title> (2)" selected for renaming and copies the check type. Disabled when either part would be under 0.5 s; tooltip "Too short to split here."
- Merge: the selected step with the next one; keeps the first title and check question. Confirm only when both have different questions: "Merge Steps <n> and <n+1>?" message "Step <n>'s question is kept." **Needs hub**: none beyond recut (the client edits steps and sends the full lesson).
- Reorder: hidden. Steps must stay contiguous in the video (teach cleans them to contiguous spans), so reordering would scramble the clip timeline. The step list shows no drag handles. If reordering is ever supported, it needs non-contiguous spans on the hub.
- Rename: double click (Mac), or the title field.
- Every change is one undo step. Undo and Redo: Command Z, Shift Command Z, toolbar buttons, and three-finger swipe on iPad and iPhone (system).

### 14.5 Draft and autosave

- Edits save locally at once and to the hub 1 s after the last change (recut). **Needs hub**: a draft copy separate from the published lesson; until then every save changes the live lesson and the indicator says so.
- Indicator in the toolbar (`footnote`, `ink2`): "Saving", "Saved", "Saved on this device only" (hub unreachable; retries when back), "Could not save" in `bad` with "Try Again".
- Recut takes a while for long lessons; while it runs, the timeline is read only and the indicator reads "Updating clips". Errors from recut are shown verbatim in a banner (e.g. "step 3: bad timestamp: '01:7x'").

---

## 15. Publish and access

**Needs hub** for all of section 15 (visibility, access lists, roles, publish state).

### 15.1 States

| State | Badge | Meaning |
|---|---|---|
| Draft | "Draft" (neutral) | Only the owner and editors see it |
| Published | "Published" (good) | Visible to its audience in Library |
| Unlisted | "Unlisted" (neutral, `link` symbol) | Not in Library; opens by link or QR only |

### 15.2 Publish sheet

From the editor's Publish button. Medium detent on iPhone, form sheet elsewhere.

| Element | Copy |
|---|---|
| Title | "Publish <title>" |
| Section | "Who can find it" |
| Options (radio rows) | "Only Me", "People with Access", "Everyone on This Hub" |
| Toggle | "Unlisted" with footer "Not shown in Library. Share the link instead." |
| Checklist (read only, from the lesson) | "<n> steps", "<c> checked by camera", "<m> manual", warnings in caution: "Step <n> has no check question.", "Step <n> failed its test." (from `self_test.ok == false`) |
| Primary | "Publish" (or "Update" when already published) |
| Quiet | "Cancel" |

After publish: `success`, toast "Published". Unlisted shows a share row with "Copy Link" and "Show QR Code".

### 15.3 Access

From the publish sheet ("Manage Access") or the editor's More menu. Navigation title "Access".

- Field "Invite by name", placeholder "Name on this hub", suggestions from hub accounts; role menu next to it (Editor, Learner); "Invite".
- List of people: initials, name, role menu ("Owner", "Editor", "Learner"), swipe "Remove".
- Owner row cannot be removed; "Transfer Ownership" is a separate destructive action with confirm "Make <name> the owner?", message "You become an editor."
- Role meanings in the footer: "Owners publish and manage access. Editors change steps. Learners take the lesson."

---

## 16. Insights

For owners and editors. Per lesson. From learn events (proposal P26: `run_start`, `step_enter`, `check`, `advance`, `mistake`, `run_done`, `breaker`), and from the Databricks dashboard when configured. **Needs hub**: a read API over stored events, or a link out to the Databricks dashboard. Without it, this screen shows its empty state; it never shows sample numbers.

**Layout**: navigation title "Insights", subtitle the lesson title. Lesson picker (menu) in the toolbar.

1. Summary row (`numeral`): "Runs" <n>, "Finished" <f> (<p>%), "Median time" <m:ss> against "Expert" <m:ss>, "Rating" <4.6> with "<k> ratings".
2. "Where people get stuck": a bar list, one row per step: step number and title, a horizontal bar of median time on the step relative to the expert's time for that step, and the count of mistakes raised. The top 3 steps by median time over expert are marked with `exclamationmark.circle` caution and the label "Most time over the expert". Under each, "<x> of <runs> needed Next by hand" (manual advances on camera steps).
3. "Checks": share of camera steps verified by camera, median check latency (from `check.latency_ms`), times checks were off and why (from `breaker` events: "No key", "Rate limited", "Errors", "Spending limit").
4. "Comments": newest first: stars, comment, name (or "Someone" without accounts), relative date. "Show All".
5. Footer: "From <n> runs on this hub since <date>." and, when Databricks is configured, "Open Dashboard" (opens the AI/BI dashboard URL).

Minimum data: a step's numbers show only with 3 or more runs that reached it; otherwise "Not enough data" in its row. Ratings show average only with 1 or more rating, and always with the count.

Empty states

| Case | Symbol | Title | Message |
|---|---|---|---|
| no runs yet | `chart.bar.xaxis` | "No runs yet" | "When people take this lesson, you will see where they get stuck." |
| hub keeps no history | `externaldrive.badge.xmark` | "No history on this hub" | "This hub does not store learner events. Connect Databricks on the hub to keep them." |
| no ratings | (inline in Comments) | | "No ratings yet." |

---

## 17. Settings

Sheet from the gear on iPhone (pattern from Vibeflux `SettingsView.swift`), sidebar item on iPad, Settings window on Mac with tabs Hub, Appearance, Learn, Account, About. Navigation title "Settings". Rows use symbol tiles (`SettingsLabel`).

| Section | Row | Control and copy |
|---|---|---|
| Hub | current hub | hub row; tap opens Hub details: "Address" (monospaced, Copy), "Status" (dot and "Connected" / "Reconnecting"), "Checks" ("Camera checks" / "Simulated checks" / "Off: <reason>"), "Reconnect Now", "Remove This Hub" (destructive) |
| Hub | "Connect to Another Hub" | `qrcode.viewfinder` accent row, opens 3.1 |
| Hub | Recent | as 3.4 |
| Appearance | "Theme" | value: theme name; opens the picker (THEMES.md, Theme picker) |
| Appearance | "Appearance" | segmented System, Light, Dark; footer "Themes with one look keep it." |
| Learn | "Captions" | toggle, default on |
| Learn | "Caption Size" | menu Small, Medium, Large, Extra Large; live preview line on a black bar: "Fold the top corner down to meet the center." |
| Learn | "Voice Next" | toggle, default off; footer "Listens for \"next\" and \"back\" while a lesson is open. Ignores the expert's clip while it plays. Turn it off in a noisy room." |
| Learn | "Speak Mistakes" | toggle; footer "Reads the mistake card out loud." |
| Learn | "Step Results" | toggle, default on; footer "A short note after each step with your time." |
| Learn | "Haptics" | toggle, default on (iPhone and Android only) |
| Learn | "Keep Screen On" | toggle, default on |
| Camera | "Camera" | menu: Back, Front (iPhone); camera list on Mac |
| Camera | "Glasses" | row with status ("Connected", "Not connected") opening the glasses card (12.2) and "Disconnect Glasses" |
| Account | name, role | only with accounts; "Sign Out" |
| About | "Version" | e.g. "0.1.0" |
| About | "Privacy" | note row: "The hub never saves your camera frames. Checks send frames to the hub's check service and nothing is kept." (backed by M15 test in `docs/PLAN.md`; keep wording in sync with what the hub does) |
| About | "Open Source Licenses" | push |

Changing the theme redraws the app and reopens Settings at the picker (Vibeflux `RootView.reopenSettings`).

---

## 18. Errors and banners

Banners use DESIGN 3.12; one at a time, highest first.

| Condition | Where | Symbol, tone | Copy | Action |
|---|---|---|---|---|
| Hub unreachable on launch | full screen empty state | `wifi.exclamationmark`, caution | Title "Cannot reach the hub". Message "Make sure this device is on the same Wi-Fi as <hub name> and that HandOver is running there." | "Try Again" (primary), "Change Hub" |
| Hub lost mid use | banner | `arrow.clockwise`, caution | "Reconnecting to <hub name>." (no countdown) | "Retry" small after 10 s |
| Hub back | none; `success` haptic once | | | |
| Checks off, no key | banner in Learn | `key.slash`, caution | "Checks are off: the hub has no check key. Use Next to move on." | |
| Checks off, rate limited | banner | `hourglass`, caution | "Checks are paused: too many requests. Use Next for now." | |
| Checks off, errors | banner | `exclamationmark.triangle`, caution | "Checks are failing on the hub. Use Next for now." | |
| Budget reached | banner | `creditcard.trianglebadge.exclamationmark`, caution | "Checks are off: the hub reached its spending limit. Use Next to move on." | |
| Simulated checks | banner, once per lesson, dismissible | `testtube.2`, caution | "Simulated checks. Steps pass on a timer, not by looking." | "OK" |
| Recording as camera source | chip on live pane | `film`, caution | "Recording" | |
| Camera lost | live pane | | "Camera lost. Keep going with Next." | |
| Lesson not found | empty state | `questionmark.folder` | Title "Lesson not found". Message "It may have been deleted on the hub." | "Back to Library" |
| Lesson unreadable | empty state | `doc.badge.exclamationmark`, bad | Title "This lesson cannot be opened". Message: hub text. | "Back to Library" |
| Clip failed | clip pane | | "Clip did not load." | "Try Again" |
| Too many cameras or viewers (close 1013) | banner | `person.3`, caution | "The hub has too many connections. Trying again." | |
| Another device took over (close 4000) | banner | `iphone.slash` | "Another device took over as the camera." | "Send Again" |
| Upload too large (413) | upload | bad | "video is larger than 2 GB" shown as "This video is over 2 GB. Trim it or record a shorter take." | |
| Hub busy (429) | upload | caution | "The hub is busy with other lessons. Try again when one finishes." | "Try Again" |

Mapping of `check_offline_reason` to copy: `no_key`, `rate_limited`, `errors`, `budget` as above. Any other value: "Checks are off. Use Next to move on."

---

## 19. Hub needs

Features above that need hub work. None of these exist in `CONTRACT.md` Revision 5. The apps must hide the feature, not fake it, until the hub provides it.

| Feature | Needed from the hub |
|---|---|
| Simulated checks badge | `check_mode` in `state`, or `GET /api/health` (proposal P25) |
| Hub name, accounts flag | `GET /api/health` fields `name`, `accounts` |
| QR connect | a page on the hub that shows the `handover://connect` code |
| Phone as camera and viewer | `/ws/ui?frames=0` to skip binary frames |
| Sign in, approval, roles, profile | accounts, sessions, device approval, roles per lesson |
| Progress across devices, Profile history | stored run summaries per account |
| Library cover, description, visibility, owner | lesson fields `cover`, `description`, `visibility`, `owner`, `published` |
| Ratings and comments | store and read ratings per lesson |
| Insights | read API over learn events (proposal P26), or a dashboard link |
| Processing stages | job statuses `transcribing` and `voiceover`, optional `progress` 0 to 1 |
| Multi-part takes | multi-file upload (CLI `--concat` exists; HTTP does not) |
| Test This Question | HTTP endpoint running the self-test for one step |
| Captions editing | write `captions/NN.vtt` via recut or a new endpoint |
| Per-step voiceover and voice list | per-step voiceover regenerate and remove, list of voices |
| Drafts | a draft copy separate from the live lesson |
| Publish, access | visibility, unlisted links, access lists |

Exists today and usable now: lessons list and detail, upload with job polling, recut, delete, `/ws/ui` and `/ws/camera` with hello, next, back, goto, dismiss_mistake, `state` with status, last_check and reason, camera, check_offline and reason (`no_key`, `rate_limited`, `errors`, `budget`), mistake, advance.

---

## 20. Score and stats rules

So that every number on Done, Profile and Insights is real and reproducible.

### 20.1 What is recorded per run (client)

From the moment `select_lesson` is answered until `status == done`:
- Per step: time on the step (summed across visits, charged on each `state` position change, as `Learn.tsx` does), how it was left forward (`advance.reason`: camera, button, voice), whether a `behind` mistake was raised, whether checks were off at any moment on that step (`check_offline` true in any state while on it), and whether it was skipped (left forward by `goto`, or jumped over by an `ahead` advance from k to k+2 for step k+1).
- Run time: from start to done. Not available if the hub disconnected for more than 10 s during the run (marked "interrupted").

### 20.2 Score

Computed only when the run is not interrupted and at least half of the steps have a recorded time. Otherwise "Not enough data".

Three parts, each 0 to 1:
- **Checked**: camera-verified camera steps divided by camera steps that had checks available the whole time. Manual steps and steps with checks off are left out, so a learner is never marked down because checks were off. If no step qualifies, this part is dropped and the other two share its weight.
- **Pace**: the mean over steps with a time of `min(1, expert seconds / your seconds)`. Skipped steps count 0.
- **Clean**: `1 - min(1, mistakes raised / number of steps)`.

Score = round(100 x (0.5 x Checked + 0.3 x Pace + 0.2 x Clean)). With Checked dropped: round(100 x (0.6 x Pace + 0.4 x Clean)).

Show the parts on demand: tapping the score shows a sheet "How the score works" with the three parts as plain sentences: "6 of 7 camera steps checked by camera.", "Your pace was 82% of the expert's.", "1 mistake in 8 steps."

### 20.3 Best and weakest step

Among steps with a recorded time and not skipped:
- Weakest: the most mistakes, then the highest your-to-expert time ratio.
- Best: verified by camera with no mistakes and the lowest ratio; if none is camera-verified, the lowest ratio with no mistakes.
Needs at least 2 qualifying steps.

### 20.4 The tip

The first rule that matches:
1. Weakest step has a `common_mistake`: "On step <n>, watch for this: <common_mistake>"
2. Weakest step had a mistake: "Replay step <n>'s clip before you try it again."
3. Weakest step took over twice the expert's time: "Step <n> took the longest. Watch the expert's hands closely there."
4. Any step skipped: "You skipped step <n>. Try it once so the camera can check it."
5. Checks were off for part of the run: "Checks were off for part of this run, so try again for a full score."
6. Otherwise: "Try it again without looking at the clip."

### 20.5 Insights aggregates

Medians, not means. Counts always shown next to rates. A step row needs 3 runs that reached it. Times come from `advance.step_seconds` and `step_enter.expert_seconds` in the hub's learn events; mistakes from `mistake` events; check-off periods from `breaker` events.
