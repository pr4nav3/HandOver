# HandOver pitch (judging Sun 2026-11-15, 1:00 to 2:30 PM)

Owner: Prayush. Rehearsal-ready version for the Windows demo. Where this file and an older doc disagree, docs/HANDOFF.md wins, then this file.

Live demo: the origami fortune teller, folded at the table. Showcase: the bike front wheel check, pre-recorded and always called a recording (TEAM_RULES.md).

Rules for reading this file:
- Lines in quotes are spoken word for word. Everything else is a stage direction.
- `[[like this]]` is a fill-in. Do not say a blank out loud. If it is still blank at 12:45 PM, say "we haven't measured that" instead.
- **IF X** lines are said only when condition X is confirmed below.
- Step numbers, titles and lines come from Soham's v2 template (`lessons/templates/fortune-teller-v2.steps.json` and `.voice.json`). Anything marked [[confirm after v2 is cut]] must be checked against `lessons/fortune-teller-v2/lesson.json` once it exists.

## 0. Confirm before 12:45 PM (Pranav reads each one out, the team answers yes or no)

| Code | Question | Answer |
|---|---|---|
| V2 | `fortune-teller-v2` is cut, linted, self-tested and loaded on the demo hub, 9 steps, titles as in section 2 | [[yes/no]] |
| CAMERA STEPS | After the self-test, steps 5, 6, 7 and 9 are still camera steps (not turned manual) | [[yes/no, list any that went manual]] |
| HAND TIMED | The v2 cut points came from Soham's hand-timed steps file (the template note says "Timed by hand from IMG_2450.mov") | [[yes/no]] |
| ONE TAKE | fortune-teller-v2 was cut from one take with no splicing | [[yes/no]] |
| HAND EDITS | How many cut points or titles did we move after the review sheet | [[number]] |
| TAKE DEVICE | What recorded the fortune teller take (Meta glasses or a phone), and who folded it | [[device, person]] |
| PAPER | Sheets ready on the table: pre-folded through step 4, through step 5, through step 8, finished, blank (counts in section 6) | [[yes/no]] |
| SETUP | Black board flat, lamp at the side, phone on its stand pointing straight down, one sheet fills about half the frame | [[yes/no]] |
| CATCH | The planted mistake (skip the flip at step 6) is spoken within 10 s in rehearsal | [[x of y tries]] |
| GLASSES | Meta glasses stream to the hub as the learner camera today (frames on the Learn screen for 60 s) | [[yes/no]] |
| PROVIDER | Check provider and model on the demo hub, from `state.check_mode` (auto = Claude Haiku `claude-haiku-5-5` when an Anthropic key is in .env, else Gemini `gemini-3.5-flash-lite`) | [[confirm provider from state.check_mode]] |
| VOICE | Which provider voiced fortune-teller-v2 and the app cues | [[Kokoro or ElevenLabs, whichever voiced the demo lesson]] |
| DBX | Dashboard loads over the `_real` views and Genie answers "Which step do people get stuck on?" | [[yes/no]] |
| BIKE REC | The bike showcase plays on the demo laptop: Front wheel check open in Teach, and [[bike run recording file]] plays with the Recording label | [[yes/no]] |

If V2 is no, tell Soham right away: every step number and line in section 2 comes from the v2 template and does not match `fortune-teller-v1`. Run v1 with Next on every step and drop the planted mistake beat.
If CATCH is under 3 of 4, drop the planted mistake beat and use the "not caught" line in section 4 if it misses live. Do not make step 6 manual unless it also fails to pass a real flip.
If BIKE REC is no, drop section 2b and never mention the bike at the table.

---

## 1. The lines

One-liner (Devpost, hallway, poster):
> "An expert does a task once on camera. HandOver turns that take into a lesson that plays the right clip for each step and moves on only when the learner's camera shows the step is done."

Hook (open and close with it):
> "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person."

Databricks line (keep word for word):
> "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle."

Privacy line (from docs/PRIVACY.md, word for word):
> "The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go. What we keep is the expert's take and a log of which steps the camera confirmed, which is what the dashboard shows."

---

## 2. The 4-minute script

### Who does what

| Person | Job at the table | Speaks |
|---|---|---|
| **Soham** | Host. Faces the judge, runs the learner beat, hands the judge the paper. | Hook, learner beat, Done screen, contrast, close |
| **Pranav** | Drives the Windows laptop (mouse and keyboard). Never leaves it. Presses Next on manual steps. Starts replay if needed. | Expert beat; fallback lines about the screen |
| **Sikandar** | The learner at the board. Folds step 5, swaps in the step-9 sheet, keeps the phone framed, resets the paper between judges. If the judge won't fold, he folds every step. | Nothing scripted; one line if he swaps cameras |
| **Prayush** | Databricks. Warms the warehouse, owns the dashboard and Genie tabs, keeps his own laptop as backup screen. | Databricks beat, privacy line |

Screens on the demo laptop (Chrome, full screen, tabs left to right): 1 Learn, 2 Teach (Fold a fortune teller, v2, open), 3 Databricks dashboard, 4 Genie (new chat, nothing typed). The bike showcase (section 2b) is not open; Pranav opens it only if asked. Nothing else open, notifications off.

Why we start mid-lesson: the fortune teller has 9 steps and a first-timer needs well over 4 minutes for all of them. Steps 1 to 4 are creases, so we pre-fold them. The judge sees 3 steps live (5, 6 and 7), Pranav presses Next on step 8 (manual), and step 9 closes the lesson on a sheet that already has its step 8 creases.

Starting state when the judge walks up: black board under the lamp, phone on its stand pointing straight down. On the board, one sheet pre-folded through step 4 (a flat square with both diagonal and both straight creases). Next to the board, out of frame, one sheet pre-folded through step 8. Learn tab shows **Fold a fortune teller**, step 5 ("Fold all four corners to the center"), badge **Watching**, live view of the board on the left, the expert's clip looping on the right.

### Script

| Time | Who speaks | Spoken (exact) | Who clicks or does what |
|---|---|---|---|
| 0:00 | Soham | "Hi, we're HandOver." "Think about the person at work who knows a hands-on task cold." "They show the new hire. Then the next one. Then the next one." "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." "We'll show it with paper, so you can try it." | Pranav is on tab 1 (Learn), not touching anything. Sikandar stands by the board, hands off. |
| 0:20 | Pranav | "Here's the expert side." "This is one raw video of someone folding a paper fortune teller." **IF ONE TAKE:** "One take, no editing." "It's nine steps." **IF HAND TIMED:** "We marked where each step ends. The pipeline did the rest." **ELSE:** "The model watched the frames and cut each step at the moment it's done." "Every step gets its own clip, a picture of what done looks like, and one yes or no question for the camera." "Then a voice model reads a short narration over each clip." "Here's step five." (let it play about 5 s) "Raw video in, lesson out." **IF HAND EDITS > 0:** "We moved [[number]] cut points by hand after checking them." **IF BIKE REC:** "The same pipeline cut a bike front wheel check. That one's a recording, and we can show you after." | Pranav: tab 2 (Teach). Fold a fortune teller is open with the steps timeline. Run the mouse along the timeline once, then click step 5 so the clip plays with sound. |
| 0:55 | Soham | "Now the learner side." "The camera is just a phone on a stand, looking down at the board." **IF GLASSES:** "Sikandar's wearing the same kind of Meta glasses, streaming to the laptop." "On the left is what the camera sees. On the right is the expert's clip for the step we're on." "We pre-folded the first four creases to save time. This is step five. Sikandar will do this one, then it's your turn." | Pranav: tab 1 (Learn). Sikandar folds the four corners to the center, presses the flaps flat, takes his hands away. Do not talk while he folds (about 15 to 20 s). |
| 1:20 | Soham | (on the chime and "That's it. Next step.") "Hear that? The camera saw four flaps meeting in the middle, so it moved on by itself." "Nobody pressed anything." "It compares the frame to the expert's before and done pictures. It moves on after two confident yeses, and if it's unsure, it waits. And Next always works." | Badge goes green **Verified**, step 6 clip starts. Pranav points at the badge with the cursor, no click. Sikandar slides the paper toward the judge's side of the board, still in frame. |
| 1:35 | Soham | "Step six is where people slip. You're supposed to flip it over." "Want to try something? Don't flip it. Leave it seams up and take your hands away." | Judge leaves the paper as is. Hands out of frame. |
| 1:40 | Soham | (wait for the spoken line, up to 10 s; say nothing) Then: "That's the expert's warning for this exact step." "If you fold the next corners on the wrong side, the fortune teller won't open." "A video can't tell you that you got it wrong. This one did." "Now flip it over." | The amber banner shows step 6's common_mistake and the lesson voice says it once (browser speech only if the cue audio fails): "Flip it over first. The seams should face down." [[confirm after v2 is cut]] Judge flips the paper, hands away. |
| 1:55 | Soham | (on the chime and "That's it. Next step.") "There. Verified." "Last fold for you. Same as before, all four corners to the center." | Badge green, step 7. Judge folds the four corners in. If they are stuck after about 25 s or it is past 2:25, Sikandar finishes the fold. If it does not pass about 6 s after hands are clear, Pranav presses Next with no comment. |
| 2:25 | Soham | (on the chime) "Step eight is two creases the camera can't see, so we tap Next." "And Sikandar has one with those creases done." | Pranav presses Next (step 8 is manual). Sikandar moves the judge's sheet off the board and puts down the sheet pre-folded through step 8, then opens the four pockets. Badge green on step 9, Done screen. |
| 2:35 | Soham | "Done. That's the time on each step next to the expert's, how many steps the camera checked, how many were marked done by hand, and the mistake it caught." "We started at step five, so the first four show as skipped." [[confirm how the Done screen shows steps 1 to 4]] | Done screen. Pranav points at Checked by camera, Marked done, Mistakes caught. Sikandar hands the judge the finished fortune teller to keep. |
| 2:45 | Prayush | "Every run ends up in Databricks." "This dashboard reads only real camera runs. No mock checks, no replays, no test rows." "Here's time per step, learners against the expert. Here's how often a step was passed by the camera versus by Next. Here are the mistakes it caught, by step." "Then we just ask Genie." "Which step do people get stuck on?" (answer appears) "It names [[step Genie names]]. That's the clip the expert should re-record first." "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle." | Pranav: tab 3 (dashboard). Prayush points at the three widgets. Pranav: tab 4 (Genie), clicks the common question "Which step do people get stuck on?" (click, never type). |
| 3:25 | Prayush | "And notice what's not in there." "The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go. What we keep is the expert's take and a log of which steps the camera confirmed, which is what the dashboard shows." | Pranav: back to tab 1 (Learn). Sikandar starts resetting the paper quietly. |
| 3:40 | Soham | "So how is this different?" "Dozuki turns video into written guides." "Retrocausal tracks steps live, but it needs a fixed station camera and labeled work cycles." "We keep the expert's own video as the instruction, and the learner's camera decides when the next clip plays." "One recording and a phone." | No clicks. |
| 3:52 | Soham | "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." "Thanks. Happy to take questions." | No clicks. |

Pacing rules:
- Silence while hands are folding. One line per chime, not more.
- If the judge has a question mid-demo, answer it in one sentence and continue from the same beat.
- Behind at 2:00 (step 7 not started): Sikandar folds step 7 himself while Soham says nothing.
- Behind at 2:35: skip step 9. Pranav presses Next on 8 and 9, and Soham says "We'll skip the last two for time. Those count as marked done." Then go to Prayush.
- Over time at 2:45: Prayush says only the Databricks line and the Genie click, then the privacy line. Drop the widget tour.
- Over time at 3:40: skip the contrast beat and go straight to the close.

### 2b. Bike showcase (pre-recorded, about 30 seconds)

The bike is never at the table and never live. Use this only when a judge asks "does it work on anything besides paper?", during Q&A, or in place of the contrast beat at 3:40 if the demo ran short. Skip it if BIKE REC is no.

| Who | Spoken (exact) | Does |
|---|---|---|
| Soham | "This is a recording." "Same pipeline, a different job: checking a bike's front wheel. Eleven steps, wheel out, rim and spokes checked, wheel back in, brake tested." | Pranav: tab 2 (Teach), switch to Front wheel check, click step 10 so the produced clip plays (about 5 s, slow zoom and a highlight on the hands). |
| Soham | "Here a learner closed the quick release pointing forward. It said:" (let the recording play the line) "That's the bike version of the flip." | Pranav plays [[bike run recording file]]. The Recording label must be on screen. Line in the recording: "The lever is pointing forward. Fold it back along the fork." [[confirm in lessons/front-wheel-v1/lesson.json]] |
| Soham | "Paper is what we can hand you at a table. The bike is the kind of job we built it for." | Pranav: back to tab 1 (Learn). |

---

## 3. Short versions

Both use a sheet pre-folded through step 5 (flaps up), so the judge goes straight to the flip.

### 30 seconds (hallway, or the judge is leaving)

Soham: "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person. The expert records the job once. We cut it into steps, each with their clip and a check. The learner works under a phone camera, and the next clip plays only when the camera sees the step is done. Skip a fold on this fortune teller and it tells you. Want to see it?"

Pranav, while Soham talks: Learn tab, step 6. Sikandar puts the step-5 sheet on the board, flaps up, so the judge can skip the flip right away.

### 90 seconds (the judge says "you have a minute or two")

| Time | Who | Spoken | Does |
|---|---|---|---|
| 0:00 | Soham | "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." | Learn tab, step 6, step-5 sheet on the board, flaps up |
| 0:10 | Pranav | "This was one raw video of a paper fortune teller. It's nine steps, each with a clip, a picture of done, and a yes or no question. Raw video in, lesson out." | Tab 2, click step 5, 3 s of clip, back to tab 1 |
| 0:30 | Soham | "This one's folded up to the flip. Don't flip it. Hands away." (spoken warning) "That's the expert's warning for this exact step. Now flip it." (chime, "That's it. Next step.") "The camera saw it and moved on." | Judge leaves it, then flips it |
| 1:05 | Prayush | "Every run lands in Databricks. Genie, which step do people get stuck on?" (answer) "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle." | Tab 4, click the question |
| 1:25 | Soham | "And the hub never saves your camera frames. Thanks." | Tab 1 |

---

## 4. Fallback plays

One rule: say what happened in plain words, then take the next rung. Never present a recording as live.

| Failure | What you see | Who says what | What to click or do |
|---|---|---|---|
| Wi-Fi down | Phone page shows reconnecting, or checks time out and the badge stops moving | Soham: "The network dropped. The clips live on the laptop, so the lesson keeps going." | Pranav: switch the laptop and phone to [[backup hotspot name]]; reload the phone capture page. If not back in 20 s, continue with Next. |
| Model down, quota or budget | Badge says **Checks off, use Next** | Soham: "Our vision checks are off for a moment, so we press Next. The breaker turns them back on by itself." | Pranav presses Next on each step. Do not restart the hub. |
| Glasses fail | Learn shows camera lost with the last frame dimmed, or the glasses never connect | Sikandar: "Switching to the phone. Ten seconds." | Sikandar takes off the glasses; phone on the stand opens `https://[[laptop IP]]:8443/capture`, taps Start Camera. Newest camera wins. |
| Phone camera fails | Camera lost, last frame dimmed | Soham: "The camera dropped. Here's a recording of the same steps, and the screen labels it." | Pranav: run `python -m server.replay lessons\fortune-teller-v2\norm.mp4 --loop` [[confirm after v2 is cut]]. The **Recording** tag shows. Say "recording" every time you refer to it. |
| Judge folds it wrong | Fold on the wrong line, corners not at the center, a tear, or the paper got flipped twice. Badge stays **Watching** | Soham: "Paper's forgiving, the camera less so. Here's a fresh one at the same step." | Sikandar swaps in a sheet pre-folded to the current step's start (step-4 sheet for step 5, step-5 sheet for step 6). If a wrong fold already passed, Pranav clicks Back. |
| Bad angle | Paper at the edge of the frame, phone tilted, or hands still in the frame | Nobody speaks. | Sikandar re-centers the paper so it fills about half the frame, phone straight down, hands out of the frame. Checks only run when the picture is still. |
| Lighting | Glare on the paper, a hard shadow, or the badge stays **Watching** over 8 s with a finished fold | Soham: "The light's fighting us. One second." | Sikandar angles the lamp in from the side, never straight down (glare). If still stuck, Pranav presses Next. |
| Lamp dead | No lamp, hall light only | Nobody speaks. | Use [[spare lamp or second phone torch]]. Without one, keep going and expect more waits; Pranav presses Next after about 8 s. |
| Board cluttered or missing | Spare sheets, a phone or a cup in the frame; or no black board | Nobody speaks. | Only the one sheet on the board. Spare sheets stay off the board, out of frame. No board: use [[backup dark surface]]. |
| Databricks slow or cold | Dashboard spinner over 10 s, or Genie still thinking | Prayush: "The warehouse is waking up, so here's the same view from five minutes ago." | Prayush turns his own laptop toward the judge with the dashboard and the saved Genie answer screenshot. If that is down too, skip to the privacy line. |
| Mistake not caught within 10 s | No amber banner, no line read aloud, step 6 still **Watching** | Soham: "It didn't catch it this time. Next always works, and here's a recording where it did." | Pranav presses Next, then plays [[skipped-flip recording file]] with the Recording tag. If it misses twice, drop the planted mistake beat for the rest of judging. |
| Wrong pass (advances before the step is done) | Green **Verified** on a step that is not done | Soham: "That one passed too early. Back fixes it." | Pranav clicks Back. Count it for the Q&A numbers. |
| Teach tab or a clip won't load | Blank Teach page or a frozen clip | Pranav: "That page didn't load, so I'll reload. The lesson is on the laptop." | Ctrl+R once. Still dead: skip to the learner beat and say "the expert side is in the recording if you want it later." |
| Everything down | Hub not responding | Soham: "Our setup is down, so here's a recording of the full demo from this morning." | Play [[backup video file]] on Pranav's laptop or a phone. Never call it live. |
| Judge declines to fold | Judge shakes head | Soham: "No problem. Sikandar will fold, you watch the screen." | Sikandar does steps 6 and 7, including skipping the flip. Script unchanged. |

---

## 5. Judge Q&A

Rule for every answer: what is built, what is not, a measured number or "we haven't measured that". No estimates out loud.

**Accuracy and how it works**

1. **How often does it pass a step you didn't do?**
"In ten real runs by people new to the task, the camera verified [[camera-verified steps]] steps, [[manual steps]] were done by Next, and we saw [[false passes]] false passes and [[false alarms]] false alarms. Unsure never advances, and Back undoes a wrong pass."

2. **How does it decide a step is done?**
"Each check sends a vision model three pictures: the expert's before, the expert's done, and your live frame, with one yes or no question. It moves on after two confident yeses on two different frames, at 0.8 or higher, or one yes at 0.92 or higher that names no difference. A yes that names a difference counts as unsure, and unsure or a timeout never advances."

3. **How does it catch a mistake?**
"After about five seconds of steady no's, it makes one extra comparison against the step before, this step and the next one. If you still look like the step before, it shows this step's mistake line and reads it aloud. It never moves you forward on its own when you're behind."

4. **How reliable is the catch?**
"In rehearsal the skipped flip was caught [[x of y]] times. If it misses, Next always works."

5. **What if the camera angle is different from the expert's?**
"It isn't a pixel match. The question is about the end state, like four flaps meeting in the middle. A very different angle makes it less sure, and unsure means it waits. We tested with the phone on a stand looking straight down at the board; we haven't measured other angles."

6. **What tasks does it fail on?**
"Anything where done isn't visible: torque, tightness, a sound. On the fortune teller, a crease folded and opened again is too faint for the camera, so steps four and eight are manual, and the lesson says so."

**Speed and cost**

7. **How fast is a check?**
"In our timing runs one Claude Haiku check took about 1.1 to 1.3 seconds at the median. Today on this network it's [[venue median check ms]] ms, that number on the dashboard. From hands still to the next clip it's about [[settle to advance s]] seconds."

8. **Why not check every frame?**
"A motion gate only asks the model when the picture is still and has changed, plus a heartbeat every few seconds. That keeps calls down and avoids judging a half-done fold."

9. **What does it cost?**
"About [[cost per check, from python -m server.check --bench]] per check, so a full lesson run is about [[cost per run]]. Claude calls are paid, and the hub has a hard spend cap: 20 dollars a day and 50 total. We haven't priced it at scale."

**Privacy**

10. **Where do the camera frames go?**
"The hub never saves your camera frames. It keeps the newest one in memory, sends it with the expert's reference to the model for one check, and drops it. There's a test that fails if a learner frame ever touches disk."

11. **Does the model provider keep them?**
"They go over the provider's API, whose terms say API data isn't used for training. For a real deployment we'd want an on-device check or a zero-retention agreement. We haven't built that."

12. **What's in Databricks? Any video?**
"Numbers only: run id, lesson, step, check answer, confidence, latency, timestamps. No images, no names, no accounts. The only video that can go to Databricks is the expert's lesson clips."

**Why this, and who else**

13. **Why not just a YouTube video?**
"A video doesn't know where you are. You pause and scrub with paper in both hands. This one waits for you, and it tells you when you skipped the flip."

14. **Why glasses?**
"The expert's hands are busy. Glasses record what they see, with no tripod and no camera operator, and that point of view is what a learner copies. For the learner, any phone works." **IF GLASSES:** "The glasses can be the learner's camera too." **ELSE:** "We use a phone for the learner today."

15. **Who are your competitors?**
"Dozuki turns video into written guides, and checks photos of finished work. Retrocausal tracks steps live, but needs a fixed station camera and labeled cycles. We keep the expert's own clip as the instruction, and a phone decides when the next one plays."

16. **Why origami?**
"It's safe to hand you at a table, every fold leaves a shape a camera can see, and skipping the flip is a real mistake people make. We also cut a bike front wheel check with the same pipeline. That one's a recording." Offer section 2b only if BIKE REC is yes.

**What's real**

17. **What's real and what's mocked?**
"The check you just saw was a real model call; if checks were mocked, the screen shows a Mock checks pill. Replays show a Recording tag, and the bike is a recording. The first four folds were done before you walked up. The dashboard is our own rehearsal runs, filtered to real camera runs only, not users. The narration is [[hand-written by us or written by Claude]] and spoken by [[Kokoro, a local voice model / ElevenLabs]], not the expert's own voice. The coach cues, like "That's it. Next step.", are in the same voice. There's no voice command yet; you press Next."

18. **Which models?**
"[[confirm provider from state.check_mode]] runs each live check. By default that's Claude Haiku when an Anthropic key is set, and Gemini 3.5 Flash-Lite otherwise. The pipeline cuts the clips and picks the reference frames, Claude writes narration when we don't, and [[Kokoro on the laptop / ElevenLabs]] speaks it, with Kokoro as the fallback."

19. **How much of the lesson did a human touch?**
"We wrote the nine-step plan and the check questions." **IF HAND TIMED:** "Soham marked where each step ends by watching the take." "[[confirm: narration lines hand-written by us or written by Claude]]. The pipeline cut the clips and picked the reference frames, and a self-test turns any step it can't check into a manual step. We moved [[hand edits]] cut points after the review. Making the lesson took about [[minutes take to lesson]] minutes."

20. **What did you build this weekend?**
"The pipeline from raw video to a cut, narrated, rendered lesson. The hub that runs the camera checks, the mistake catch and the breaker. The web Learn, Done and Teach screens, and the phone camera page. The Databricks tables, filtered views, dashboard and Genie space." Only add other apps (iPhone, Android, desktop) if asked and only the ones tested today: [[tested apps]].

**Databricks**

21. **What is Databricks actually doing?**
"It's the data layer, never in the live loop. The hub logs every check, advance and caught mistake, and uploads them to Unity Catalog tables about once a minute and at the end of each run. The dashboard reads filtered views, and Genie answers plain-English questions over them. If Databricks is down, the demo doesn't notice; events stay in a local file."

22. **Is my run in there now?**
"It uploads when the run ends, so it shows after a refresh in about a minute. What you see now is our rehearsal runs."

**Next**

23. **What happens if the model goes down?**
"After a few errors or a rate limit, checks turn off for 30 seconds and the badge says Checks off, use Next. The clips are on the laptop, so the lesson still finishes."

24. **Does it scale to a team?**
"Today it's one learner per laptop hub. A lesson is a folder of clips and one JSON file, so it copies easily. Many learners at once needs a hosted hub, which we haven't built."

25. **Who would pay for this?**
"Our guess is teams that onboard people on physical tasks, like bike shops, maintenance and the trades. The expert's time is the expensive part, and this asks for it once. We haven't talked to buyers yet."

26. **What's next?**
"Test it with real learners at a shop, an editor so the expert can fix cuts without us, and an on-device check so frames never leave the room. None of that is built yet."

Numbers you may quote (only once filled):
- Ten real runs: [[runs]] runs, [[camera-verified steps]] camera-verified, [[manual steps]] manual, [[false passes]] false passes, [[false alarms]] false alarms.
- Planted skipped flip caught: [[x of y]].
- Check latency: 1.1 to 1.3 s median in 5-call timing runs (server/README.md); venue [[venue median check ms]] ms.

---

## 6. Logistics

### Paper (prep before 12:30 PM, Soham and Sikandar)

Use the same square paper as the take: [[paper size used in the take]]. One judge visit uses one step-4 sheet. Judging is 90 minutes at about 6 minutes a visit, so plan for about 15 visits.

| Stack | How many | What it is | Used for |
|---|---|---|---|
| A. Through step 4 | 20 | Flat square, both diagonals and both straight creases made, opened flat | The live sheet, one per visit (15 visits plus spares) |
| B. Through step 5 | 6 | Four corners folded to the center, flaps up | 30 s and 90 s versions, and the swap if a judge's step 5 goes wrong |
| C. Through step 8 | 2 to start | Small square, creased in half both ways | Step 9 finale. Refilled during each reset (see below) |
| D. Finished | 2 | A full fortune teller | To show on the table and hand over if the finale is skipped |
| E. Blank | 10 | Plain squares | Judges who want to fold from step 1 after the demo, and rehearsal |

Stack A is about a minute per sheet for someone practiced, so about 20 minutes split between two people. Keep the stacks off the board, out of the camera's view, labeled A to E.

### Setup, 12:00 to 12:45 PM

| Person | Do this |
|---|---|
| Pranav | Stop any stale hub. `scripts\preflight.py` says READY. `scripts\run_server.ps1`. Chrome at `http://[[laptop IP]]:8000/`, tabs 1 to 4 as in section 2. Badge must not show Mock checks. Confirm PROVIDER, V2 and CAMERA STEPS. Confirm BIKE REC plays. Laptop on charger, sleep off. |
| Sikandar | Black board flat, lamp angled in from the side. Phone on its stand, `https://[[laptop IP]]:8443/capture`, Start Camera, pointing straight down, one sheet filling about half the frame, auto-lock off, on charger. **IF GLASSES:** glasses charged and streaming. |
| Soham | Paper stacks A to E (above). One full paper run from step 5 to Done on the demo laptop. Planted flip caught? Fill CATCH. Backup video and skipped-flip recording ready to play. |
| Prayush | `python -m server.databricks --warm` on the demo laptop (prints `warm: ok`). Open the dashboard once so tiles render. Genie: new chat, the common question visible, not sent. Same two tabs on his own laptop. Screenshot of a good Genie answer saved. |
| All | Two full run-throughs, 12:45 to 1:00, someone plays the judge and times it. Fill section 0. |

### Before each judge visit (30 seconds)

| Person | Check |
|---|---|
| Pranav | Learn tab, Fold a fortune teller started fresh, step 5, badge **Watching**, no Recording tag, no Checks off. |
| Sikandar | One stack A sheet on the board, centered. One stack C sheet next to the board, out of frame. Nothing else on the board. Phone framed, battery above 30%. |
| Soham | Finished fortune teller (stack D) on the table to point at. |
| Prayush | If the dashboard or Genie has been idle 10 minutes or more, re-warm (`python -m server.databricks --warm` or `SELECT 1;` in the SQL editor), then reload the dashboard. Genie on a new chat. |

### Reset between judges (under 60 seconds)

1. Sikandar: take the judge's sheet (now through step 7), crease it in half both ways (step 8) and put it on stack C for the next finale. Put a fresh stack A sheet on the board. If the judge kept the finished one, nothing else to do.
2. Pranav: End lesson, pick Fold a fortune teller again (a fresh select starts a new run in Databricks; do not use goto 0), open Steps, pick step 5. Close any replay terminal.
3. Prayush: Genie new chat; note the time for the 10-minute warm rule.
4. Soham: write down anything that went wrong (false pass, missed catch, latency) for the Q&A numbers. Count stack A; under 5 left, Soham pre-folds more between visits.
5. Every 30 minutes: phone, glasses, hotspot batteries.

### Timing

- Judging runs 1:00 to 2:30 PM. Keep each visit to 4 minutes plus questions.
- If a judge says they have 2 minutes, use the 90-second version. If they are walking past, the 30-second one.
- [[confirm on Discord: judging format, table number, how many judges per visit]]

---

## 7. Words

Never say:
- "first", "only", "the first to", "the only one", "nobody else"
- any time or cost saving, any percentage improvement, any user or customer count
- anything about past winners or what judges reward
- a competitor other than Dozuki and Retrocausal by name
- "the expert's own voice" about any narration (it is a synthesized voice)
- "Gemini checks it" unless PROVIDER says gemini (say "a vision model")
- voice commands ("say next"): not built. Spoken cues are built ("That's it. Next step.", the mistake line, "You're ahead of me", done); name the voice provider only as [[Kokoro or ElevenLabs, whichever voiced the demo lesson]]
- "two images" (each check sends three: before, done, live)
- "one take" unless ONE TAKE is yes
- glasses as the live camera unless GLASSES is yes
- the bike as live, or as being at the table (it is a recording)
- that the judge folded the whole thing (we start at step 5 on pre-folded paper; say so)
- Sikandar as a beginner if he folded the expert take (TAKE DEVICE)
- "real-time", "100%", "always accurate", "never wrong", "it understands", "AI watches you"
- "users" for our test runs (say "our rehearsal runs")
- "live" about a replay (say "recording")
- "your run is already in Databricks" (it uploads at run end)
- "Mac" anything; the demo hub is a Windows laptop
- any app or platform not shown working at the table today
- "revolutionary", "seamless", "cutting-edge", "empower", "leverage", "unlock", "game-changer", "disrupt"
- any number still in `[[ ]]`

Say instead:
- "does it once"; "the expert's own clip"; "the lesson watches the next person"
- "a how-to video that waits for you"
- "it only moves on a confident yes; if it's unsure, it waits; Next always works"
- "the hub never saves your camera frames"
- "we pre-folded the first four creases to save time"
- "this is a recording" whenever it is
- "we haven't measured that" or "we haven't built that"
