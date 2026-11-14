# HandOver contract V2 (hub <-> web <-> apps <-> capture)

Revision 2, 2026-11-14. Owner: Developer 1. Supersedes CONTRACT.md (EXISTS items checked against CONTRACT.md and server/main.py as of this revision, including the parallel session's `rev`, `from`, 3 s timeout, recut swap and Windows signal fixes). Change process: docs/research/architecture.md section 13.

Every item is marked:
- **EXISTS**: implemented in server/ today. Clients may rely on it now.
- **NEW**: to be built. Clients must not assume it until Dev 1 says it is merged. Each NEW item has a priority (P0, P1, P2).

Compatibility rules:
- Every NEW field is optional for the reader. Readers ignore unknown fields and unknown message types.
- Old clients keep working: a camera that only sends binary JPEGs, and a viewer that only knows the EXISTS messages.
- New clients keep working against the EXISTS hub: never require `welcome` or `/api/info` to stream. Fall back to plain frames.

## 1. Runtime

### 1.1 Ports and processes (EXISTS)
- One process serves http on `HANDOVER_PORT` (default 8000) and, when `certs/cert.pem` and `certs/key.pem` exist, https on `HANDOVER_HTTPS_PORT` (default 8443). Both share one learn session. Both bind 0.0.0.0.
- Run from source: `.venv/bin/python -m server.main` (or `scripts/run_server.sh`). Python 3.12, deps frozen in `server/requirements.lock`.

### 1.2 Data locations
| Item | Rule | Status |
|---|---|---|
| Lessons | `HANDOVER_LESSONS`, else `<data>/lessons` | EXISTS (data = repo root) |
| Data dir `<data>` | `HANDOVER_DATA`; else frozen app: macOS `~/Library/Application Support/HandOver`, Windows `%LOCALAPPDATA%\HandOver`; else repo root | NEW P0 |
| Uploads | `<data>/uploads` (today `server/uploads`) | NEW P0 |
| Certs | `HANDOVER_CERTS`, else `<data>/certs` | EXISTS (repo `certs/`) |
| Gemini key | env `GEMINI_API_KEY` or `GOOGLE_API_KEY`, else `<data>/.env`. Never printed, never returned by any endpoint | EXISTS (repo `.env`) |
| Hub identity | `<data>/hub.json` `{"hub_id": "<uuid4 hex>", "name": "<str>"}`, created on first run | NEW P0 |
| Web app | `HANDOVER_WEB_DIST`, else `sys._MEIPASS/web/dist`, else `<repo>/web/dist` | NEW P0 |
| ffmpeg | `HANDOVER_FFMPEG`, else `sys._MEIPASS/ffmpeg[.exe]`, else PATH, else `/opt/homebrew/bin/ffmpeg` | NEW P0 (today PATH then Homebrew) |
| ffprobe | `HANDOVER_FFPROBE`, else the folder of the ffmpeg found, else the same order as ffmpeg | NEW P0 |

### 1.3 Environment variables
| Var | Default | Meaning | Status |
|---|---|---|---|
| `HANDOVER_LESSONS` | `<data>/lessons` | lessons folder | EXISTS |
| `HANDOVER_PORT` | 8000 | http port | EXISTS |
| `HANDOVER_HTTPS_PORT` | 8443 | https port | EXISTS |
| `HANDOVER_CERTS` | `<data>/certs` | folder with cert.pem, key.pem | EXISTS |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY` | none | Gemini key | EXISTS |
| `HANDOVER_CHECK_MODEL` | `gemini-3.5-flash-lite` | check model | EXISTS |
| `HANDOVER_CHECK` | `gemini` | `gemini` (falls back to local), `local`, `mock`. Today only `mock` is recognized | EXISTS (`mock`), NEW P1 (`local`, `gemini`) |
| `HANDOVER_MOCK_PASS_SECONDS` | 6 | mock passes after N s on a step | EXISTS |
| `HANDOVER_CHECK_TIMEOUT` | 3 | seconds before a Gemini call counts as unsure (an error for the breaker) | EXISTS |
| `HANDOVER_DEBOUNCE_N` | 2 | consecutive Gemini yes to advance | EXISTS |
| `HANDOVER_MIN_CONF` | 0.8 | minimum confidence for a yes | EXISTS |
| `HANDOVER_TEACH_MODEL` | `gemini-3.8-flash` | step extraction model | EXISTS |
| `HANDOVER_TEACH_MOCK` | unset | `1` = no Gemini, three placeholder steps | EXISTS |
| `HANDOVER_DATA` | see 1.2 | data dir | NEW P0 |
| `HANDOVER_WEB_DIST` | see 1.2 | built web app | NEW P0 |
| `HANDOVER_FFMPEG`, `HANDOVER_FFPROBE` | see 1.2 | binaries | NEW P0 |
| `HANDOVER_NAME` | computer name | hub display name | NEW P0 |
| `HANDOVER_OPEN_BROWSER` | 1 | launcher opens the browser | NEW P0 |
| `HANDOVER_MDNS` | 1 | 0 = do not advertise | NEW P2 (mDNS is cut by SCOPE; build only if time) |
| `HANDOVER_GATE` | 1 | 0 = no motion gate | NEW P1 |
| `HANDOVER_BREAKER_SECONDS` | 30 | circuit breaker open time | NEW P1 |
| `HANDOVER_LOCAL_N` | 3 | consecutive local passes to advance | NEW P1 |
| `HANDOVER_IMPORT_MAX_MB` | 2048 | import size cap | NEW P0 |

## 2. Lesson ids
- Read rule (EXISTS): `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. Any other id in a path gives 400 `bad lesson id`.
- Upload with an explicit `id` (EXISTS): the id is cleaned first (lowercased, runs of anything outside `a-z0-9-` become `-`), then must pass the read rule, else 400 `bad lesson id`. The response returns the cleaned id, which is the folder the pipeline writes. Example: `My_Lesson` -> `my-lesson`.
- Generated ids are a slug of the title, with `-2`, `-3`... on a clash (EXISTS).
- Import uses the same cleaning as upload (NEW P0).

## 3. lesson.json

Folder: `<lessons>/<id>/` with `lesson.json`, `norm.mp4`, `clips/NN.mp4`, `captions/NN.vtt`, `frames/NN.jpg` (NN = 01, 02, ...), plus `extraction.json` (transcript used by recut). All paths inside lesson.json are relative to the lesson folder and use forward slashes.

### 3.1 Top level
| Field | Type | Default if absent | Status |
|---|---|---|---|
| `id` | string | folder name | EXISTS |
| `title` | string | folder name | EXISTS |
| `video` | string or null | `"norm.mp4"`. null = source video not included (imported with `video=0`) | EXISTS (string), NEW P0 (null) |
| `steps` | Step[] | `[]` (a lesson with no steps is immediately `done`) | EXISTS |
| `format_version` | int | 1 | NEW P0 |
| `source_language` | string (BCP 47, e.g. `"en"`) | `"en"` | NEW P2 |
| `languages` | string[] | `[source_language]` | NEW P2 |

### 3.2 Step
| Field | Type | Default if absent | Status |
|---|---|---|---|
| `n` | int, 1-based | index + 1 | EXISTS |
| `title` | string | `""` | EXISTS |
| `start`, `end` | string. Written as `"MM:SS"`, or `"MM:SS.s"` (one decimal) when not a whole second. Also accepted on read: `"HH:MM:SS"`, a number of seconds | required | EXISTS |
| `clip` | string | `clips/NN.mp4` | EXISTS |
| `captions` | string | `captions/NN.vtt` | EXISTS |
| `ref_frame` | string | `frames/NN.jpg` | EXISTS |
| `check_type` | `"camera"` or `"manual"` | `"camera"` for the check loop | EXISTS |
| `check_question` | string (`""` when manual) | `"Is this step finished?"` | EXISTS |
| `prerequisites` | int[] (1-based step numbers, each < n) | `[]` | EXISTS |
| `ref_time` | string, same formats as `start`, absolute time in norm.mp4 | null = last frame of the clip | NEW P1 |
| `common_mistake` | string, short, shown and spoken when the learner is behind | `""` | NEW P1 |
| `mistake_question` | string, yes/no question whose yes means the common mistake is present; added to the mistake prompt | `""` | NEW P1 |
| `i18n` | object `{ "<lang>": { "title": string, "captions": string, "audio": string or null } }` | `{}` | NEW P2 |

Recut rule (NEW P0): recut rewrites only `n`, `start`, `end`, `clip`, `captions`, `ref_frame`, `check_type`, `check_question`, `prerequisites` and keeps every other field on each step and at the top level. Today recut drops unknown fields.

## 4. REST

All errors are FastAPI style: HTTP status plus body `{"detail": "<message>"}`. Messages below are exact.

### 4.1 Root and pages
| Method, path | Response | Status |
|---|---|---|
| `GET /` | When the web dist exists: `index.html` of the web app (the app uses hash routes `#/learn`, `#/teach`, so no fallback routing is needed); `/assets/*` served from the dist. Otherwise: `{"app":"HandOver","api":"/api/lessons","capture":"/capture","ui":"http://localhost:5173"}` | EXISTS (JSON), NEW P0 (dist) |
| `GET /capture` | `server/static/capture.html`, `Cache-Control: no-cache` | EXISTS |
| `GET /join` | `server/static/join.html`, `Cache-Control: no-cache`. Query `hub` (string, optional) is for the page only | NEW P0 |

### 4.2 Hub info and helpers
`GET /api/info` (NEW P0) -> 200
```json
{
  "app": "HandOver",
  "contract": 2,
  "version": "0.2.0",
  "hub_id": "3f9c2a7e1b4d4e0f9a1c2b3d4e5f6a7b",
  "name": "Studio MacBook",
  "os": "macos",
  "ports": {"http": 8000, "https": 8443},
  "urls": {
    "local": "http://localhost:8000/",
    "lan": ["http://192.168.1.20:8000/", "http://172.20.10.3:8000/"],
    "join": ["http://192.168.1.20:8000/join?hub=3f9c...", "http://172.20.10.3:8000/join?hub=3f9c..."],
    "capture": ["https://192.168.1.20:8443/capture", "https://172.20.10.3:8443/capture"]
  },
  "check": {"mode": "gemini", "model": "gemini-3.5-flash-lite", "has_key": true,
            "offline": false, "offline_reason": null},
  "mdns": true,
  "languages": ["en"]
}
```
| Field | Type | Notes |
|---|---|---|
| `contract` | int | 2 for this document |
| `version` | string | app version |
| `os` | `"macos"`, `"windows"`, `"linux"` | |
| `ports.https` | int or null | null when no certs |
| `urls.lan`, `urls.join` | string[] | best first (section 9.2). Empty when no LAN address |
| `urls.capture` | string[] | empty when no certs |
| `check.mode` | `"gemini"`, `"local"`, `"mock"` | configured mode |
| `check.model` | string or null | null unless mode is gemini |
| `check.has_key` | bool | never the key itself |
| `check.offline`, `check.offline_reason` | same as state fields in 6.4 | |
| `mdns` | bool | advertising right now |
| `languages` | string[] | union of languages across lessons; `["en"]` until P2 |

`GET /api/qr?text=<url-encoded string>` (NEW P0) -> 200 `image/svg+xml`, QR of `text`, quiet zone 4, dark modules `#000`, light `#fff`. 400 `text required` if empty, 400 `text too long` if over 512 chars.

`PUT /api/settings` (NEW P1), only from 127.0.0.1 or ::1, else 403 `settings can only be changed on the hub computer`. Body `{"gemini_key": string}`. Writes `<data>/.env` (file mode 600 where the OS supports it), resets the circuit breaker, and returns `{"has_key": bool, "mode": "gemini"|"local"|"mock"}`. An empty string removes the key. 400 `body must be JSON`.

`POST /api/shutdown` (NEW P0), localhost only (same 403 rule). Returns `{"ok": true}`, then the hub stops within 1 s.

### 4.3 Lessons
| Method, path | Request | Response | Status |
|---|---|---|---|
| `GET /api/lessons` | | `[{"id": str, "title": str, "steps": int}]` sorted by id. Folders with a bad id, a missing lesson.json or unreadable JSON are skipped | EXISTS |
| `GET /api/lessons/{id}` | | lesson.json as stored, `Cache-Control: no-cache`. 400 `bad lesson id`, 404 `lesson not found`, 500 `lesson.json unreadable: <reason>` | EXISTS |
| `POST /api/lesson` | multipart: `file` (video, required), `title` (string, required; blank becomes `Untitled lesson`), `id` (optional, cleaned per section 2) | `{"job": str (12 hex), "id": str}`. 400 `bad lesson id`, 409 `lesson id already exists` (also while a job for that id is running), 413 `video is larger than 2 GB`. Unknown or odd file extensions are saved as `.mp4`. A failed job removes its half-built lesson folder; the upload file is deleted after the job either way | EXISTS |
| `POST /api/lesson` with `file` repeated | multipart: several `file` parts; the first is the main take, the rest are joined after it in order | same | NEW P1 |
| `GET /api/jobs/{job}` | | `{"status": "queued"|"normalizing"|"extracting"|"cutting"|"translating"|"done"|"error", "message": str, "id": str}`. 404 `job not found`. Jobs live in memory and are lost on restart. Error messages over 400 chars are shortened to start + ` ... ` + tail. `done` message is `ready` | EXISTS (`translating` NEW P2) |
| `POST /api/lessons/{id}/recut` | optional body: a full lesson object (JSON). Empty body = recut from the stored lesson.json | the new lesson.json. The body's `id` is replaced by the path id. Errors restore the previous lesson.json: 400 `bad lesson id`, 404 `lesson not found`, 400 `body must be JSON`, 400 `body must be a lesson object with steps`, 400 `<timestamp error>` (e.g. `step 2: bad timestamp: 'x'`, `step 2 has no length after clamping (00:10 to 00:10, video 40.0 s)`, `lesson has no steps`). Every timestamp is checked before cutting, and new clips, captions and frames are built in `.recut_tmp/` and swapped in only when all steps succeed, 500 `recut failed: <Type>: <reason>`. If the lesson is active, the engine reloads it, keeps the step (clamped) and broadcasts state | EXISTS |
| same | lesson with `video: null` | 409 `source video not included; re-cut is unavailable for this lesson` | NEW P0 |
| `DELETE /api/lessons/{id}` | | `{"deleted": id}`. 404 `lesson not found`. If it is the active lesson, the engine clears the lesson (`lesson_id: null`) and broadcasts state | NEW P1 |
| `GET /api/lessons/{id}/export` | query `video=0` omits norm.mp4 (default includes it) | 200 `application/zip`, `Content-Disposition: attachment; filename="<id>.handover"`, streamed. Package format: section 8. 400 `bad lesson id`, 404 `lesson not found` | NEW P0 |
| `POST /api/lessons/import` | multipart `file` (a `.handover` zip), optional `id` (create rule) | `{"id": str, "title": str, "steps": int, "renamed": bool}`. 400 `not a HandOver lesson file`, 400 `unsupported package version <n>`, 400 `unsafe path in package: <name>`, 400 `missing file in package: <path>`, 400 `lesson.json invalid: <reason>`, 400 `bad lesson id`, 413 `package too large`. Never overwrites: a clash gets `-2`, `-3`... and `renamed: true` | NEW P0 |
| `POST /api/lessons/import` with JSON | body `{"url": "http://<host>:<port>/api/lessons/<id>/export"}` (http or https on a private or loopback address only) | same as above. 400 `url not allowed`, 502 `could not download package: <reason>` | NEW P2 |
| `POST /api/lessons/{id}/translate` | body `{"languages": string[], "speech": bool}` | `{"job": str, "id": str}`; job status `translating` then `done`. 400 `languages required` | NEW P2 |

### 4.4 Lesson files (EXISTS)
- `GET /lessons/{id}/<path>` serves the lesson folder: mp4 with range requests, `.vtt` as `text/vtt`, `Cache-Control: no-cache` on every file.

## 5. Engine semantics (EXISTS unless marked)

- One global session. `step` is a 0-based index. `total` = number of steps.
- Position: `position = total` when done, else `step`.
- `go(to, reason)`: `to` is clamped to `0..total`. No-op if `to == position`. `to == total` sets done, keeps `step = total - 1` (0 when there are no steps), and broadcasts `advance` with `to == total`. `to < total` clears done.
- `next` -> `go(position + 1)`. `back` -> `go(position - 1)`, reason `button`. From done, back goes to `total - 1` (`from == total`).
- `goto` accepts only `0 <= step < total` (it cannot set done). Anything else is ignored silently.
- `select_lesson` always resets to step 0, done false, even for the same lesson.
- `rev` (EXISTS): lesson.json modification time in ms, 0 with no lesson. Refreshed on select and after a recut. When it changes, clients refetch the lesson and append `?v=<rev>` to every clip, caption and frame URL.
- Stale command guard (EXISTS): `next` and `back` may carry `from` (the step index the client was showing). The hub ignores the command silently when `from` differs from the current position. On the done screen both `total - 1` and `total` count as current. `from` absent = legacy, always applied. A non-integer `from` (or a boolean) is treated as stale.
- Every step change resets the debouncer, `last_check` (to null), `checking`, `verified`, the step timer, and ignores frames taken before the step began.
- Status precedence: `done` (a lesson is loaded and done, or it has no steps) > `manual` (current step's `check_type == "manual"`) > `verified` > `checking` > `watching`. With no lesson: `watching`, `step: 0`, `total: 0`.
- Camera check: only on `check_type == "camera"` steps (absent means camera), only with a camera connected and a readable `ref_frame`. One check in flight, newest frame only. A result from a previous step is discarded.
- Advance by camera: N consecutive passes (section 7), then status `verified` for 1.2 s, then `go(position + 1, "camera")` if the step has not changed meanwhile.
- Manual steps advance only by next (button, voice, timer, or the phone).
- `camera_connected` changes broadcast state only when the camera count goes 0 to 1 or 1 to 0. NEW P0: also broadcast when the active camera changes.

## 6. WebSocket `/ws/camera`

Senders: iOS app, Android app, capture.html, replay.py.

### 6.1 Client -> hub
| Message | Fields | Status |
|---|---|---|
| binary | one JPEG (must start with `FF D8`). Other binary is ignored. Recommended about 1 fps, long side 640 to 1280. NEW P1: frames over 2 MB are ignored | EXISTS |
| `hello` (text JSON, optional, first message; may be sent again any time to update) | `{"type":"hello","device_id":str,"name":str,"platform":"ios"|"android"|"web"|"replay"|"other","source":"glasses"|"phone"|"browser"|"file","model":str|null,"app_version":str|null}` | NEW P0 |
| `next` | `{"type":"next","reason":"button"|"voice","from":int}`. Accepted only after hello. Same `from` rule as `/ws/ui` | NEW P1 |
| `back` | `{"type":"back","from":int}`. Accepted only after hello | NEW P1 |

hello field rules:
- `device_id`: stable per install (UUID kept in app storage; capture.html keeps one in localStorage; replay uses `replay-<hostname>`). 1 to 64 chars.
- `name`: what the UI shows, 1 to 40 chars, e.g. `"iPhone"`, `"Pixel 9"`, `"Ray-Ban Meta via iPhone"`, `"iPhone Safari"`, `"Replay: fold.mp4"`.
- `model`: e.g. `"Ray-Ban Meta Gen 2"`, `"iPhone18,1"`; null if unknown.
- Unknown `platform` or `source` values are stored as `"other"` / `"phone"`. Malformed hello is ignored (the socket stays open).

A camera that never sends hello (EXISTS clients) gets `name: "Camera <n>"` (n counts connections since start), `platform: "other"`, `source: "phone"`, `device_id: null`.

### 6.2 Hub -> client (text JSON; old clients ignore it)
| Message | Fields | When | Status |
|---|---|---|---|
| `welcome` | `{"type":"welcome","camera_id":str,"active":bool,"hub":{"hub_id":str,"name":str,"version":str,"contract":2}}` | reply to the first hello | NEW P0 |
| `camera_status` | `{"type":"camera_status","active":bool}` | this camera became active or idle | NEW P0 |
| `state`, `advance`, `mistake` | exactly as in section 7.2 | after hello, on every change (never binary frames) | NEW P1 |
| `error` | `{"type":"error","message":str}` | e.g. `no lesson selected` for next/back | NEW P1 |

Close code 4000, reason `replaced`: a newer connection sent hello with the same `device_id`. The old socket is closed by the hub. Clients must not auto-reconnect on code 4000.

### 6.3 Multiple cameras (NEW P0)
- Every connection gets a `camera_id` (`cam-<n>`). All count toward `cameras`.
- Active camera = the one that connected (or sent its first hello) most recently. Only frames from the active camera are used for checks and sent to viewers. Others stay connected and idle.
- Takeover: if the active camera sends no frame for 5 s and another camera sent a frame within the last 2 s, the camera with the newest frame becomes active.
- When the active camera disconnects, the connected camera with the newest frame becomes active (or none).
- Every change of active camera sends `camera_status` to the affected cameras, broadcasts state, and starts the check fresh (frames from the old camera are not judged).

## 7. WebSocket `/ws/ui`

Senders: the web app on any device. Any number of viewers; all receive the same messages.

Query `frames=0` (NEW P1): the hub sends no binary frames to this client (phones used as remotes, status displays).

### 7.1 Client -> hub (text JSON)
| Message | Effect | Status |
|---|---|---|
| `{"type":"select_lesson","id":str}` | load lesson, step 0. Errors come back as `error` with `bad lesson id`, `lesson not found` or `lesson.json unreadable: <reason>` | EXISTS |
| `{"type":"next","reason":"button"|"voice"|"timer","from":int}` | next. Any other or missing reason counts as `button`. `timer` is reserved; nothing sends it yet. `from` optional, see section 5 | EXISTS |
| `{"type":"back","from":int}` | back (reason `button`). `from` optional | EXISTS |
| `{"type":"goto","step":int}` | jump (reason `button`), 0-based, `< total` | EXISTS |
| `{"type":"dismiss_mistake"}` | clears `state.mistake` and broadcasts state | NEW P1 |

Any message other than `select_lesson` with no lesson loaded gets `{"type":"error","message":"no lesson selected"}` (EXISTS). Invalid JSON and unknown types are ignored (EXISTS).

### 7.2 Hub -> client
Binary (EXISTS): the newest live JPEG from the active camera, long side at most 960, quality 75, at most 4 per second, dropped when the client is more than 2 messages behind.

`state` (EXISTS fields first). Sent on connect and on every change.
```json
{"type":"state","lesson_id":"fortune-teller-v1","rev":1763154180123,"step":4,"total":8,"status":"watching",
 "last_check":{"done":"no","confidence":0.82,"latency_ms":910,"source":"gemini","reason":"seams still facing up"},
 "camera_connected":true,
 "camera":{"camera_id":"cam-3","name":"Ray-Ban Meta via iPhone","platform":"ios","source":"glasses"},
 "cameras":2,
 "check_source":"gemini","check_offline":false,"check_offline_reason":null,
 "mistake":null}
```
| Field | Type | Status |
|---|---|---|
| `lesson_id` | string or null | EXISTS |
| `rev` | int, lesson.json mtime in ms (0 with no lesson) | EXISTS |
| `step` | int, 0-based | EXISTS |
| `total` | int | EXISTS |
| `status` | `"watching"`, `"checking"`, `"verified"`, `"manual"`, `"done"` | EXISTS |
| `last_check` | `{"done":"yes"|"no"|"unsure","confidence":float 0..1 (3 decimals),"latency_ms":int}` or null | EXISTS |
| `last_check.source` | `"gemini"`, `"local"`, `"mock"` | NEW P1 |
| `last_check.reason` | string up to 8 words saying what differs from the reference, or null. The UI shows it only when confidence >= 0.7 (SCOPE MUST 4) | NEW P1 |
| `camera_connected` | bool, at least one camera connected | EXISTS |
| `camera` | `{"camera_id":str,"name":str,"platform":str,"source":str}` for the active camera, or null | NEW P0 |
| `cameras` | int, connected cameras | NEW P0 |
| `check_source` | `"gemini"`, `"local"`, `"mock"`: the checker in effect now | NEW P1 |
| `check_offline` | bool: true when Gemini is not being used although mode is gemini (UI shows the "Offline check" badge) | NEW P1 |
| `check_offline_reason` | `"no_key"`, `"rate_limited"` (a 429), `"errors"` (3 errors or timeouts in a row), or null | NEW P1 |
| `mistake` | the current mistake object (same fields as the `mistake` message minus `type`), or null. Cleared on step change, on `dismiss_mistake`, and when a check on this step answers yes | NEW P1 |

`advance` (EXISTS): `{"type":"advance","from":int,"to":int,"reason":"camera"|"button"|"voice"|"timer"}`. Sent right before the matching state. `to` may equal `total` (finished), and `from` may equal `total` (back from finished). The UI plays the chime when reason is `camera`.

`mistake` (NEW P1): sent once when the mistake check fires.
```json
{"type":"mistake","step":4,"kind":"behind","looks_like":3,
 "message":"Flip it over first.","confidence":0.86}
```
| Field | Type | Notes |
|---|---|---|
| `step` | int, 0-based | current step |
| `kind` | `"behind"` or `"ahead"` | behind: the live frame matches the previous step's finished state. ahead: it matches the next step's |
| `looks_like` | int, 0-based | the step the frame matches |
| `message` | string | behind: the current step's `common_mistake` if set, else `This still looks like step <looks_like + 1>.` Ahead: `You're ahead.` |
| `confidence` | float 0..1 | |
| `source` | `"gemini"` or `"local"` | which checker matched |

Behind never moves the step. Ahead (SCOPE MUST 5, jump ahead): the hub confirms with one normal check of step k+1 (its question and reference). On yes >= 0.8 it sends this `mistake` message with `kind:"ahead"`, then `go(k + 2, "camera")` (an `advance` whose `to - from == 2`, or `to == total` at the end). Without that confirmation it sends nothing.

`error` (EXISTS): `{"type":"error","message":str}`.

## 8. Check rule

EXISTS:
- Reference = the current step's `ref_frame`. Live frame, reference and `check_question` go to `HANDOVER_CHECK_MODEL` with low media resolution and minimal thinking. Answer JSON `{"done":"yes"|"no"|"unsure","confidence":0..1}`.
- Debounce: `HANDOVER_DEBOUNCE_N` (2) consecutive yes with confidence >= `HANDOVER_MIN_CONF` (0.8). Any no, unsure or low-confidence yes resets. Timeout or any error = unsure, confidence 0.
- Mock: yes 0.9 after `HANDOVER_MOCK_PASS_SECONDS` on the step, else no 0.85, about 0.6 s per call.

NEW P1 (details in architecture.md section 7):
- Motion gate before any call. Heartbeat call every 6 s.
- Timeout 3 s. Circuit breaker: 3 consecutive errors or timeouts, or any 429, opens it for `HANDOVER_BREAKER_SECONDS`; then one trial call.
- Local OpenCV check while the breaker is open, in `local` mode, or with no key: `HANDOVER_LOCAL_N` (3) consecutive passes. `last_check.confidence` for local = the step score, 0..1.
- While Gemini is up, local only vetoes: no advance if local names another step with a lead > 0.2.
- Mistake check: after 5 s of settled consecutive no on a camera step, at most once per 10 s per step. Gemini multiple choice (references k-1, k, k+1) when online; the local scores against those references when the breaker is open. Never in mock mode.

## 9. Discovery, QR and join

### 9.1 mDNS (NEW P1)
- Service type `_handover._tcp.local.`, instance name = hub name, port = http port.
- TXT: `v=2`, `id=<hub_id>`, `name=<hub name>`, `ips=<comma separated IPv4, best first>`, `https=<port or 0>`.
- Clients probe `GET http://<ip>:<port>/api/info` for each IP (1.5 s timeout) and use the first that returns `app == "HandOver"`.

### 9.2 LAN address order (NEW P0)
IPv4 only. Exclude loopback, 169.254.0.0/16, and interfaces named like `utun*`, `awdl*`, `llw*`, `bridge*`, `vEthernet*`, `docker*`, `vmnet*`, `Tailscale*`. Order: 192.168.0.0/16, then 172.16.0.0/12, then 10.0.0.0/8, then others.

### 9.3 QR and join (NEW P0)
- QR content: `http://<best lan ip>:<http port>/join?hub=<hub_id>`.
- join.html offers:
  - "Open in HandOver app": `handover://connect?host=<location.hostname>&port=<location.port or 80>&hub=<hub>`.
  - "Use this browser": `https://<host>:<https port>/capture`, shown only when `/api/info` reports `ports.https`.
- Native apps accept any of: a `handover://connect?...` URL, any `http(s)://host[:port]/...` URL (use host and port, default port 8000 when the URL has none), or typed `host` / `host:port`.

## 10. Lesson package `.handover` (NEW P0)

- A zip. Videos stored (no compression). Text files deflated. Entry names are forward-slash relative paths.
- Required entries: `manifest.json`, `lesson.json`, and every `clip`, `captions` and `ref_frame` path that lesson.json names.
- Optional entries: `extraction.json`, `norm.mp4`, `captions/NN.<lang>.vtt`, `audio/*`.
- `manifest.json`:
```json
{"format":"handover-lesson","format_version":1,"app_version":"0.2.0",
 "created_at":"2026-11-14T21:03:00Z","lesson_id":"fortune-teller-v1",
 "title":"Fold a fortune teller","includes_video":true,"hub_os":"macos"}
```
| Field | Type |
|---|---|
| `format` | always `"handover-lesson"` |
| `format_version` | int; importers reject versions they do not know |
| `app_version` | string |
| `created_at` | string, UTC ISO 8601 with `Z` |
| `lesson_id`, `title` | string |
| `includes_video` | bool |
| `hub_os` | `"macos"`, `"windows"`, `"linux"` |
- Import: reject absolute names, drive letters, `..`, backslashes, symlinks, more than 2000 entries, total uncompressed size over `HANDOVER_IMPORT_MAX_MB`. Unpack into a temp folder inside the lessons root, validate, then rename into place. Rewrite lesson.json `id` to the final id. If `norm.mp4` is absent, set `video` to null.

## 11. Replay (EXISTS)
`python -m server.replay VIDEO [--url ws://localhost:8000/ws/camera] [--fps 1] [--loop] [--start SEC] [--select LESSON_ID]`. Sends JPEG frames at the given rate. `--select` sends `select_lesson` on `/ws/ui` first and waits for a state confirming it. NEW P0: sends hello `{"platform":"replay","source":"file","name":"Replay: <file name>"}` first, and finds ffmpeg through the 1.2 lookup.
