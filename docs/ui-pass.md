# UI pass for the demo

A hierarchy and motion pass over the Apple app (Mac, iPad, iPhone). It is additive: every screen keeps every feature, every theme and every test. Nothing is restyled. The work is to make the three things that sell HandOver impossible to miss, and to add a handful of motions that make the moments feel finished.

The three things that sell it, in order:

1. The camera verdict. The lesson moves on because the camera saw the step done.
2. The catch. The learner is behind, HandOver names the step and says the mistake out loud.
3. The expert's hands beside your hands.

Everything below serves those. If a change does not make one of the three more visible, it is out of scope.

## Rules for whoever runs this

- Work on a branch off `main`. One commit per numbered item below, in order, so any item can be reverted alone.
- Build and run the existing test suite after each item. If an item breaks a test, fix the item, not the test, unless the test asserts the old emphasis (for example, Next being the primary button).
- No new colors, fonts, radii or shadows. Use the tokens in `apps/apple/Sources/DesignSystem/Tokens.swift` and the roles in `apps/design/DESIGN.md` section 2. Status uses `good`, `caution`, `bad`. Never the accent.
- Every animation goes through `HOMotion.resolve(_, reduceMotion:)` so Reduce Motion turns it off, as `LearnView.swift` already does for its panels.
- Nothing pulses, breathes or loops. A motion runs once, on an event, and stops. The status dot stays still.
- Refresh `apps/apple/screenshots/` at the end so the README images match.

## 1. Learn: the verdict is the loudest thing on screen

Files: `apps/apple/Sources/Features/Learn/LearnView.swift`, `apps/apple/Sources/DesignSystem/Components/StatusBadge.swift`.

Today the status is a grey "Watching" pill with "Last check 0.9 s / folded side still up" in secondary text, bottom left, far from the video. Next is the largest accent element on the screen.

Change:

- Move the status badge onto the learner's camera tile, top trailing corner, as the over-video chip style already used for Replay and "This Mac". Keep the `StatusBadge` view and `LearnStatus` enum as they are. Only the placement changes.
- On `.verified`, the badge turns `good`, reads "Step done", and the camera tile gets a 2 point `good` inset stroke that fades out over 0.9 s. The badge stays green for the flash window the client already holds, then the next step's "Watching" appears.
- The last-check line ("Last check 0.9 s", the model's reason) moves under the step title, in `ink2`, one line, so the title, the instruction and the evidence read as one block.
- Next becomes the secondary style (outline) on Mac and iPad. Keep its size and position, the keyboard hint and the Space shortcut. On iPhone portrait it stays filled: it is the only control reachable with a thumb.
- Keep "Do this step. HandOver moves on when it sees it done." under the title. It is the best line in the app.

Check: screenshot the step 4 state. The eye should go video, green chip, step title, then Next.

## 2. Learn: the two videos take the room

File: `LearnView.swift`, the Mac and iPad layout.

Today the step list takes 27 percent of the width and the lower 40 percent of the window is empty.

Change:

- Size the two tiles by height first: both tiles the same height, as tall as fits between the progress bar and the title block, then width from the aspect ratio. Letterbox inside the tile, never shrink the tile.
- The step list collapses to the list button in the toolbar by default on Mac and iPad, as it already does in landscape. Remember the user's choice.
- Title block (step count, title, instruction, last check) sits in one row with Back and Next, under the tiles. Nothing below that row.

Check: on a 13 inch Mac window the tiles are at least 60 percent of the window height.

## 3. Learn: the catch is a card, not a caption

Files: `apps/apple/Sources/DesignSystem/Components/MistakeCard.swift`, `LearnView.swift`.

Today "Flip it over first." is headline text in the letterbox bar under the clip, with Show Step 3 and I'm Fine beside it.

Change:

- The card moves under the learner's camera tile, full tile width, `caution` wash with a 3 point `caution` bar on the leading edge, label "Mistake" in caps, the message in `headline`, the two actions on the trailing side. The component exists; only its placement and the wash change.
- It enters with a 0.28 s rise (8 points up, fade in) and leaves with a fade. Once.
- While the card is up, the current step's row in the list and the current progress segment are `caution`. Nothing else on screen is amber.
- The camera tile gets a `caution` inset stroke for the same 0.9 s as the green one in item 1, so the two outcomes rhyme.

Check: with a mistake active there is exactly one amber card, one amber row, one amber segment.

## 4. Home: lessons first, glasses first

Files: `apps/apple/Sources/Features/Library/LibraryView.swift`, `apps/apple/Sources/Features/Onboarding/OnboardingHomeCard.swift`, `apps/apple/Sources/Features/Learn/CameraChoiceSheet.swift`.

Today the first screen is a "How it works" card, two large Learn and Teach tiles, an Everyone / Mine / Shared / My Orgs control, then Continue, and the lesson grid is below the fold.

Change:

- The "How it works" card shows until the first lesson is started, then never again. It already has a close button; make the close automatic on first lesson start.
- The Learn and Teach tiles become one row of two regular buttons under the title, not hero tiles. Teach stays. The lesson grid starts within the first screen.
- The library scope control (Everyone, Mine, Shared with Me, My Orgs) shows only when signed in. Signed out, the grid is the grid.
- Lesson covers use the step 1 reference frame already on disk. The bike lesson, with real hands, is the first card. Rename nothing in lesson data; the "(synthetic renders)" lessons simply sort after real ones.
- In the camera sheet, Meta glasses is the first option. Drop the "Experimental" chip and the grey state. Keep the "iPhone only" line under it on Mac and iPad, since that is true.

Check: a fresh window on a 13 inch Mac shows at least four lesson covers without scrolling.

## 5. Done: lead with the camera, not the score

File: `apps/apple/Sources/Features/Done/DoneView.swift`.

Today a 75 "Good" ring is the hero. The ring is generic and the number is derived.

Change:

- The headline becomes "2 of 3 steps checked by camera" in `title` size, with your time against the expert's directly under it. The ring shrinks to the stat row or goes. Keep the number in the data, so analytics are unchanged.
- The per-step bars stay. The bar for a camera-checked step fills in with a 0.6 s width animation, staggered 60 ms per row, once, on appear. Marked-done steps draw without motion. The difference reads as "the camera saw these".
- "Best step" and "Practice this" cards stay. "Practice the Weakest Step" stays the one primary button.
- Done uses the same theme as Learn. Today Learn is light and Done is dark on Mac; pick the light one.

## 6. Editor: one accent

File: `apps/apple/Sources/Features/Editor/EditorTimeline.swift`.

Today the timeline is eight blocks in eight colors. The rest of the app uses one accent.

Change: the selected step is `accent`, every other step is `well` with a `lineStrong` hairline between them, the number stays in each block. The colors in `EditorModels` can stay for the step list dots if anything depends on them; the timeline stops using them.

## 7. Motion, the whole list

These are all the motions the pass adds. Each runs once, on an event. Durations are from `HOMotion` where a matching curve exists; add one there if not.

| Moment | Motion | Duration |
| --- | --- | --- |
| Step verified | Camera tile `good` inset stroke fades out; badge switches to "Step done" | 0.9 s |
| Step changes | Title block: old title fades out and the new one rises 8 points into place; progress segment fills left to right | 0.32 s, 0.4 s |
| Expert clip changes | Cross-dissolve between the outgoing and incoming clip tiles | 0.25 s |
| Mistake caught | Card rises 8 points and fades in; tile `caution` stroke fades out | 0.28 s, 0.9 s |
| Mistake cleared | Card fades out | 0.2 s |
| Lesson complete | Done sheet slides up (exists); per-step camera bars fill, staggered | 0.6 s + 60 ms per row |
| Button press | Scale to 0.97 on press, back on release, system curve | 0.12 s |

Not added: idle loops, parallax, blur transitions, confetti, count-up numbers, skeleton shimmer.

## 8. What stays exactly as it is

Themes and the theme picker. Captions and the captions control. Device audio control. Replay. The steps popover. Orgs, accounts, sharing. Teach and the editor's functions. The onboarding pages (only the home card's dismissal changes). The protocol, the hub, lesson files.

## Optional tooling

Two Claude Code skills fit an emphasis pass without restyling. Neither is required.

- Impeccable, by Paul Bakaus: `npx impeccable install`, then use only `critique`, `audit`, `distill` and `typeset`, with `## Platform: ios` in its PRODUCT.md. Skip `bolder`, `delight`, `overdrive`. The installer adds hooks and telemetry; read what it installs.
- GitHub's `anti-ui-slop` skill from the awesome-copilot repository, with its `ios` playbook.
