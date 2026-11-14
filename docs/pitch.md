# HandOver pitch (judging Sun 2026-11-15, 1:00 to 2:30 PM)

Owner: Prayush. Follows docs/PLAN.md section 7 beat for beat and the fallback ladder in docs/SCOPE.md section 4. Prayush talks and handles judges; everyone else works the table quietly.

Anything in `[__ ]` is a fill-in from tonight's measurements. Do not say a number that is still blank. Anything marked **IF** is conditional: say it only if the condition is true at 12:00 PM Sunday.

Conditions to settle before 12:30 PM (Soham and Pranav confirm out loud to Prayush):
- **GLASSES**: did the 8 PM glasses gate pass (60 s of frames through the iPhone app, no gap over 5 s, one camera advance)? If no, glasses are never mentioned as a live camera. They stay only as the expert's recorder.
- **ONE TAKE**: was the bike lesson cut from a single take, with no splicing (`--concat`)? If no, never say "one take".
- **HAND EDITS**: were any bike step boundaries or questions fixed by hand? If yes, say so when asked.
- **CATCH**: did the skipped-flip catch ship and pass at least 18 of 20 at the 8 AM rehearsal? If no, step 5 is manual and the catch beat uses its fallback.
- **DONE+**: does the done screen show per-step time vs the expert, or only total time and camera-checked count?
- **DBX**: are the Databricks tables, dashboard and Genie space live? If no, skip that half of the beat.
- **BIKE TAKE**: confirm the bike lesson was recorded on the Meta glasses and what the take covers (wheel off only, or off and back on). Adjust the 0:20 line to match.
- **PRIVACY TEST**: is the M15 test (learn frames never touch disk) merged? The privacy line is true either way; the test is what we point to if asked.

---

## 1. The hook

Verbatim (PLAN.md section 1, SCOPE.md section 1):

> "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person."

Hallway version, one sentence:

> "An expert does a task once on Meta glasses, and HandOver turns it into a lesson that watches you through a camera and plays the next step once you've done this one."

---

## 2. The 4-minute script

Roles at the table:
- **Prayush**: talks, faces the judge, hands over control, never touches the laptop unless Soham is busy.
- **Soham**: at the Mac. Drives the screens (Teach, Learn, Databricks tab), watches the badge and the hub terminal, presses Next on cue, starts replay if needed.
- **Pranav**: owns the camera rig. iPhone app on the stand or chest mount, glasses if gated in. Swaps down the camera ladder.
- **Sikandar**: props. Hands the judge a fresh sheet, keeps pre-folded examples of each step in reach, has the backup video ready on his phone, resets the board between judges.

| Time | Prayush says | On screen / who does what | If this beat fails, Prayush says |
|---|---|---|---|
| 0:00 to 0:20 | "Hi, I'm Prayush, and this is HandOver." "Think of a new hire on a shop floor." "Someone senior shows them how, then shows the next person, and the next." "Experts teach the same task over and over." "With HandOver they do it once, and the lesson watches the next person." | Learn screen idle, fortune teller lesson picked, "Waiting for camera" or live view. Soham at the Mac, Pranav at the rig, Sikandar holding paper. | None. |
| 0:20 to 0:55 | "This is the expert side." "Sikandar did a bike front wheel quick-release, wearing Meta glasses and talking as he went." **IF ONE TAKE:** "He did it in one take." "One Gemini call cut that video into these steps." "Each step has his own clip, captions from his voice, a reference frame, and a yes-or-no check." "The reference frame shows what done looks like." "Later, the camera asks that question about your work." "Here's one." (clip plays about 4 s) "That's his voice and his hands." | Soham switches to Teach, opens the bike lesson timeline, clicks one mid-lesson clip (the quick-release lever step reads best). Captions on. | "The page didn't load, so I'll reload it." (Soham reloads; the lesson is on disk.) Still dead: "Here's the same screen from a recording." (Sikandar plays the backup video clip of the Teach screen.) |
| 0:55 to 2:10 | "Now you're the learner. Want to fold a fortune teller?" "Paper goes on the black board." "The camera above you is just an iPhone." **IF GLASSES:** "The camera is the same Meta glasses, streaming through the phone." "The screen plays the expert's clip for the step you're on. Copy his hands." "The clip loops, so watch it as many times as you like." "Step one is manual, so tap Next once it's flat." (judge folds) "Watch the badge. It says Watching while it compares your paper to his reference frame." "Hear that chime? The camera saw your fold and moved on." "Green means Verified, and the next clip starts on its own." "It needs two confident yeses in a row. If it's unsure, it waits." "And if it's ever wrong, Next always works." "That small number is how long each check took." "Keep going, you're doing great." | Sikandar slides a fresh sheet onto the board. Pranav checks the live view is framed on the board. Soham presses Next on step one if the judge doesn't. Clips advance by camera with a chime and a green "Verified". | Camera drops (Pranav steps down the ladder: glasses, iPhone app, Safari capture): "The camera dropped, so we're switching to the phone. Ten seconds." Live camera can't recover: "I'll show you a recorded fold instead. You'll see the Recording banner." (Soham starts replay.) Gemini down, badge says "Checks off, use Next": "Our vision checks are off right now, so you'll press Next. The clips still work." Misfire: "It missed that one. Next always works." |
| 2:10 to 2:40 | **IF CATCH:** "Try something for step five. Don't flip the paper. Just keep going." (wait) "There. It says you're still on the flip, and it names the step." "It compared your paper to the step before and the step after." "A video can't tell you that you skipped something." "Flip it over, and it moves on." | Sikandar points at step five on the judge's sheet if needed. Amber banner and voice name the step. Judge flips, the step passes. | Not caught within 10 s: "It didn't catch it this time. I'll press Next and show you a recording where it did." (Soham presses Next, then plays the skipped-flip replay with the "Recording" banner.) **IF NO CATCH shipped:** skip the skip. Say "Step five, the flip, is a manual step today. Tap Next." |
| 2:40 to 3:10 | "Done. That's your time and how many steps the camera checked." "Steps you finished with Next are counted too." **IF DONE+:** "And your time on each step next to the expert's." **IF DBX:** "Every check and every step goes into Databricks." "This is time per step, learners against the expert, from our own test runs." "This one ranks steps by how often people press Next instead of passing." "We ask Genie one question. Which step do people get stuck on?" (answer appears) "That tells the expert which clip to re-record." | Done screen. Soham switches to the Databricks tab: AI/BI dashboard, then the Genie space with the question pre-typed and sent. Sikandar starts resetting the board. | Dashboard slow or down: "Databricks is slow on the hall Wi-Fi, so I'll skip it." Go straight to the next beat. |
| 3:10 to 3:40 | "So how is this different?" "Dozuki turns video into documents." "Retrocausal needs a station camera and labeled cycles." "We keep the expert's own video as the instruction." "And the learner's camera decides when the next clip plays." **IF ONE TAKE:** "HandOver needs one take and any phone." **ELSE:** "HandOver needs one recording of the expert and any phone." | Soham returns to the Learn screen. | None. |
| 3:40 to 4:00 | "One more thing. The hub never saves your camera frames." "It checks them with Gemini and lets them go." "Experts teach the same task over and over." "With HandOver they do it once, and the lesson watches the next person." "Thank you. Keep the fortune teller." | Judge keeps the folded fortune teller. | None. |

Last resort, any beat, everything down: "Our setup is down, so here's a recording of the full demo from this morning." Sikandar plays the backup video. Never present it as live.

Pacing notes:
- The fold is the longest beat. Stop talking while the judge is folding. Say one line per chime, not more.
- If the judge folds fast and is ahead of the clips: "You're faster than the expert. It catches up after each check."
- If the judge declines to fold: "No problem. Sikandar will fold, and you watch the screen." Script is unchanged.
- If time is short at 2:40, drop the Databricks half and go to the contrast line.

---

## 3. Short versions

### 60 seconds (judge is rushed, fold already in progress or not possible)

"Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person.
The expert does the task on Meta glasses and talks through it.
One Gemini call cuts the video into steps. Each step gets his clip, captions, a reference frame and a yes-or-no check.
The learner works under a camera. The screen plays the expert's clip for the current step.
Gemini compares the live frame to the reference. Two confident yeses, and the next clip plays. Next always works.
**IF CATCH:** If you skip a step, like the flip here, it tells you which one.
**IF DBX:** Every check lands in Databricks, so the expert can see which step people get stuck on.
Dozuki turns video into documents. Retrocausal needs a station camera and labeled cycles. HandOver needs **IF ONE TAKE:** one take **ELSE:** one recording and any phone.
And the hub never saves your camera frames."

### 20 seconds

"Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person.
The expert's own clip plays for each step, and the camera checks you finished it before the next one plays.
Want to try folding one?"

---

## 4. Judge Q&A

Rule for every answer: say what is built, say what is not, give a measured number or say we have not measured it. Never estimate out loud.

**1. How often does it pass a step you didn't do?**
"It needs two yeses in a row at 0.8 confidence or higher. Unsure never advances, and a timeout counts as unsure. Step one is manual because flat paper proves nothing. Questions ask about shape and seams, not color. In ten folds by someone new, we saw `[__ false passes out of __ camera-checked steps]`. Back undoes a wrong pass."

**2. How fast is it?**
"Each check is one Gemini Flash-Lite call at low image resolution with minimal thinking. Median was `[__ s, from M1]` on our hotspot. We call when your hands are still, plus a heartbeat every 6 seconds. After a step is done it takes two checks and a short green hold, so about `[__ s from hands still to next clip, from rehearsal]`."

**3. Why not just watch a YouTube video?**
"A video doesn't know where you are. You pause and scrub with paper or grease on your hands. HandOver is a how-to video that waits for you. **IF CATCH:** And it notices when you skip a step. On the expert side, nobody edits anything; they just do the job and talk."

**4. Why glasses?**
"The expert's hands are busy. Glasses record exactly what they see, with no tripod and no camera operator. That point of view is what the learner needs to copy. For learners, any phone works. **IF GLASSES:** The glasses can also be the learner's camera; that's what you saw. **ELSE:** Streaming the glasses as the learner's camera didn't hold up tonight, so we use a phone."

**5. What if the learner's camera angle is different from the expert's?**
"It isn't a pixel match. Gemini judges whether the finished state matches, using a question about shape and seams. A very different angle makes it less sure, and unsure means it waits, so the worst case is pressing Next. We tested top-down on a black board under a lamp. We haven't measured other angles."

**6. Privacy?**
"The hub never saves your camera frames. **IF PRIVACY TEST:** There's a test in the repo that checks that. Frames do go to Gemini's API for the check. On the free tier Google may review inputs, so a real deployment would use a paid tier that doesn't train on data, or an on-device check. We haven't built that. The camera points down at your hands, not at people."

**7. What does a check cost?**
"Google's docs put a low-resolution image at about 280 tokens, so roughly 700 input tokens per check with two images and the question. We ran on the free tier, so we haven't paid anything or priced it at scale. A full fold used `[__ calls per run, from rehearsal logs]`."

**8. What tasks does it fail on?**
"Anything where done isn't visible. Torque, tightness, a sound, a smell. Steps that look the same before and after. Tiny parts, or work that leaves the frame. Those become manual steps, and the learner presses Next. On the bike, how tight the lever is can't be judged by a camera, so the clip teaches it and the learner confirms."

**9. How does it know I skipped a step?** (IF CATCH)
"After five seconds of steady no's, it makes one extra call comparing your frame to the previous, current and next reference. If you still match the previous step, it says so and names it. It never moves you on its own when you're behind."

**10. Does it scale to a whole team of learners?**
"Today it's one learner per laptop hub. A lesson is just a folder of clips and a JSON file, so it copies easily. Many learners at once means accounts and a hosted hub. We haven't built either."

**11. Who are your competitors?**
"Dozuki turns video into documents. Retrocausal tracks steps live, but needs a fixed station camera and labeled cycles. We keep the expert's own video as the instruction, and the learner's camera decides when the next clip plays. General camera assistants have no expert recording, so they have to guess the steps."

**12. What's the business model?**
"We haven't settled it. Our guess is a per-site subscription for teams that onboard people on physical tasks, like manufacturing and the trades. The expert's time is the expensive part, and this asks for it once. We haven't talked to buyers yet."

**13. What is Databricks actually doing?**
"It's the data layer, never in the live loop. The hub batches every check, advance and caught mistake into Unity Catalog tables every few seconds. Lesson files go to a Volume. The dashboard shows time per step and where people press Next instead of passing. Genie answers questions in plain English. If Databricks is down, the demo doesn't notice, and events stay in a local file."

**14. What did you actually build in 24 hours?**
"The teach pipeline: normalize the video, one Gemini call for steps and checks, cut clips, captions and reference frames. The hub: FastAPI, websockets, the check loop, two-yes debounce, motion gate and a breaker for outages. The learn and teach screens. **IF iPhone app shipped:** A native iPhone camera app. A Safari capture page, a replay tool, the Databricks plumbing, and two real lessons. The commit history is all from this weekend."

**15. What's mocked?**
**IF the live fold ran on real Gemini:** "Nothing in the loop you just saw. There's a mock check mode, but it's for tests. When we play a recording as the camera, the screen says Recording. The Databricks numbers are our own rehearsal runs, not users. Step one is manual by design. **IF NOT GLASSES:** The glasses recorded the lessons but aren't streaming live."

**16. What happens if Gemini goes down?**
"After three errors in a row or any rate limit, checks turn off for 30 seconds and the badge says 'Checks off, use Next'. The lesson still finishes. The clips are on the laptop, so they never depend on the network."

**17. Which models?**
"Gemini 3.8 Flash cuts the expert video into steps, once per lesson. Gemini 3.5 Flash-Lite runs each check. `[confirm both ids from M1 before judging]`."

**18. How long does it take to make a lesson?**
"For the bike take, about `[__ min from upload to finished lesson, from Soham's teach log]`. The expert just has to narrate and pause after each step."

**19. How accurate was the step cutting?**
"On the bike lesson, `[__ of __ step boundaries kept as Gemini cut them]`. **IF HAND EDITS:** We moved `[__]` by hand." If not measured: "We checked it by eye, we didn't score it."

**20. Is it accessible?**
"Every clip is captioned from the expert's voice. There's a voice Next, off by default because halls are loud. We haven't tested it with disabled users, so I won't claim more than that."

Measured counts to quote when asked how well it works (only these, only once filled):
- Planted flip caught: `[__ of 20, from 8 AM rehearsal]`.
- Novice folds: `[__ folds; __ camera-verified steps, __ manual, __ false passes, __ false alarms, from the 8 PM and overnight runs]`.

---

## 5. Table logistics

### Before 12:00 PM (setup hour is 12:00 to 1:00)
- Both hotspots charged. Mac on hotspot A. Hotspot B on and tested with the iPhone.
- Certs valid for the hotspot IP (rerun `scripts/certs.sh` if the IP changed). iPhone trusts the mkcert root. Auto-lock off.
- Gemini demo key in `.env` (not the rehearsal key).

### Setup order, 12:00 to 12:40
1. Power strip, Mac on charger, lamp plugged in.
2. Black board flat, lamp angled to avoid glare, stand or chest mount over the board.
3. Soham: `scripts/run_server.sh`; open Chrome at `http://localhost:8000/#/learn`, pick the fortune teller lesson, step 0.
4. Pranav: iPhone app connected, live view framed on the board, badge shows camera connected. **IF GLASSES:** glasses charged and paired, frames confirmed.
5. Soham: warm the Databricks warehouse (`python -m server.databricks --warm`, or run any query in the SQL editor). Open the dashboard and the Genie space in Chrome tabs, Genie question typed but not sent.
6. Chrome tabs, left to right: Learn, Teach (bike lesson timeline open), Databricks dashboard, Genie. Nothing else open. Notifications off, Do Not Disturb on.
7. Soham: a second terminal with the replay commands ready (clean fold and skipped-flip recordings).
8. Sikandar: 10+ sheets stacked, pre-folded examples of each step, backup video on his phone at full brightness.
9. Two full run-throughs, 12:40 to 1:00, with someone acting as the judge.

### Who stands where
- Judge: in front of the black board, facing the Mac screen.
- Prayush: beside the judge, half facing them, half facing the screen.
- Soham: behind the Mac, one hand on the trackpad.
- Pranav: beside the rig, out of the camera's view.
- Sikandar: on the other side of the board, out of frame, paper in hand.

### What's on which screen
- Mac: Chrome full screen, Learn tab by default. Terminal hidden behind it.
- iPhone: HandOver camera app (or Safari `/capture`), screen up, on the stand.
- Sikandar's phone: backup video paused at 0:00.

### Between judges (under a minute)
- Sikandar: clear the board, put down a fresh sheet, finished fortune teller goes with the judge.
- Soham: back to the Learn tab, re-pick the fortune teller lesson so it starts at step 0. Close any replay. Check the badge is not "Checks off".
- Pranav: confirm the live view is still framed and the phone is charging.
- Prayush: glance at the Databricks tab; if it's been idle a while, Soham re-warms it.
- Every 30 minutes: check hotspot battery, iPhone battery, glasses battery.

---

## 6. Words

Never say:
- "first", "only", "the first to", "the only one"
- any training-time saving or percentage, any user or customer count
- "one take" unless ONE TAKE is confirmed
- "glasses" as the live camera unless GLASSES is confirmed
- "revolutionary", "seamless", "cutting-edge", "empower", "leverage", "unlock", "game-changer", "disrupt"
- "AI watches you", "it knows", "it understands" (it compares two pictures and answers yes or no)
- "real-time" (checks take `[__ s]`), "100%", "always accurate", "never wrong"
- any competitor other than Dozuki and Retrocausal by name
- "users" for our test runs (say "our test runs" or "rehearsal folds")
- "live" about a replay (say "recording")

Say instead:
- "does it once"; "the expert's own clip"; "the lesson watches the next person"
- "a how-to video that waits for you"
- "two confident yeses in a row"; "if it's unsure, it waits"; "Next always works"
- "the hub never saves your camera frames"
- "we haven't measured that" or "we haven't built that"
- "this is a recording" whenever it is
- "any phone" for the learner camera
