# HandOver

An expert does a task once on camera, for example on Meta glasses. HandOver turns the take into a lesson that plays the expert's clip for each step and moves on when the learner's camera shows the step is done.

## Why

A lot of hands-on skill is still passed along the slow way: someone who knows the task stands next to someone who doesn't and shows them, again and again. Manufacturers may need as many as 3.8 million new workers between 2024 and 2033, and Deloitte and the Manufacturing Institute estimate 1.9 million of those jobs could go unfilled. The people who can teach are a bottleneck.

Existing tools split into two groups. Some turn an expert's video into a document: Dozuki CreatorPro's "Video to Guide" outputs numbered text steps and a quiz. Others check work with cameras: Retrocausal's Assembly Copilot tracks steps live, but setup means a station camera that can see every step, a few captured work cycles, a labeled cycle and a trained model.

HandOver uses the expert's own hands as the instruction, and the learner's camera decides when the next clip plays: a how-to video that waits for you.

## What it does

HandOver has two sides.

**Teach.** The expert does the task once while wearing Meta glasses (or in front of any camera). HandOver cuts the take into steps. Each step gets a short imperative title, its own clip, timed captions, a reference frame that shows what done looks like, and a yes or no check question about shape or count. Steps whose result a camera can't judge, like a crease made and unfolded, are marked manual. A calm voiceover is written per step and spoken over the clips.

**Learn.** The learner points a phone or laptop camera at their hands. The screen shows their live view next to the expert's clip for the current step. When the picture is still and has changed, the hub offers a frame to the vision model at most every 0.5 seconds: it sends the step's reference frame, the previous step's reference as a "before" example when there is one, the live frame and the question. Two confident yeses on two different frames (confidence 0.8 or more) mark the step verified; a chime and a short spoken cue ("That's it. Next step.") play and the next clip starts. One yes at 0.92 or more that names no difference also passes. "No" or "unsure" resets the count, so a guess never moves the lesson. Next always works. The fixed cues are spoken in the lesson voice, and the clip ducks while a cue plays; a step's own mistake message is spoken by the browser's speech synthesis.

**Mistakes.** After 5 seconds of steady "no", the hub makes one extra call comparing the live frame to the previous, current and next reference. If the learner still matches the previous step, the screen names it and says the step's common mistake out loud. It never moves a learner forward on its own when they are behind.

**Done.** The done screen shows the learner's time on each step next to the expert's, and how many steps the camera checked.

**For the expert, later.** Every check, advance and caught mistake can go to Databricks. A dashboard shows time per step against the expert and where people press Next instead of passing, and Genie answers "Which step do people get stuck on?" in plain English.

## How it is built

**Hub.** One Python process (FastAPI, uvicorn, websockets) runs on a laptop on the local network. It serves the lesson files, the web app, a camera socket and a UI socket, plus an HTTPS port with a local mkcert certificate so phone browsers can use the camera.

**Teach pipeline** (`server/teach.py`, `server/voice.py`, `server/produce.py`):
1. ffmpeg normalizes the take to H.264, TV-range yuv420p, so it plays on every browser and on Windows.
2. Step extraction. With a Gemini key, Gemini 3.8 Flash watches and hears the take in one call. With a Claude key, Claude reads frames and a local faster-whisper transcript with word timestamps. For silent takes, Claude Sonnet finds the earliest moment each step's end state is visible (pass 1 over sampled frames, with a template step list as the prior), then refines each cut on frames 0.25 s apart.
3. ffmpeg cuts one clip per step. A reference frame is picked near the end of each step where the hands are out of the way. Check questions are rewritten from the frames: shape and counts, never color.
4. A self-test runs each question against its own reference (should be yes) and the previous one (should be no). With `--strict-self-test`, steps that fail become manual.
5. Voiceover: hand-written lines win; otherwise Claude Haiku writes one or two short lines per step. Kokoro speaks them locally (ElevenLabs is a switch, with Kokoro as the fallback), and the mix ducks under the clip with timed WebVTT captions. See `docs/voice.md`.
6. Output is a folder: `lesson.json`, clips, captions and reference frames. A linter checks it. `scripts/make_lesson.ps1` runs the whole chain in one command, with `-Recut` after hand edits.
7. Optional: `server/produce.py` renders a produced course video per step with title cards, a slow zoom toward the hands, a highlight ring, step labels and crossfades.

**Learn loop** (`server/main.py`, `check.py`, `gate.py`, `mistake.py`):
- The iPhone path sends JPEG frames at up to 15 a second by default, long side 640. The hub keeps just the newest frame per camera, in memory.
- A motion gate (Pillow) samples motion up to eight times a second and lets a frame through when the picture has settled and differs from the last checked frame, plus a 2 s heartbeat.
- The check calls Claude Haiku (`claude-haiku-5-5`, with prompt caching) or Gemini (`gemini-3.5-flash-lite`). The answer is evidence first: what it sees, what differs, done yes/no/unsure, and confidence. A "yes" that names a difference is turned into "unsure".
- Up to two checks run at once on different settled frames. Answers are ordered by frame, so a late answer for an old frame never outweighs a newer one.
- A breaker turns checks off after 3 errors or timeouts in a row, any rate limit, or the spend cap, and the screen says "Checks off, use Next". Claude spend has a hard $20 per day and $50 total cap.

**Screens.** React, TypeScript and Vite. Learn draws the live feed on a canvas (newest frame each time), preloads the next clip, and shows honest states: camera lost, reconnecting, Recording for replays, checks off. A phone capture page streams the camera over the local network. Playwright end-to-end tests drive a real hub with a replayed camera.

**Data layer** (Databricks, never in the live loop). The hub writes every learn event to a local JSON lines file. With credentials, it batches them into four Unity Catalog tables (`lessons`, `steps`, `runs`, `events`) every 60 s and at run end, with MERGE on event id so retries never duplicate rows. The setup SQL also creates a Volume for lesson files and includes six dashboard query templates for step time, manual advances, likely false passes, camera readiness, check health and run outcomes. Mock runs remain local; replay runs are tagged by source/attempt kind so a dashboard can include or exclude them explicitly. If Databricks is slow or down, the learn loop doesn't notice; a test runs the loop against a hung warehouse.

**Native apps:** a SwiftUI app for iPhone, iPad and Mac, an Android app in Kotlin and Jetpack Compose, and a Tauri desktop app for Windows, Linux and Mac with a Rust core, each with its own test suite. Each one is a viewer of the hub and can be its camera. The iPhone and Android apps include the Meta Wearables Device Access Toolkit 1.0.1 for glasses streaming. The iOS Developer Mode path has been signed with a Personal Team and exercised with a Ray-Ban Meta Gen 2; distribution remains subject to Meta's preview and Apple signing rules. The hub also has accounts, courses, organizations and an editor with undo and redo (`HANDOVER_AUTH=optional` by default).

Optional and off by default: understanding mode (a per-step rubric as a second vote), and skipping ahead two steps on an "ahead" verdict (a wrong skip is worse than a missed catch).

## Challenges

- **Latency.** A check has to feel like a nod, not a wait. A leaner answer format brought one Claude Haiku check to about 1.1 to 1.3 s at the median in timing runs. Pipelining two checks on different frames and a fast path for one very confident yes cut the time from "hands still" to "next clip" further.
- **False passes.** Early checks said yes to almost-done paper. The check now sends the previous step's reference as a "before" picture, makes the model name what differs before it answers, turns a yes that names a difference into unsure, and strips color words from questions. On synthetic folds, the plain check still said yes on 10 of 63 not-finished frames; a second vote from the rubric cut that to 4 of 63 but blocked a sheet turned 45 degrees, so it stays behind a switch.
- **Debounce with checks in flight.** With two checks running at once, answers come back out of order. The debounce sorts them by frame so an old yes can never pass a step the newest frame says is not done.
- **Skipping ahead.** On synthetic folds, a learner who skipped a flip was called "ahead" in 15 of 23 tries. Ahead stays a banner, and "behind" is the case the hub acts on.
- **Silent takes.** Cutting by narration fails when the expert works quietly. Vision boundaries fix that: a stronger model finds the earliest moment each step's end state is visible, then refines the cut on frames a quarter second apart. On a real take it gave eight coherent steps for about 3 cents.
- **Windows.** The hub was written on a Mac and runs on Windows too: file locks while swapping voiced clips, font lookup for produced videos, ffmpeg paths, a spend ledger safe across processes, and a clear error when a port is already taken. The end-to-end test passes on Windows.
- **Stale controls.** A phone pressing End after the laptop had started a new lesson would end the wrong run. End now carries the lesson and run ids, and stale ones are ignored.
- **Databricks Free Edition.** One small warehouse and a daily compute quota. The hub flushes every 60 s instead of every few seconds, uses MERGE so retries don't duplicate, keeps tests and mock runs from reaching the warehouse, and tags replays so queries can filter them.
- **Glasses streaming.** The toolkit's live camera path is Bluetooth Classic. The phone forwards selected JPEG frames to the local hub with newest-only backpressure. Developer Mode registration and a Gen 2 live flow have worked on a signed iPhone build; broader device/firmware endurance is still release evidence to collect.

## What we learned

- Check questions must describe what a camera can see: shape, seam count, how many flaps. Color and "is it creased" are unreliable.
- Some steps can't be checked from a photo. Marking them manual is better than a check that passes by accident.
- Asking the model to name what differs before it says yes catches most of its own over-eager answers.
- Measure before tuning. Timing runs set the debounce and the check rate, not the other way around.
- Every link has a fallback (phone page, replay with a visible tag, Next), so a flaky network never blocks a learner.
- Keep analytics out of the live loop. The learn screen never waits on the warehouse.

## What's next

- Accuracy numbers from people new to a task, then from a real workplace task with a real expert.
- Repeatable sustained glasses-as-learner-camera runs across the supported phone, firmware and glasses matrix.
- Checks on a no-retention tier or on device.
- Translated captions and a voice "next" for loud rooms.
- A hosted hub so a whole team of learners can use the same lessons.
- Safety warnings and a tools list pulled from the expert's own take.

## Privacy

See `docs/privacy.md`. In short: the hub never saves learner camera frames. The private event log contains compact run metadata (including lesson/run IDs and a signed-in learner ID), but no images, audio, stable device IDs, camera names, IP addresses or auth tokens. The expert's take, clips and reference frames are lesson content and are stored separately.

Sources: Manufacturing Institute and Deloitte, April 3, 2024, themanufacturinginstitute.org/manufacturers-need-as-many-as-3-8-million-new-employees-by-2033/; dozuki.com/creatorpro; retrocausal.ai. Latency: `server/docs/checks.md`. Synthetic accuracy: `server/docs/understanding.md` and `server/docs/checks.md`.
