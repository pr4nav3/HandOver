# Second half of the build (Sunday Nov 15, from about 1:30 AM)

Three people, three lanes, about 2.5 hours to a demo that runs on its own. Software is at MVP; what is left is content, voice, Databricks and a real rehearsal. Everything runs on Pranav's Windows laptop from `C:\Users\karth\Projects\HandOver-soham` (branch `pranav/live-fps-and-checks`, same as `main`).

| Lane | Who | Output |
|---|---|---|
| A. Bike lesson, highlights, app voice cues | Pranav + Claude | `lessons/front-wheel-v1` narrated and rendered, cues in the app |
| B. Origami lesson | GPT Pro person | step times, titles and narration lines for the new take, as two small files (below) |
| C. Databricks | Prayush | credentials on the demo laptop, tables and dashboard live, one Genie question |
| D. Test | everyone, Pranav drives | the checklist at the end, all green on the demo laptop |

## A. Bike lesson (Pranav + Claude)

Take: front wheel off, rim checked, wheel back on, spin, front brake. Template with 11 steps: `lessons/templates/front-wheel.steps.json` (drop the steps the take does not contain).

1. Run the pipeline on the take (silent take, vision cuts at done moments, voiceover):
   `scripts\make_lesson.ps1 -Video <take> -Id front-wheel-v1 -Title "Front wheel check" -Template lessons\templates\front-wheel.steps.json -NoSpeech`
2. Open `lessons\front-wheel-v1\review\sheet.jpg`. Move any start or end in `lesson.json`, fix titles, then `scripts\make_lesson.ps1 -Id front-wheel-v1 -Recut`.
3. Narration: the lines live in `docs/VOICE_SHEET.md`. Hand-written lines win over Claude's: put them in `lessons/front-wheel-v1/review/voice.json` (`{"steps": {"1": "line", "2": "line"}}`) and run `python -m server.voice lessons/front-wheel-v1 --script lessons/front-wheel-v1/review/voice.json --mode replace`.
4. Highlights and zoom: `python -m server.produce lessons/front-wheel-v1 --theme ivory --accent #1F49D6` writes `clips_produced/NN.mp4` with a slow push-in toward the hands, a highlight ring at the key moment, a step label and a progress bar. Review them, then point each step's `clip` at the produced file so Learn plays the rendered version. The hub never touches these; a recut rebuilds the plain clips and the render is rerun.
5. Planted mistake for the demo: close the quick release pointing forward. The step's `common_mistake` is the spoken line.

## B. Origami lesson (GPT Pro person)

You do not need the repo running. Deliver two small files and we run the pipeline.

1. Watch the new paper take once at normal speed, once slowly. The fortune teller has eight to nine steps; the list in `lessons/templates/fortune-teller.steps.json` is the prior. Keep steps whose END STATE is clearly visible (a completed fold), split or merge where the take differs.
2. File 1, `fortune-teller-v2.steps.json`, same shape as the template: per step `start`, `end` as `MM:SS.s`, `title` (shape words, never color), `check_question` (one yes or no question about shape or count, or `"manual"` for a step the camera cannot judge), `common_mistake` (one short spoken sentence used when the learner is behind). `start` of a step is the moment the hands begin it; `end` is the first moment its end state is visible.
3. File 2, `voice.json`: `{"steps": {"1": "one or two calm sentences, at most 22 words", ...}}`. Rules in `docs/VOICE_SHEET.md`. Never read the check question aloud. Second person, present tense, concrete ("Bring the bottom corner up to the top corner.").
4. Send both files to Pranav. We cut, voice (Kokoro, voice `af_heart`), self-test and lint in one command. If you want to hear the voice first, the sample clip is in `lessons/fortune-teller-v1/clips/02.mp4`.

Use GPT for drafting the lines and for sanity-checking the step list against the video, not for audio: one voice across both lessons matters more than any single line.

## C. Databricks (Prayush)

Data layer only, never in the live loop. The hub writes every learn event to `logs/events.jsonl` with or without credentials, and the uploader is a no-op until the three variables exist.

1. On the demo laptop, add to `.env` (never commit): `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_WAREHOUSE_ID` (optional `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`).
2. `.venv\Scripts\python scripts\databricks_setup.py --check` says exactly what is missing with no network. Then `scripts\databricks_setup.py --with-history`: warehouse, schema, four tables, Volume, the 13 dashboard views (`ds_<name>` plus `ds_<name>_real` without mock and replay runs), today's real events from `logs/events.jsonl`, the real lessons' files. Free Edition quota: the script batches and polls slowly; run it once.
3. Your SQL and dashboard JSON from `prayush/story-dbx` are read from `databricks/` in the working tree; Claude is merging that branch into main so they are there.
4. Dashboard: one AI/BI dashboard over the `_real` views (steps per run, camera-checked versus manual, mistakes per step, check latency). Genie: one question rehearsed and screenshotted: "Which step do people get stuck on?"
5. Before judging: warm the warehouse (open the dashboard once), and confirm `python -m server.databricks --selftest --remote` shows rows arriving.
6. If anything fails, the demo does not change: the hub keeps the local JSONL and the UI never waits on Databricks (tested with a hung warehouse).

## D. Test on the demo laptop (last 45 minutes)

1. Stop the stale hub: `Stop-Process -Id 42320`. `scripts\preflight.py` must say READY.
2. `scripts\run_server.ps1`. Laptop: `http://<ip>:8000/`. Phone: `https://<ip>:8443/capture`, tap Start Camera, see the step title and the YOU tab.
3. Ten real folds by someone who has not folded one: count camera-verified steps, manual steps, false passes, false alarms. Tune `HANDOVER_DEBOUNCE_N`, `HANDOVER_MIN_CONF`, `HANDOVER_CHECK_INTERVAL_S` only from those counts.
4. Bike lesson play-through once; the planted quick release mistake caught within 10 s or step becomes manual for the demo.
5. Breaker rehearsal: start the hub with an invalid key, see "Checks off, use Next", finish a lesson by Next.
6. Replay fallback: `python -m server.replay lessons\front-wheel-v1\norm.mp4 --loop` shows the Recording tag. Record a 20 s skipped-step clip for the catch fallback.
7. Backup video of a full clean run, phone screen recording plus laptop screen.
8. Freeze. Only fixes after this, each run once on the laptop.
