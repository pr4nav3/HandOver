# UI pass for the demo

A hierarchy and motion pass over the desktop and phone apps. It is additive: every screen keeps every feature, every theme and every test. Nothing is restyled. The work is to make the three things that sell HandOver impossible to miss, and to let the few motions that already exist in the design system do their job at the right moments.

The three things that sell it, in order:

1. The camera verdict. The lesson moves on because the camera saw the step done.
2. The catch. The learner is behind, HandOver names the step and says the mistake out loud.
3. The expert's hands beside your hands.

Everything below serves those. If a change does not make one of the three more visible, it is out of scope.

## Which app

The items are written at the design level and apply to both desktop apps. Do the one the demo laptop runs first.

| | Apple app (SwiftUI, Mac, iPad, iPhone) | Desktop app (Tauri, TypeScript) |
| --- | --- | --- |
| Learn | `apps/apple/Sources/Features/Learn/LearnView.swift` | `apps/desktop/ui/src/views/learn.ts`, the `.badge-wrap`, `.mistake-card` and `button.next` blocks |
| Status badge | `apps/apple/Sources/DesignSystem/Components/StatusBadge.swift` | `.badge` rules in `apps/desktop/ui/src/styles/app.css` |
| Mistake card | `apps/apple/Sources/DesignSystem/Components/MistakeCard.swift` | `.mistake-card` in `learn.ts` and `app.css` |
| Home | `apps/apple/Sources/Features/Library/LibraryView.swift`, `apps/apple/Sources/Features/Onboarding/OnboardingHomeCard.swift` | `apps/desktop/ui/src/views/home.ts` (`how` card, `Continue learning` block) |
| Camera choice | `apps/apple/Sources/Features/Learn/CameraChoiceSheet.swift` | `apps/desktop/ui/src/views/pair.ts` |
| Done | `apps/apple/Sources/Features/Done/DoneView.swift` | the done block in `learn.ts`, `ring` in `components.ts` |
| Editor timeline | `apps/apple/Sources/Features/Editor/EditorTimeline.swift` | `HUES` in `apps/desktop/ui/src/views/editor.ts` |
| Motion | `HOMotion` in `apps/apple/Sources/DesignSystem/Tokens.swift` | transitions in `app.css`, with the `prefers-reduced-motion` rule |

## Rules for whoever runs this

- Work on a branch off `main`. One commit per numbered item, in order, so any item can be reverted alone.
- Build and run the existing tests after each item. If an item breaks a test, fix the item, not the test, unless the test asserts the old emphasis (for example, Next being the primary button).
- No new colors, fonts, weights, radii or shadows. Use the tokens in `Tokens.swift` and the roles in `apps/design/DESIGN.md` section 2. Status uses `good`, `caution`, `bad`. Never the accent.
- Motion comes from `HOMotion`. The curves there already cover almost everything in this pass: `panel` for cards and sheets, `layout` for segments and bars, `snappy` for label changes, `clip` for the clip cross-fade, `press` for buttons. This pass adds one curve. Every call goes through `HOMotion.resolve(_, reduceMotion:)` so Reduce Motion turns it off, as `LearnView.swift` already does.
- Nothing pulses, breathes or loops. A motion runs once, on an event, and stops. The status dot stays still.
- Refresh `apps/apple/screenshots/` at the end so the README images match.

## 1. Learn: the verdict is the loudest thing on screen

Today the status is a grey "Watching" pill with "Last check 0.9 s / folded side still up" in secondary text, bottom left, far from the video. Next is the largest accent element on the screen.

Change:

- Move the status badge onto the learner's camera tile, top trailing corner, in the over-video chip style already used for Replay and "This Mac". Keep `StatusBadge` and the `LearnStatus` enum, labels included ("Verified" stays "Verified"). Only the placement changes.
- On `.verified`, the camera tile gets a 2 point `good` inset stroke that fades out. Add one curve for it, `HOMotion.verdict = .easeOut(duration: 0.9)`, and use it in both directions, so the stroke appears at once and leaves slowly. The badge turns `good` with `snappy`, as it does today, and holds for the flash window the client already keeps.
- The last-check line ("Last check 0.9 s", then the model's reason) moves under the step title, in `ink2`, one line, so the title, the instruction and the evidence read as one block.
- Next becomes the secondary style (outline) on Mac and iPad. Keep its size, position, keyboard hint and the Space shortcut. On iPhone portrait it stays filled: it is the only control a thumb reaches. This is the one judgment call in the pass; if the team wants Next filled, skip this bullet and the rest still holds.
- Keep "Do this step. HandOver moves on when it sees it done." under the title. It is the best line in the app.

Check: screenshot the step 4 state. The eye should go video, green chip, step title, then Next.

## 2. Learn: the two videos take the room

Today the step list takes 27 percent of the width and the lower 40 percent of the window is empty.

Change:

- Size the two tiles by height first: both the same height, as tall as fits between the progress bar and the title block, then width from the aspect ratio. Letterbox inside the tile, never shrink the tile.
- The step list collapses to the list button in the toolbar by default on Mac and iPad, as it already does in landscape. Remember the user's choice.
- The title block (step count, title, instruction, last check) sits in one row with Back and Next, under the tiles. Nothing below that row.

Check: on a 13 inch Mac window the tiles are at least 60 percent of the window height.

## 3. Learn: the catch is a card, not a caption

Today "Flip it over first." is headline text in the letterbox bar under the clip, with Show Step 3 and I'm Fine beside it.

Change:

- The card moves under the learner's camera tile, full tile width: `caution` wash, a 3 point `caution` bar on the leading edge, the label "Mistake" in caps, the message in `headline`, the two actions on the trailing side. The component exists; only its placement and the wash change.
- It enters and leaves with `panel`, which it already uses. No new motion.
- While the card is up, the current step's row in the list and the current progress segment are `caution`. Nothing else on screen is amber.
- The camera tile gets a `caution` inset stroke with the same `verdict` curve as the green one, so the two outcomes rhyme.

Check: with a mistake active there is exactly one amber card, one amber row, one amber segment.

## 4. Home: lessons first, glasses honest

Today the first screen is a "How it works" card, two large Learn and Teach tiles, an Everyone / Mine / Shared / My Orgs control, then Continue, and the lesson grid is below the fold.

Change:

- The "How it works" card hides itself the first time a lesson is started, and stays hidden. It already has a close button; this makes the close automatic.
- The Learn and Teach tiles become one row of two regular buttons under the title, not hero tiles. Teach stays. The lesson grid starts within the first screen.
- The library scope control (Everyone, Mine, Shared with Me, My Orgs) shows only when signed in. Signed out, the grid is the grid.
- Lessons sort by last updated, newest first, which puts the bike lesson, with real hands, ahead of the synthetic origami ones. Rename nothing in lesson data.
- In the camera sheet on iPhone, Meta glasses is the first option, with no "Experimental" chip and no grey state. On Mac and iPad it stays in the list, second, readable, with the line "Use the iPhone app" under it, since that is true. Nothing is shown as selectable that cannot be selected.

Check: a fresh window on a 13 inch Mac shows at least four lesson covers without scrolling.

## 5. Done: lead with the camera, not the score

Today a 75 "Good" ring is the hero. The ring is generic and the number is derived.

Change:

- The ring goes. The headline becomes "2 of 3 steps checked by camera" in `title` size, with your time against the expert's directly under it. The score number moves into the stat row, so analytics and the rating flow are unchanged.
- The per-step bars stay. The bar for a camera-checked step fills in with `layout`, staggered 60 ms per row, once, on appear. Marked-done steps draw without motion. The difference reads as "the camera saw these".
- "Best step" and "Practice this" cards stay. "Practice the Weakest Step" stays the one primary button.
- Done uses the light theme, the same as Learn. Today Learn is light and Done is dark on Mac.

## 6. Editor: one accent

Today the timeline is eight blocks in eight colors. The rest of the app uses one accent.

Change: the selected step is `accent`, every other step is `well` with a `lineStrong` hairline between them, the number stays in each block. The hue table can stay for anything else that reads it; the timeline stops using it.

## 7. Motion, the whole list

Everything the pass touches, with the curve it uses. Six of seven already exist in `HOMotion`.

| Moment | Motion | Curve |
| --- | --- | --- |
| Step verified | Camera tile `good` inset stroke fades out; badge label switches | `verdict` (new, easeOut 0.9 s); `snappy` |
| Step changes | Old title fades, new title rises 8 points into place; progress segment fills | `panel`; `layout` |
| Expert clip changes | Cross-fade between outgoing and incoming clip | `clip` |
| Mistake caught | Card in; tile `caution` stroke fades out | `panel`; `verdict` |
| Mistake cleared | Card out | `panel` |
| Lesson complete | Done sheet in (exists); camera bars fill, staggered 60 ms per row | `panel`; `layout` |
| Button press | Scale 0.98, exists | `press` |

Not added, on purpose: idle loops, pulsing dots, parallax, blur or glass transitions, confetti, count-up numbers, skeleton shimmer, spring overshoot on text, gradient fills, glow.

Desktop app only: `.hub-pill.wait .dot` and `.dot.warn` in `app.css` pulse forever. Principle 8 says still things stay still. Replace the pulse with the solid dot and let the label carry the state.

## 8. What stays exactly as it is

Themes and the theme picker. Captions and the captions control. Device audio control. Replay. The steps popover. Orgs, accounts, sharing. Teach and the editor's functions. The onboarding pages (only the home card's dismissal changes). The protocol, the hub, lesson files.

## 9. Taste check before merging

Open each changed screen and refuse the merge if any of these appear:

- A gradient anywhere, including on buttons, progress or text.
- Purple, violet or any hue not in THEMES.md.
- A glow, a colored shadow, or a shadow on a card that does not float.
- A dot, ring or badge that animates while nothing is happening.
- Motion with overshoot or bounce on text or cards.
- Emoji, decorative icons beside headings, or an illustration added for warmth.
- A number that counts up, a confetti burst, a shimmer placeholder.
- More than one filled accent button on a screen.
- Copy that sells ("Great job!", "You're crushing it"). The app says what happened: "Checked by camera", "Verified", "Step done".

## Optional tooling

Two Claude Code skills fit an emphasis pass without restyling. Neither is required.

- Impeccable, by Paul Bakaus: `npx impeccable install`, then use only `critique`, `audit`, `distill` and `typeset`, with `## Platform: ios` in its PRODUCT.md. Skip `bolder`, `delight`, `overdrive`. The installer adds hooks and telemetry; read what it installs.
- GitHub's `anti-ui-slop` skill from the awesome-copilot repository, with its `ios` playbook.
