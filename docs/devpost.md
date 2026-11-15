<!--
BEFORE YOU SUBMIT (delete this whole comment before pasting into Devpost)

Conditionals: each has an IF block and an ELSE block. Keep one, delete the other, delete the markers.
  [ ] C1  Glasses gate (Sat 8 PM): frames from Ray-Ban Meta reached the hub through the iPhone app for 60 s
          with no gap over 5 s and one camera advance. Appears in: What it does, How we built it, Challenges,
          Accomplishments, Built with.
  [ ] C2  iPhone app (W8a): built, signed and streaming the phone camera. Appears in: How we built it, Built with.
  [ ] C3  The catch (M9 + W6): skipped flip named on screen and spoken. Appears in: What it does, Accomplishments.
  [ ] C4  Done screen (S-D) merged and showing real per-step times. Appears in: What it does.
  [ ] C5  Databricks: events landing in Unity Catalog, dashboard built, Genie answers the question.
          Appears in: How we built it, Accomplishments, Built with.
  [ ] C6  Motion gate (M5) merged. Appears in: How we built it, Challenges.
  [ ] C7  Breaker (M6) merged with the "Checks off, use Next" badge. Appears in: How we built it, Challenges.
  [ ] C8  Bike lesson really was cut from one take. Appears in: What it does. ("One take" is allowed ONLY if true.)
  [ ] C9  Privacy test (M15) merged: a test asserts learn frames never touch disk. Appears in: How we built it.
  [ ] C10 Clean reference frames (M8) merged: stillest hands-free frame near the end of each step.
          Appears in: How we built it.
  [ ] C11 Gemini gate result (6 PM): advance rule stayed at 2 confident yeses, or dropped to 1 yes plus Next.
          Appears in: What it does, Challenges.

Placeholders (search for "[[" ):
  [ ] [[DEMO VIDEO URL]]           backup demo video (YouTube or Vimeo, public or unlisted)
  [ ] [[MEDIAN LATENCY]]           median of the 20 timed checks from `python -m server.check --time`
  [ ] [[NOVICE RESULTS]]           counts from the ten novice folds: camera-verified, manual, false passes, false alarms
  [ ] [[CATCH RATE]]               planted flips caught out of 20 at the 8 AM rehearsal
  [ ] [[REPO URL]]                 public GitHub link
  [ ] Gallery photos: judge folding, glasses on Sikandar, bike lesson timeline, dashboard, Genie answer
  [ ] Try-it links: Devpost has no hosted demo (the hub runs on one Mac on a hotspot). Leave "Try it out" as the
      repo link only.

Rule check before pasting: no "first", no "only", no training-time savings figure, no user count,
competitors are Dozuki and Retrocausal and nobody else.
-->

# HandOver

**Tagline (under 200 characters):**
An expert does a task once on Meta glasses. HandOver turns it into a lesson that plays their clip for each step and moves on when the learner's camera shows the step is done.

---

## Inspiration

A lot of hands-on skill is still passed along the slow way: someone who knows the task stands next to someone who doesn't and shows them, again and again. Manufacturers may need as many as 3.8 million new workers between 2024 and 2033, and Deloitte and the Manufacturing Institute estimate 1.9 million of those jobs could go unfilled. Demand for skilled people is growing faster than the supply of experienced people who can teach them.

The tools we found split into two groups. Some turn an expert's video into a document: Dozuki CreatorPro has "Video to Guide," which outputs numbered text steps and a quiz. Others check work with cameras: Retrocausal's Assembly Copilot tracks steps live, but setup means installing a station camera that can see every step, capturing a few work cycles, labeling one, and deploying a trained model.

We wanted the expert's own hands and voice as the instruction, and a camera that decides when the next clip plays. A how-to video that waits for you.

## What it does

HandOver has two sides.

**Teach.** An expert wears Meta glasses and does the task while talking through it. They upload the video. HandOver sends it to Gemini in one call and gets back the steps: start and end times, a short imperative title, a yes/no question about what the object looks like when the step is done, and a transcript of the narration. The server then cuts one clip per step, writes WebVTT captions from the transcript, and saves a reference frame showing the finished state. Steps whose result can't be seen in a photo (a crease made and unfolded, a felt tension) are marked manual.

**Learn.** The learner points a camera at their hands. The screen shows their live view next to the expert's clip for the current step, captioned. About once a second the hub sends Gemini the live frame, the step's reference frame and the check question. When the answer is yes with confidence of at least 0.8 twice in a row, the step is verified, a chime plays, and the next clip starts. A "no" or "unsure" resets the count, so HandOver never advances on a guess. The Next button always works, and voice "next" is built in (off by default for loud rooms).

<!-- IF C11 = gate passed (median 2.5 s or less): keep the paragraph above as is. -->
<!-- ELSE C11 (median over 2.5 s): replace "twice in a row" with "once" and add: "Gemini latency on the venue hotspot was too high for two checks in a row, so one confident yes advances the step." -->

The live demo is an origami fortune teller folded by a judge at our table. The pre-recorded showcase is a bike front wheel quick-release.

<!-- IF C8 (bike lesson was one take): -->
The bike lesson was cut from one take with no hand editing.
<!-- ELSE C8: -->
The bike lesson was cut from our expert's recording by the same pipeline; we picked boundaries by reviewing the output, not by editing clips by hand.
<!-- END C8 -->

<!-- IF C3 (catch shipped): -->
**It notices a skipped step.** If the learner sits on a "no" for 5 seconds, HandOver compares their camera against the previous, current and next reference frames. If it still looks like the previous step, an amber banner and a spoken line name the step ("Still step 4: flip it over"). If it already looks like the next step, it says "You're ahead" and moves on. In the demo, the judge can leave the paper unflipped on purpose and watch the screen call it out.
<!-- ELSE C3: -->
<!-- (delete the paragraph above; do not mention mistake detection anywhere) -->
<!-- END C3 -->

<!-- IF C4 (done screen shipped): -->
**It shows how the run went.** The done screen lists the learner's time next to the expert's for each step, how many steps the camera verified, and how many were advanced by hand.
<!-- ELSE C4: -->
<!-- (delete the paragraph above) -->
<!-- END C4 -->

<!-- IF C1 (glasses gate passed): -->
**Glasses on both sides.** The expert records on Ray-Ban Meta glasses, and the learner can wear them too: our iPhone app pulls the glasses camera through Meta's Wearables Device Access Toolkit and streams it to the hub.
<!-- ELSE C1: -->
**Glasses for the expert, any phone for the learner.** The expert records on Ray-Ban Meta glasses. The learner uses a phone on a stand or chest mount, which gives a steady angle and needs no fitting.
<!-- END C1 -->

## How we built it

**The hub.** One FastAPI process on a Mac serves everything: the REST API for lessons and teach jobs, the lesson files with range requests, the web app, a phone camera page, and two WebSockets. Cameras send JPEGs to `/ws/camera`; the web app gets state, advances and a downscaled live preview on `/ws/ui`. It listens on HTTP 8000 and HTTPS 8443 in the same process so both share one learn session. Lessons are plain folders: `lesson.json`, `clips/NN.mp4`, `captions/NN.vtt`, `frames/NN.jpg`.

**Teach pipeline** (`server/teach.py`). Three stages: normalize, extract, cut.
- Normalize with ffmpeg to 1080p, 30 fps constant, H.264 and AAC, tagged SDR bt709. Several files can be joined into one before extraction, since glasses recordings come in short pieces.
- Extract with one `gemini-3.8-flash` call on the whole video, using a Pydantic schema for structured output. The prompt treats narration as the main signal for step boundaries and uses the video to place each boundary where the hands start the new action. It asks for 3 to 12 steps and for check questions answerable from one photo.
- Cut each clip, slice the transcript into per-clip captions, and grab the reference frame.
- A recut endpoint rebuilds clips from an edited `lesson.json` in a temp folder and swaps them in when every step succeeds, so a bad edit never leaves a half-built lesson.

<!-- IF C10 (clean reference frames merged): -->
- The reference frame is the stillest frame without hands in the last 15% of each step, not the literal last frame, which was often blurred or blocked by a hand. Check questions describe shape and seam count, not paper color, so a judge's sheet doesn't have to match the expert's.
<!-- ELSE C10: -->
- The reference frame is the last frame of each step's clip.
<!-- END C10 -->

**Check loop** (`server/check.py`, `server/main.py`). The check uses `gemini-3.5-flash-lite` with two images (reference, then live), low media resolution, minimal thinking and temperature 0, and returns `{"done": "yes|no|unsure", "confidence"}`. One check runs at a time, always on the newest frame. A result that comes back after the step changed is thrown away, and a new step is never judged with a frame taken before it began. A call that takes longer than 3 seconds counts as unsure.

<!-- IF C6 (motion gate merged): -->
A motion gate keeps calls down: the hub compares small grayscale thumbnails of consecutive frames and calls Gemini when the scene is still and has changed since the last check, with a heartbeat call every 6 seconds.
<!-- END C6 -->
<!-- IF C7 (breaker merged): -->
After 3 errors in a row or any rate-limit response, a breaker turns checks off for 30 seconds and the screen says "Checks off, use Next" instead of silently stalling.
<!-- END C7 -->

**Web app** (React, TypeScript, Vite). A Learn screen and a Teach screen, served by the hub. Teach shows the full take with a colored step timeline and a grid of step thumbnails; click one to play that clip. Learn shows honest live states: "Waiting for camera," "Reconnecting," a dimmed last frame with "Camera lost. Keep going with Next," and a "Recording" badge whenever frames come from a replayed video instead of a live camera.

**Cameras.** Any phone browser can be the camera through `/capture` over HTTPS. `server/replay.py` streams an MP4 into the hub as if it were a live camera, which is how we tested the loop without folding paper every time and how we keep a labeled fallback for the demo.

<!-- IF C2 (iPhone app works): -->
A native SwiftUI iPhone app sends about one JPEG per second to the hub, shows the current step title, and has Next and Back buttons so the learner doesn't have to reach for the laptop.
<!-- IF C1 (glasses gate passed), add: -->
The same app can switch its source to Ray-Ban Meta glasses through Meta's Wearables Device Access Toolkit, and falls back to the phone camera on its own if the glasses stream stops.
<!-- END C1 -->
<!-- ELSE C2: -->
<!-- (delete the paragraph above; the Safari /capture page is the phone path) -->
<!-- END C2 -->

<!-- IF C5 (Databricks shipped): -->
**Data layer** (Databricks). Databricks is never in the live loop. `server/databricks.py` writes every learn event (run start and end, step entered, check result, advance, mistake, checks off) to a local JSONL file, and a background thread batches them into Unity Catalog tables through the SQL Statement Execution API: one statement per table, at most every 5 seconds, nothing sent when there is nothing new. Lesson files go to a Unity Catalog Volume. An AI/BI dashboard shows learner time per step against the expert's, how often each camera step was forced with Next, and likely false passes (a camera advance followed by Back within 60 seconds). A Genie space answers "Which step do people get stuck on?" in plain English.
<!-- ELSE C5: -->
<!-- (delete the paragraph above and the Databricks tags in Built with) -->
<!-- END C5 -->

**Privacy.** Learn frames live in memory. The hub keeps the newest frame in one slot and overwrites it with the next; it never writes a learner's camera frame to disk. Frames are sent to the Gemini API for the check.
<!-- IF C9 (privacy test merged): add "A test in the suite fails if a learn frame ever lands on disk." -->

**Team.** Soham built the server, the teach pipeline and the check loop, and cut both lessons. Pranav built the web app, the phone capture page, the iPhone app and the Databricks plumbing. Sikandar recorded the expert takes on the glasses, ran the props and tested with people who had never folded a fortune teller. Prayush built the Databricks dashboard and Genie space and put together the story and pitch.

## Challenges we ran into

**iPhone HDR footage looked washed out in the browser.** iPhones record HDR (PQ or HLG in bt2020). Chrome played our clips gray and flat. Converting the color matrix to bt709 wasn't enough: ffmpeg carried the HDR frame tags from the input and those won over our encoder flags. We now detect the transfer function with ffprobe, convert bt2020 to bt709, and rewrite the frame tags explicitly.

**Waiting on a cloud model while someone folds paper.** A single Gemini check takes a noticeable fraction of a second, and a single yes can be a fluke when the paper is half folded. We settled on two confident yeses in a row at 0.8 or higher, one check in flight at a time, and a 3 second timeout that counts as unsure. We measured [[MEDIAN LATENCY]] median over 20 real checks before tuning the debounce.
<!-- IF C6 or C7: add "Free-tier rate limits for these models aren't published, so we added the motion gate and breaker to keep call volume down and fail visibly." -->

**A dependency broke the day before.** google-genai shipped a breaking release on November 12 that changed defaults. We froze every Python dependency into `server/requirements.lock` on the demo Mac, pinned the API version to v1beta explicitly, and installed from the lock on every machine.

**Phones won't open the camera over plain HTTP.** Browsers require a secure context for `getUserMedia`. We generate mkcert certificates for the laptop's hotspot IP and serve HTTPS on 8443 from the same process as HTTP, so the phone page and the laptop screen share one session. Every demo phone has the mkcert root trusted ahead of time.

**A Next tap could skip a step.** If the camera advanced a step at the same moment the learner pressed Next, both landed and the learner jumped two steps. Every Next and Back now carries the step the client was showing, and the hub ignores it if the step already changed.

**Keeping learner video off disk.** The easy path for debugging is to save frames. We didn't. Frames are held in memory, checked, forwarded to the screen at a reduced size, and overwritten.

<!-- IF C1 (glasses gate passed): -->
**Getting frames out of the glasses.** Meta's toolkit is a developer preview, raw frames arrive with the app in the foreground, and backgrounding ends the session. The iPhone app keeps the screen awake, throttles the glasses stream to one frame per second, and switches to the phone camera when frames stop.
<!-- ELSE C1: -->
**Glasses as a live camera didn't make the cut.** We time-boxed streaming from Ray-Ban Meta through an iPhone app and set an 8 PM go/no-go. It didn't pass that test reliably, so the glasses stay the expert's recorder and the learner uses a phone.
<!-- END C1 -->

## Accomplishments that we're proud of

- A judge can fold a fortune teller at our table and watch the expert's clips advance as each fold is seen.
- The expert does no editing. One Gemini call gives the steps, titles, check questions and transcript; ffmpeg does the rest.
- The screen tells the truth about its state: camera lost, reconnecting, recorded input, and Next always works.
- The check refuses to guess. "Unsure" never moves a step.
<!-- IF C3: - The screen catches a skipped flip and names the step, out loud. In rehearsal under venue light it caught [[CATCH RATE]] of 20 planted mistakes. -->
<!-- IF C5: - Every run lands in Databricks, and Genie can tell the expert which step people get stuck on. -->
<!-- IF C1: - Ray-Ban Meta glasses streaming live into the loop through our own iPhone app. -->
- Ten folds by people who had never folded one: [[NOVICE RESULTS]].

## What we learned

- Narration is the strongest signal for where a step begins. The video is better at confirming where the hands actually start.
- Check questions have to describe what a camera can see: shape, seam count, how many flaps. Color and "is it creased" are unreliable.
- Some steps can't be checked from a photo, and saying so (a manual step) is better than a check that passes by accident.
- A fallback for every link (phone page, replay with a visible "Recording" badge, the Next button) made it safe to demo on hackathon Wi-Fi.
- Measure before tuning. The latency numbers decided the debounce rule, not the other way around.

## What's next for HandOver

- A review editor so the expert can rename steps and drag boundaries before publishing.
- A self-test at teach time: run each check question against its own reference frame (should be yes) and the previous one (should be no), and flag steps that can't tell them apart.
- Safety warnings and a tools list pulled from the expert's own narration.
- Translated captions.
- A deployment where frames are checked on a paid tier with no data retention, or on device.
- Testing in a real workplace with a real expert and new hires.

## Built with

python, fastapi, uvicorn, websockets, pydantic, pillow, ffmpeg, google-gemini, gemini-3.8-flash, gemini-3.5-flash-lite, google-genai, react, typescript, vite, playwright, webvtt, mkcert, meta-ray-ban-glasses
<!-- IF C2: add swift, swiftui -->
<!-- IF C1: add meta-wearables-device-access-toolkit -->
<!-- IF C5: add databricks, unity-catalog, databricks-sql, databricks-genie, ai-bi-dashboards -->

## Try it out

- [[REPO URL]]
- Demo video: [[DEMO VIDEO URL]]

---

## Gallery (upload in this order)

The PNGs in `web/screenshots/` use the synthetic color-bar test lesson. Reshoot 2, 3, 4 and 6 on the real fortune teller or bike lesson if there is time; otherwise use the listed file and keep the caption.

1. **Photo: a judge folding under the lamp, phone or glasses on, learn screen behind.** Caption: "A judge folds a fortune teller. Each clip plays when the camera sees the last fold is done."
2. **Teach screen, bike lesson** (reshoot of `08-teach-lesson.png`). Caption: "The expert's take, cut into steps by one Gemini call. Click any step to play its clip."
3. **Learn screen mid-lesson** (`02-learn-mid-lesson-1920.png` or a reshoot). Caption: "Live camera on the left, the expert's captioned clip for this step on the right."
4. **Verified** (`11-real-server-verified.png`). Caption: "Two confident yeses from the check, a chime, and the next clip starts."
5. **Mistake banner** (IF C3; new screenshot). Caption: "The learner skipped the flip. HandOver names the step and says it out loud."
6. **Done screen** (IF C4; `12-real-server-done.png` or a reshoot). Caption: "Your time against the expert's for every step."
7. **Manual step** (`04-manual-step.png`). Caption: "Steps a photo can't confirm are marked manual. The learner presses Next."
8. **Honest states** (`13-reconnecting.png`). Caption: "When the connection drops, the screen says so and Next still works."
9. **Databricks dashboard** (IF C5). Caption: "Learner time per step against the expert, from real runs."
10. **Genie answer** (IF C5). Caption: "Asking Genie which step people get stuck on."
11. **Photo: Sikandar recording the bike lesson on Ray-Ban Meta.** Caption: "The expert records once while narrating."
12. **iPhone app** (IF C2). Caption: "The phone streams the camera and shows the current step with a Next button."

Sources for the Inspiration section (keep in the repo, not needed on Devpost): Manufacturing Institute and Deloitte, April 3, 2024, themanufacturinginstitute.org/manufacturers-need-as-many-as-3-8-million-new-employees-by-2033/; Dozuki, dozuki.com/creatorpro; Retrocausal, retrocausal.ai.
