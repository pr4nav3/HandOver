# HandOver contract (hub <-> web <-> iPhone app <-> capture)

Revision 5, 2026-11-14 (lean scope). EXISTS items are implemented in server/ today and clients may rely on them. NEW items are to be built this weekend for a feature in docs/PLAN.md; clients must not assume one until its owner says it is merged. Nothing else exists or is planned. Change process: say it in the group, one person edits and bumps this Revision line, everyone pulls. Freeze 6 AM Sunday.

Compatibility: every NEW field is optional for the reader; readers ignore unknown fields and message types. A camera that only sends binary JPEGs keeps working.

## 1. Runtime (EXISTS)
- One process serves http on `HANDOVER_PORT` (8000) and, when `certs/cert.pem` and `certs/key.pem` exist, https on `HANDOVER_HTTPS_PORT` (8443). Both share one learn session. Both bind 0.0.0.0.
- Run from source on the Mac: `scripts/run_server.sh` (or `.venv/bin/python -m server.main`). Python 3.12, deps frozen in `server/requirements.lock`.
- Lessons: `HANDOVER_LESSONS`, else `<repo>/lessons`. Certs: `HANDOVER_CERTS`, else `<repo>/certs`. Gemini key: `GEMINI_API_KEY` or `GOOGLE_API_KEY`, else `<repo>/.env`; never printed, never returned by any endpoint. ffmpeg and ffprobe from PATH, then Homebrew's folder.

Environment variables:
| Var | Default | Meaning | Status |
|---|---|---|---|
| `HANDOVER_LESSONS`, `HANDOVER_PORT`, `HANDOVER_HTTPS_PORT`, `HANDOVER_CERTS` | see above | | EXISTS |
| `GEMINI_API_KEY`, `GOOGLE_API_KEY` | none | Gemini key | EXISTS |
| `HANDOVER_CHECK` | `gemini` | `gemini` or `mock`. Today only `mock` is recognized; anything else means gemini | EXISTS |
| `HANDOVER_CHECK_MODEL` | `gemini-3.5-flash-lite` | check model | EXISTS |
| `HANDOVER_MOCK_PASS_SECONDS` | 6 | mock passes after N s on a step | EXISTS |
| `HANDOVER_CHECK_TIMEOUT` | 3 | seconds before a Gemini call counts as unsure (an error for the breaker) | EXISTS |
| `HANDOVER_DEBOUNCE_N` | 2 | consecutive yes to advance | EXISTS |
| `HANDOVER_MIN_CONF` | 0.8 | minimum confidence for a yes | EXISTS |
| `HANDOVER_TEACH_MODEL` | `gemini-3.8-flash` | step extraction model | EXISTS |
| `HANDOVER_TEACH_MOCK` | unset | `1` = no Gemini, three placeholder steps | EXISTS |
| `HANDOVER_GATE` | 1 | 0 = no motion gate | NEW (M5) |
| `HANDOVER_BREAKER_SECONDS` | 30 | breaker open time | NEW (M6) |
| `HANDOVER_MOCK_MISTAKE` | unset | test only, mock mode only: `behind:<0-based step>` or `ahead:<0-based step>`; after 4 s on that step the hub sends `mistake` as in 7.2 with `source: "mock"`. Never set in a demo | NEW (M9) |

## 2. Lesson ids (EXISTS)
- Read rule: `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`; anything else in a path gives 400 `bad lesson id`.
- Upload with an explicit `id`: lowercased, runs of anything outside `a-z0-9-` become `-`, then the read rule; the response returns the cleaned id. Generated ids are a slug of the title with `-2`, `-3`... on a clash.

## 3. lesson.json
Folder `<lessons>/<id>/`: `lesson.json`, `norm.mp4`, `clips/NN.mp4`, `captions/NN.vtt`, `frames/NN.jpg` (NN = 01, 02, ...), plus `extraction.json` (transcript used by recut). Paths inside are relative to the lesson folder, forward slashes.

Top level:
| Field | Type | Default | Status |
|---|---|---|---|
| `id`, `title` | string | folder name | EXISTS |
| `video` | string | `"norm.mp4"` | EXISTS |
| `steps` | Step[] | `[]` (no steps = immediately `done`) | EXISTS |
| `safety` | string[], short warnings from the narration | `[]` | NEW (S-S) |
| `tools` | string[], tools named in the narration | `[]` | NEW (S-S) |

Step:
| Field | Type | Default | Status |
|---|---|---|---|
| `n` | int, 1-based | index + 1 | EXISTS |
| `title` | string | `""` | EXISTS |
| `start`, `end` | `"MM:SS"` or `"MM:SS.s"`; `"HH:MM:SS"` and plain seconds accepted on read | required | EXISTS |
| `clip`, `captions`, `ref_frame` | string | `clips/NN.mp4`, `captions/NN.vtt`, `frames/NN.jpg` | EXISTS |
| `check_type` | `"camera"` or `"manual"` | `"camera"` | EXISTS |
| `check_question` | string (`""` when manual) | `"Is this step finished?"` | EXISTS |
| `prerequisites` | int[] (1-based, each < n) | `[]` | EXISTS |
| `ref_time` | string, same formats as `start`, absolute time in norm.mp4 for the reference frame | null = last frame of the clip | NEW (M8) |
| `common_mistake` | string, shown and spoken when the learner is behind | `""` | NEW (M9) |
| `self_test` | `{"own":"yes|no|unsure","prev":"yes|no|unsure","ok":bool}` from the teach-time self-test | null = not run | NEW (S-T) |

Recut rule (NEW, M8): recut rewrites only `n`, `start`, `end`, `clip`, `captions`, `ref_frame`, `check_question`, `prerequisites` and keeps every other field. Step 1 is made manual only for new extractions, never by recut. Today recut drops unknown fields.

## 4. REST
Errors are FastAPI style: status plus `{"detail": "<message>"}`; messages below are exact.

| Method, path | Request | Response | Status |
|---|---|---|---|
| `GET /` | | When `web/dist` exists: the web app's `index.html` (hash routes `#/learn`, `#/teach`), `/assets/*` from the dist with correct MIME types. Otherwise `{"app":"HandOver","api":"/api/lessons","capture":"/capture","ui":"http://localhost:5173"}` | EXISTS (JSON), NEW (W1, dist) |
| `GET /capture` | | `server/static/capture.html`, `Cache-Control: no-cache` | EXISTS |
| `GET /api/lessons` | | `[{"id","title","steps":<count>}]` sorted by id; folders with a bad id or unreadable lesson.json are skipped | EXISTS |
| `GET /api/lessons/{id}` | | lesson.json, `Cache-Control: no-cache`. 400 `bad lesson id`, 404 `lesson not found`, 500 `lesson.json unreadable: <reason>` | EXISTS |
| `POST /api/lesson` | multipart `file` (video), `title` (blank becomes `Untitled lesson`), optional `id` | `{"job": str, "id": str}`. 400 `bad lesson id`, 409 `lesson id already exists`, 413 `video is larger than 2 GB`. A failed job removes its half-built folder | EXISTS |
| `GET /api/jobs/{job}` | | `{"status":"queued|normalizing|extracting|cutting|done|error","message":str,"id":str}`; 404 `job not found`; jobs are in memory | EXISTS |
| `POST /api/lessons/{id}/recut` | optional body: a full lesson object; empty = recut from stored lesson.json | the new lesson.json. Timestamps are validated first; new files are built in `.recut_tmp/` and swapped in only when every step succeeds; errors restore the old lesson.json (400 `<timestamp error>`, 500 `recut failed: <reason>`). If the lesson is active the engine reloads it and broadcasts state | EXISTS |
| `DELETE /api/lessons/{id}` | | `{"deleted": id}`; 404. If active, the engine clears the lesson and broadcasts state | NEW (low priority) |
| `GET /lessons/{id}/<path>` | | lesson files: mp4 with range requests, `.vtt` as `text/vtt`, `Cache-Control: no-cache` | EXISTS |

## 5. Engine semantics (EXISTS unless marked)
- One global session. `step` is 0-based. `total` = number of steps. `position = total` when done, else `step`.
- `go(to, reason)`: `to` clamped to `0..total`; no-op if equal to position; `to == total` sets done and keeps `step = total - 1`; `to < total` clears done.
- `next` = `go(position + 1)`; `back` = `go(position - 1)` with reason `button`; `goto` accepts `0 <= step < total` only; `select_lesson` always resets to step 0.
- `rev`: increasing int, opaque (0 with no lesson), refreshed on select and after a recut. When it changes, clients refetch the lesson and append `?v=<rev>` to clip, caption and frame URLs.
- Stale guard: `next` and `back` may carry `from` (the step the client showed). The hub ignores the command when `from` differs from the current position (on the done screen both `total - 1` and `total` count). `from` absent = always applied.
- Every step change resets the debouncer, `last_check`, timers, and ignores frames taken before the step began.
- Status precedence: `done` > `manual` > `verified` > `checking` > `watching`. No lesson: `watching`, `step 0`, `total 0`.
- Camera check only on camera steps, only with a camera connected and a readable `ref_frame`. One check in flight, newest frame only. Advance by camera: N consecutive passes, `verified` for 1.2 s, then `go(position + 1, "camera")`.
- Manual steps advance only by next (button, voice, or the phone).
- Active camera (NEW, W8): the camera that connected or sent hello most recently; only its frames are judged and forwarded. If it sends nothing for 5 s and another camera sent a frame in the last 2 s, that camera becomes active. `camera_connected` broadcasts on 0 to 1, 1 to 0, and on active-camera change.

## 6. WebSocket `/ws/camera`
Senders: iPhone app, capture.html, replay.py.

Client to hub:
| Message | Fields | Status |
|---|---|---|
| binary | one JPEG (starts `FF D8`); about 1 fps, long side 640 to 1280. Frames over 2 MB are ignored (NEW) | EXISTS |
| `hello` | `{"type":"hello","device_id":str,"name":str,"platform":"ios|web|replay","source":"glasses|phone|browser|file"}`, optional, first message; may repeat to update. Malformed hello is ignored | NEW (W4, W8, replay) |
| `next` | `{"type":"next","reason":"button","from":int}`, only after hello; same `from` rule as `/ws/ui` | NEW (W8) |
| `back` | `{"type":"back","from":int}`, only after hello | NEW (W8) |

A camera that never sends hello gets `name: "Camera <n>"`, `platform: "other"`, `source: "phone"`.

Hub to client (text JSON; old clients ignore it):
| Message | When | Status |
|---|---|---|
| `camera_status` `{"type":"camera_status","active":bool}` | this camera became active or idle | NEW (W8) |
| `state`, `advance`, `mistake` as in 7.2 | after hello, on every change; never binary frames | NEW (W8, so the phone can show the step title) |
| `error` `{"type":"error","message":str}` | e.g. `no lesson selected` | NEW (W8) |

Close code 4000 reason `replaced`: a newer connection sent hello with the same `device_id`; clients must not auto-reconnect on 4000.

## 7. WebSocket `/ws/ui`
Senders: the web app. Any number of viewers; all receive the same messages.

Client to hub (text JSON):
| Message | Effect | Status |
|---|---|---|
| `{"type":"select_lesson","id":str}` | load lesson, step 0; errors as `error` with `bad lesson id`, `lesson not found`, `lesson.json unreadable: <reason>` | EXISTS |
| `{"type":"next","reason":"button|voice","from":int}` | next; other or missing reason counts as `button`; `from` optional | EXISTS |
| `{"type":"back","from":int}` | back | EXISTS |
| `{"type":"goto","step":int}` | jump, 0-based, `< total` | EXISTS |
| `{"type":"dismiss_mistake"}` | clears `state.mistake`, broadcasts state | NEW (M9) |

Any message other than `select_lesson` with no lesson loaded gets `error` `no lesson selected`. Invalid JSON and unknown types are ignored.

Hub to client:
- Binary (EXISTS): newest live JPEG from the active camera, long side at most 960, quality 75, at most 4 per second, dropped when the client is more than 2 messages behind.
- `state` (EXISTS fields first), on connect and every change:
```json
{"type":"state","lesson_id":"fortune-teller-v1","rev":1763154180123,"step":4,"total":8,"status":"watching",
 "last_check":{"done":"no","confidence":0.82,"latency_ms":910,"reason":"seams still facing up"},
 "camera_connected":true,
 "camera":{"name":"Ray-Ban Meta via iPhone","platform":"ios","source":"glasses"},
 "check_offline":false,"check_offline_reason":null,
 "mistake":null}
```
| Field | Type | Status |
|---|---|---|
| `lesson_id` | string or null | EXISTS |
| `rev` | increasing int | EXISTS |
| `step`, `total` | int | EXISTS |
| `status` | `watching`, `checking`, `verified`, `manual`, `done` | EXISTS |
| `last_check` | `{"done":"yes|no|unsure","confidence":0..1,"latency_ms":int}` or null | EXISTS |
| `last_check.reason` | up to 8 words on what differs from the reference, or null; UI shows it at confidence >= 0.7 | NEW (M6) |
| `camera_connected` | bool | EXISTS |
| `camera` | `{"name","platform","source"}` of the active camera, or null. UI shows a "Recording" banner when `source == "file"` | NEW (W5, W8) |
| `check_offline` | bool: Gemini not in use although mode is gemini; UI shows "Checks off, use Next" | NEW (M6) |
| `check_offline_reason` | `"no_key"`, `"rate_limited"`, `"errors"`, or null | NEW (M6) |
| `mistake` | the current mistake object (7.2 fields minus `type`) or null; cleared on step change, `dismiss_mistake`, or a yes on this step | NEW (M9) |

- `advance` (EXISTS): `{"type":"advance","from":int,"to":int,"reason":"camera|button|voice"}`, sent right before the matching state; `to` may equal `total` (finished). UI plays the chime when reason is `camera`.
- `mistake` (NEW, M9), sent once when the mistake check fires:
```json
{"type":"mistake","step":4,"kind":"behind","looks_like":3,"message":"Flip it over first.","confidence":0.86,"source":"gemini"}
```
`kind` is `behind` (live frame matches the previous step's finished state; never moves the step; `message` is `common_mistake` or `This still looks like step <looks_like + 1>.`) or `ahead` (matches the next step; confirmed by one normal check of step k+1 at >= 0.8, then `go(k + 2, "camera")`; `message` is `You're ahead.`). `source` is `gemini` or `mock`.
- `error` (EXISTS): `{"type":"error","message":str}`.

## 8. Check rule
EXISTS: reference = current step's `ref_frame`. Live frame, reference and `check_question` go to `HANDOVER_CHECK_MODEL` with low media resolution and minimal thinking; answer `{"done":"yes|no|unsure","confidence":0..1}`. Debounce `HANDOVER_DEBOUNCE_N` consecutive yes at `HANDOVER_MIN_CONF`; any no, unsure or low yes resets; timeout or error = unsure 0. Mock: yes 0.9 after `HANDOVER_MOCK_PASS_SECONDS` on the step, else no 0.85.

NEW (M5, M6, M9):
- Motion gate: call only when the frame is still and changed since the last check; heartbeat call every 6 s.
- Breaker: 3 consecutive errors or timeouts, or any 429, sets `check_offline` for `HANDOVER_BREAKER_SECONDS`, then one trial call. While open, no checks run; the learner uses Next.
- Mistake check: after 5 s of settled consecutive no on a camera step, at most once per 10 s per step, one Gemini multiple-choice call over references k-1, k, k+1. Never in mock mode except the `HANDOVER_MOCK_MISTAKE` hook.

## 9. Replay (EXISTS)
`python -m server.replay VIDEO [--url ws://localhost:8000/ws/camera] [--fps 1] [--loop] [--start SEC] [--select LESSON_ID]`. Sends JPEG frames at the given rate; `--select` sends `select_lesson` on `/ws/ui` first. NEW: sends hello `{"platform":"replay","source":"file","name":"Replay: <file>"}` first so the UI shows the "Recording" banner.
