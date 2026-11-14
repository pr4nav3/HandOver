# Shared contract (server <-> web <-> capture)

All agents follow this. Change it only through the Lead.

## Paths
- Repo root: `/Users/sohamaggarwal/Projects/HandOver`
- Python venv: `.venv` (Python 3.12, env frozen in `server/requirements.lock`). Run `.venv/bin/python`.
- Lessons on disk: `lessons/<id>/` at repo root (override with env `HANDOVER_LESSONS`).
  - `lesson.json`, `norm.mp4`, `clips/NN.mp4`, `captions/NN.vtt`, `frames/NN.jpg` (NN = 01, 02, ...).
- Gemini key: env `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). Never print it. Optional `.env` at repo root (gitignored).

## lesson.json
```json
{"id":"fortune-teller-v1","title":"Fold a fortune teller","video":"norm.mp4",
 "steps":[{"n":4,"title":"Fold all four corners to the center","start":"00:22","end":"00:41",
   "clip":"clips/04.mp4","captions":"captions/04.vtt","ref_frame":"frames/04.jpg",
   "check_type":"camera","check_question":"Is the paper a smaller square with four triangular flaps meeting at the center?",
   "prerequisites":[3]}]}
```
`check_type` is `"camera"` or `"manual"`. Paths inside are relative to the lesson folder.

## REST (FastAPI, `server/main.py`, port 8000 http; 8443 https when certs exist)
- `GET /api/lessons` -> `[{"id","title","steps":<count>}]`
- `GET /api/lessons/{id}` -> lesson.json
- `POST /api/lesson` multipart: `file` (video), `title` (str), optional `id` -> `{"job":"<job id>","id":"<lesson id>"}`
- `GET /api/jobs/{job}` -> `{"status":"queued|normalizing|extracting|cutting|done|error","message":str,"id":str}`
- `POST /api/lessons/{id}/recut` -> re-cut clips/captions/frames from lesson.json timestamps (editor = fix timestamps, re-cut)
- Static: `/lessons/{id}/...` serves the lesson folder (mp4 with range requests, `.vtt` as `text/vtt`).
- `GET /capture` -> `server/static/capture.html` (phone capture page).

## WebSocket `/ws/camera` (phone, glasses app, replay script)
- Client sends binary JPEG frames. Nothing else required. Server replies nothing (may send `{"type":"ack"}` text; clients ignore).

## WebSocket `/ws/ui` (laptop learn screen)
Server -> client:
- binary message = latest live JPEG frame (downscaled, at most a few per second).
- text JSON:
  - `{"type":"state","lesson_id":str|null,"step":int (0-based index),"total":int,"status":"watching|checking|verified|manual|done","last_check":{"done":"yes|no|unsure","confidence":float,"latency_ms":int}|null,"camera_connected":bool}`
    sent on connect and on every change.
  - `{"type":"advance","from":int,"to":int,"reason":"camera|button|voice|timer"}` right after a step change (UI plays chime when reason is camera).
Client -> server (text JSON):
- `{"type":"select_lesson","id":str}` (resets to step 0)
- `{"type":"next","reason":"button|voice"}`, `{"type":"back"}`, `{"type":"goto","step":int}`

## Check rule
Reference = `frames/NN.jpg` of the current step (last frame of that step's clip). Live frame + reference + `check_question`
to `gemini-3.5-flash-lite`, JSON `{"done":"yes|no|unsure","confidence":0..1}`. One check in flight; keep latest frame only.
Advance on 2 consecutive yes with confidence >= 0.8. Any no/unsure resets. Manual steps advance only by next.
