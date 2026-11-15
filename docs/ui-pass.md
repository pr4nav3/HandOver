# UI pass for the demo: iPhone, iPad and Mac

One list for Soham, to run once on his Mac. It merges the earlier Apple plan and the desktop list, both now removed.

Two apps are in scope:

| App | Code | Runs on | Build |
| --- | --- | --- | --- |
| Phone app (SwiftUI) | `apps/apple` | iPhone and iPad | `xcodegen generate`, open `HandOver.xcodeproj` |
| Desktop app (Tauri) | `apps/desktop` (Rust core, TypeScript and CSS under `ui/`) | Mac | `npm run tauri dev` in `apps/desktop/ui` |

Out of scope: the Mac target of the SwiftUI app, Windows, Linux, `apps/android`. Do not delete them in this pass; they just get no attention. The web app in `web/` is a separate thing and is not touched.

Every desktop item below was checked against the running app on Nov 15 (hub on 127.0.0.1:8000, the `devserver` bridge, Default theme, light, 1440 by 900). The phone items were checked against the code; `apps/apple/screenshots/` is stale (the Learn shots show a tray that no longer renders, and several "iPhone" shots were rendered on the Mac), so re-render on the iOS simulator before and after.

## What sells HandOver, in order

1. The camera verdict. The lesson moves on because the camera saw the step done.
2. The catch. The learner is behind, HandOver names the step and says the mistake out loud.
3. The expert's hands beside your hands.

Part A makes those three impossible to miss. Parts B and C remove what gets in their way. If a change does not serve one of the three or remove noise around them, it is out of scope.

## Rules for whoever runs this

- Branch off `main`. One commit per numbered item so any item can be reverted alone. No AI attribution lines in commit messages.
- After each item: the SwiftUI tests for `apps/apple`, and `npm test` plus `npm run check` in `apps/desktop/ui`. The tests assert the design rules; fix the item, not the test, unless the test asserts the old emphasis.
- No new colors, fonts, weights, radii or shadows. SwiftUI uses `Tokens.swift`; the desktop uses only the theme variables (`--bg`, `--panel`, `--panel-2`, `--text`, `--muted`, `--faint`, `--border`, `--border-strong`, `--accent`, `--on-accent`, `--accent-ink`, `--green`, `--amber`, `--red`). Anything hard-coded breaks 13 of the 14 themes.
- Flat surfaces (DESIGN.md rule 1). Shadows only on things that float: toast, sheets, popovers. No blur, no glow, no gradients.
- Status colors are `good`, `caution`, `bad`. Never the accent for status.
- Nothing pulses, breathes or loops. A motion runs once, on an event, and stops. SwiftUI motion goes through `HOMotion.resolve(_, reduceMotion:)`; the desktop keeps its `prefers-reduced-motion` rule.
- Copy: Title Case on buttons and Settings rows, sentence case elsewhere, no dashes, no selling ("Great job!"). Say "your phone" and "this computer"; "iPhone" and "Mac" only where the code knows it is one.
- One filled accent button per screen.
- Refresh `apps/apple/screenshots/` at the end.

## Already done (uncommitted on Pranav's PC, pull first)

Desktop Learn: both videos fill their column height inside flat panel cards, so the divider visibly trades space between them; the gradient step card is a plain muted "Step 5 of 9" line; the "When this step is done" card is gone; the badge class no longer collides with the camera pane's `.live` rule; card shadow and glow removed. Files: `views/learn.ts`, `styles/app.css`, `tests/accessibility.test.ts`.

---

## Part A. Both apps: the verdict, the catch, the hands

Written at the design level. The table says where each lives.

| | Phone app | Desktop app |
| --- | --- | --- |
| Learn | `Features/Learn/LearnView.swift`, `LearnTab.swift`, `Panes.swift`, `PiPTile.swift` | `ui/src/views/learn.ts`, `.badge*`, `.mistake-card`, `button.next` in `app.css` |
| Status badge | `DesignSystem/Components/StatusBadge.swift` | `.badge` rules in `app.css`, `learn_feedback.ts` |
| Mistake card | `DesignSystem/Components/MistakeCard.swift` | `.mistake-card` in `learn.ts` and `app.css` |
| Home | `Features/Library/LibraryView.swift`, `Features/Onboarding/OnboardingHomeCard.swift` | `ui/src/views/home.ts` |
| Camera choice | `Features/Learn/CameraChoiceSheet.swift` | `ui/src/views/pair.ts` |
| Done | `Features/Done/DoneView.swift` | the done block in `learn.ts`, `ring` in `components.ts` |
| Editor timeline | `Features/Editor/EditorTimeline.swift` | `HUES` in `ui/src/views/editor.ts` |
| Motion | `HOMotion` in `DesignSystem/Tokens.swift` | transitions in `app.css` |

### A1. The verdict is the loudest thing on screen

Desktop today: a grey "Watching" pill with "Last check 0.9 s" and the model's reason in secondary text, bottom left, far from the video. Phone today: a `LearnFeedbackCard` (`LearnFeedback.swift:75` to `110`, placed at `LearnView.swift:258`, `328`, `422`) under the step title, with its own heading, its own badge, a tinted wash and a debug line ("12 fps · Live"). Either way, Next is the largest accent element on the screen.

- Move the status badge onto the learner's camera tile, top trailing corner, in the over-video chip style already used for Replay and the camera name. Keep `StatusBadge`, `LearnStatus` and the labels. On the phone this means deleting `LearnFeedbackCard` from Learn and using `StatusBadge(overVideo:)` on the live pane and the PiP tile. Checking may stay accent, as DESIGN 3.1 says; verified is `good`, mistake is `caution`.
- On verified, the camera tile gets a 2 point `good` inset stroke that fades out over 0.9 s (SwiftUI: add `HOMotion.verdict = .easeOut(duration: 0.9)`; desktop: one CSS transition on the `.live` border). The badge turns `good` and holds for the flash window the client already keeps.
- One `ink2` line under the step title carries the evidence (the last check and the model's reason). On the phone, `stepInfo(showsHint: false)` at `LearnView.swift:243`, `333` and `418` currently hides "Do this step. HandOver moves on when it sees it done."; turn the hint back on.
- Next becomes the secondary (outline) style on iPad and Mac. Keep its size, position and shortcuts. On iPhone portrait it stays filled: it is the only control a thumb reaches. This is the one judgment call; if the team wants Next filled, skip this bullet and the rest still holds.
- Keep "Do this step. HandOver moves on when it sees it done." under the title.

Check: on the step 4 state the eye goes video, green chip, step title, then Next.

### A2. The two videos take the room

- Size the tiles by height first: as tall as fits between the progress bar and the title block, then width from the aspect ratio. Letterbox inside the tile, never shrink the tile. (Done on the desktop; see Already done. On iPad the step list collapses to the toolbar list button by default, as it already does in landscape, and the choice is remembered.)
- The title block (step count, title, instruction, last check) sits in one row with Back and Next under the tiles. Nothing below that row.

Check: on a 13 inch Mac window and on iPad landscape the tiles are at least 60 percent of the window height.

### A3. The catch is a card, not a caption

- The mistake card sits directly under the learner's camera tile, full tile width: `caution` wash, a 3 point `caution` bar on the leading edge, the message in `headline`, the two actions on the trailing side. No caps label (that would be a tracked micro-label). `MistakeCard.swift` has the wash but no leading bar; add the bar. On iPad today a `Spacer` in the wide layout parks the card and Next about 500 points below the videos (`learn-ipad.png`); remove it so the card and the controls sit under the panes.
- It enters and leaves with the existing `panel` curve (SwiftUI) or a 0.28 s rise and fade (desktop). Once.
- While the card is up, the current step's row and the current progress segment are `caution`. Nothing else on screen is amber. (On the phone, `LearnFeedbackCard` also turns caution for held and waiting camera, `LearnFeedback.swift:16`; deleting it in A1 fixes that.) The camera tile gets a `caution` inset stroke with the same curve as the green one, so the two outcomes rhyme.

Check: with a mistake active there is exactly one amber card, one amber row, one amber segment.

### A4. Home: lessons first

Desktop today: a "How it works" card, two hero tiles, then the lessons. Phone today: `OnboardingHomeCard` ("Pick a lesson to start", with Hide), two hero tiles, the scope control (already gated on sign-in, `LibraryView.swift:155`), Continue, then the grid.

- The home card hides itself the first time a lesson is started and stays hidden; the Hide becomes automatic. On the desktop, remove the "How it works" card outright (`home.ts:39` to `54`).
- The Learn and Teach hero tiles go. The phone keeps one row of two regular buttons under the title; the desktop has Lessons and Teach in the pane already, so it keeps nothing (`home.ts:83` to `102`).
- The library scope control (Everyone, Mine, Shared with Me, My Orgs) shows only when signed in.
- Lessons sort by last updated, newest first, which puts the bike lesson with real hands ahead of the synthetic origami ones. Rename nothing in lesson data.
- Camera sheet: on iPhone, Meta glasses is the first option, no "Experimental" chip, no grey state. On iPad and Mac it stays second, readable, with "Use the iPhone app" under it. Nothing is shown as selectable that cannot be selected.

Check: a fresh window on a 13 inch Mac, and a fresh iPhone Home, show lesson covers without scrolling.

### A5. Done: lead with the camera, not the score

- The 75 "Good" ring goes. The headline becomes "2 of 3 steps checked by camera" in `title` size, with your time against the expert's directly under it. The score number moves into the stat row so analytics and rating are unchanged. Phone: `CompletionHalo` (`DoneView.swift:119`, `361` to `385`), a confetti tick burst with an overshoot spring, goes too, and so do the five staggered `DoneReveal`s (`138` to `143`).
- The per-step bars stay. A camera-checked step's bar fills in once on appear, staggered 60 ms per row; marked-done steps draw without motion. The difference reads as "the camera saw these".
- "Practice the Weakest Step" stays the one primary button. Done uses the same theme look as Learn (today Learn is light and Done is dark on Mac).

### A6. Editor: one accent

The timeline is eight blocks in eight colors. The selected step is `accent`, every other step is `well` with a `lineStrong` hairline between them, the number stays in each block. The hue table can stay for anything else that reads it.

### A7. Motion, the whole list

| Moment | Motion | SwiftUI curve | Desktop |
| --- | --- | --- | --- |
| Step verified | Camera tile `good` stroke fades out; badge label switches | `verdict` (new), `snappy` | 0.9 s ease-out, 0.15 s |
| Step changes | Old title fades, new title rises 8 points; progress segment fills | `panel`, `layout` | 0.32 s, 0.4 s |
| Expert clip changes | Cross-fade between clips | `clip` | 0.25 s |
| Mistake caught | Card in; tile `caution` stroke fades out | `panel`, `verdict` | 0.28 s, 0.9 s |
| Mistake cleared | Card out | `panel` | 0.2 s |
| Lesson complete | Done sheet in; camera bars fill, staggered | `panel`, `layout` | 0.6 s plus 60 ms per row |
| Button press | Scale 0.98 | `press` | exists |

Not added, on purpose: idle loops, pulsing dots, parallax, blur or glass transitions, confetti, count-up numbers, skeleton shimmer, spring overshoot, gradient fills, glow. Desktop: `.hub-pill.wait .dot` and `.dot.warn` pulse forever; replace with the solid dot and let the label carry the state.

---

## Part B. Desktop app on Mac: cleanup

Biggest visible wins first. B1 to B7 are the pass; B8 to B12 if there is time.

### B1. Step thumbnails never load (bug)

Course detail, the Learn steps popover and the editor show black boxes where step frames should be. The images carry `loading="lazy"` and the WebView never starts them, even in view; removing the attribute loads them at once. Drop it at `views/course.ts:63`, `views/editor.ts:115`, `components.ts:23`.

### B2. Home

See A4 for the hero. Also: step count and expert time back on the cards (`home.ts:141` passes `meta: ""`); "View all" becomes "See All" (139), "Try again" becomes "Try Again" (163), "No lessons yet." becomes "Nothing here yet" (136); the search field (147) only navigates to Lessons, so filter in place or remove it; "Pair a Phone" once, in the header.

### B3. Chrome

- `.pane-mark` (`app.css:157`) is a fixed `#315f88` tile that ignores every theme. Use `--accent` and `--on-accent`.
- The hub pill shows "Connected" at all times (`main.ts:121` to `127`). Show it only when connecting, reconnecting or replaced.
- The three uppercase tracked micro-labels (`app.css:212`, `1967`, `2259`) become 13px, weight 600, `--muted`, sentence case. They are the strongest generic-dashboard tell, visible on every Settings and sheet heading.
- Mac: the window `backgroundColor` in `app/tauri.conf.json` is `#0b0b0c`, so a light theme flashes dark at launch and on resize. Set it to the Default light paper, or set it from the chosen theme at startup.

### B4. Course detail

At 900 px tall the left column is cover, title, meta, 200 px of nothing, then "Before you start", Camera and Start pinned to the bottom (`.detail-start { margin-top: auto }`). Let the column flow top-aligned. Error copy: "This lesson cannot be opened", button "Back to Lessons" (`course.ts:78`).

### B5. Learn, the rest

- No camera yet: the waiting card sits at the top of an otherwise empty column. Center it vertically (`.live.waiting { margin: auto 0 }`).
- Manual steps hide the whole camera column (`.learn-grid.manual-focus`), so the layout jumps. Keep the column and dim the camera to 50 percent.
- The steps popover (`.course-list`, `app.css:3027`) is a wide frosted panel with an 18px blur that covers the step title. Solid `--panel`, hairline, the one floating shadow, anchored to the disclosure's width.
- "Turn on sound" and the transport bar are hard-coded dark pills (`app.css:2714`, `2736`). Fine over video; give them a token so Newsprint and Ivory can tune them.
- Captions are native cues drawn under the letterboxed picture. Acceptable for now; our own caption bar over the picture only after everything else.

### B6. Sheets

- Remove `backdrop-filter: blur(14px)` on `.sheet-backdrop` (`app.css:2210`). A 40 percent `--bg` scrim is enough.
- Delete the green "Ready on localhost / Your iPhone sign-in syncs here" card on top of Pair and the camera sheet (`pair.ts:137` to `140`).
- Camera sheet: the two option cards wrap "iPhone Camera" and "Use your phone" onto two lines each. Two list rows: "Phone camera, stream from the HandOver app" and "Meta glasses, stream from Ray-Ban Meta through the phone", with "Use this computer instead" under them.
- "Scan with the iPhone Camera" becomes "Scan with your phone" (`pair.ts:167`, `219`). Remove `pair-radar` (pulses) and the green drop-shadow and bounce on `.pair-success-ring` (`app.css:4957` to `4958`).
- Sign in sheet title "Set Up Your Hub" in Title Case to match "Finish Setup".

### B7. Settings

- Sections become Hub, Appearance, Learn, Camera, About (`settings.ts:140` to `212`). Version, Show Welcome Again and Privacy move under About; today they sit under "Keyboard".
- The first row is labeled "Mac" on every platform (142). Label it with the hub host.
- "Pair iPhone" (147) becomes "Pair a Phone", secondary style. Settings has no primary button.
- Remove the helper line under every toggle and "Themes with one look keep it."
- Rows in Title Case: "Chime When the Camera Confirms a Step", "Notify Me in the Background", "Reconnect to the Last Hub at Launch". "Model sees every" (95) becomes "Check Every".
- Hub status appears twice (142 and 191); keep one. "Disconnect" (196) becomes "Remove This Hub".

### B8. Platform words

Mac and iPhone are hard-coded in `onboarding.ts:201` to `202`, `settings.ts:142` and `147`, `profile.ts:223`, `pair.ts:54`, `130`, `136`, `157`, `167`. `main.ts` already computes `PLATFORM` and `CAMERA_NAME`; export them and use "this computer" and "your phone" elsewhere.

### B9. Profile

- Up to six stat tiles with glow rings (`profile.ts:160` to `170`, `app.css:2145` to `2150`). Three tiles, no rings: Lessons finished, Steps checked by camera, Your time against the expert's.
- Copy: "Your private learning insights stay attached to your hub account." becomes "Your runs and times show up here once you sign in." "Camera-verified steps" (221) becomes "Steps checked by camera". "Activity" (272) becomes "Progress". Sign Out (254) moves to the bottom.

### B10. Teach

- "Record a Take" is a static card styled like the clickable Upload card (`teach.ts:59` to `61`). A one-line note under the Upload card, or a real action.
- "Choose video" becomes "Choose a File" (57). The sheet is titled "Make a Lesson" but its button says "Make Course" (83, 96); "Make a Lesson" for both.
- Lesson rows carry a Published pill, the word Edit and a chevron. Keep the pill and the chevron.

### B11. Stylesheet hygiene, one commit

- Delete the dead rules: `.block-head h2.with-avatar` (731 to 735), `.card-row` (737 to 744), `.make-card` (836 to 854), `.learn-workbar` (2350 to 2356), `.layout-hint` (2372 to 2375), `.progress*` (2389 to 2426), `.ob-foot` (3564 to 3568), `.hub-row` (4413 to 4425), `.pair-steps` (5020 to 5038), `.pair-num` from the selector at 4540. About 120 lines.
- Remove the `.done-card` shadow (3274) and the blur on `.tutorial-transport` (2739) and `.result-moment` (2819). Cut the segmented control shadow (4225) to 6 percent. One floating-shadow variable for toast, sheet and popover (630, 2223, 3027).
- Radii: 14 becomes 12; 10, 9 and 7 become 8. Font sizes: 14 becomes 13 or 15; 11 and 10 become 12. Weights 500 and 600 only.
- Entrance keyframes (2105, 2164, 3256, 3597, 3701, 3729, 4948) go; keep spin. Remove the hover zoom on covers (787).
- `.danger` white on `--red` fails contrast on dark themes (380). `.qr-wait .spinner` (4895) is black on black on dark themes.

### B12. Editor and organizations

- The editor hides the pane and its loading, error and "needs a newer hub" states have no Back button (`editor.ts:84` to `88`). Add one. "Saved on the hub" becomes "Saved".
- Org page header has Teach, Invite, Leave and Delete inline (`orgs.ts:119` to `122`). Teach, Invite and a More menu. Gate "New Organization" on `can_create_org` (36).

---

## Part C. Phone app on iPhone and iPad: cleanup

Biggest visible wins first. C1 to C6 are the pass. Re-render every iPhone and iPad screenshot on the simulator at the end; the current set is stale.

### C1. iPhone portrait Learn: stop letterboxing the expert

`learn-iphone-portrait.png`: the expert clip is a 16 by 9 video inside a tall portrait tile (`LearnView.swift:217` to `245`, `minHeight: screen.height * 0.4`), so more than half the tile is black, the caption floats in the black, and the learner's camera is an unlabeled PiP in the corner (`PiPTile` at 233).

Change: the clip tile is as wide as the screen and as tall as its aspect ratio needs, no taller. The learner's camera becomes a second tile under it, same width, labeled with the camera name chip, instead of a PiP; portrait has the vertical room. The caption bar sits over the bottom of the clip. Step info and controls stay below. PiP stays for landscape only.

Check: on an iPhone 15 portrait screenshot, no black band taller than 16 points above or below either picture.

### C2. iPad and iPhone landscape

- iPad (`LearnView.swift` wide layout around 394 to 422): the live pane is capped at 34 percent width while the clip has `layoutPriority(2)`; spec 7.5 says equal. Make them equal, then A2 and A3 (remove the `Spacer`).
- iPhone landscape (`LearnView.swift:302` to `350`): with a mistake active the step title disappears (`learn-iphone-landscape-mistake.png`), and the order is clip left with a side column. Spec 7.4: live on the left, clip on the right, one control row under the panes. Fix the vanished title first, then the order.
- The partial `ProgressRing` in the iPad sidebar ("3 of 5 done") and on the Continue card reads as a spinner. Replace with "Step 4 of 8" text or a static bar. The selected step row is an accent wash with accent icon and text; with Next that is four accent marks on one screen. Wash only, `ink` text.

### C3. Top bar and the Replay chip

- Close, a centered title (`LearnView.swift:464`), the "Device audio" pill, Steps and More share 375 points, so the title truncates. Left-align the title and move Device audio (`LearnAudioOutputControl` at 356 and 464) into the More menu, where SCREENS.md 7.2 already has "Mute Clip". The bar is Close, title, Steps, More.
- `ReplayClipButton` (`Panes.swift` around 245) is always shown and spins with an ad-hoc spring. Spec 3.4: controls appear on tap. Show Replay only in the tap-revealed controls, through `HOMotion`.

### C4. Six tabs on iPhone

`AppSection` has six cases and `RootView.swift:55` makes a tab of each, so iOS folds the last two into a "More" tab. Spec: four tabs (Home, Organizations, Teach, Profile), with Learn and Be the Camera as full-screen covers and Settings behind a gear.

### C5. The `SymbolTile` motif

The accent-tinted icon square (`Rows.swift:106` to `117`) is used in 12 places: Teach rows, the camera sheet, the role page, the home card, Settings rows. It is the main generic-app motif. Default it to a plain `ink2` symbol with no wash, or drop the icon, at every call site.

### C6. Camera sheet, Done, explainers

- Camera sheet (`flow-start-sheet.png`): five stacked cards, each with two helper lines, plus a status card on top ("Connected to", `CameraChoiceSheet.swift:121`; "Signed in as", 107) and a second one at the bottom ("Ready to use this mac.", 87, with "mac" lowercase). Remove both status cards; one subtitle line per option; then A4's glasses-first order.
- Done (`done-iphone.png`): after A5, the stat row holds three (Your time, Expert, Checked by camera); the lightbulb tip merges into the Practice this card as its second line; "Back to Library" (`DoneView.swift:274`) becomes "Back to Home" in the navigation bar, leaving two buttons. `TimeBar.swift:21` draws "you" in accent; use `ink`.
- Explainers: the "What Happens Next" numbered card on Teach (`TeachView.swift:227`), the footer under every Settings section, the "Spoken Guidance" section whose only row is Spoken Guidance, the frameworks list in About (`SettingsView.swift:358`), "Tap a lesson to review its steps". One footnote per screen at most.

### C7. Copy pass, one commit

- `LearnFeedback.swift:30` to `58` is written for origami: "That fold is right", "Bring the fold into view", "Keep folding", "Checking this fold". It shows on the bike lesson. After A1 only the badge labels remain; if any of these lines survive, make them task-neutral: "Step done", "Bring your work into view", "Keep going", "Checking".
- Close confirm (`LearnView.swift:156` to `164`): "Leave this lesson?", "Your place is saved on this device.", buttons "Leave" and "Keep Going".
- Video pills (`LearnView.swift:599` to `615`): "Simulated checks" and "Checks off", matching the badge; not "Mock checks", "AI budget reached", "Rate limited".
- Role page: cards say "Learn" and "Teach", not "I Want to Learn"; "Both" becomes a third card or a footnote link; drop the hedging subhead.
- Loops and bounces: `WelcomeArt.swift:144` (iterative symbol effect), `MakeCourseView.swift:192` and `ConnectViews.swift:71` to `73` (bounce). Still.

### C8. Tokens

`HORadius.controlLarge = 16` (`Tokens.swift:44`) is not in DESIGN 2.5; large buttons should be 12. Literal radii at `ThemePage.swift:139` and `OrgComponents.swift:41`; `.tracking(1)` at `OrgComponents.swift:94`. On-video tone colors are hex in `Surfaces.swift:46` to `52` and the wash defaults are system green and orange (`Theme.swift:27` to `29`); route them through the theme. The avatar palette's "Violet" (`AvatarStore.swift:17`) is a hue outside THEMES.md.

### C9. Keep

Progress bar segments, the steps sheet with Expert and You times (`course.png`), the mistake card wash, "Do this step. HandOver moves on when it sees it done.", the theme picker, the onboarding pages.

---

## Taste check before merging

Open each changed screen and refuse the merge if any of these appear: a gradient anywhere; a hue not in THEMES.md; a glow, colored shadow, or shadow on a card that does not float; a dot, ring or badge that animates while nothing is happening; overshoot or bounce; emoji, decorative icons beside headings, illustrations for warmth; count-up numbers, confetti, shimmer; more than one filled accent button on a screen; copy that sells. The app says what happened: "Checked by camera", "Verified", "Step done".

## Order of work

Thirty minutes, desktop: A1, A3, B1, B2 with A4, B3. Thirty minutes, phone: A1 (delete the feedback card, badge on the video), A3 (remove the iPad Spacer), C1, C3, C4. Everything else in the order written. A2 is done on the desktop and is the biggest single change on iPad, so it comes right after the thirty if there is a second hour.
