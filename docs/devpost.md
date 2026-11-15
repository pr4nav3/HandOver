<!--
BEFORE YOU PASTE (delete this comment; it is not for Devpost)

1. Search this file for "[[" and fill or delete every placeholder. The full list is in "Submission checklist" at the bottom.
2. Lines marked IF: keep only if the condition is true at submit time, then delete the IF marker.
3. Rule check: no "first", no "only", no savings figure, no user count, no past winners, competitors are Dozuki and Retrocausal and nobody else. Every number below comes from the repo or is a placeholder.
4. Model names: the live check runs on Claude Haiku when an Anthropic key is in .env (HANDOVER_CHECK_PROVIDER=auto), Gemini otherwise. Confirm which one the demo hub shows in state.check_mode before pasting. docs/pitch.md still says Gemini for checks; the two must match on judging day.
-->

# Devpost fields (paste these first)

**Project name:** HandOver

**Tagline (165 characters):**
An expert does a task once on Meta glasses. HandOver turns it into a lesson that plays their clip for each step and moves on when your camera shows the step is done.

(If neither demo lesson was recorded on the glasses, use: "An expert does a task once on camera. HandOver turns it into a lesson that plays their clip for each step and moves on when your camera shows the step is done.")

**Built with (Devpost tags):**
python, fastapi, uvicorn, websockets, pydantic, pillow, numpy, ffmpeg, anthropic, claude-haiku, claude-sonnet, google-gemini, google-genai, faster-whisper, kokoro, onnxruntime, react, typescript, vite, playwright, webvtt, mkcert, databricks, unity-catalog, databricks-sql, ai-bi-dashboards, databricks-genie, databricks-volumes, swift, swiftui, kotlin, jetpack-compose, rust, tauri, meta-wearables-device-access-toolkit, meta-ray-ban-glasses

**Try it out:**
- https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer
- Demo video: [[DEMO VIDEO URL]]

**Tracks and prizes to select** (MadHacks has not published its prize list in the repo research; tick only the ones that appear on the Devpost submit form):

| Track | Why we fit |
|---|---|
| Overall | A judge folds a fortune teller at the table and the expert's clips advance as the camera sees each fold done. |
| Best AI project | Vision models do real work in both halves: cutting an expert take into steps with checks, and judging each learner step with yes, no or unsure plus a confidence. Unsure never advances. |
| Databricks (sponsor) | Every learner run lands in Unity Catalog tables, lesson files go to a Volume, an AI/BI dashboard reads filtered views, and Genie answers "Which step do people get stuck on?" |
| Best use of Gemini API (if offered) | Gemini cuts expert takes into steps and hears the narration in one call, and is the second check provider. [[confirm which provider cut the demo lessons]] |
| Hardware / Qualcomm (if offered) | Meta glasses record the expert's point of view; iPhone and Android apps carry the Meta Wearables toolkit. Claim glasses streaming just if it was demoed. |
| Productivity or workforce (if offered) | Built for onboarding on physical tasks: the expert's time is asked for once. |
| Accessibility (if offered) | Captions on every clip, spoken narration, mistakes spoken aloud, an always-on Next. Not tested with disabled users, and we say so. |

---

## Inspiration

A lot of hands-on skill is still passed along the slow way. Someone who knows the task stands next to someone who doesn't and shows them, again and again. Manufacturers may need as many as 3.8 million new workers between 2024 and 2033, and Deloitte and the Manufacturing Institute estimate 1.9 million of those jobs could go unfilled. The people who can teach are a bottleneck.

The tools we found split into two groups. Some turn an expert's video into a document: Dozuki CreatorPro's "Video to Guide" outputs numbered text steps and a quiz. Others check work with cameras: Retrocausal's Assembly Copilot tracks steps live, but setup means a station camera that can see every step, a few captured work cycles, a labeled cycle and a trained model.

We wanted the expert's own hands as the instruction, and the learner's camera deciding when the next clip plays. A how-to video that waits for you.

## What it does

HandOver has two sides.

**Teach.** The expert does the task once while wearing Meta glasses (or any camera). HandOver cuts the take into steps. Each step gets a short imperative title, its own clip, timed captions, a reference frame that shows what done looks like, and a yes or no check question about shape or count. Steps whose result a camera can't judge, like a crease made and unfolded, are marked manual. A calm voiceover is written per step and spoken over the clips.

**Learn.** The learner points a phone or laptop camera at their hands. The screen shows their live view next to the expert's clip for the current step. About once a second, when the picture is still and has changed, the hub asks a vision model whether the step is done: it sends the step's reference frame, the previous step's reference as a "before" example, the live frame and the question. Two confident yeses on two different frames (confidence 0.8 or more) mark the step verified, a chime plays and the next clip starts. One yes at 0.92 or more that names no difference also passes. "No" or "unsure" resets the count, so a guess never moves the lesson. Next always works.

**The catch.** After 5 seconds of steady "no", the hub makes one extra call comparing the live frame to the previous, current and next reference. If the learner still matches the previous step, the screen names it and says the step's common mistake out loud. It never moves a learner forward on its own when they are behind.

**Done.** The done screen shows the learner's time on each step next to the expert's, and how many steps the camera checked.

**For the expert, later.** Every check, advance and caught mistake goes to Databricks. A dashboard shows time per step against the expert and where people press Next instead of passing, and Genie answers "Which step do people get stuck on?" in plain English.

## How we built it

**Hub.** One Python process (FastAPI, uvicorn, websockets) runs on the demo laptop. It serves the lesson files, the web app, a camera socket and a UI socket, plus an HTTPS port with a local mkcert certificate so phone browsers can use the camera.

**Teach pipeline** (`server/teach.py`, `server/voice.py`, `server/produce.py`):
1. ffmpeg normalizes the take to H.264, TV-range yuv420p, so it plays on every browser and on Windows.
2. Step extraction. With a Gemini key, Gemini 3.8 Flash watches and hears the take in one call. With a Claude key, Claude reads frames and a local faster-whisper transcript with word timestamps. For silent takes, Claude Sonnet finds the earliest moment each step's end state is visible (pass 1 over sampled frames, with a template step list as the prior), then refines each cut on frames 0.25 s apart.
3. ffmpeg cuts one clip per step. A reference frame is picked near the end of each step where the hands are out of the way. Check questions are rewritten from the frames: shape and counts, never color.
4. A self-test runs each question against its own reference (should be yes) and the previous one (should be no). With `--strict-self-test`, steps that fail become manual.
5. Voiceover: Claude Haiku writes one or two short lines per step, Kokoro speaks them locally, and the mix ducks under the clip with timed WebVTT captions.
6. Output is a folder: `lesson.json`, clips, captions and reference frames. A linter checks it. `scripts/make_lesson.ps1` runs the whole chain in one command, with `-Recut` after hand edits.
7. Built but optional: `server/produce.py` renders a produced course video per step with title cards, a slow zoom toward the hands, a highlight ring, step labels and crossfades.

**Learn loop** (`server/main.py`, `check.py`, `gate.py`, `mistake.py`):
- Cameras send JPEG frames at about 15 fps, long side 640. The hub keeps just the newest frame per camera, in memory.
- A motion gate (Pillow) lets a frame through when the picture has settled and differs from the last checked frame, plus a 6 s heartbeat.
- The check calls Claude Haiku (`claude-haiku-5-5`, with prompt caching) or Gemini (`gemini-3.5-flash-lite`). The answer is evidence first: what it sees, what differs, done yes/no/unsure, and confidence. A "yes" that names a difference is turned into "unsure".
- Up to two checks run at once on different settled frames. Answers are ordered by frame, so a late answer for an old frame never outweighs a newer one.
- A breaker turns checks off after 3 errors or timeouts in a row, any rate limit, or the spend cap, and the screen says "Checks off, use Next". Claude spend has a hard $20 per day and $50 total cap.

**Screens.** React, TypeScript and Vite. Learn draws the live feed on a canvas (newest frame each time), preloads the next clip, and has honest states: camera lost, reconnecting, Recording for replays, checks off. A phone capture page streams the camera over the local network. Playwright end-to-end tests drive a real hub with a replayed camera.

**Data layer** (Databricks, never in the live loop). The hub writes every learn event to a local JSON lines file. With credentials, it batches them into Unity Catalog every 60 s and at run end, with MERGE on event id so retries never duplicate rows. One setup script creates the schema, four tables (`lessons`, `steps`, `runs`, `events`), a Volume for lesson files and 13 dashboard views, each with a `_real` twin that drops mock, replay and self-test runs. The AI/BI dashboard reads the `_real` views. A Genie space over the four tables has tested example queries and the demo question. If Databricks is slow or down, the demo doesn't notice; a test runs the loop against a hung warehouse.

**Native apps** (built and tested, see the next section for what is demoed): a SwiftUI app for iPhone, iPad and Mac (250 tests), an Android app in Kotlin and Jetpack Compose (306 tests), and a Tauri desktop app for Windows, Linux and Mac with a Rust core (33 tests). Each one is a viewer of the hub and can be its camera. The iPhone and Android apps include the Meta Wearables Device Access Toolkit 1.0.1 for glasses streaming. The hub also has accounts, courses, organizations and an editor with undo and redo (46 routes, 25 tests), switched off in the demo build.

## What is demoed live, and what is built but not demoed

| Live at the table | Built and tested, not in the live demo |
|---|---|
| Hub on a Windows laptop, Learn screen in Chrome | Native iPhone, iPad and Mac app (250 tests) |
| Learner camera: a phone on the capture page [[IF GLASSES: or Meta glasses]] | Android app (306 tests) and Tauri desktop app (33 tests) |
| Fortune teller lesson, folded by the judge, advanced by real model checks | Glasses as the live learner camera: the toolkit code compiles, but streaming from the iPhone needs a paid Apple Developer team, and a free team was rejected [[delete if the glasses were demoed live]] |
| Teach view of the [[bike lesson / fortune teller]] lesson, clips playing | Produced course videos (`server/produce.py`) |
| [[IF CATCH: the skipped-step catch named on screen and spoken]] | Accounts, courses, organizations and the lesson editor (switched off in the demo build) |
| Done screen with time per step against the expert | Understanding mode (a per-step rubric as a second vote), behind a switch and off by default |
| [[IF DBX: Databricks dashboard and one Genie answer, from our own rehearsal runs]] | Skipping ahead two steps on an "ahead" verdict: built, off by default because a wrong skip is worse than a missed catch |
| Fallbacks, if needed: a replay with a visible Recording tag, "Checks off, use Next" | |

Lessons on disk are cut from our own takes. [[Say whether any step boundary or question was fixed by hand.]] The fortune teller lesson in the repo has [[3]] of [[9]] steps checked by the camera; the rest are manual by design.

## Challenges we ran into

- **Latency.** A check has to feel like a nod, not a wait. A leaner answer format brought one Claude Haiku check to about 1.1 to 1.3 s at the median in our timing runs. Pipelining two checks on different frames and a fast path for one very confident yes cut the time from "hands still" to "next clip" further.
- **False passes.** Early checks said yes to almost-done paper. We added the previous step's reference as a "before" picture, made the model name what differs before it answers, turned a yes that names a difference into unsure, and stripped color words from questions. On synthetic folds, the plain check still said yes on 10 of 63 not-finished frames; a second vote from the rubric cut that to 4 of 63 but blocked a sheet turned 45 degrees, so it stays behind a switch.
- **Debounce with checks in flight.** With two checks running at once, answers come back out of order. The debounce sorts them by frame so an old yes can never pass a step the newest frame says is not done.
- **Skipping ahead.** On synthetic folds, a learner who skipped a flip was called "ahead" in 15 of 23 tries. We kept ahead as a banner and made "behind" the case we act on.
- **Silent takes.** Cutting by narration fails when the expert works quietly. We added vision boundaries: a stronger model finds the earliest moment each step's end state is visible, then refines the cut on frames a quarter second apart. On a real take it gave eight coherent steps for about 3 cents.
- **A Windows demo laptop.** The hub was written on a Mac and demoed on Windows: file locks while swapping voiced clips, font lookup for produced videos, ffmpeg paths, a spend ledger safe across processes, and a clear error when a port is already taken. The end-to-end demo test now passes 21 of 21 on Windows.
- **Stale controls.** A phone pressing End after the laptop had started a new lesson would end the wrong run. End now carries the lesson and run ids, and stale ones are ignored.
- **Databricks Free Edition.** One small warehouse and a daily compute quota. We flush every 60 s instead of every few seconds, use MERGE so retries don't duplicate, keep tests from ever reaching the warehouse, and filter mock and replay runs out of the charts.
- **Glasses streaming.** The toolkit streams over a Wi-Fi link that needs entitlements a free Apple team can't get. The glasses stayed the expert's recorder.

## Accomplishments that we're proud of

- A judge can fold a fortune teller at our table and watch the expert's clips advance as each fold is seen.
- One command turns a raw take into a narrated, captioned lesson with checks, and a self-test that flags steps a camera can't tell apart.
- The check refuses to guess. Unsure never moves a step, and Next always works.
- The screen tells the truth: camera lost, reconnecting, Recording for replays, checks off and why.
- A test asserts that learn frames never touch disk.
- Every learner run lands in Databricks as rows, filtered so test runs never reach the charts.
- Four clients on one wire contract: web, Apple, Android and desktop, each with its own test suite.
- [[NOVICE RESULTS]]
- [[IF CATCH: In rehearsal the catch named [[CATCH RATE]] planted skipped steps.]]

## What we learned

- Check questions must describe what a camera can see: shape, seam count, how many flaps. Color and "is it creased" are unreliable.
- Some steps can't be checked from a photo. Marking them manual is better than a check that passes by accident.
- Asking the model to name what differs before it says yes catches most of its own over-eager answers.
- Measure before tuning. Timing runs set the debounce and the check rate, not the other way around.
- A fallback for every link (phone page, replay with a visible tag, Next) made it safe to demo on hackathon Wi-Fi.
- Keep analytics out of the live loop. The demo never waits on the warehouse.

## What's next for HandOver

- Real accuracy numbers from people who have never folded one, then from a real workplace task with a real expert.
- Glasses as the learner's camera, on a paid Apple Developer team.
- Checks on a no-retention tier or on device.
- Translated captions and a voice "next" for loud rooms.
- A hosted hub so a whole team of learners can use the same lessons.
- Safety warnings and a tools list pulled from the expert's own take.

## Privacy

The hub never saves your camera frames. It keeps the newest frame in memory, asks the model whether the step is done, and lets it go.

- Frames travel over the local network (HTTPS on the phone page, with the hub's own certificate).
- `server/test_engine.py::test_privacy_learn_frames_never_touch_disk` asserts on every run that learn frames are never written to disk.
- The model sees one live frame plus the step's reference frames per check, about once a second when the picture is still and changed. We don't store what we send; the provider's API terms apply.
- The event log and Databricks hold numbers: run id, lesson id, step numbers, answers, confidence, latency and timestamps. No images, no names, and a random run id.
- The expert's take is the product content and stays on the laptop. Lesson files can go to a Databricks Volume; that is the expert's video, never a learner's camera.
- When a recording is the camera, the screen says Recording. When checks are off, the screen says so.

## Team

- **Pranav:** web Learn and Teach screens, phone capture page and certificates, the iPhone camera app, Databricks plumbing in the hub, the Windows demo hub and the bike lesson.
- **Soham:** the hub (teach pipeline, checks, motion gate, mistakes, engine), the Apple, Android and desktop apps, and the origami lesson.
- **Sikandar:** the expert takes, props, novice runs, replays and the backup video.
- **Prayush:** Databricks tables, dashboard and Genie, plus the pitch, poster and this Devpost.

---

# Submission checklist (do not paste)

**Links**
- [ ] Repo: https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer (confirm it is public before submitting)
- [ ] Demo video: [[DEMO VIDEO URL]] (YouTube or Vimeo, public or unlisted, a real run; say "recording" in it)
- [ ] Devpost URL into the poster QR box (`poster/README.md`, step 1)

**Placeholders to fill or delete**
- [ ] [[DEMO VIDEO URL]]
- [ ] [[NOVICE RESULTS]]: from ten real folds by people new to it: camera-verified steps, manual steps, false passes, false alarms. If not run, delete the bullet.
- [ ] [[CATCH RATE]]: planted skipped steps caught out of the number tried. If not run, delete the bullet.
- [ ] [[IF GLASSES]]: glasses used as the live learner camera? If not, delete; if yes, also delete the "paid Apple team" row.
- [ ] [[IF CATCH]] and [[IF DBX]]: keep only what was shown working on the demo laptop.
- [ ] [[bike lesson / fortune teller]]: which lesson the Teach view shows. `front-wheel-v1` is not in the repo yet.
- [ ] [[3]] of [[9]]: camera-checked steps in the demo lesson (today's `fortune-teller-v1` has 3 of 9; update if a v2 replaces it).
- [ ] Hand edits: say whether any step boundary or question was fixed by hand.
- [ ] [[confirm which provider cut the demo lessons]] (Gemini or Claude), and the check provider shown in `state.check_mode`.
- [ ] Tagline: keep "on Meta glasses" only if the demo lessons were recorded on the glasses.

**Image gallery (3:2, upload in this order)**
Every PNG in `web/screenshots/` and `poster/img/` comes from mock or timer checks on a test lesson. Reshoot on the real lesson, or caption "Test lesson, simulated check".
1. Photo: a judge or teammate folding under the lamp, Learn screen behind. "Each clip plays when the camera sees the last fold is done."
2. Learn mid-lesson on the real lesson (reshoot of `web/screenshots/02-learn-mid-lesson.png`). "Live camera on one side, the expert's captioned clip on the other."
3. Verified (reshoot of `19-real-server-verified.png`). "Confident yeses, a chime, and the next clip starts."
4. Mistake card (reshoot of `06b-mistake-live.png`). "A skipped step, named on screen and said out loud."
5. Done (reshoot of `20-real-server-done.png`). "Your time against the expert's for every step."
6. Teach review with the step list (reshoot of `18-teach-review.png`) or `lessons/<id>/review/sheet.jpg`. "One take, cut into steps with checks."
7. Databricks dashboard on the `_real` views. "Time per step against the expert, from our rehearsal runs."
8. Genie answer to "Which step do people get stuck on?"
9. Checks off (`10-checks-off.png`, caption as a test lesson). "When the model is down, the screen says so and Next still works."
10. Native apps side by side: `apps/apple/screenshots/learn-iphone-landscape.png`, `apps/android/screenshots/learn-landscape.png`. Caption: "Built and tested; the table demo uses the web app."
11. Poster: `poster/poster.png`.

**Rule check**
- [ ] No "first", "only", savings figure, user count or past-winner claim.
- [ ] Competitors named: Dozuki and Retrocausal only.
- [ ] Every number traces to the repo or a filled placeholder.
- [ ] Model names match what the demo hub ran, and match docs/pitch.md.

Sources for Inspiration (not for Devpost): Manufacturing Institute and Deloitte, April 3, 2024, themanufacturinginstitute.org/manufacturers-need-as-many-as-3-8-million-new-employees-by-2033/; dozuki.com/creatorpro; retrocausal.ai. Repo numbers: test counts from commit messages 428b737/6375880 (Apple 250), d1c71a7 (Android 306), 8a98945 (desktop 33), 2a09b03 (library 46 routes, 25 tests), 51e0c73 (e2e 21 of 21); latency `server/docs/checks.md`; synthetic accuracy `server/docs/understanding.md` and `server/docs/checks.md`; vision boundaries 6caf276.
