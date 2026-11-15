# Second half of the build (Sunday Nov 15, from about 1:30 AM)

Three people, three lanes, about 2.5 hours to a demo that runs on its own. Software is at MVP; what is left is content, voice, Databricks and a real rehearsal. Everything runs on Pranav's Windows laptop from `C:\Users\karth\Projects\HandOver-soham` (branch `pranav/live-fps-and-checks`, same as `main`).

| Lane | Who | Output |
|---|---|---|
| A. Bike lesson, highlights, app voice cues | Pranav + Claude | `lessons/front-wheel-v1` narrated and rendered, cues in the app |
| B. Origami lesson | Soham | step times, titles and narration lines for the new take, as two small files (below) |
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

## B. Origami lesson (Soham), run it yourself

Your timed step list and voice lines are in the repo (`lessons/templates/fortune-teller-v2.steps.json`, `fortune-teller-v2.voice.json`) and the first cut of `lessons/fortune-teller-v2` is on main: nine steps at your times, your nine lines spoken by Kokoro `af_heart`, lint clean. From here you own it: adjust times or lines, recut, re-voice, push.

### Getting the take at full quality

Google Drive does not downgrade the file; only its web preview plays at 720p. Use the Download button (or the Drive desktop app), never "save video" from the preview. The iPhone original is HEVC, HLG HDR, about 14 Mbps, 1644x918 at 30 fps. HDR looks flat and grey in most Windows players and browsers; that is the player, not the file. The pipeline tone-maps HDR to SDR itself (mobius curve), so what the app plays looks right. Same for the Ray-Ban Meta glasses take, which is HDR too, 1328x1776.

### One-time setup on your machine (10 minutes)

Mac:
```sh
git clone https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer.git handover && cd handover
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r server/requirements.lock
brew install ffmpeg                       # ffmpeg 6 or newer with zscale (the Homebrew build has it)
cp .env.example .env                      # ANTHROPIC_API_KEY only if you want the self-test; cutting and voicing need no key
```
Windows: the "Run (Windows)" block in `README.md`, then the same commands with `.venv\Scripts\python`.

The first voice run downloads the Kokoro model (354 MB) into `~/.cache/handover/kokoro`.

### Cut, voice, review (3 minutes of machine time)

```sh
P=.venv/bin/python        # Windows: .venv\Scripts\python
$P -m server.teach "<path to origami new.mov>" --id fortune-teller-v2 --title "Fold a fortune teller"    --steps-json lessons/templates/fortune-teller-v2.steps.json --dry-run     # prints the planned cuts, writes nothing
$P -m server.teach "<path to origami new.mov>" --id fortune-teller-v2 --title "Fold a fortune teller"    --steps-json lessons/templates/fortune-teller-v2.steps.json               # normalize (HDR tone-mapped), cut, frames, captions
$P -m server.voice lessons/fortune-teller-v2 --script lessons/templates/fortune-teller-v2.voice.json --mode replace
$P scripts/contact_sheet.py --lesson lessons/fortune-teller-v2              # lessons/fortune-teller-v2/review/sheet.jpg
$P scripts/lesson_lint.py lessons/fortune-teller-v2                         # must end 0 FAIL
```
`teach` refuses an existing id: `rm -rf lessons/fortune-teller-v2` first when rebuilding from the take. If ffmpeg complains about an audio stream it cannot decode, that is fixed on main (the first audio track of iPhone .mov files has no codec); pull.

### Iterating

- Times: edit `start` and `end` in `lessons/fortune-teller-v2/lesson.json` (or in the steps file and rebuild), then `$P -m server.teach --recut lessons/fortune-teller-v2 --repick`. A recut drops the voiceover: run the voice command again.
- Lines: edit the voice file and rerun the voice command. Rules in `docs/VOICE_SHEET.md`; the tool warns when a line is longer than its clip allows and keeps it anyway, so shorten it.
- Questions and titles: edit `lesson.json` directly (`check_question`, `title`, `common_mistake`). `check_question: ""` with `check_type: "manual"` makes a step manual.
- Self-test (needs a Claude key, about a cent): `$P -m server.teach --recut lessons/fortune-teller-v2 --strict-self-test` marks steps the model cannot tell apart as manual. Run it once at the end.
- Watch it: `HANDOVER_CHECK=mock scripts/run_server.sh` then `http://localhost:8000/#/learn/fortune-teller-v2` (Windows: `scriptsun_server.ps1`); captions and the voice play in the Expert pane.
- Push: commit the whole `lessons/fortune-teller-v2` folder (clips, captions, frames, lesson.json; `.orig.*` files are ignored) on a branch `soham/origami-v2` and tell Pranav; he fast-forwards main. Do not commit `norm.mp4` edits or the take itself.

The planted mistake for the demo is step 6, the flip: `common_mistake` is what the app speaks when the learner skips it.

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

## E. Privacy (for the pitch and the Devpost)

`docs/PRIVACY.md` is the source: frames stay in memory, a test proves they never touch disk, the model sees one frame per check, the event log and Databricks hold numbers only, no accounts. The spoken demo line is at the bottom of that file.
