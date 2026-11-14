# Proposed changes to CONTRACT.md (for Revision 6)

From Soham, for Pranav to approve. Each proposal compares CONTRACT.md Revision 5 with the code in `server/` on branch `soham/server`. Where a review note and the code disagreed, the code wins and the block says so.

Line numbers come from the working tree at the time of writing. `main.py` was being edited at the same time, so its numbers may be off by a few lines.

Risk key: **none** means docs only. **low** means behavior a careful client may notice. **clients must update** means a client that follows Revision 5 to the letter can misbehave.

## Summary

| Id | Section | Change | Why | Risk |
|---|---|---|---|---|
| P1 | 1 | Add an optional "Tuning" table of owner-only env vars | 16 vars the code reads are not listed | none |
| P2 | 1 | `HANDOVER_CHECK` ignores case; bad values warn and use the default | config.py now validates every tunable | none |
| P3 | 1 | Runtime notes: startup cleanup, websocket ping, 8 MB message cap | Not mentioned | none |
| P4 | 2 | Upload id cleaning also trims dashes, merges repeats, cuts to 64 | Contract describes only part of it | low |
| P5 | all | Mark built NEW items as EXISTS (once merged) | Most server-side NEW items are built | none |
| P6 | 3 | `self_test` may carry `"mock": true`; written only by the CLI | Not mentioned | none |
| P7 | 3 | Recut rule also rewrites `ref_time`, keeps `check_type`; drop stale sentence | Contract is out of date | low |
| P8 | 4 | Upload: 411, 429, early 413, optional title, 422 shape | Not listed | low |
| P9 | 4 | Recut: every error string and the 500 format | Only two errors listed | low |
| P10 | 4 | Delete: 409, 500, and 404 for a folder still being built | Not listed | none |
| P11 | 4 | `x-request-id` on every HTTP response; `/assets` caching and 404 | Not mentioned | none |
| P12 | 5, 7 | `rev` is `max(previous + 1, mtime)`; when it does and does not change | Contract says only "increasing" | low |
| P13 | 5 | Verified hold 0.8 s; `checking` only after 1.5 s; fast confirm | Contract says 1.2 s | low |
| P14 | 5 | Active camera handover as coded; state on every camera change | Wording differs from the code | low |
| P15 | 6, 7 | Close 1011 on a stalled sender (reconnect), 1013 at the connection cap | Not listed | clients must update |
| P16 | 6 | Camera input limits: 5 frames per second, hello field limits, 8 KB text | Not listed | low |
| P17 | 7 | Delivery: newest frame only, latest state replaces unsent states | Contract implies one state per change | clients must update |
| P18 | 7 | No lesson loaded: unknown types also get `no lesson selected` | Contract says unknown types are ignored | low |
| P19 | 7 | `state.mistake` holds the shown mistake (`behind`, `ahead`, `live`); `ahead` skips only with `HANDOVER_AHEAD_SKIP=1` | Not spelled out | low |
| P20 | 8 | Check rule: "before" image, evidence-first answer, reason from `differs`, thinking per model | Contract describes the old two-image call | none |
| P21 | 8 | Breaker: `no_key` covers invalid keys and never retries | Not listed | low |
| P22 | 8 | Motion gate: heartbeat fires even during motion; settled and change rules | Contract is one line | none |
| P23 | 8 | Mistake check details: what resets the streak, cooldown, thresholds | Contract is one line | none |
| P24 | 9 | Replay: `--no-hello`, `device_id`, reconnect, stops on 4000 | Not listed | none |
| P25 | 4 | NEW routes `GET /api/health` and `GET /api/metrics` | Proposed, not built | none |
| P26 | new 10 | Learn events and the Databricks adapter | Not in the contract | none |

---

## P1. Tuning table (section 1)

**Current**
> Environment variables: (table of 13 rows)

**Proposed**: add below the table:

> Tuning (EXISTS, owner only; demo clients never set these). A bad or out-of-range value logs one warning and uses the default. `python -m server.config` prints every value in effect.
>
> | Var | Default | Meaning |
> |---|---|---|
> | `HANDOVER_GATE_MOTION` | 0.02 | gate holds change checks while motion is above this fraction of pixels |
> | `HANDOVER_GATE_STILL` | 0.005 | a frame counts as still below this fraction |
> | `HANDOVER_GATE_STILL_FRAMES` | 2 | still frames in a row to count as settled |
> | `HANDOVER_GATE_CHANGE` | 0.018 | change from the last checked frame needed to check again |
> | `HANDOVER_GATE_HEARTBEAT_S` | 6 | seconds between heartbeat checks |
> | `HANDOVER_MISTAKE_MIN_CONF` | 0.7 | minimum compare confidence for `behind` or `ahead`; read at hub start |
> | `HANDOVER_MISTAKE_PARALLEL` | 1 | 0 runs the mistake compare inline instead of alongside checks |
> | `HANDOVER_CHECK_LIVE_RES` | `low` | `low` or `medium` media resolution for the live image |
> | `HANDOVER_CHECK_MAX_SIDE` | 640 | long side in pixels images are shrunk to before a check (64 to 4096) |
> | `HANDOVER_SELFTEST_TIMEOUT` | 10 | seconds per teach-time self-test call |
> | `HANDOVER_VERIFIED_HOLD` | 0.8 | seconds `verified` shows before a camera advance (0 to 10); read at hub start |
> | `HANDOVER_MIN_FRAME_GAP` | 0.2 | frames from one camera closer than this many seconds are dropped (0 to 5) |
> | `HANDOVER_MAX_CAMERAS` | 8 | camera connections at once (1 to 64) |
> | `HANDOVER_MAX_VIEWERS` | 32 | `/ws/ui` connections at once (1 to 256) |
> | `HANDOVER_LOG_JSON` | 0 | 1 = one JSON object per log line |
> | `HANDOVER_FFMPEG` | unset | path to the ffmpeg binary; ffprobe is looked for next to it; then PATH, then Homebrew |

Not listed on purpose: `HANDOVER_MAX_UPLOAD_MB` and `HANDOVER_MAX_FRAME_MB` are in the config registry as "proposed" but no code reads them yet.

**Code**: server/config.py:132-181, server/gate.py:94-103, server/mistake.py:41-45, server/check.py:277-279 and 361-367, server/teach.py:168-186 and 799-804, server/replay.py:39-52, server/main.py:74, 102, 352-354, 709, 1335, 1366

## P2. `HANDOVER_CHECK` row (section 1)

**Current**
> `gemini` or `mock`. Today only `mock` is recognized; anything else means gemini

**Proposed**
> `gemini` or `mock`, any letter case. Any other value logs one warning and means gemini

**Code**: server/config.py:98-107 and 142, server/check.py:132-133

## P3. Runtime notes (section 1)

**Current**: not mentioned.

**Proposed**: add to section 1:

> - At start the hub removes leftovers from a crash: files in `server/uploads/` and `.recut_tmp/` or `.recut_old/` inside lesson folders, only when untouched for an hour. Each removal is logged. Nothing else is touched.
> - WebSockets: the hub pings every 10 s and drops a client that does not answer within 10 s. A single message over 8 MB makes uvicorn close the socket; frames between 2 MB and 8 MB are ignored by the hub instead.

**Code**: server/main.py:1469 (startup_cleanup), 1502, 1507

## P4. Upload id cleaning (section 2)

**Current**
> Upload with an explicit `id`: lowercased, runs of anything outside `a-z0-9-` become `-`, then the read rule; the response returns the cleaned id.

**Proposed**
> Upload with an explicit `id`: lowercased, runs of anything outside `a-z0-9-` become `-`, leading and trailing dashes are trimmed, repeated dashes become one, then it is cut to 64 characters (and a trailing dash is trimmed again). An id that is empty after cleaning gives 400 `bad lesson id`. The response returns the cleaned id. Generated ids are a slug of the title cut to 48 characters (`lesson` when empty), with `-2`, `-3`... on a clash with a folder or a running job.

**Code**: server/teach.py:259-264, server/main.py:163-174, 1170-1190

## P5. Mark built items as EXISTS (all sections)

**Current**: these are marked NEW.

**Proposed**: once `soham/server` is merged to main, mark EXISTS:
> - Section 1: `HANDOVER_GATE` (M5), `HANDOVER_BREAKER_SECONDS` (M6), `HANDOVER_MOCK_MISTAKE` (M9)
> - Section 3: `safety`, `tools` (S-S), `ref_time` (M8), `common_mistake` (M9), `self_test` (S-T), Recut rule (M8)
> - Section 4: `GET /` serving `web/dist` (W1, server side), `DELETE /api/lessons/{id}`
> - Section 6: 2 MB frame rule, `hello`, `next`, `back`, `camera_status`, `state`/`advance`/`mistake`/`error` to cameras, close 4000 (W4, W8)
> - Section 5: active camera (W8)
> - Section 7: `dismiss_mistake`, `last_check.reason`, `camera`, `check_offline`, `check_offline_reason`, `mistake` (field and message)
> - Section 8: motion gate, breaker, mistake check
> - Section 9: replay hello

**Code**: server/main.py (whole file), server/teach.py:727-750, server/gate.py, server/mistake.py, server/check.py:558-626, server/replay.py:93-100

## P6. `self_test` field (section 3)

**Current**
> `{"own":"yes|no|unsure","prev":"yes|no|unsure","ok":bool}` from the teach-time self-test

**Proposed**
> `{"own":"yes|no|unsure","prev":"yes|no|unsure","ok":bool,"mock":true}` from the teach-time self-test (`python -m server.teach --self-test LESSON_DIR`; uploads do not run it). `mock` is present only when it ran with `HANDOVER_CHECK=mock`, whose answers ignore the images. A step whose check call failed has no `self_test`. For step 1, `prev` compares against the frame at the step's start.

**Code**: server/teach.py:820-884, 1091-1092

## P7. Recut rule (section 3)

**Current**
> Recut rule (NEW, M8): recut rewrites only `n`, `start`, `end`, `clip`, `captions`, `ref_frame`, `check_question`, `prerequisites` and keeps every other field. Step 1 is made manual only for new extractions, never by recut. Today recut drops unknown fields.

**Proposed**
> Recut rule: recut rewrites only `n`, `start`, `end`, `clip`, `captions`, `ref_frame`, `ref_time`, `check_question`, `prerequisites` and keeps every other field of the lesson and its steps. A stored `ref_time` inside the step is used as given; one outside the step (or empty) is replaced by a newly chosen frame, and `null` means the clip's last frame. The stored `check_type` is kept; a step without one gets one. A camera step with an empty `check_question` gets `Is this step finished?`. Step 1 is made manual only for new extractions, never by recut. The top-level `id` is always the folder name.

**Code**: server/teach.py:598-622, 642-685, 727-750, 760-778, server/main.py:1272-1276 (sets `id`)

## P8. Upload errors (section 4, `POST /api/lesson`)

**Current**
> multipart `file` (video), `title` (blank becomes `Untitled lesson`), optional `id` | `{"job": str, "id": str}`. 400 `bad lesson id`, 409 `lesson id already exists`, 413 `video is larger than 2 GB`. A failed job removes its half-built folder

**Proposed**
> multipart `file` (video), optional `title` (missing or blank becomes `Untitled lesson`), optional `id` | `{"job": str, "id": str}`. 400 `bad lesson id`, 409 `lesson id already exists`, 411 `content length required` (no `Content-Length` header), 413 `video is larger than 2 GB` (also sent before the body is read when `Content-Length` is over the limit), 429 `too many jobs` (3 jobs queued or running). A missing `file` gives FastAPI's 422, whose `detail` is a list, not a string. One job runs at a time; the rest show `queued`. A failed job removes its half-built folder

**Code**: server/main.py:1054-1071 (411, early 413), 1170-1190 (429), 1208-1228

## P9. Recut errors (section 4, `POST /api/lessons/{id}/recut`)

**Current**
> errors restore the old lesson.json (400 `<timestamp error>`, 500 `recut failed: <reason>`)

**Proposed**
> Checked in this order: 400 `bad lesson id`, 404 `lesson not found`, 500 `lesson.json unreadable: <reason>`; then the body: 413 `body is larger than 1 MB`, 415 `body must be application/json`, 400 `body must be JSON`, 400 `body must be a lesson object with steps`, 400 `too many steps` (over 50); then 409 `recut already running` (a recut or delete holds the lesson lock). During the cut, errors restore the old lesson.json: 400 with the validation message (`step <n>: bad timestamp: '<value>'`, `step <n> has no length after clamping (...)`, `lesson has no steps`, `bad step in lesson.json: <type>: <message>`), or 500 `recut failed: <ExceptionType>: <message>`. Paths in messages read `<lessons>` and `<repo>`; the key never appears.

**Code**: server/main.py:1239-1294, server/teach.py:625-639, 775-776, 787-789

## P10. Delete (section 4, `DELETE /api/lessons/{id}`)

**Current**
> `{"deleted": id}`; 404. If active, the engine clears the lesson and broadcasts state

**Proposed**
> `{"deleted": id}`. 400 `bad lesson id`, 404 `lesson not found` (also for a folder with no lesson.json, such as a teach job still building), 409 `recut already running`, 500 `delete failed: <reason>`. If active, the engine clears the lesson and broadcasts state

**Code**: server/main.py:1298-1314

## P11. Request id and web assets (section 4)

**Current**: `/assets/*` "from the dist with correct MIME types"; request ids not mentioned.

**Proposed**: add under the REST intro:
> Every HTTP response carries `x-request-id`. A client may send its own (`[A-Za-z0-9_-]`, 1 to 64 characters) to match hub log lines; otherwise the hub makes one. `/assets/*` files are served with `Cache-Control: public, max-age=31536000, immutable`; a missing file gives 404 `not found`.

**Code**: server/main.py:114, 1028-1051, 1090-1098

## P12. `rev` (sections 5 and 7)

**Current**
> `rev`: increasing int, opaque (0 with no lesson), refreshed on select and after a recut.

**Proposed**
> `rev`: increasing int, opaque. It is 0 until the first lesson is selected and never goes down (it keeps its value when the active lesson is deleted). It changes when a different lesson is selected, when lesson.json changed since the last select, and after a recut. Selecting the same unchanged lesson again keeps it. Today it is `max(previous + 1, lesson.json mtime in ms)`; clients must not rely on that.

**Code**: server/main.py:153-160, 572-578, 580-589 (delete keeps rev)

## P13. Camera advance timing (section 5)

**Current**
> Advance by camera: N consecutive passes, `verified` for 1.2 s, then `go(position + 1, "camera")`.

**Proposed**
> Advance by camera: N consecutive passes, `verified` for `HANDOVER_VERIFIED_HOLD` (0.8 s), then `go(position + 1, "camera")`. Fast confirm: after a yes, the next settled frame is checked at once instead of waiting for the heartbeat. `checking` shows only when one check has been in flight for 1.5 s, so status is usually `watching` between checks. A state is sent only when status, `last_check` or another field changed, not after every identical result.

**Code**: server/main.py:102, 104, 795, 819, 844, 859-864

## P14. Active camera (section 5)

**Current**
> Active camera (NEW, W8): the camera that connected or sent hello most recently; only its frames are judged and forwarded. If it sends nothing for 5 s and another camera sent a frame in the last 2 s, that camera becomes active. `camera_connected` broadcasts on 0 to 1, 1 to 0, and on active-camera change.

**Proposed**
> Active camera: the camera that connected or sent hello most recently; only its frames are judged and forwarded. When another camera sends a frame and the active one has sent no frame for 5 s (counted from when it became active, if it never sent one), the sender becomes active. Text messages do not count as activity. When the active camera disconnects, the camera with the newest frame takes over. A state is broadcast on every camera connect, disconnect, hello and active-camera change. Unnamed cameras are numbered with the lowest free number.

**Code**: server/main.py:640-684, 703-720

## P15. Close codes (sections 6 and 7)

**Current**
> Close code 4000 reason `replaced`: a newer connection sent hello with the same `device_id`; clients must not auto-reconnect on 4000.

**Proposed**: add, for both sockets:
> Close code 1011: one send to this client took over 5 s, so the hub gave up on it. Clients should reconnect at once; the first message after reconnecting is a full state. Close code 1013 reason `too many cameras` or `too many viewers`: the cap (`HANDOVER_MAX_CAMERAS`, `HANDOVER_MAX_VIEWERS`) is reached; reconnect with a back-off.

**Code**: server/main.py:110, 112, 120, 230-244, 1335-1338, 1366-1369

## P16. Camera input limits (section 6)

**Current**
> one JPEG (starts `FF D8`); about 1 fps, long side 640 to 1280. Frames over 2 MB are ignored (NEW)

**Proposed**
> one JPEG (starts `FF D8`); about 1 fps, long side 640 to 1280. Frames over 2 MB, frames that are not JPEG, and frames that arrive less than `HANDOVER_MIN_FRAME_GAP` (0.2 s) after the previous one from the same camera are ignored.

And for `hello`: "`device_id` is cut to 128 characters and `name` to 64, both trimmed. A `platform` or `source` outside the lists makes the whole hello ignored. Fields left out keep their earlier value." For all text on both sockets: "Text over 8192 characters is ignored."

**Code**: server/main.py:105, 119, 271-286, 703-713, 1405-1413

## P17. Delivery to slow clients (section 7, and 6 for text)

**Current**
> Binary (EXISTS): newest live JPEG from the active camera, long side at most 960, quality 75, at most 4 per second, dropped when the client is more than 2 messages behind.

**Proposed**
> Binary: newest live JPEG from the active camera, long side at most 960, quality 75, at most 4 per second. Each client holds at most one unsent frame; a newer frame replaces it. Each client also holds only the latest unsent `state`, so a slow client can skip intermediate states; readers must not assume one state per advance or per check. Order per client: queued `advance`, `mistake` and `error` messages first (up to 64; when full the oldest is dropped), then the latest state, then the latest frame. So an `advance` always arrives before the state that follows it.

**Code**: server/main.py:179-244

## P18. Messages with no lesson loaded (section 7)

**Current**
> Any message other than `select_lesson` with no lesson loaded gets `error` `no lesson selected`. Invalid JSON and unknown types are ignored.

**Proposed**
> Invalid JSON, JSON that is not an object, and text over 8192 characters are ignored. With no lesson loaded, every other message except `select_lesson` gets `error` `no lesson selected`, including unknown types and objects with no `type`. With a lesson loaded, unknown types are ignored. A `goto` with a step outside `0..total-1` is ignored. On `/ws/camera`, `next` and `back` before hello are ignored, and other unknown types are always ignored.

**Code**: server/main.py:1405-1413, 1416-1427, 1430-1449, 1452-1464

## P19. `mistake` in state (section 7)

**Current**
> `mistake` | the current mistake object (7.2 fields minus `type`) or null; cleared on step change, `dismiss_mistake`, or a yes on this step

**Proposed**
> `mistake` | the mistake being shown (7.2 fields minus `type`) or null; cleared on step change, `dismiss_mistake`, or a yes on this step. `behind`, `ahead` and `live` stay here and never move the step. Only with `HANDOVER_AHEAD_SKIP=1` does a doubly confirmed `ahead` send the `mistake` message, then `advance` from k to k+2 with reason `camera` (which clears it). In mock mode the `HANDOVER_MOCK_MISTAKE` hook fires once per visit unless the last check said yes; its `ahead` still runs the confirming check.

**Code**: server/main.py:877-887, 953-971, server/mistake.py:117-135

## P20. Check rule (section 8)

**Current**
> EXISTS: reference = current step's `ref_frame`. Live frame, reference and `check_question` go to `HANDOVER_CHECK_MODEL` with low media resolution and minimal thinking; answer `{"done":"yes|no|unsure","confidence":0..1}`.

**Proposed**
> Reference = current step's `ref_frame`. When the step is not the first and the previous step's reference is readable, it is sent first as a "before" image, with the rule "if LIVE looks like this, answer no". Images are shrunk to `HANDOVER_CHECK_MAX_SIDE` (640). The call uses low media resolution (the live image may use `HANDOVER_CHECK_LIVE_RES`) and the lowest thinking level the model accepts: minimal, or low for `gemini-3.8` and `gemini-4` models, which reject minimal. The answer is evidence first, in this order: `seen` (up to 12 words on the live image, logged only), `differs` (up to 8 words on what is missing, or `nothing`), `done`, `confidence`. `last_check.reason` is `differs` cut to 8 words, or null when it says nothing.

**Code**: server/check.py:93-112, 115-129, 325-381, 396-422, server/main.py:812

## P21. Breaker (section 8)

**Current**
> Breaker: 3 consecutive errors or timeouts, or any 429, sets `check_offline` for `HANDOVER_BREAKER_SECONDS`, then one trial call. While open, no checks run; the learner uses Next.

**Proposed**
> Breaker: 3 consecutive errors or timeouts, or any 429 (`RESOURCE_EXHAUSTED`), sets `check_offline` for `HANDOVER_BREAKER_SECONDS`, then one trial call; its result closes or reopens it. A missing key, or a key the API rejects (400 `API_KEY_INVALID`, 401, 403), sets reason `no_key`, which stays open with no trial until the hub restarts. Mistake compares and ahead confirmations count toward the breaker too. While open, no checks run; the learner uses Next. Mock mode is never offline. With no key in gemini mode, `check_offline` turns true at the first check attempt.

Correction to the review: it said `check_offline` is already true at startup with no key. The hub asks `check.has_key()` at startup (main.py:487-493), but check.py does not define it yet, so today the flag turns true at the first check. Soham will add `has_key`; the last sentence then becomes "is true from startup".

**Code**: server/check.py:242-267, 558-626, server/main.py:444-448, 487-493, 915-951

## P22. Motion gate (section 8)

**Current**
> Motion gate: call only when the frame is still and changed since the last check; heartbeat call every 6 s.

**Proposed**
> Motion gate: call only when the scene has settled (2 still frames in a row) and changed since the last checked frame; the first settled frame on a new step is always checked. A heartbeat check fires 6 s after the last check even during motion, so a shaky camera is still checked. Every check still needs a frame newer than the last one checked. `HANDOVER_GATE=0` sends every frame. Thresholds are in the Tuning table (P1).

**Code**: server/gate.py:133-162, 170-181, server/main.py:787-813

## P23. Mistake check (section 8)

**Current**
> Mistake check: after 5 s of settled consecutive no on a camera step, at most once per 10 s per step, one Gemini multiple-choice call over references k-1, k, k+1. Never in mock mode except the `HANDOVER_MOCK_MISTAKE` hook.

**Proposed**
> Mistake check: after 5 s of consecutive `no` on a camera step (a `yes` or `unsure` restarts the count), at most once per 10 s per step (also across revisits), one Gemini multiple-choice call over the references k-1, k, k+1 that exist (skipped when fewer than two exist). A match counts at `HANDOVER_MISTAKE_MIN_CONF` (0.7) or more. `ahead` is then confirmed by one normal check of step k+1 at 0.8 or more. The call runs alongside normal checks, one at a time. Never in mock mode except the `HANDOVER_MOCK_MISTAKE` hook.

**Code**: server/mistake.py:29-32, 88-115, server/main.py:877-940

## P24. Replay (section 9)

**Current**
> `python -m server.replay VIDEO [--url ws://localhost:8000/ws/camera] [--fps 1] [--loop] [--start SEC] [--select LESSON_ID]`. ... NEW: sends hello `{"platform":"replay","source":"file","name":"Replay: <file>"}` first so the UI shows the "Recording" banner.

**Proposed**
> `python -m server.replay VIDEO [--url ws://localhost:8000/ws/camera] [--fps 1] [--loop] [--start SEC] [--select LESSON_ID] [--no-hello]`. Frames are scaled to 1280 wide. On every connect it sends hello `{"device_id":"replay-<host>-<pid>","platform":"replay","source":"file","name":"Replay: <file>"}` first, unless `--no-hello`. `--select` waits up to 5 s for the confirming state and exits on an error. A lost connection retries after 1, 2, 4, up to 10 s and resumes the video where it was; close 4000 stops the replay.

**Code**: server/replay.py:1-14, 55-62, 93-100, 108-125, 138-186, 189-197

## P25. Health and metrics routes (section 4, NEW, not built)

**Current**: not in the contract.

**Proposed**: two NEW rows, both `Cache-Control: no-cache`, no secrets:
> | `GET /api/health` | | `{"uptime_s","lesson_id","step","total","status","cameras","ui_clients","check_mode":"gemini|mock","check_offline","check_offline_reason","ffmpeg":bool}` | NEW |
> | `GET /api/metrics` | | `{"counters":{...},"gate":{"frames_seen","checks_allowed","last_motion","last_change"},"check_latency_ms":{"n","p50","p90","max"}}` | NEW |
>
> Counter names: `frames_in`, `frames_ignored`, `frames_too_fast`, `frames_undecodable`, `frames_replaced_slow_client`, `events_dropped_full_queue`, `ws_messages_sent`, `ws_senders_failed`, `checks`, `check_errors_<timeout|rate_limited|error|no_key>`, `advances_<camera|button|voice>`, `mistakes`, `event_sink_errors`. Counters only appear once they are above 0.

What exists today: `Engine.snapshot()` returns everything above except `ffmpeg` and `check_latency_ms`. The hub keeps no latency history yet, so those two fields are still to build.

**Code**: server/main.py:89-90, 523-530, metrics at 201, 208, 237, 241, 508, 609, 707, 710, 713, 849, 851, 959, 991

## P26. Learn events and Databricks (new section 10)

**Current**: not in the contract.

**Proposed**: a new section:

> ## 10. Learn events (EXISTS, hub internal)
> The engine sends learn events to subscribers in `EVENT_SINKS`, inline on the event loop. A sink must return at once; a failing sink is logged once and skipped. Events never hold frames. Every event has `event_id`, `ts` (UTC ISO, ms, `Z`), `run_id` (hub run, or null), `lesson_id`, `rev`, `kind`.
>
> | `kind` | When | Fields |
> |---|---|---|
> | `run_start` | `select_lesson` | `total` |
> | `step_enter` | a step becomes current (not on done) | `step`, `check_type`, `expert_seconds` (step length in the video) |
> | `check` | each check result | `step`, `done`, `confidence`, `latency_ms`, `model` (`mock` in mock mode), `gated`, `error_kind` |
> | `advance` | every step change | `from`, `to`, `reason`, `step_seconds` |
> | `mistake` | a mistake is raised | `step`, `mistake_kind`, `looks_like`, `confidence`, `source` |
> | `run_done` | first time the run reaches done | `total_seconds`, `camera_steps`, `manual_steps`, `mistakes` |
> | `breaker` | `check_offline` or its reason changes | `open`, `reason` |
>
> When `server/databricks.py` (Pranav) can be imported, the hub adds one adapter sink at startup. `run_start` calls `end_run()` then `start_run(lesson_id)`; `run_done` calls `end_run()`; `advance` becomes `emit("advance", from_step, to_step, ...)`; `mistake` becomes `emit("mistake", kind=..., ...)`; `breaker` becomes `emit("check_offline", reason)` only when it opens; `step_enter` and `check` pass through. Fields Databricks does not name go to its `extra` column. After a teach job or a recut succeeds, the hub calls `upload_lesson_files(lesson_dir, lesson_id)`.

Open points for Pranav (code facts, not proposals to change his file):
- The hub's `event_id`, `ts`, `run_id` and `rev` are dropped by the adapter; databricks.py makes its own run id.
- `check` events carry no `reason`, although the databricks.py docstring example shows one.
- `run_done` totals and breaker closing are not forwarded.
- A run ends only on done or the next `select_lesson`. Deleting the active lesson or stopping the hub leaves it open.
- `DATABRICKS_*` and `HANDOVER_EVENTS_JSONL` are read by databricks.py and are not in section 1. Pranav may want to list them.

**Code**: server/main.py:293-338, 495-521, 555, 611, 615-628, 855, 962, 1016-1017, 1157, 1293; server/databricks.py:232-314

---

## P27. Provenance, latency and learner fields (sections 5, 6, 7, 10)

Built in `server/main.py` with tests in `server/test_engine.py`. Readers ignore unknown fields, so all of these are optional for clients.

> State fields:
> | Field | Type | Meaning |
> |---|---|---|
> | `check_mode` | `"mock"`, `"claude"` or `"gemini"` | who answers the live checks |
> | `next_clip` | string or null | the next step's clip as a lesson-relative path, exactly like `"clips/03.mp4"`, as soon as this step has one confident yes (and while `verified`); null otherwise and on the last step. Clients preload it |
> | `progress` | number 0..1 or null | from understanding (`HANDOVER_UNDERSTAND=1` with a rubric); null otherwise; reset on step change |
> | `stage` | `{"index":int,"count":int,"label":str}` or null | same source and reset as `progress` |
>
> Section 5, advance by camera: `verified` (with `next_clip`) goes out at once, then `go(position + 1, "camera")` after `HANDOVER_VERIFIED_HOLD` (0.8 s). Up to `HANDOVER_MAX_INFLIGHT` (2) checks run at once on different settled frames; debounce is N confident yes answers on N different frames, in frame order. Fast path: one yes at `HANDOVER_FAST_CONF` (0.92) whose `differs` is `nothing` advances alone (`HANDOVER_FAST_PATH=1`). State from check results is sent only when it changed.
>
> Section 6: a camera that never sends hello gets `source: "unknown"` (was `"phone"`). `platform` accepts `ios`, `android`, `web`, `macos`, `windows`, `linux`, `replay`; any other string becomes `"other"` and the hello still counts (next and back stay unlocked); a non-string platform makes the hello malformed. Frame rate: "about 2 fps, long side at most 960" (was "about 1 fps, long side 640 to 1280"); the hub accepts frames 0.2 s apart (`HANDOVER_MIN_FRAME_GAP`).
>
> Section 7, `select_lesson`: optional `"token"` (a sign-in token). When it resolves, the run is tagged with the learner's user id; otherwise the run is anonymous. Never an error.
>
> Section 7.2, `mistake.kind`: `behind`, `ahead`, or `live` (advisory, from understanding with `HANDOVER_LIVE_MISTAKES=1`, carries `label` and no `looks_like`, never moves the step). `ahead` only shows the banner and never moves the step unless `HANDOVER_AHEAD_SKIP=1`, which also needs the k+1 confirm at 0.9 and a yes for step k on the same frame. `source` is `claude`, `gemini` or `mock`.
>
> Section 10: `run_start` carries `learner` (user id or null), `source` (the active camera's source or null) and `check_mode`, and the adapter passes them to `databricks.start_run` (only the arguments its signature accepts).

New settings for section 1 (not yet in `server/config.py`): `HANDOVER_MAX_INFLIGHT` (int, 2, 1 to 4), `HANDOVER_FAST_PATH` (bool, 1), `HANDOVER_FAST_CONF` (float, 0.92, 0.5 to 1), `HANDOVER_AHEAD_SKIP` (bool, 0). Test-only: `HANDOVER_MOCK_LATENCY_MS` (`scripts/latency_bench.py`, 600, 0 to 10000).

---

## Suggested Revision 6 changelog

- Section 1: added an optional Tuning table (16 owner-only env vars); `HANDOVER_CHECK` ignores case; bad values warn and use the default; runtime notes on startup cleanup, websocket ping and the 8 MB message cap.
- Section 2: upload id cleaning trims and merges dashes and cuts to 64; generated ids cut to 48.
- Section 3: `self_test` may carry `mock: true` and comes from the CLI only; Recut rule now rewrites `ref_time`, keeps `check_type`, and keeps unknown fields (removed "Today recut drops unknown fields").
- Section 4: listed every upload, recut and delete error (411, 413 before the body, 415, 422 shape, 429, 409, 500 formats); `x-request-id` on every response; `/assets` caching; NEW `GET /api/health` and `GET /api/metrics`.
- Section 5: verified hold is 0.8 s (`HANDOVER_VERIFIED_HOLD`); fast confirm; `checking` only after 1.5 s in flight; states only on change; `rev` rules spelled out; active camera handover as coded.
- Sections 6 and 7: close 1011 (stalled sender, reconnect) and 1013 (connection cap); 5 frames per second cap per camera; hello field limits; 8 KB text cap; newest frame only and latest state only per client (do not assume one state per advance); with no lesson, unknown types also get `no lesson selected`; `state.mistake` holds the shown mistake, and `ahead` skips only with `HANDOVER_AHEAD_SKIP=1`.
- Section 8: check sends the previous step's reference as a "before" image, answers evidence first, takes `reason` from `differs`, and picks thinking per model; breaker `no_key` covers invalid keys and never retries; heartbeat fires during motion; mistake check details.
- Section 9: replay `--no-hello`, `device_id`, reconnect with back-off, stops on 4000.
- New section 10: learn events and the Databricks adapter.
- Statuses: built server items moved from NEW to EXISTS.
- Provenance, latency and learner fields (P27): `check_mode`, `next_clip`, `progress`, `stage`; pipelined confirm and fast path; camera default source `unknown`; more hello platforms; 2 fps; `select_lesson` token; `live` mistakes; ahead never skips by default.
