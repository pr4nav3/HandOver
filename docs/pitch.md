# HandOver pitch (judging Sun 2026-11-15, 1:00 to 2:30 PM)

Owner: Prayush. Rehearsal-ready version for the Windows demo laptop. Where this file and an older doc disagree, docs/HANDOFF.md wins, then this file, then the code.

Live demo: the origami fortune teller, folded at the table. Showcase: the bike front wheel check, pre-recorded and always called a recording (TEAM_RULES.md).

---

## Cheat card (read this if you read nothing else)

**Soham (host)**
1. Open: "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person."
2. On the first chime: "Hear that? Nobody touched the laptop."
3. On the catch: "You still look like step five, so it warned you. A how-to video can't tell you that."
4. Anything breaks: say what happened in plain words, then "Next always works."

**Pranav (laptop)**
5. "Raw video in, lesson out." Then hands visibly off the keyboard until a manual step.

**Prayush (Databricks)**
6. "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle."
7. "The hub never saves your camera frames."

**Everyone, in Q&A**
8. No number we didn't measure. Say "we haven't measured that" or "we haven't built that."

**Never say**
1. "first", "only", "nobody else", or any claim about past winners.
2. Any savings, percentage improvement, user or customer count, or a number still in `[[ ]]`.
3. "Live" about anything recorded (the bike, a replay), or "the expert's voice" about any spoken line (narration is Kokoro, the mistake line is the browser's own voice).

---

Rules for reading this file:
- Lines in quotes are spoken word for word. Everything else is a stage direction.
- `[[like this]]` is a fill-in. Never say a blank out loud. Still blank at 12:45 PM: say "we haven't measured that".
- **IF X** lines are said only when row X in section 0 is yes.
- On-screen text in **bold quotes** is the exact string from `web/src` (Learn.tsx, Done.tsx, StepList.tsx, cues.ts).
- Steps, titles and mistake lines come from `lessons/fortune-teller-v2/lesson.json` (on disk, checked).

## 0. Confirm before 12:45 PM (Pranav reads each one out, the team answers)

What is already checked on disk: `fortune-teller-v2` exists, 9 steps, titled "Fold a fortune teller". Steps 4 and 8 are manual, the other 7 are camera steps. Step 6 is "Flip the folded square over" with the mistake line "Flip it over first. The seams should face down." Narration lines came from Soham's file and were voiced by Kokoro `af_heart`. Cut points came from Soham's hand-timed steps file ("Timed by hand from IMG_2450.mov"). The take was an iPhone video.

| Code | Question | Answer |
|---|---|---|
| V2 | `fortune-teller-v2` loaded on the demo laptop, lint clean, same 9 steps as above | [[yes/no]] |
| CAMERA STEPS | After the self-test, steps 5, 6, 7 and 9 are still camera steps | [[yes/no, list any that went manual]] |
| ONE TAKE | v2 was cut from one take with no splicing | [[yes/no]] |
| HAND EDITS | Cut points or titles moved after the review sheet | [[number]] |
| FOLDER | Who folded in the take (so we never call them a beginner) | [[person]] |
| VOICE | v2 narration still Kokoro (not re-voiced with ElevenLabs) | [[yes/no]] |
| PAPER | Stacks A to E ready, off the board (section 6) | [[yes/no]] |
| SETUP | Black board flat and empty, lamp from the side, phone on its stand pointing straight down | [[yes/no]] |
| CATCH | Step 6 left unflipped: banner and spoken line appear | [[x of y tries]], [[seconds from step 6 start to banner]] |
| SPURIOUS | In rehearsal, a **"Mistake"** banner showed on step 5 or 7 while someone was still folding | [[how many times]] |
| GLASSES | Meta glasses stream to the hub as the learner camera (frames on Learn for 60 s) | [[yes/no]] |
| PROVIDER | `state.check_mode` on the demo hub (auto = Claude Haiku `claude-haiku-5-5` when an Anthropic key is set, else Gemini `gemini-3.5-flash-lite`) | [[claude or gemini]] |
| DBX | `python -m server.databricks --upload fortune-teller-v2` done (Genie and the per-step widgets need its `steps` rows). Dashboard Lesson filter set to `fortune-teller-v2`, not `synthetic-fortune-teller-v1`. Genie answers "Which step do people get stuck on?" | [[yes/no]] |
| BIKE REC | `front-wheel-v1` opens in Teach on the demo laptop (it is not in this repo checkout), and [[bike run recording file]] plays with the Recording label | [[yes/no]] |

If CATCH is under 3 of 4: drop the catch beat and use the "not caught" fallback if it misses live. Do not make step 6 manual unless a real flip also fails.
If BIKE REC is no: drop section 2b and never mention the bike.

---

## 1. The lines

One-liner (Devpost, hallway, poster):
> "An expert does a task once on camera. HandOver turns that take into a lesson that plays the right clip for each step and moves on only when the learner's camera shows the step is done."

Hook (open and close with it):
> "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person."

Databricks line (keep word for word):
> "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle."

Privacy line (docs/PRIVACY.md, word for word; the script uses the first two sentences, Q&A uses all of it):
> "The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go. What we keep is the expert's take and a log of which steps the camera confirmed, which is what the dashboard shows."

---

## 2. The 4-minute script

### Who does what

| Person | Job at the table | Speaks |
|---|---|---|
| **Soham** | Host. Faces the judge, coaches the judge's folds. | Hook, learner beats, Done, close |
| **Pranav** | Drives the laptop. Selects the lesson, presses Next on step 8, never leaves the keyboard. | Expert beat |
| **Sikandar** | At the board. Places the sheet, finishes steps 7 to 9, resets between judges. If the judge won't fold, he folds. | Nothing scripted |
| **Prayush** | Databricks. Keeps the warehouse warm, owns tabs 3 and 4, backup screen on his own laptop. | Databricks, privacy |

Chrome on the demo laptop, full screen, tabs left to right: 1 Lessons/Learn, 2 Teach ("Fold a fortune teller" open), 3 Databricks dashboard (page "Where learners get stuck", Lesson filter `fortune-teller-v2`), 4 Genie (new chat). Nothing else open, notifications off.

Starting state when the judge walks up: tab 1 on the Lessons page (no lesson running). Board empty under the lamp. One stack A sheet (folded through step 4) and one stack C sheet (through step 8) beside the board, out of frame. A finished fortune teller on the table.

Why it starts this way (code facts, do not skip):
- A sheet sitting still on the board makes the hub run checks. After about 5 seconds of "no" it runs the mistake compare and can show a warning before the judge arrives. So the board stays empty until someone folds.
- Every minute a run sits idle counts as learner time on that step in Databricks. So Pranav selects the lesson at 0:50, not before, and ends it after each visit.
- Jumping to step 5 marks step 1 **"Marked done"** and steps 2 to 4 **"Skipped"** on the Done screen. That is expected.

### Script

"(silent)" rows are hands time with nobody talking. Word counts and seconds are in the timing budget below.

| Time | Who | Spoken (exact) | Does |
|---|---|---|---|
| 0:00 | Soham | "Hi, we're HandOver." (hold up the finished fortune teller) "In two minutes you'll fold part of this, and a camera will decide when you're done." "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." | Pranav: tab 2 (Teach), Fold a fortune teller already open. |
| 0:20 | Pranav | "Here's the expert side: one phone video of someone folding a fortune teller." **IF ONE TAKE:** "One take." "We marked where each of the nine steps ends. The pipeline made the rest: a clip per step, a picture of done, a yes or no question for the camera, and narration." "Here's step five." (clip plays about 4 s) "Raw video in, lesson out." | Run the mouse along the step timeline once, click step 5 so it plays with sound. |
| 0:48 | Soham | "Now the learner side: a phone on a stand, looking down." **IF GLASSES:** "Sikandar's glasses can stream too." "Left is the live camera, right is the expert's clip. We folded steps one to four ahead of time. Step five is yours: all four corners to the center." "Pranav, hands off." | Pranav: tab 1, click **Fold a fortune teller**, click step 5 in the step list, then lifts both hands off the laptop. Badge reads **"Watching"**. Sikandar puts the stack A sheet on the board in front of the judge. |
| 1:06 | (silent) | Nobody talks while the judge folds. Soham may point at a corner, no words. | Judge folds step 5, takes hands away. If stuck at 30 s, Sikandar finishes it. Chime and **"That's it. Next step."** at about 1:31. |
| 1:31 | Soham | "Hear that? Nobody touched the laptop. It saw your four flaps meet in the middle, so it played the next clip." "Step six is a flip. Leave it for a moment. Hands off." | Badge flashes **"Verified"**, step 6 clip plays. Pranav's hands stay up. Judge leaves the paper seams up. |
| ~1:45 | (silent) | Wait for the banner. If it appears while you're talking, stop mid-sentence. | Amber card labeled **"Mistake"** with **"Flip it over first. The seams should face down."** and buttons **"Show step 5"** and **"OK"**. The browser's built-in voice reads the line once (it is not the Kokoro voice). The step-6 segment of the progress bar turns amber. |
| 1:48 | Soham | "It's been watching, and you still look like step five, so it warned you." "Fold the next corners on the wrong side, and the fortune teller won't open." "A how-to video can't tell you that. Now flip it." | Judge flips, hands away. Chime at about 2:09. Do not press OK; the card clears on the advance. |
| 2:09 | Soham | "Verified. It moves on only after confident yeses. If it's unsure, it waits, and Next always works." "Sikandar will finish the last steps." "Step eight is creases a camera can't see, so that's a Next." | Sikandar folds step 7 on the judge's sheet (about 12 s), hands away, chime. Then he swaps in the stack C sheet; Pranav presses Next (step 8 is manual); Sikandar opens the four pockets, hands away. Chime and **"That's the whole thing. Nicely done."** If step 7 or 9 doesn't pass 6 s after hands are clear, Pranav presses Next, no comment. |
| 2:39 | Soham | "Done. Your time on each step next to the expert's, which steps the camera checked, and the mistake it caught." "You keep that one." | Done screen **"Lesson complete"**. Pranav points at **"Mistakes caught"** and the step bars. Sikandar hands the judge the fortune teller from the board. |
| 2:49 | Prayush | "Every real run lands in Databricks. This is what the expert sees." "Time per step against the expert. Camera or Next, per step. Mistakes caught, per step." "Or the expert just asks Genie." "Which step do people get stuck on?" (answer appears) "It says step [[n]], [[title]]." **IF it names step 6:** "Part of that is us: we ask every judge to skip the flip. But that's the point. The expert sees which step to re-record or warn about." "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle." | Pranav: tab 3. Prayush points at "Time per step: learners vs the expert", "How each step was passed", "Mistakes the camera caught, per step". Pranav: tab 4, clicks the sample question button (never type). |
| 3:35 | Prayush | "And there's no video of you in there. The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go." | Pranav: back to tab 1. Sikandar starts the reset quietly. |
| 3:48 | Soham | "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." "Thanks. Happy to take questions." | No clicks. |

### Timing budget

| Beat | Spoken words | Speech s | Silent s (not overlapped) | Total s | Ends |
|---|---|---|---|---|---|
| Hook | 40 | 17 | 0 | 17 | 0:17 (start Pranav at 0:20) |
| Expert side | 55 (with ONE TAKE) | 24 | 4 (clip) | 28 | 0:48 |
| Learner setup | 42 (48 with GLASSES) | 18 | 0 (clicks during speech) | 18 | 1:06 |
| Judge folds step 5, check | 0 | 0 | 25 | 25 | 1:31 |
| Auto-advance | 33 | 14 | 0 | 14 | 1:45 |
| Wait for the catch | 0 | 0 | 3 | 3 | 1:48 |
| Catch, judge flips | 38 | 16 | 5 | 21 | 2:09 |
| Sikandar finishes 7 to 9 | 35, spoken over the hands | (inside) | 30 | 30 | 2:39 |
| Done | 24 | 10 | 0 | 10 | 2:49 |
| Databricks | 95 (68 if Genie doesn't name step 6) | 41 | 5 (Genie answers) | 46 | 3:35 |
| Privacy | 30 | 13 | 0 | 13 | 3:48 |
| Close | 26 | 11 | 0 | 11 | 3:59 |
| **Total** | **424 at most** | **about 164** | **about 72** | **about 3:59** | |

Speech is counted at 140 words a minute. There is no slack: one extra sentence anywhere means using a pacing rule below. If Genie names another step, the Databricks beat is about 12 s shorter and the close lands near 3:47.

The budget only holds if nobody adds a sentence. The contrast beat (Dozuki, Retrocausal) is now Q&A material (section 5, Q11). Say it before the close only if you reach privacy before 3:30.

### Pacing rules
- Silence while the judge's hands are folding. One line per chime, not more.
- A judge question mid-demo: one-sentence answer, then continue from the same beat.
- Behind at 1:40 (step 5 not passed): Sikandar finishes it, Pranav presses Next if needed.
- Behind at 2:25 (step 7 not passed): Pranav presses Next on 7, 8 and 9. Soham: "We'll skip the last steps for time. Those count as marked done." Go to Prayush.
- Behind at 2:55: Prayush says only "Every real run lands in Databricks.", clicks the Genie question, reads the answer, then the Databricks line. Drop the widget tour.
- Behind at 3:40: drop privacy, go to the close.

### 2b. Bike showcase (pre-recorded, about 30 seconds)

Never at the table, never live. Use only when a judge asks "does it work on anything besides paper?", in Q&A, or if the demo ends before 3:30. Skip if BIKE REC is no.

| Who | Spoken (exact) | Does |
|---|---|---|
| Soham | "This is a recording." "Same pipeline, a different job: checking a bike's front wheel. Wheel out, rim and spokes checked, wheel back in, brake tested." | Pranav: tab 2, switch to Front wheel check, click step 10 so the produced clip plays (slow push-in and a highlight on the hands). |
| Soham | "Here a learner closed the quick release pointing forward." (let the recording play the line) "That's the bike version of the flip." | Pranav plays [[bike run recording file]], **"Recording"** tag on screen. Line: [[confirm step 10 common_mistake in lessons/front-wheel-v1/lesson.json; the template says "Fold the lever back along the fork. A lever pointing forward can catch on something and open."]] |
| Soham | "Paper is what we can hand you at a table. The bike is the kind of job we built it for." | Back to tab 1. |

---

## 3. Short versions

Both start with step 6 as the current step and the board empty. Sikandar puts a stack B sheet (through step 5, flaps up) on the board only when Soham says "hands off". The catch fires on its own about 5 to 10 seconds later.

### 30 seconds (hallway, or the judge is leaving)

Soham: "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person. The expert records the job once, and it's cut into steps, each with a clip and a camera check. The learner works under a phone, and the next clip plays only when the camera sees the step is done. Want to see it catch a mistake?"

### 90 seconds (the judge says "you have a minute or two")

| Time | Who | Spoken | Does |
|---|---|---|---|
| 0:00 | Soham | "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." | Pranav: Fold a fortune teller, step 6 |
| 0:10 | Pranav | "This was one phone video of a fortune teller. Nine steps, each with a clip, a picture of done and a yes or no question. Raw video in, lesson out." | Tab 2, step 5 clip for 3 s, back to tab 1 |
| 0:25 | Soham | "This one's folded up to the flip, and nobody has flipped it. Hands off." (banner and spoken line) "It saw you're still on step five. Now flip it." (chime) "Verified. Nobody touched the laptop." | Sikandar places the stack B sheet; judge flips after the line |
| 1:00 | Prayush | "Every real run lands in Databricks. Genie, which step do people get stuck on?" (answer) "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle." | Tab 4, click the question |
| 1:25 | Soham | "And the hub never saves your camera frames. Thanks." | Tab 1 |

---

## 4. Fallback plays

One rule: say what happened in plain words, then take the next rung. Never present a recording as live.

| Failure | What you see | Who says what | What to do |
|---|---|---|---|
| Wi-Fi down | **"Reconnecting"** note, or the badge stops moving | Soham: "The network dropped. The clips are on the laptop, so the lesson keeps going." | Pranav: laptop and phone to [[backup hotspot name]], reload the phone capture page. Not back in 20 s: continue with Next. |
| Model down, rate limit or budget | Badge **"Checks off, use Next"** with a reason: **"Rate limited"**, **"Check errors"**, **"AI budget reached"** or **"No API key"**. Spoken: "I can't see well right now. Tap Next when you're done." | Soham: "Our vision checks are off right now, so we press Next." | Pranav presses Next on each step. Errors and rate limits retry after 30 s on their own; budget and a missing key do not, so don't wait. Don't restart the hub mid-demo. |
| Glasses fail | **"Camera lost"**, **"Keep going with Next."**, last frame dimmed | Sikandar: "Switching to the phone. Ten seconds." | Phone on the stand opens `https://[[laptop IP]]:8443/capture`, taps Start Camera. Newest camera wins. |
| Phone camera fails | Same **"Camera lost"** card; spoken "I lost the camera. Keep going with Next." | Soham: "The camera dropped. Here's a recording of the same steps, and the screen labels it." | Pranav: `python -m server.replay lessons\fortune-teller-v2\norm.mp4 --loop`. The **"Recording"** tag shows. Say "recording" every time. Replay runs never reach the dashboard. |
| Spurious warning while folding | **"Mistake"** card on step 5 or 7 while hands are still working | Soham: "It thinks that fold isn't finished yet. Keep going." | Pranav clicks **"OK"**. Count it for Q&A. |
| Judge folds it wrong | Fold on the wrong line, a tear, flipped twice; badge stays **"Watching"** | Soham: "Paper's forgiving, the camera less so. Here's a fresh one at the same step." | Sikandar swaps in the sheet for the current step's start (A for step 5, B for step 6). If a wrong fold already passed, Pranav clicks **"Back"**. |
| Bad angle | Paper at the frame edge, phone tilted, hands in frame | Nobody speaks. | Sikandar re-centers, phone straight down, hands out. Checks wait for a still picture. |
| Lighting | Glare, hard shadow, or **"Watching"** over 8 s on a finished fold | Soham: "The light's fighting us. One second." | Lamp in from the side, never straight down. Still stuck: Next. |
| Board cluttered or missing | Spare sheets, phone or cup in frame | Nobody speaks. | One sheet on the board, nothing else. No board: [[backup dark surface]]. |
| Databricks slow | Spinner over 10 s, or Genie still thinking | Prayush: "The warehouse is waking up, so here's the same view from a few minutes ago." | Prayush turns his laptop with the dashboard and the saved Genie screenshot. That's down too: skip to privacy. |
| Mistake not caught in 10 s | No card, no line, step 6 still **"Watching"** | Soham: "It didn't catch it this time. Next always works, and here's a recording where it did." | Pranav presses Next, plays [[skipped-flip recording file]] with the Recording tag. Missed twice: drop the beat for the rest of judging. |
| Wrong pass | **"Verified"** on a step that isn't done | Soham: "That one passed too early. Back fixes it." | Pranav clicks **"Back"**. The dashboard counts it as a false pass. |
| Teach tab or clip won't load | Blank page or frozen clip | Pranav: "That page didn't load, so I'll reload it." | Ctrl+R once. Still dead: skip to the learner beat. |
| Everything down | Hub not responding | Soham: "Our setup is down, so here's a recording of the full demo from this morning." | Play [[backup video file]]. Never call it live. |
| Judge won't fold | Judge shakes head | Soham: "No problem. Sikandar will fold, you watch the screen." | Sikandar does it all. Script unchanged. |

---

## 5. Judge Q&A

Rule: one to three sentences. What is built, what is not, a measured number or "we haven't measured that". No estimates out loud.

**How it works**

1. **How does it decide a step is done?**
"Each check sends a vision model the expert's before picture, the expert's done picture and your live frame, with one yes or no question. A yes under 0.8 confidence counts as unsure. It moves on after two confident yeses on two different frames, or one yes at 0.92 or higher where the model says nothing differs from the done picture. Unsure, no, or a timeout never moves you on."

2. **How do you stop false passes?**
"Five layers. The before picture is in every check, and the model is told to say no if you still look like it. It needs two confident yeses on different frames. It only checks when the picture is still. When we build a lesson, a self-test turns steps the model can't tell apart into manual steps. And Back undoes a wrong pass, which the dashboard counts. In our runs we saw [[false passes]] false passes in [[runs]] runs."

3. **How does it catch a mistake?**
"After about five seconds of no's on one step, it makes one extra comparison: do you look like the step before, this step or the next one? If you look like the step before, it shows that step's mistake line and reads it out. It never moves you forward on its own when you're behind."

4. **How reliable is the catch?**
"In rehearsal the unflipped square was caught [[x of y]] times. If it misses, Next always works."

5. **What if the paper is a different color, or the angle is different?**
"The model is told to ignore color, size, position and lighting and judge only folds, outline and layers, and no check question mentions color. We tested with [[paper used in the take]] and a phone looking straight down. We haven't measured other colors or angles. Less sure means it waits."

6. **Did you train a model?**
"No. Each check is a prompt with the expert's reference pictures and one question. A new task needs a new recording, not training data."

7. **What tasks does it fail on?**
"Anything where done isn't visible: torque, tightness, a sound. On this one, a crease folded and opened again is too faint, so steps four and eight are manual, and the screen says so."

8. **Can it work for other tasks?**
"Anything where done is visible to a camera. We've cut two: this one, and a bike front wheel check, which is a recording." **IF BIKE REC:** offer section 2b.

**Why this**

9. **Why not just a video?**
"A video doesn't know where you are. You pause and scrub with paper in both hands. This plays the next clip when you're done, waits when you're not, and tells you when you're still on the step before. And the expert finds out which step people struggle with."

10. **Why glasses?**
"The expert's hands are busy, and glasses record what they see, with no tripod. This take was on a phone. For the learner, any phone works." **IF GLASSES:** "The glasses can be the learner's camera too."

11. **Who are your competitors?**
"Dozuki turns video into written guides, and checks photos of finished work. Retrocausal tracks steps live, but needs a fixed station camera and labeled cycles. We keep the expert's own clip as the instruction, and a phone decides when the next one plays."

12. **Why origami?**
"It's safe to hand you at a table, every fold leaves a shape a camera can see, and forgetting the flip is a real mistake people make."

**Speed and cost**

13. **How fast is a check?**
"In our timing runs one Claude Haiku check took about 1.1 to 1.3 seconds at the median. Today it's [[venue median check ms]] ms, the Check p50 tile on the dashboard. From hands still to the next clip it's about [[settle to advance s]] seconds."

14. **Why not check every frame?**
"A motion gate asks the model only when the picture is still and has changed, plus a check every six seconds. That keeps calls down and avoids judging a half-done fold."

15. **What does it cost?**
"About [[cost per check]] per check, so a lesson run is about [[cost per run]]. The hub has a hard Claude spend cap, 20 dollars a day and 50 total. We haven't priced it at scale."

**Privacy**

16. **Where do the camera frames go?**
"The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go. What we keep is the expert's take and a log of which steps the camera confirmed, which is what the dashboard shows. A test fails if a learner frame ever touches disk."

17. **Does the model provider keep them?**
**IF PROVIDER is claude:** "They go to Anthropic's API, which doesn't train on API data by default." **IF gemini:** "They go to Google's Gemini API, and on the free tier Google's terms allow review of inputs." Both: "For a real deployment we'd want an on-device check or a zero-retention agreement. We haven't built that."

18. **What's in Databricks? Any video?**
"Event rows: run id, lesson, step, check answer, confidence, latency, timestamps, and a few words on what the model saw differ, like 'seams up'. No images, no names; nobody signs in at the demo. The only video there is the expert's lesson clips."

**What's real**

19. **What's real and what's mocked?**
"The checks you just saw were real model calls. Simulated checks would say **'Simulated checks'** next to the badge, and those runs never reach Databricks. Replays show a **'Recording'** tag, and the bike is a recording. Steps one to four were folded before you walked up. The dashboard is our rehearsal runs and today's judge runs, real camera runs only. We wrote the narration; Kokoro, a voice model on the laptop, speaks it. The mistake warning is read by the browser's built-in voice. There's no voice command; you press Next."

20. **Which models?**
"[[claude or gemini, from PROVIDER]] runs each live check: Claude Haiku when an Anthropic key is set, Gemini 3.5 Flash-Lite otherwise. Kokoro speaks the narration. For this lesson we timed the cuts by hand." **IF the bike was cut by vision boundaries:** "The bike was cut by a model that finds the moment each step is done."

21. **How much of the lesson did a human touch?**
"We wrote the nine steps, check questions, mistake lines and narration, and Soham marked where each step ends. The pipeline normalized the video, cut the clips, picked the done pictures and voiced the lines. We moved [[hand edits]] cut points after review. Making it took about [[minutes take to lesson]] minutes."

22. **What did you build this weekend?**
"The pipeline from raw video to a cut, narrated lesson. The hub that runs the camera checks, the mistake catch and the breaker. The Learn, Done and Teach screens and the phone camera page. The Databricks tables, filtered views, dashboard and Genie space." Other apps only if asked and only those tested today: [[tested apps]].

**Databricks**

23. **What is Databricks doing?**
"It's the data layer, never in the live loop. The hub logs every check, advance and caught mistake, and sends them to Unity Catalog tables at most once a minute and right when a run ends. The dashboard reads filtered views without replays or simulated runs, and Genie answers plain-English questions over them. If Databricks is down, the demo doesn't notice; events stay in a local file."

24. **Why Databricks and not a spreadsheet?**
"For one laptop a file would do. The point is many hubs writing to one place, and an expert who doesn't write SQL asking Genie which step to fix."

25. **Is my run in there now?**
"It's sent when your run finishes, so after a refresh in about a minute. What you saw was our earlier runs."

**Next**

26. **What happens if the model goes down?**
"After three errors in a row or any rate limit, checks turn off for 30 seconds and the badge says 'Checks off, use Next'. The clips are on the laptop, so the lesson still finishes."

27. **Does it scale to a team?**
"Today it's one learner per laptop hub. A lesson is a folder of clips and one JSON file, so it copies easily. Many learners at once needs a hosted hub, which we haven't built."

28. **Who would pay for this?**
"Our guess is teams that onboard people on physical tasks, like bike shops, maintenance and the trades. The expert's time is the expensive part, and this asks for it once. We haven't talked to buyers yet."

29. **What's next?**
"Test it with real learners at a shop, let the expert fix cuts without us, and an on-device check so frames never leave the room. None of that is built yet."

Numbers you may quote (only once filled):
- Real runs: [[runs]] runs, [[camera-verified steps]] camera-verified, [[manual steps]] by Next, [[false passes]] false passes, [[false alarms]] false alarms.
- Unflipped square caught: [[x of y]].
- Check latency: 1.1 to 1.3 s median in 5-call timing runs (server/README.md); venue [[venue median check ms]] ms.

---

## 6. Logistics

### Paper (prep before 12:30 PM, Soham and Sikandar)

Same square paper as the take: [[paper size used in the take]]. About 15 visits in 90 minutes.

| Stack | How many | What it is | Used for |
|---|---|---|---|
| A. Through step 4 | 20 | Flat square, both diagonals and both straight creases, opened flat | The judge's sheet, one per visit |
| B. Through step 5 | 6 | Four corners at the center, flaps up | 30 s and 90 s versions, swaps |
| C. Through step 8 | 2 to start | Small square, creased in half both ways | Step 9 finale; refilled every reset |
| D. Finished | 2 | A full fortune teller | Hook prop; hand over if the finale is skipped |
| E. Blank | 10 | Plain squares | Judges who want to fold from step 1 after |

All stacks off the board, out of frame, labeled A to E.

### Setup, 12:00 to 12:45 PM

| Person | Do this |
|---|---|
| Pranav | Stop any stale hub. `scripts\preflight.py` says READY. `scripts\run_server.ps1`. Chrome at `http://[[laptop IP]]:8000/`, tabs 1 to 4. No **"Simulated checks"** text by the badge. Confirm V2, CAMERA STEPS, PROVIDER, BIKE REC. Charger in, sleep off. |
| Sikandar | Board flat and empty, lamp from the side. Phone on its stand at `https://[[laptop IP]]:8443/capture`, Start Camera, straight down, auto-lock off, on charger. **IF GLASSES:** glasses charged and streaming. |
| Soham | Paper stacks. One full run from step 5 to Done. Fill CATCH and SPURIOUS. Backup video and skipped-flip recording ready. |
| Prayush | `python -m server.databricks --upload fortune-teller-v2` if not done. `python -m server.databricks --warm` (prints `warm: ok`). Open the dashboard, set Lesson to `fortune-teller-v2`. Genie: new chat. Same two tabs on his laptop. Screenshot a good Genie answer. |
| All | Two timed run-throughs, 12:45 to 1:00, someone plays the judge. Fill section 0. |

### Before each judge visit (30 seconds)

| Person | Check |
|---|---|
| Pranav | Tab 1 on the Lessons page, no lesson running. Tab 2 on Fold a fortune teller. |
| Sikandar | Board empty. One stack A and one stack C sheet beside it, out of frame. Phone framed, battery above 30%. |
| Soham | Finished fortune teller in hand for the hook. |
| Prayush | Idle 10 minutes or more: re-warm, reload the dashboard. Genie on a new chat. |

### Reset between judges (under 60 seconds)

1. Pranav: **"End lesson"** on tab 1 (an idle run inflates step times on the dashboard). Close any replay terminal.
2. Sikandar: take the judge's leftover sheet if any (through step 7), crease it in half both ways and put it on stack C. Board empty.
3. Prayush: Genie new chat; note the time for the 10-minute warm rule.
4. Soham: write down any false pass, missed catch, spurious warning or slow check for the Q&A numbers. Stack A under 5: fold more.
5. Every 30 minutes: phone, glasses and hotspot batteries.

### Timing
- Judging 1:00 to 2:30 PM. Four minutes plus questions.
- Judge says 2 minutes: 90-second version. Walking past: 30-second version.
- [[confirm on Discord: judging format, table number, judges per visit]]

---

## 7. Words

Never say:
- "first" as a claim, "only", "the first to", "the only one", "nobody else" (ordinals are fine as "steps one to four")
- any time or cost saving, any percentage improvement, any user or customer count
- anything about past winners or what judges reward
- a competitor other than Dozuki and Retrocausal by name
- "the expert's own voice" about any spoken line; narration is Kokoro (or [[ElevenLabs if VOICE changed]]), the mistake line is the browser's built-in voice
- "Gemini checks it" unless PROVIDER says gemini (say "a vision model")
- voice commands ("say next"): not built
- "two images" (most checks send three: before, done, live)
- "one take" unless ONE TAKE is yes
- glasses as the live camera unless GLASSES is yes; the v2 take was a phone video
- the bike as live, or as being at the table
- that the judge folded the whole thing (we start at step 5 on pre-folded paper; say so)
- the folder of the take as a beginner (FOLDER)
- "real-time", "100%", "always accurate", "never wrong", "it understands", "AI watches you"
- "users" for our test runs (say "our rehearsal runs")
- "live" about a replay (say "recording")
- "your run is already in Databricks" (it is sent when the run ends)
- "Mac" anything; the demo hub is a Windows laptop
- any app or platform not shown working at the table today
- "revolutionary", "seamless", "cutting-edge", "empower", "leverage", "unlock", "game-changer", "disrupt"
- any number still in `[[ ]]`

Say instead:
- "does it once"; "the expert's own clip"; "the lesson watches the next person"
- "a how-to video that waits for you"
- "it only moves on a confident yes; if it's unsure, it waits; Next always works"
- "the hub never saves your camera frames"
- "we folded steps one to four ahead of time"
- "this is a recording" whenever it is
- "we haven't measured that" or "we haven't built that"
