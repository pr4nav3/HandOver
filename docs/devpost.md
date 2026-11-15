<!--
BEFORE YOU PASTE (delete this comment; it is not for Devpost)

1. Search this file for "[[" and fill or delete every placeholder. The full list is in "Submission checklist" at the bottom.
2. Lines marked IF: keep only if the condition is true at submit time, then delete the IF marker.
3. Rule check: no "first", no "only", no savings figure, no user count, no past winners, competitors are Dozuki and Retrocausal and nobody else. Every number below comes from the repo or is a placeholder.
4. Model names: the live check runs on Claude Haiku when an Anthropic key is in .env (HANDOVER_CHECK_PROVIDER=auto), Gemini otherwise. Confirm which one the demo hub shows in state.check_mode before pasting. docs/pitch.md uses the same wording; keep the two matching on judging day.
-->

# Devpost fields (paste these first)

**Project name:** HandOver

**Tagline:**
An expert records a task once. HandOver turns it into a lesson that plays their clip for each step and moves on when your camera sees the step is done.

(IF the bike or any demo lesson was recorded on the glasses, use: "An expert records a task once on Meta glasses. HandOver turns it into a lesson that plays their clip for each step and moves on when your camera sees the step is done.")

**Built with (Devpost tags):**
python, fastapi, uvicorn, websockets, pydantic, pillow, numpy, httpx, ffmpeg, anthropic, claude-haiku, claude-sonnet, google-gemini, google-genai, faster-whisper, kokoro, react, typescript, vite, playwright, mkcert, databricks, unity-catalog, databricks-sql, ai-bi-dashboards, databricks-genie, swift, swiftui, kotlin, jetpack-compose, rust, tauri, meta-wearables-device-access-toolkit

**Try it out:**
- https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer
- Demo video: [[DEMO VIDEO URL]]

**Tracks and prizes to select** (tick only the ones that appear on the Devpost submit form):

| Track | Why we fit |
|---|---|
| Overall | A judge folds a paper fortune teller at our table, and the expert's next clip plays when the camera sees each fold done. |
| Best AI project | Models do real work on both sides: cutting an expert take into steps with checks, and judging each learner step as yes, no or unsure with a confidence. Unsure never advances. |
| Databricks (sponsor) | Every learner run lands in Unity Catalog tables. Lesson files go to a Volume. A two-page AI/BI dashboard and a Genie space read filtered views that drop test runs. |
| Best use of Gemini API (if offered) | Gemini can cut an expert take into steps while hearing the narration in one call, and is the second live check provider. [[confirm which provider cut or titled the demo lessons]] |
| Hardware (if offered) | Meta glasses record the expert's point of view. The iPhone and Android apps include the Meta Wearables Device Access Toolkit. [[Add "and stream to the hub" if glasses streaming was demoed]] |
| Productivity or workforce (if offered) | Built for onboarding on hands-on tasks: the expert records once, and every learner gets the same coach. |
| Accessibility (if offered) | Captions on every clip, spoken narration, mistakes said out loud, and a Next button that always works. Not tested with disabled users, and we say so. |

---

## Inspiration

A lot of hands-on skill is still passed along the slow way. Someone who knows the task stands next to someone who doesn't and shows them, again and again. Manufacturers may need as many as 3.8 million new workers between 2024 and 2033, and Deloitte and the Manufacturing Institute estimate 1.9 million of those jobs could go unfilled. The people who can teach are a bottleneck.

The tools we found split into two groups:
- **Video to document.** Dozuki CreatorPro's "Video to Guide" turns an expert's video into numbered text steps and a quiz.
- **Camera checks.** Retrocausal's Assembly Copilot tracks steps live, but setup means a station camera that sees every step, captured work cycles, labeling and a trained model.

We wanted the expert's own hands as the instruction, and the learner's camera deciding when the next clip plays. A how-to video that waits for you.

## What it does

An expert does a task once on camera. HandOver cuts the video into steps. A learner then follows along with a phone camera on their hands: the expert's clip for the current step plays, and when the camera sees the step is done, the next clip starts. If the learner goes wrong, it says so out loud.

**Teach.** The expert records the task once, on Meta glasses or a phone. Each step gets:
- a short imperative title and its own clip, with timed captions
- a reference frame that shows what done looks like
- one yes or no check question about shape or count
- a short narration line, spoken over the clip

Steps a camera can't judge, like a crease made and unfolded, are marked manual and pass with Next.

**Learn.** The screen shows the learner's live camera next to the expert's clip. About once a second, when the picture is still and has changed, the hub sends a vision model three images and the question: the step's reference ("done"), the previous step's reference ("before") and the live frame.
- Two confident yeses (0.8 or more) on two different frames pass the step. A chime plays, a voice says "That's it. Next step." and the next clip starts.
- One yes at 0.92 or more that names no difference passes on its own.
- A "no", an "unsure" or a low-confidence yes resets the count. A guess never moves the lesson.
- Next always works.

**The catch.** After 5 seconds of settled "no", the hub makes one extra call: does the live frame look like the previous, current or next step? If it still looks like the previous step, the screen shows the step's common mistake (for example, "Flip it over first. The seams should face down.") and says it out loud. Being behind never moves the lesson.

**Done.** The learner sees their time on each step next to the expert's, and how many camera steps the camera confirmed.

**For the expert, later.** Every check, advance and caught mistake lands in Databricks. A dashboard shows which steps take learners longest compared with the expert and where they press Next instead of passing, and Genie answers "Which step do people get stuck on?" in plain English.

## How we built it

```
 TEACH (once, on the laptop)                         LEARN (live, at the table)

 expert take (glasses or phone)                      phone camera ──JPEG ~15 fps──┐
        │                                                                          ▼
 ffmpeg: H.264, SDR, TV-range yuv420p               ┌──────────── HUB (FastAPI) ────────────┐
        │                                            │ newest frame per camera, in memory     │
 steps: Gemini (video + audio, one call)             │ motion gate: settled and changed       │
   or Claude (frames + local Whisper)                │ check: done ref + before ref + live    │
   or vision boundaries (Claude Sonnet)              │   Claude Haiku, or Gemini Flash-Lite   │
        │                                            │ frame-ordered debounce, breaker        │
 clips, reference frames, questions, self-test       │ catch: compare prev / this / next ref  │
        │                                            └───────┬───────────────────┬───────────┘
 narration: hand-written or Claude Haiku,                    │ state, frames     │ events
   spoken by Kokoro, timed WebVTT                            ▼                   ▼
        │                                            Learn screen (React)   logs/events.jsonl
 lessons/<id>/  lesson.json, clips, frames, VTT ───► clips + spoken cues         │ every 60 s, MERGE
        │                                                                         ▼
        └──────── upload ──────────────────────────────────────────────►  Databricks
                                                                  Volume, 4 tables, _real views,
                                                                  AI/BI dashboard, Genie space
```

**Hub.** One Python process (FastAPI, uvicorn, websockets) on the demo laptop. It serves the lessons, the web app, a camera socket and a UI socket, plus an HTTPS port with a local mkcert certificate so phone browsers allow the camera.

**Teach pipeline** (`server/teach.py`, `server/voice.py`):
1. ffmpeg normalizes the take to H.264, TV-range yuv420p. HDR phone and glasses takes are tone-mapped to SDR so white paper keeps its creases.
2. Step extraction. With a Gemini key, Gemini 3.8 Flash watches and hears the take in one call. With a Claude key, Claude reads frames plus a local faster-whisper transcript with word timestamps. For silent takes, Claude Sonnet finds the earliest moment each step's end state is visible (a template step list as the prior), then refines each cut on frames 0.25 s apart. Cut times can also be set by hand and rebuilt with `-Recut`.
3. ffmpeg cuts one clip per step. A reference frame is picked near the end of each step where the hands are out of the way. Check questions are rewritten from the frames: shape and counts, never color.
4. A self-test runs each question against its own reference (should be yes) and the previous one (should be no). Steps that fail become manual.
5. Narration: hand-written lines win; otherwise Claude Haiku writes one or two short lines per step. Kokoro speaks them on the laptop (ElevenLabs is a switch, with Kokoro as the fallback), with timed WebVTT captions.
6. Output is a folder: `lesson.json`, clips, captions and reference frames. A linter checks it. `scripts/make_lesson.ps1` runs the whole chain in one command.

**Learn loop** (`server/main.py`, `check.py`, `gate.py`, `mistake.py`):
- Cameras send JPEG frames at about 15 fps, long side 640. The hub keeps the newest frame per camera, in memory.
- A motion gate (Pillow) passes a frame when the picture has settled and differs from the last checked frame, plus a 6 s heartbeat.
- The check calls Claude Haiku (`claude-haiku-5-5`, with prompt caching on the reference images) when an Anthropic key is set, else Gemini (`gemini-3.5-flash-lite`). The answer is short JSON with the evidence first: what differs, then done, then confidence.
- Up to two checks run at once on different settled frames. Answers are ordered by frame, so a late answer for an old frame never outweighs a newer one.
- A breaker turns checks off after 3 timeouts or errors in a row, any rate limit, or the spend cap, and the screen says checks are off and to use Next. Claude spend has a hard cap of $20 a day and $50 in total.

**Learn screen.** React, TypeScript and Vite. The live feed is drawn on a canvas, the next clip is preloaded, and the states are honest: camera lost, reconnecting, Recording for replays, checks off. Spoken cues are pre-rendered in the lesson's voice, and the clip ducks while one plays; the per-step mistake line uses browser speech. A phone capture page streams the camera over the local network. Playwright end-to-end tests drive a real hub with a replayed camera.

**Native apps** (built and tested, not in the table demo): a SwiftUI app for iPhone, iPad and Mac (259 tests), an Android app in Kotlin and Jetpack Compose (306 tests), and a Tauri desktop app for Windows, Linux and Mac with a Rust core (33 tests). Each is a viewer of the hub and can be its camera. The iPhone and Android apps include the Meta Wearables Device Access Toolkit 1.0.1. The hub also has accounts, courses, organizations and an editor with undo and redo (46 routes, 25 tests) for the apps; the web demo doesn't use them.

## Databricks: what the expert gets back

The expert recorded the task once. Databricks is how they find out where it didn't land.

**What lands where** (Unity Catalog, `workspace.handover`):

| Object | What it holds |
|---|---|
| `lessons`, `steps` tables | Each lesson and its steps, with the expert's start and end time, check type and question |
| `runs` table | One row per learner attempt |
| `events` table | Every run start and end, step entered, check (yes, no or unsure, confidence, latency, what differed), advance (camera, Next or voice) and caught mistake |
| `lessons` Volume | The lesson files: `lesson.json`, clips, reference frames and captions |
| `events_real`, `runs_real` views | The tables without replay runs, mock checks and self-test rows |
| 13 dashboard views, each with a `_real` twin | Time per step, step summary, how each step was passed, Next rate on camera steps, false passes, check answers and latency, mistakes, where runs stopped, checks-off incidents |

One script, `scripts/databricks_setup.py`, creates all of it, uploads a lesson to the Volume and checks the result. It never prints the token.

**AI/BI dashboard, two pages, all on the `_real` views:**
- **Where learners get stuck.** Runs, finished runs, camera-checked share, mistakes caught and median check time. Learner median time per step next to the expert's. How each step was passed (camera or Next). Mistakes caught per step. A step-by-step table with "x expert", Next on camera steps, false passes and where runs stopped.
- **Camera check quality.** Yes, no and unsure per step. p50 and p90 check latency per step. Next rate on camera steps. Average confidence. False passes (a camera pass the learner undid with Back within 60 s). Where unfinished runs stopped. When checks went off and why.

**Genie space** over `events_real`, `runs_real`, `lessons` and `steps`. The raw tables are left out, so answers never include test runs. Its instructions define the terms an expert uses: "stuck" is the step with the largest learner-to-expert time ratio, backed by the Next rate and mistakes; step numbers are 1-based in answers; times are shown in Chicago time; with fewer than 5 runs, Genie says so. Eight example SQL queries were each run on the warehouse. Sample questions include "Which step do people get stuck on?" and "Which camera steps do learners skip with Next most often?"

**Why it matters to the expert.** A step where learners take three times the expert's time, press Next instead of passing, or get caught behind is a step whose clip or question needs work. The expert sees that without watching any learner.

**Never in the live loop.** The hub writes every event to a local JSON lines file. With credentials, a background thread sends batches every 60 s and at run end, using MERGE on event id so a retry never duplicates rows. Runs with mock checks stay local. If Databricks is slow or down, the lesson doesn't notice: a test runs the loop against a hung warehouse and asserts checks and advances are not delayed.

## What is demoed live, and what is built but not demoed

| Live at the table | Built and tested, not in the live demo |
|---|---|
| Hub on a Windows laptop, Learn screen in Chrome | Native iPhone, iPad and Mac app (259 tests) |
| Learner camera: a phone on a stand, on the capture page [[IF GLASSES: or Meta glasses]] | Android app (306 tests) and Tauri desktop app (33 tests) |
| Fortune teller lesson, folded by the judge, advanced by real model checks | Glasses as the live learner camera: the toolkit code compiles, but iPhone streaming needs a paid Apple Developer team [[delete if the glasses were demoed live]] |
| Teach view of the fortune teller lesson, clips playing | Accounts, courses, organizations and the lesson editor (used by the apps) |
| [[IF CATCH: the skipped-flip catch named on screen and spoken]] | Understanding mode (a per-step rubric as a second vote), behind a switch and off by default |
| Done screen with time per step against the expert | Skipping two steps ahead on an "ahead" verdict: built, off by default because a wrong skip is worse than a missed catch |
| [[IF DBX: Databricks dashboard and one Genie answer, from our own rehearsal runs]] | |
| Fallbacks, if needed: a replay with a visible Recording tag, checks off with Next | |
| [[IF BIKE REC: Showcase, pre-recorded and labeled Recording: the bike front wheel check lesson]] | |

The fortune teller lesson was cut from our own take, at step times our teammate marked by hand; the pipeline made the clips, reference frames, questions and narration. [[Say whether any question or reference frame was fixed by hand.]] It has [[7]] of 9 steps checked by the camera; steps 4 and 8 are creases the camera can't see, so they are manual. At the table the judge starts at step 5 on paper pre-folded through step 4, so a visit fits in four minutes. The bike front wheel check is a recording, not done live.

## Challenges we ran into

- **Latency.** A check has to feel like a nod, not a wait. A leaner answer format brought one Claude Haiku check to about 1.1 to 1.3 s at the median in our timing runs. Two checks in flight on different frames and a fast path for one very confident yes cut the time from "hands still" to "next clip" further.
- **False passes on almost-done paper.** We added the previous step's reference as a "before" picture, made the model write what differs before it answers, treat a yes below 0.8 as unsure, and stripped color words from questions. On synthetic folds (drawn, not photographed) the check still said yes on 10 of 63 not-finished frames, which is why one yes is not enough. A second vote from a per-step rubric cut that to 4 of 63, but it blocked a sheet turned 45 degrees, so it stays behind a switch.
- **Out-of-order answers.** With two checks in flight, answers come back in any order. The debounce sorts by frame, so an old yes can never pass a step the newest frame says is not done.
- **Skipping ahead.** On synthetic folds, a learner who skipped a flip was called "ahead" in 15 of 23 tries, and the confirm call said yes 4 of 6 times. We made "behind" the case we act on, and the two-step skip stays off.
- **Silent takes.** Cutting by narration fails when the expert works quietly. Vision boundaries find the earliest frame where each step's end state is visible, then refine on frames a quarter second apart. On a real take it gave eight coherent steps for about 3 cents.
- **HDR phone video.** iPhone takes are HDR, and a plain conversion blew out white paper and hid the creases the checks depend on. We tone-map to SDR, and skip the codec-less opening audio track in iPhone files that made ffmpeg refuse the file.
- **A Windows demo laptop.** The hub was written on a Mac and demoed on Windows: file locks while swapping voiced clips, fonts, ffmpeg paths, a spend ledger safe across processes, and a clear error when a port is taken. The end-to-end demo test passes 21 of 21 on Windows.
- **Stale controls.** A phone pressing End after the laptop had started a new lesson would end the wrong run. End now carries the lesson and run ids, and stale ones are ignored.
- **Databricks Free Edition.** One small warehouse and a daily compute quota. We flush every 60 s instead of every few seconds, MERGE so retries don't duplicate, keep tests from ever reaching the warehouse, and filter mock and replay runs out of the charts.
- **Glasses streaming.** The toolkit's registration needs a paid Apple Developer team, and we had a free one. The glasses stayed the expert's recorder.

## Accomplishments that we're proud of

- A judge can fold a fortune teller at our table and watch the expert's clips advance as each fold is seen.
- One command turns a raw take into a narrated, captioned lesson with checks, plus a self-test that makes steps a camera can't tell apart manual.
- The check refuses to guess. Unsure never moves a step, and Next always works.
- The screen tells the truth: camera lost, reconnecting, Recording for replays, checks off and why.
- A test asserts that learn frames never touch disk.
- Every learner run lands in Databricks as rows, filtered so test runs never reach the charts or Genie.
- Four clients on one wire contract: web, Apple, Android and desktop, each with its own test suite.
- [[NOVICE RESULTS]]
- [[IF CATCH: In rehearsal the catch named [[CATCH RATE]] planted skipped steps.]]

## What we learned

- Check questions must describe what a camera can see: shape, seam count, how many flaps. Color and "is it creased" are unreliable.
- Some steps can't be checked from a photo. Marking them manual beats a check that passes by accident.
- Asking the model to name what differs before it answers makes its yes more careful.
- Measure before tuning. Timing runs set the debounce and the check rate.
- A fallback for every link (phone page, replay with a visible tag, Next) made it safe to demo on hackathon Wi-Fi.
- Keep analytics out of the live loop. The demo never waits on the warehouse.

## What's next for HandOver

- Real accuracy numbers from people who have never folded one, then from a workplace task with a real expert.
- Glasses as the learner's camera, on a paid Apple Developer team.
- Checks on a no-retention tier or on device.
- Translated captions and a voice "next" for loud rooms.
- A hosted hub so a whole team of learners can use the same lessons.
- Safety warnings and a tools list pulled from the expert's own take.

## Privacy

The hub never saves your camera frames. It keeps the newest frame in memory, asks the model whether the step is done, and lets it go.

- Frames travel over the local network (HTTPS on the phone page, with the hub's own certificate).
- `server/test_engine.py::test_privacy_learn_frames_never_touch_disk` asserts on every run that learn frames are never written to disk.
- Per check, the model sees one live frame plus the step's reference frames, about once a second when the picture is still and changed. We don't store what we send; the provider's API terms apply.
- The event log and Databricks hold numbers and short text: run id, lesson id, step numbers, answers, confidence, latency, timestamps. No images, no names, and a random run id.
- The expert's take is the lesson content and stays on the laptop. Lesson files can go to a Databricks Volume; that is the expert's video, never a learner's camera.
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
- [ ] Optional: published dashboard link (`databricks/dashboard.md`) in "Try it out", only if it shows real runs and the published link opens without a login

**Placeholders to fill or delete**
- [ ] [[DEMO VIDEO URL]] (two places)
- [ ] [[NOVICE RESULTS]]: from real folds by people new to it: camera-verified steps, manual steps, false passes, false alarms. If not run, delete the bullet.
- [ ] [[CATCH RATE]]: planted skipped steps caught out of the number tried. If not run, delete the bullet.
- [ ] [[IF GLASSES]]: glasses used as the live learner camera? If not, delete; if yes, also delete the "paid Apple Developer team" row.
- [ ] [[IF CATCH]] and [[IF DBX]]: keep only what was shown working on the demo laptop.
- [ ] [[IF BIKE REC]]: keep only if `front-wheel-v1` and its recording play on the demo laptop (today only `lessons/templates/front-wheel.steps.json` is on disk).
- [ ] [[7]] of 9: camera-checked steps in the demo lesson. Today's `lessons/fortune-teller-v2/lesson.json` has 7 of 9 (steps 4 and 8 manual). Recount if it is rebuilt.
- [ ] "Say whether any question or reference frame was fixed by hand." Step times were hand-marked (commit 8d51dc5).
- [ ] [[confirm which provider cut or titled the demo lessons]] (Gemini or Claude), and the check provider shown in `state.check_mode`. If no Gemini call was used for the demo lessons, delete the Gemini track row or reword it as "second provider".
- [ ] Tagline: use the "on Meta glasses" version only if a demo lesson was recorded on the glasses (the fortune teller v2 take is an iPhone video).

**Image gallery (3:2, upload in this order)**
Every PNG in `web/screenshots/` and `poster/img/` comes from mock or timer checks on a test lesson. Reshoot on the real lesson, or caption "Test lesson, simulated check".
1. Photo: a judge or teammate folding under the lamp, Learn screen behind. "Each clip plays when the camera sees the last fold is done."
2. Learn mid-lesson on the real lesson (reshoot of `web/screenshots/02-learn-mid-lesson.png`). "Live camera on one side, the expert's captioned clip on the other."
3. Verified (reshoot of `19-real-server-verified.png`). "Confident yeses, a chime, and the next clip starts."
4. Mistake card (reshoot of `06b-mistake-live.png`). "A skipped step, named on screen and said out loud."
5. Done (reshoot of `20-real-server-done.png`). "Your time against the expert's for every step."
6. Teach review with the step list (reshoot of `18-teach-review.png`) or `lessons/<id>/review/sheet.jpg`. "One take, cut into steps with checks."
7. Dashboard page "Where learners get stuck". "Learner time per step against the expert, from our rehearsal runs."
8. Dashboard page "Camera check quality". "Check answers, latency and false passes per step."
9. Genie answer to "Which step do people get stuck on?"
10. Checks off (`10-checks-off.png`, caption as a test lesson). "When the model is down, the screen says so and Next still works."
11. Native apps side by side: `apps/apple/screenshots/learn-iphone-landscape.png`, `apps/android/screenshots/learn-landscape.png`. Caption: "Built and tested; the table demo uses the web app."
12. Poster: `poster/poster.png`.

**Rule check**
- [ ] No "first", "only", savings figure, user count or past-winner claim.
- [ ] Competitors named: Dozuki and Retrocausal only.
- [ ] Every number traces to the repo or a filled placeholder.
- [ ] Model names match what the demo hub ran, and match docs/pitch.md.

Sources for Inspiration (not for Devpost): Manufacturing Institute and Deloitte, April 3, 2024, themanufacturinginstitute.org/manufacturers-need-as-many-as-3-8-million-new-employees-by-2033/; dozuki.com/creatorpro; retrocausal.ai. Repo numbers: test counts from commit messages a294a7c (Apple 259), d1c71a7 (Android 306), 8a98945 (desktop 33), 2a09b03 (library 46 routes, 25 tests), 51e0c73 (e2e 21 of 21); thresholds `server/config.py` (HANDOVER_MIN_CONF 0.8, HANDOVER_FAST_CONF 0.92, HANDOVER_MISTAKE_SETTLE_S 5, HANDOVER_GATE_HEARTBEAT_S 6, budget 20 and 50 USD); latency `server/docs/checks.md` and 9d1bdc2; synthetic accuracy `server/docs/understanding.md` (10 of 63, 4 of 63) and `server/docs/checks.md` (15 of 23, 4 of 6); vision boundaries 6caf276; HDR 3452196; Databricks `scripts/databricks_setup.py`, `databricks/dashboard.md`, `databricks/genie.md`, `server/databricks.py`, `server/test_engine.py::test_slow_databricks_never_delays_checks_or_advances`.
