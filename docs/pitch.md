# HandOver pitch (judging Sun 2026-11-15, 1:00 to 2:30 PM)

Owner: Prayush. Rehearsal-ready version for the Windows demo. Where this file and an older doc disagree, docs/HANDOFF.md wins, then this file.

Rules for reading this file:
- Lines in quotes are spoken word for word. Everything else is a stage direction.
- `[[like this]]` is a fill-in. Do not say a blank out loud. If it is still blank at 12:45 PM, say "we haven't measured that" instead.
- **IF X** lines are said only when condition X is confirmed below.

## 0. Confirm before 12:45 PM (Pranav reads each one out, the team answers yes or no)

| Code | Question | Answer |
|---|---|---|
| BIKE | A bike with a quick release front wheel and rim brake is at the table, on a stand, and the camera can see the fork | [[yes/no]] |
| ONE TAKE | front-wheel-v1 was cut from one take with no splicing | [[yes/no]] |
| HAND EDITS | How many bike cut points or titles did we move by hand after the review sheet | [[number]] |
| TAKE DEVICE | What recorded the bike take (Meta glasses or a phone), and who did it | [[device, person]] |
| CATCH | The planted mistake (lever closed pointing forward) is spoken within 10 s in rehearsal | [[x of y tries]] |
| GLASSES | Meta glasses stream to the hub as the learner camera today (frames on the Learn screen for 60 s) | [[yes/no]] |
| PROVIDER | Check provider and model on the demo hub, from `state.check_mode` (auto = Claude Haiku `claude-haiku-5-5` when an Anthropic key is in .env, else Gemini `gemini-3.5-flash-lite`) | [[confirm provider from state.check_mode]] |
| DBX | Dashboard loads over the `_real` views and Genie answers "Which step do people get stuck on?" | [[yes/no]] |
| ORIGAMI | Which origami lesson is loaded for the paper swap | [[fortune-teller-v1 or v2]] |

If BIKE is no, run the paper swap in section 2b for the whole learner beat. If CATCH is under 3 of 4, make step 10 manual (`check_question: "manual"`) and use the "not caught" line in section 4.

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
| **Soham** | Host. Faces the judge, runs the learner beat, hands the judge the lever. | Hook, learner beat, Done screen, contrast, close |
| **Pranav** | Drives the Windows laptop (mouse and keyboard). Never leaves it. Starts replay if needed. | Expert beat; fallback lines about the screen |
| **Sikandar** | The learner at the bike. Seats the wheel. Resets the bike between judges. Keeps the phone camera framed. | Nothing scripted; one line if he swaps cameras |
| **Prayush** | Databricks. Warms the warehouse, owns the dashboard and Genie tabs, keeps his own laptop as backup screen. | Databricks beat, privacy line |

Screens on the demo laptop (Chrome, full screen, tabs left to right): 1 Learn, 2 Teach (Front wheel check open), 3 Databricks dashboard, 4 Genie (new chat, nothing typed). Nothing else open, notifications off.

Starting state when the judge walks up: bike on the stand, front wheel out of the fork, skewer back in the wheel with the lever open. Learn tab shows **Front wheel check**, step 9 ("Lower the fork onto the axle so it seats in both slots"), badge **Watching**, live view of the fork on the left, the expert's clip looping on the right.

### Script

| Time | Who speaks | Spoken (exact) | Who clicks or does what |
|---|---|---|---|
| 0:00 | Soham | "Hi, we're HandOver." "Think about the person at a bike shop who knows how to check a front wheel." "They show the new hire. Then the next one. Then the next one." "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." | Pranav is on tab 1 (Learn), not touching anything. Sikandar stands by the bike, hands off. |
| 0:20 | Pranav | "Here's the expert side." "This is one raw video of a front wheel check. Wheel out, rim and spokes checked, wheel back in, brake tested." **IF ONE TAKE:** "One take, no editing." "We gave it a plan of eleven steps. The model watched the frames and cut each step at the moment it's done." "Every step gets its own clip, a picture of what done looks like, and one yes or no question for the camera." "Then it writes a short narration for each step, a local voice model reads it, and it renders the clip with a slow zoom and a highlight on the hands." "Here's step ten." (let it play about 5 s) "Raw video in, lesson out." **IF HAND EDITS > 0:** "We moved [[number]] cut points by hand after checking them." | Pranav: tab 2 (Teach). Front wheel check is open with the steps timeline. Run the mouse along the timeline once, then click step 10 so the produced clip plays with sound. |
| 0:55 | Soham | "Now the learner side." "Sikandar has never [[confirm: done this lesson / seen this clip]]." "The camera is just a phone on a stand, pointed at the fork." **IF GLASSES:** "He's wearing the same kind of Meta glasses, streaming to the laptop." "On the left is what the camera sees. On the right is the expert's clip for the step he's on." "He's at step nine. Put the wheel back in." | Pranav: tab 1 (Learn). Sikandar lowers the fork onto the axle and takes his hands away. Do not talk over the next 5 s. |
| 1:10 | Soham | (on the chime and "That's it. Next step.") "Hear that? The camera saw the axle seated in both slots, so it moved on by itself." "Nobody pressed anything." "It compares his frame to the expert's before and done pictures. It moves on after two confident yeses, and if it's unsure, it waits. And Next always works." | Badge goes green **Verified**, step 10 clip starts. Pranav points at the badge with the cursor, no click. |
| 1:25 | Soham | "Step ten is the one that matters. Closing the quick release." "Want to try it? Close the lever, but point it forward, like a lot of people do." | Soham hands the judge the lever side. Sikandar shows where the lever is. If the judge says no, Sikandar does it. Hands away after closing. |
| 1:35 | Soham | (wait for the spoken line, up to 10 s; say nothing) Then: "That's the expert's warning for this exact step." "A lever pointing forward can catch on something and open." "A video can't tell you that you got it wrong. This one did." "Now fold it back along the fork." | The amber banner shows the step's common_mistake and the lesson voice says it once (browser speech only if the cue audio fails) ([[confirm exact text in lessons/front-wheel-v1/lesson.json]]). Judge or Sikandar folds the lever back, hands away. |
| 1:55 | Soham | (on the chime) "There. Verified." "Last step is spin and brake." | Badge green, step 11. Sikandar spins the wheel and squeezes the brake. If it does not pass in about 6 s, Pranav presses Next with no comment. |
| 2:10 | Soham | "Done. That's the learner's time next to the expert's, how many steps the camera checked, how many were marked done by hand, and the mistake it caught." | Done screen. Pranav points at Checked by camera, Marked done, Mistakes caught. |
| 2:25 | Prayush | "Every run ends up in Databricks." "This dashboard reads only real camera runs. No mock checks, no replays, no test rows." "Here's time per step, learners against the expert. Here's how often a step was passed by the camera versus by Next. Here are the mistakes it caught, by step." "Then we just ask Genie." "Which step do people get stuck on?" (answer appears) "It names [[step Genie names]]. That's the clip the expert should re-record first." "So: raw expert video in, a structured lesson out, every learner run lands as rows, and Genie tells the expert where people struggle." | Pranav: tab 3 (dashboard). Prayush points at the three widgets. Pranav: tab 4 (Genie), clicks the common question "Which step do people get stuck on?" (click, never type). |
| 3:15 | Prayush | "And notice what's not in there." "The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go. What we keep is the expert's take and a log of which steps the camera confirmed, which is what the dashboard shows." | Pranav: back to tab 1 (Learn). Sikandar starts resetting the bike quietly. |
| 3:35 | Soham | "So how is this different?" "Dozuki turns video into written guides." "Retrocausal tracks steps live, but it needs a fixed station camera and labeled work cycles." "We keep the expert's own video as the instruction, and the learner's camera decides when the next clip plays." "One recording and a phone." | No clicks. |
| 3:50 | Soham | "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." "Thanks. Happy to take questions." | No clicks. |

Pacing rules:
- Silence while hands are working. One line per chime, not more.
- If the judge has a question mid-demo, answer it in one sentence and continue from the same beat.
- Over time at 2:25: Prayush says only the Databricks line and the Genie click, then the privacy line. Drop the widget tour.
- Over time at 3:35: skip the contrast beat and go straight to the close.

### 2b. Paper swap (no bike, or the judge wants to fold)

Same timings. Replace the 0:55 to 2:10 beats with the [[ORIGAMI lesson id]] lesson, paper on the board, phone on the stand pointing down.
- Soham: "Want to fold a fortune teller? Paper on the board. Copy the hands on the right." On a camera step: "Hear that? It saw your fold and moved on." Manual steps: "This one the camera can't judge, so tap Next."
- Planted mistake, the flip step: "Try this. Skip the flip and keep going." The banner shows and the browser reads "Flip it over first. The seams should face down." ([[confirm the line in the loaded lesson.json]])
- Pranav starts the lesson at the step before the first camera-checked fold so the judge sees an auto-advance within 30 s.

---

## 3. Short versions

### 30 seconds (hallway, or the judge is leaving)

Soham: "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person. The expert records the job once. We cut it into steps, each with their clip and a check. The learner works under a phone camera, and the next clip plays only when the camera sees the step is done. Close a bike's quick release the wrong way and it tells you. Want to see it?"

Pranav, while Soham talks: Learn tab, step 10, so the judge can close the lever right away.

### 90 seconds (the judge says "you have a minute or two")

| Time | Who | Spoken | Does |
|---|---|---|---|
| 0:00 | Soham | "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." | Learn tab, step 9 |
| 0:10 | Pranav | "This was one raw video of a front wheel check. The model cut it into eleven steps, each with a clip, a picture of done, and a yes or no question. Raw video in, lesson out." | Tab 2, click step 10, 3 s of clip, back to tab 1 |
| 0:30 | Soham | "Sikandar puts the wheel back in." (chime) "The camera saw it seated and moved on. Now close the lever, but point it forward." (spoken warning) "That's the expert's warning for this exact step." | Sikandar seats wheel; judge closes lever forward, then fixes it |
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
| Phone camera fails | Camera lost, last frame dimmed | Soham: "The camera dropped. Here's a recording of the same steps, and the screen labels it." | Pranav: run `python -m server.replay lessons\front-wheel-v1\norm.mp4 --loop`. The **Recording** tag shows. Say "recording" every time you refer to it. |
| Databricks slow or cold | Dashboard spinner over 10 s, or Genie still thinking | Prayush: "The warehouse is waking up, so here's the same view from five minutes ago." | Prayush turns his own laptop toward the judge with the dashboard and the saved Genie answer screenshot. If that is down too, skip to the privacy line. |
| Mistake not caught within 10 s | No amber banner, no line read aloud, step 10 still **Watching** | Soham: "It didn't catch it this time. Next always works, and here's a recording where it did." | Pranav presses Next, then plays [[skipped-step recording file]] with the Recording tag. After this judge: make step 10 manual for the rest of judging. |
| Wrong pass (advances before the step is done) | Green **Verified** on a step that is not done | Soham: "That one passed too early. Back fixes it." | Pranav clicks Back. Count it for the Q&A numbers. |
| Teach tab or a clip won't load | Blank Teach page or a frozen clip | Pranav: "That page didn't load, so I'll reload. The lesson is on the laptop." | Ctrl+R once. Still dead: skip to the learner beat and say "the expert side is in the recording if you want it later." |
| Everything down | Hub not responding | Soham: "Our setup is down, so here's a recording of the full demo from this morning." | Play [[backup video file]] on Pranav's laptop or a phone. Never call it live. |
| Judge declines to touch the bike | Judge shakes head | Soham: "No problem. Sikandar will do it, you watch the screen." | Sikandar closes the lever forward. Script unchanged. |

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
"In rehearsal the forward lever was caught [[x of y]] times. If it misses, Next always works."

5. **What if the camera angle is different from the expert's?**
"It isn't a pixel match. The question is about the end state, like the lever lying flat along the fork. A very different angle makes it less sure, and unsure means it waits. We tested with the phone on a stand at the side of the fork; we haven't measured other angles."

6. **What tasks does it fail on?**
"Anything where done isn't visible: torque, tightness, a sound. On the bike, how tight the lever is can't be judged by a camera, so the clip teaches it and the learner confirms. Those steps are manual, and the lesson says so."

**Speed and cost**

7. **How fast is a check?**
"In our timing runs one Claude Haiku check took about 1.1 to 1.3 seconds at the median. Today on this network it's [[venue median check ms]] ms, that number on the dashboard. From hands still to the next clip it's about [[settle to advance s]] seconds."

8. **Why not check every frame?**
"A motion gate only asks the model when the picture is still and has changed, plus a heartbeat every few seconds. That keeps calls down and avoids judging a half-done move."

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
"A video doesn't know where you are. You pause and scrub with grease on your hands. This one waits for you, and it tells you when you closed the lever the wrong way."

14. **Why glasses?**
"The expert's hands are busy. Glasses record what they see, with no tripod and no camera operator, and that point of view is what a learner copies. For the learner, any phone works." **IF GLASSES:** "The glasses can be the learner's camera too." **ELSE:** "We use a phone for the learner today."

15. **Who are your competitors?**
"Dozuki turns video into written guides, and checks photos of finished work. Retrocausal tracks steps live, but needs a fixed station camera and labeled cycles. We keep the expert's own clip as the instruction, and a phone decides when the next one plays."

**What's real**

16. **What's real and what's mocked?**
"The check you just saw was a real model call; if checks were mocked, the screen shows a Mock checks pill. Replays show a Recording tag. The dashboard is our own rehearsal runs, filtered to real camera runs only, not users. The narration is [[hand-written by us or written by Claude]] and spoken by [[Kokoro, a local voice model / ElevenLabs]], not the expert's own voice. The coach cues, like "That's it. Next step.", are in the same voice. There's no voice command yet; you press Next."

17. **Which models?**
"[[confirm provider from state.check_mode]] runs each live check. By default that's Claude Haiku when an Anthropic key is set, and Gemini 3.5 Flash-Lite otherwise. Claude finds where each step is done in the expert's video and writes the narration, and [[Kokoro on the laptop / ElevenLabs]] speaks it, with Kokoro as the fallback."

18. **How much of the lesson did a human touch?**
"We wrote the eleven-step plan; [[confirm: narration lines hand-written by us or written by Claude]]. The model found where each step ends and picked the reference frames, and a self-test turns any step it can't check into a manual step. We moved [[hand edits]] cut points by hand. Making the lesson took about [[minutes take to lesson]] minutes."

19. **What did you build this weekend?**
"The pipeline from raw video to a cut, narrated, rendered lesson. The hub that runs the camera checks, the mistake catch and the breaker. The web Learn, Done and Teach screens, and the phone camera page. The Databricks tables, filtered views, dashboard and Genie space." Only add other apps (iPhone, Android, desktop) if asked and only the ones tested today: [[tested apps]].

**Databricks**

20. **What is Databricks actually doing?**
"It's the data layer, never in the live loop. The hub logs every check, advance and caught mistake, and uploads them to Unity Catalog tables about once a minute and at the end of each run. The dashboard reads filtered views, and Genie answers plain-English questions over them. If Databricks is down, the demo doesn't notice; events stay in a local file."

21. **Is my run in there now?**
"It uploads when the run ends, so it shows after a refresh in about a minute. What you see now is our rehearsal runs."

**Next**

22. **What happens if the model goes down?**
"After a few errors or a rate limit, checks turn off for 30 seconds and the badge says Checks off, use Next. The clips are on the laptop, so the lesson still finishes."

23. **Does it scale to a team?**
"Today it's one learner per laptop hub. A lesson is a folder of clips and one JSON file, so it copies easily. Many learners at once needs a hosted hub, which we haven't built."

24. **Who would pay for this?**
"Our guess is teams that onboard people on physical tasks, like bike shops, maintenance and the trades. The expert's time is the expensive part, and this asks for it once. We haven't talked to buyers yet."

25. **What's next?**
"Test it with real learners at a shop, an editor so the expert can fix cuts without us, and an on-device check so frames never leave the room. None of that is built yet."

Numbers you may quote (only once filled):
- Ten real runs: [[runs]] runs, [[camera-verified steps]] camera-verified, [[manual steps]] manual, [[false passes]] false passes, [[false alarms]] false alarms.
- Planted lever caught: [[x of y]].
- Check latency: 1.1 to 1.3 s median in 5-call timing runs (server/README.md); venue [[venue median check ms]] ms.

---

## 6. Logistics

### Setup, 12:00 to 12:45 PM

| Person | Do this |
|---|---|
| Pranav | Stop any stale hub. `scripts\preflight.py` says READY. `scripts\run_server.ps1`. Chrome at `http://[[laptop IP]]:8000/`, tabs 1 to 4 as in section 2. Badge must not show Mock checks. Confirm PROVIDER. Laptop on charger, sleep off. |
| Sikandar | Bike on the stand, lamp angled at the fork. Phone on its stand, `https://[[laptop IP]]:8443/capture`, Start Camera, fork centered in frame, auto-lock off, on charger. **IF GLASSES:** glasses charged and streaming. |
| Soham | [[ORIGAMI lesson]] check: one paper run start to end. Paper stack, pre-folded examples. Backup video ready to play. |
| Prayush | `python -m server.databricks --warm` on the demo laptop (prints `warm: ok`). Open the dashboard once so tiles render. Genie: new chat, the common question visible, not sent. Same two tabs on his own laptop. Screenshot of a good Genie answer saved. |
| All | Two full run-throughs, 12:45 to 1:00, someone plays the judge and times it. Fill section 0. |

### Before each judge visit (30 seconds)

| Person | Check |
|---|---|
| Pranav | Learn tab, Front wheel check started fresh, step 9, badge **Watching**, no Recording tag, no Checks off. |
| Sikandar | Wheel out, skewer in the wheel, lever open. Phone framed, battery above 30%. |
| Soham | Fresh sheet on the board for the paper swap. |
| Prayush | If the dashboard or Genie has been idle 10 minutes or more, re-warm (`python -m server.databricks --warm` or `SELECT 1;` in the SQL editor), then reload the dashboard. Genie on a new chat. |

### Reset between judges (under 60 seconds)

1. Sikandar: lever open, wheel out, skewer back in the wheel.
2. Pranav: End lesson, pick Front wheel check again (a fresh select starts a new run in Databricks; do not use goto 0), open Steps, pick step 9. Close any replay terminal.
3. Prayush: Genie new chat; note the time for the 10-minute warm rule.
4. Soham: write down anything that went wrong (false pass, missed catch, latency) for the Q&A numbers.
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
- "we haven't measured that" or "we haven't built that"
- "this is a recording" whenever it is
