# Developer 1 autonomous work prompt (HandOver hub, packaging, CI)

Humans, before pasting: the repo exists at `https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer` (owned by teammate pr4nav3; Soham109 has write). Decide public vs private (private: free Actions minutes are limited and macOS jobs count 10x). On the lead Mac run `git remote add origin https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer.git && git push -u origin main`. Dev 2 clones that repo.

Paste everything below this line into a Claude Code session started in the HandOver repo on Developer 1's Mac.

---

You are the AI coding agent for **Developer 1** of HandOver. Work on your own for many hours until every item in your scope is done and verified, or clearly reported as not done. Follow this prompt exactly. Where it conflicts with an older doc, this prompt, `docs/PLAN.md` and `docs/CONTRACT_V2.md` win. `docs/PLAN.md` wins on times and drop order.

## 1. Mission and context

- HandOver: an expert does a task once on camera while narrating. The hub cuts that take into steps (Gemini plus ffmpeg) and plays the expert's own clip per step. The learner's camera streams JPEGs at about 1 fps; the hub moves on only when a vision check says the step is done.
- One Python FastAPI hub (`server/`) is the only server and the only stateful node. Every camera (iOS app, Android app, `capture.html`, `server.replay`) and every viewer (the web app) speak one contract: `docs/CONTRACT_V2.md`.
- You build the hub, the AI checks, the teach pipeline fixes, the desktop app (PyInstaller plus a small Tk window), the installers, CI, the smoke test and the demo lessons.
- Developer 2 builds the web app, the iOS app, the Android app, `capture.html` and `join.html`. They depend on your contract and your hub being up at each sync point.
- Hackathon: hacking ends **12:00 PM Sunday 2026-11-15**, judging 1:00 PM. Fixed times: contract freeze 6:00 AM, feature freeze 8:00 AM, code freeze 10:30 AM, submit 11:30 AM, hacking ends 12:00 PM, judging 1:00 PM.
- **Late start rule:** if you start after a sync's clock time, run that sync as soon as both sides' milestones for it are merged, in order. Never skip a sync.
- Git: `main` has commits `c8c9ff6`, `a6e2e55`, `6f60138` and later (plan and prompt docs). The remote is `https://github.com/pr4nav3/MetaGlasses-ExpertKnowlegeTransfer`; the humans add it before you start. If `git remote -v` shows none, ask them and keep working locally.
- Today `server.test_server` and `server.test_check` pass on this Mac (checked before this prompt was written).

### Read first, in this order
1. `docs/PLAN.md` (sections 3, 5, 6 are your work list, ownership, gates and timeline)
2. `docs/CONTRACT_V2.md` (authoritative interface; you own it)
3. `docs/research/architecture.md` (sections 7, 9, 11, 13 especially)
4. `docs/research/ai.md` (motion gate, breaker, local check numbers)
5. `docs/RESEARCH_GLASSES_GEMINI.md` (google-genai 3.3 notes, model ids)
6. `docs/research/platforms.md`, `docs/SPEC.md`, `docs/IDEAS.md`
7. The code: `server/main.py`, `check.py`, `teach.py`, `replay.py`, `test_server.py`, `test_check.py`, and `scripts/*.sh`

## 2. Ownership

You may edit only these paths:

| Path | Notes |
|---|---|
| `server/main.py`, `check.py`, `teach.py`, `replay.py`, `__init__.py` | EXISTS |
| `server/test_check.py`, `server/test_server.py`, `server/tests/**` | plain-assert tests, no pytest dependency; `python -m server.tests` runs every `server/tests/test_*.py` |
| `server/paths.py`, `discovery.py`, `package.py`, `gate.py`, `local_check.py`, `mistake.py`, `launcher.py`, `translate.py` | NEW |
| `server/requirements.txt`, `server/requirements.lock` | M2 adds segno, ifaddr, opencv-python-headless, numpy; lock made only with the section 4 command |
| `scripts/**` | `smoke.py`, `demo_replay.sh` are NEW |
| `packaging/**` | PyInstaller spec, build requirements, ffmpeg fetchers, dmg script, Inno Setup, licenses |
| `.github/workflows/**` | calls `apps/*/ci.sh` and `npm` scripts, never edits them |
| `lessons/**`, `recordings/` (gitignored) | demo lessons and replay files |
| `docs/CONTRACT_V2.md`, `README.md`, `.gitignore`, `CONTRACT.md` | shared files, change process in section 3.3 |
| `docs/DECISIONS_DEV1.md` | whole file (yours alone) |

Never edit (Developer 2 owns them): `web/**`, `server/static/**` (you only serve those files), `apps/ios/**`, `apps/android/**` (including `apps/android/ci.sh`; the `android` CI job only calls it), `assets/icon/**` (read only, for app icons), `docs/TESTED.md`, `docs/DEVPOST.md`, `docs/pitch/**`, `docs/DECISIONS_DEV2.md`.

Never edit (lead owns them): `docs/PLAN.md`, `docs/IDEAS.md`, `docs/SPEC.md`, `docs/SCOPE.md`, `docs/ARCHITECTURE.md`, `docs/RESEARCH_GLASSES_GEMINI.md`, `docs/research/**`, `docs/DEV2_PROMPT.md`, `docs/REVIEW_FIXES.md`, this file.

Need a change in a file you do not own? Write the exact change in one message for the human to pass on, and record it in `docs/DECISIONS_DEV1.md`. A new top-level path needs the lead's OK first.

## 3. Contract you implement

Every NEW field is optional for readers. Old clients (plain binary JPEG cameras, viewers that know only EXISTS messages) must keep working. Exact names below; full detail is in `docs/CONTRACT_V2.md`.

### 3.1 Already EXISTS (do not break)
- REST: `GET /api/lessons`, `GET /api/lessons/{id}`, `POST /api/lesson` (multipart `file`, `title`, `id`), `GET /api/jobs/{job}`, `POST /api/lessons/{id}/recut`, `GET /lessons/{id}/<path>`, `GET /capture`, `GET /` (JSON for now).
- `/ws/ui` client to hub: `select_lesson {id}`, `next {reason, from}`, `back {from}`, `goto {step}`. Hub to client: binary JPEG, `state`, `advance {from, to, reason}`, `error {message}`.
- `state` fields: `lesson_id`, `rev`, `step`, `total`, `status`, `last_check {done, confidence, latency_ms}`, `camera_connected`.
- Env: `HANDOVER_LESSONS`, `HANDOVER_PORT`, `HANDOVER_HTTPS_PORT`, `HANDOVER_CERTS`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `HANDOVER_CHECK_MODEL`, `HANDOVER_CHECK=mock`, `HANDOVER_MOCK_PASS_SECONDS`, `HANDOVER_CHECK_TIMEOUT`, `HANDOVER_DEBOUNCE_N`, `HANDOVER_MIN_CONF`, `HANDOVER_TEACH_MODEL`, `HANDOVER_TEACH_MOCK`.

### 3.2 NEW, by priority
| Pri | Item | Exact names |
|---|---|---|
| P0 | Data paths | `HANDOVER_DATA`, `<data>/uploads`, `<data>/certs`, `<data>/.env`, `<data>/hub.json {"hub_id","name"}`, `HANDOVER_WEB_DIST`, `HANDOVER_FFMPEG`, `HANDOVER_FFPROBE`, `HANDOVER_NAME`, `HANDOVER_OPEN_BROWSER` |
| P0 | Web app at `/` | `index.html` plus `/assets/*` from the dist when it exists, else today's JSON |
| P0 | Info and QR | `GET /api/info` with `app`, `contract: 2`, `version`, `hub_id`, `name`, `os`, `ports.http`, `ports.https`, `urls.local`, `urls.lan`, `urls.join`, `urls.capture`, `check.mode`, `check.model`, `check.has_key`, `check.offline`, `check.offline_reason`, `mdns`, `languages`. `GET /api/qr?text=` (SVG, errors `text required`, `text too long`). `GET /join` (serves `server/static/join.html`, no-cache; 404 `join page not installed` when the file is missing). `POST /api/shutdown` (localhost only, 403 `settings can only be changed on the hub computer`) |
| P0 | LAN order | section 9.2: IPv4 only, drop loopback, 169.254/16, `utun*`, `awdl*`, `llw*`, `bridge*`, `vEthernet*`, `docker*`, `vmnet*`, `Tailscale*`; order 192.168, 172.16/12, 10/8, others |
| P0 | Camera hello | client `hello {device_id, name, platform, source, model, app_version}`; hub `welcome {camera_id, active, hub {hub_id, name, version, contract}}`, `camera_status {active}`; close code 4000 reason `replaced`; no-hello camera gets `name "Camera <n>"`, `platform "other"`, `source "phone"`, `device_id null`; a repeated hello on an open socket updates `name`, `platform`, `source`, `model` and broadcasts state if that camera is active |
| P0 | Active camera | `camera_id` = `cam-<n>`; newest hello or connect wins; takeover after 5 s silence if another sent within 2 s; `state.camera {camera_id, name, platform, source}`, `state.cameras` (int); broadcast on active change |
| P0 | lesson.json | `format_version` (default 1), `video: null` support (recut gives 409 `source video not included; re-cut is unavailable for this lesson`) |
| P0 | Recut rule | recut rewrites only `n`, `start`, `end`, `clip`, `captions`, `ref_frame`, `check_question`, `prerequisites`; keeps the stored `check_type` and every other step and top-level field |
| P0 | Replay | sends `hello {"platform":"replay","source":"file","name":"Replay: <file name>","device_id":"replay-<hostname>-<pid>"}` first; finds ffmpeg through the 1.2 lookup |
| P1 (S-P, SHOULD) | Package | `GET /api/lessons/{id}/export[?video=0]`, `POST /api/lessons/import` returning `{id, title, steps, renamed}`; `manifest.json` fields `format`, `format_version`, `app_version`, `created_at`, `lesson_id`, `title`, `includes_video`, `hub_os`; `HANDOVER_IMPORT_MAX_MB`; every error string in section 4.3 and the safety rules in section 10 |
| P1 | Camera socket commands | camera `next {reason, from}`, `back {from}` (after hello only); hub sends `state`, `advance`, `mistake`, `error` to cameras after hello, never frames; frames over 2 MB ignored |
| P1 | Check state | `HANDOVER_CHECK` = `gemini`, `local`, `mock`; `last_check.source`, `last_check.reason`; `check_source`, `check_offline`, `check_offline_reason` (`no_key`, `rate_limited`, `errors`); `HANDOVER_GATE`, `HANDOVER_BREAKER_SECONDS`, `HANDOVER_LOCAL_N` |
| P1 | Mistake | `mistake {step, kind ("behind" or "ahead"), looks_like, message, confidence, source}`; `state.mistake`; `/ws/ui` `dismiss_mistake`; step fields `ref_time`, `common_mistake`, `mistake_question`; test hook `HANDOVER_MOCK_MISTAKE=behind:<step index>` or `ahead:<step index>` (mock mode only, `source: "mock"`) |
| P1 | Other | `/ws/ui?frames=0` (built in M4); `DELETE /api/lessons/{id}`; `PUT /api/settings {gemini_key}` (S-K) |
| P2 | Only if all else is done | step `self_test` (S-T), top-level `safety` and `tools` (S-S), multi-file upload, mDNS (`HANDOVER_MDNS`, STRETCH), translate job, import from URL, `source_language`, `languages`, `i18n` |

`rev` is an increasing int and opaque to clients: today it is lesson.json mtime in ms, kept strictly increasing (M2).

### 3.3 Contract change process (you own `docs/CONTRACT_V2.md`)
1. Developer 2 sends a request with the exact text (field, type, which side sends it).
2. You edit, bump the `Revision` line at the top, commit `Contract: <what changed>`, and reply with the commit hash.
3. Additive optional changes: you decide alone. Renames, removals or type changes need both humans and land with the hub and client change in the same hour.
4. When you implement a NEW item, change its marker to EXISTS in the same commit, so Dev 2 knows they can rely on it. Tell the human which items flipped at each sync.
5. **6:00 AM Sunday contract freeze**: `git tag contract-freeze && git push origin contract-freeze`. After that, bug fixes only, both humans agree. The freeze check must print nothing (marker flips and the Revision line are allowed):
   ```
   git diff contract-freeze -- docs/CONTRACT_V2.md | grep '^[+-][^+-]' | grep -v 'EXISTS\|NEW\|Revision'
   ```

## 4. Environment setup (macOS)

1. Check: `git status`, `git log --oneline -3`, `git remote -v`, `which ffmpeg uv gh node`, `gh auth status` (do not print tokens).
2. The existing `.venv` uses Homebrew Python 3.12, which has **no `_tkinter`** (verified: `import tkinter` fails). The launcher window needs Tk. Rebuild the venv with uv's managed Python, which includes Tk:
   ```
   mv .venv .venv-old-homebrew
   uv venv --python 3.12 --python-preference only-managed .venv
   uv pip install --python .venv/bin/python -r server/requirements.lock
   .venv/bin/python -c "import tkinter; print(tkinter.TkVersion)"
   .venv/bin/python -m server.test_check && .venv/bin/python -m server.test_server
   ```
   If both tests pass, tell the human `.venv-old-homebrew` can be removed by hand; do not delete it yourself. If uv cannot fetch a managed Python, record it and ask the human (alternative: `brew install python-tk@3.12`, which needs their OK).
3. Adding a dependency: add it to `server/requirements.txt`, then regenerate the lock for every OS and install it. **Never use `uv pip freeze` for the lock** (it drops platform markers, and the Windows install then fails on uvloop):
   ```
   uv pip compile server/requirements.txt --universal --python-version 3.12 -o server/requirements.lock
   uv pip install --python .venv/bin/python -r server/requirements.lock
   grep -n uvloop server/requirements.lock      # must carry sys_platform != 'win32'
   ```
   Review the diff (no stray packages). Build-only tools (pyinstaller) go in `packaging/requirements-build.txt`, never the runtime lock.
4. Gemini key: read only from `GEMINI_API_KEY`, `GOOGLE_API_KEY` or `.env` at the repo root (or `<data>/.env`). **Never print it**, never `cat .env`, never log it, never put it in a commit, CI log or URL. When both env vars are set, google-genai uses `GOOGLE_API_KEY`. To check a key exists:
   ```
   { test -n "$GEMINI_API_KEY" || test -n "$GOOGLE_API_KEY" || grep -qE '^(GEMINI|GOOGLE)_API_KEY=.' .env; } && echo key present
   ```
5. Web dist for serving at `/`: `npm --prefix web ci && npm --prefix web run build` (reading and building Dev 2's code is fine; never edit it).

### Windows
- There is no Windows machine unless the humans say so. Windows is built and smoke tested in CI (`hub-win`). Label every Windows claim "built and smoke tested in CI, not tested by hand".
- Write portable code: `pathlib` everywhere, `ffmpeg.exe` and `ffprobe.exe` names, no `shell=True`, utf-8 on every read and write, `%LOCALAPPDATA%\HandOver` data dir, signal fallbacks, PowerShell for the CI smoke step.
- Windows first run, written in `README.md` and shown as one short line in the Tk window on Windows: firewall prompt, allow Private and Public networks or set the hotspot network to Private; SmartScreen, More info, then Run anyway.

## 5. Gemini rules

- Models: `gemini-3.8-flash` for teach (`HANDOVER_TEACH_MODEL`), `gemini-3.5-flash-lite` for checks (`HANDOVER_CHECK_MODEL`). Both have a free tier.
- `gemini-3.1-pro-preview` has **no free tier**. Never call it, and never enable billing or any paid service, without asking the human first.
- **Measure first (M1), before tuning anything:** 20 real check calls.
  ```
  .venv/bin/python -m server.check --time lessons/demo-v1/frames/02.jpg lessons/demo-v1/frames/02.jpg "Is this step finished?" -n 20
  ```
  Gate on the printed p50: **2.0 s or less passes**. 2.0 to 2.5 s: wider motion gate (longer stillness window, longer heartbeat). Over 2.5 s: advance on one confident yes plus local agreement. Write the numbers, the network used and the project limits (the human reads them at aistudio.google.com/rate-limit) in `docs/DECISIONS_DEV1.md`. Run it once now on the current network and again at 6 PM on the hotspot (ask the human to switch networks; never change network settings yourself).
- Values from `docs/research/ai.md` and architecture.md section 7 (start here, tune only with measurements, record changes):

| Setting | Value |
|---|---|
| Motion gate input | 160x90 gray, 5x5 blur, absdiff vs previous frame |
| Motion pixel | diff > 25 |
| Hold | while motion > 2% |
| Check allowed | motion < 0.5% for 2 frames and > 3% different from the last checked frame |
| Heartbeat | one check every 6 s regardless |
| Timeout | 3 s (`HANDOVER_CHECK_TIMEOUT`), counts as an error |
| Breaker opens | 3 consecutive errors or timeouts, or any 429 |
| Breaker open time | 30 s (`HANDOVER_BREAKER_SECONDS`), then one trial call |
| Local score | 0.5 HS histogram correlation + 0.3 (1 - matchShapes I1, clipped) + 0.2 edge density similarity |
| Local pass | current step best with lead >= 0.1 and histogram correlation >= 0.75; `HANDOVER_LOCAL_N` = 3 in a row |
| Local veto (Gemini up) | no advance if local names another step with lead > 0.2 |
| Mistake check | after 5 s of settled consecutive no on a camera step, at most once per 10 s per step; behind at match A confidence >= 0.7; ahead confirmed by one normal check of k+1 at yes >= 0.8 |
| Debounce | 2 consecutive yes at >= 0.8 (EXISTS) |

- Save rehearsal calls: use mock or local mode for everything except the measurements and the real loop tests. Count calls per run with the gate on and record it.

## 6. Milestones (in order)

For every milestone: write or extend a test first where it is testable, implement, run the verification command, look at the output yourself, commit. Before any heavy step (PyInstaller, full test suite, web build, a long replay) run the load check in section 10.

Base hub for checks, unless stated: `HANDOVER_CHECK=mock HANDOVER_MOCK_PASS_SECONDS=3 .venv/bin/python -m server.main` (run it in the background and stop it after).

### M2. Frozen-app foundations (first; everything else sits on it)
Done when:
- **PyInstaller probe, first:** a one-file Tk hello window built with `--onedir --windowed` in `build/pyi-probe/` (install pyinstaller from `packaging/requirements-build.txt`) starts and shows Tk. If it fails, record why in `docs/DECISIONS_DEV1.md` and, after asking the human, switch the venv to Homebrew `python-tk@3.12`.
- **Dependencies:** add `segno`, `ifaddr`, `opencv-python-headless` and `numpy` to `server/requirements.txt` and regenerate the lock with the section 4 command.
- **Test runner:** `server/tests/__init__.py` and `server/tests/__main__.py`; `.venv/bin/python -m server.tests` imports every `server/tests/test_*.py`, runs each `test_*` function, prints `ok` or the failure per test and exits non-zero on any failure.
- `.gitignore` already has the runtime entries (`.venv*/`, `/hub.json`, `/uploads/`, `/logs/`, `recordings/`, `build/`, `dist/`, `.recut_tmp/`, `.recut_old/`, `*.log`, `*.spec.bak`); keep them.
- `server/paths.py` is the one place for: data dir (`HANDOVER_DATA`; else frozen: `~/Library/Application Support/HandOver` on macOS, `%LOCALAPPDATA%\HandOver` on Windows; else repo root), lessons (`HANDOVER_LESSONS` else `<data>/lessons`), uploads (`<data>/uploads`), certs, `.env`, `hub.json`, web dist (`HANDOVER_WEB_DIST`, `sys._MEIPASS/web/dist`, `<repo>/web/dist`), static dir (bundle aware), and `ffmpeg()` / `ffprobe()` lookup (`HANDOVER_FFMPEG`, `sys._MEIPASS/ffmpeg[.exe]`, PATH, `/opt/homebrew/bin/ffmpeg`; ffprobe: `HANDOVER_FFPROBE`, same folder as the found ffmpeg, then the same order).
- `main.py`, `check.py`, `teach.py` and `replay.py` use it. No other module computes `REPO / ...` for data. **`replay.py` no longer calls bare `"ffmpeg"`.** The missing-tool error still says "not found on PATH" (an existing test checks that text) and names `HANDOVER_FFMPEG`.
- Paths are resolved when needed or through one init call, so the launcher can set env vars before import. `HANDOVER_LESSONS` still overrides.
- `GET /` serves the web dist `index.html` and `/assets/*` when the dist exists, else the old JSON. **MIME types:** `main.py` registers `text/javascript` (`.js`, `.mjs`), `text/css` (`.css`), `image/svg+xml` (`.svg`) and `application/json` (`.json`) with `mimetypes.add_type` at import, because the Windows registry can map `.js` to `text/plain` and the browser then refuses the module.
- **Recut keeps fields:** `teach.cut()` merges each old step (matched by position) under the rewritten fields and keeps unknown top-level fields and the stored `check_type`. Today `cut()` rebuilds every step from scratch and drops `ref_time`, `common_mistake` and anything else.
- **`rev` is always correct:** it changes after every recut and every lesson.json write, even when two writes land in the same millisecond (use `max(mtime_ms, previous_rev + 1)` for the active lesson). Dev 2 busts thumbnail and clip caches with `?v=<rev>`, so a stale rev shows old media.
- `start_hub()` / `stop_hub()` in `main.py`: run the servers on a background thread's event loop; install signal handlers only when on the main thread (the launcher thread cannot install them; today `serve()` always tries).
- **Upload size early:** reject `POST /api/lesson` (and later `/api/lessons/import`) with 413 from the `Content-Length` header before the body is read, using a small ASGI middleware or a raw `Request` check; keep the streaming cap for chunked uploads with no header. Today FastAPI parses the full multipart body (up to many GB to a temp file) before the handler runs.
Verify:
- New tests in `server/test_server.py`: recut keeps `ref_time`, `common_mistake`, `check_type` and a custom top-level field; rev strictly increases across two quick recuts; 413 arrives for a large `Content-Length` without the body being read (send a small body with a big header via the raw ASGI client or `httpx` with a generator); `paths.ffmpeg()` honors `HANDOVER_FFMPEG`; frozen data dir chosen when `sys.frozen` is patched; replay builds its command from `paths.ffmpeg()`; `.js` assets come back as `text/javascript`.
- `.venv/bin/python -m server.test_server && .venv/bin/python -m server.test_check && .venv/bin/python -m server.tests` all `ok`.
- With the web built: start the base hub, `curl -s http://localhost:8000/ | head -c 200` shows HTML; `curl -sI http://localhost:8000/assets/<a file from web/dist/assets>` is 200.
- `HANDOVER_FFMPEG=/nonexistent .venv/bin/python -m server.replay lessons/demo-v1/norm.mp4` fails with a clear message, not a traceback from bare `ffmpeg`.

### M3. Info, QR, join, smoke script, demo replay script
Done when:
- `GET /api/info` returns every field in 3.2 with real values; `hub.json` created on first run (uuid4 hex, name from `HANDOVER_NAME` else the computer name); `GET /api/qr` (segno); `GET /join` (404 `join page not installed` when `join.html` is missing); `POST /api/shutdown`; LAN order per 9.2 in `server/discovery.py` (ifaddr) with unit tests on a fake interface list.
- **`scripts/smoke.py`** (stdlib plus `httpx` and `websockets`, runs on macOS, Linux and Windows):
  - Default mode `--base http://localhost:8000`: `/api/info` has `app == "HandOver"` and `contract == 2`; `/api/qr?text=x` is SVG; `/api/lessons` lists `demo-v1`; when `/` serves HTML, the first `/assets/*.js` named in `index.html` has `Content-Type` starting with `text/javascript`; starts `python -m server.replay lessons/demo-v1/norm.mp4 --select demo-v1 --url <ws of base>`; on `/ws/ui?frames=0` (skipping any binary message, since `frames=0` lands in M4) expects `state.camera.name == "Replay: norm.mp4"`, `state.camera.platform == "replay"`, and an `advance` with `reason == "camera"` within 30 s. Once S-P lands, an export then import round trip runs only when smoke's own `HANDOVER_DATA` env is set to a path under `build/` (give it the same value as the hub), and then deletes the imported lesson with `DELETE /api/lessons/{id}`; otherwise it prints a skip note. Prints one `PASS name` or `FAIL name: why` line per check, exits non-zero on any fail, always stops the replay child.
  - `watch` mode: connects to `/ws/ui?frames=0` (skipping binary) and prints every `state`, `advance`, `mistake` and `error` as one `json.dumps(msg)` line (default separators, so `grep '"kind": "behind"'` works), with a local timestamp prefix, flushed after every line (so `tee` gets whole lines). Reconnects on drop. Ctrl+C exits cleanly.
  - `watch --press-next-on-manual SEC`: when `state.status` has been `manual` for SEC seconds, sends `{"type":"next","reason":"button","from":<step>}` once for that step and prints `PRESSED next on manual step <n>` (1-based). This is how a replay reaches done past manual steps.
  - Until M4 lands, the camera assertions print `FAIL` honestly; that is expected at Sync 1. They must PASS at Sync 2.
- **`scripts/demo_replay.sh RECORDING [LESSON_ID]`**: one command for the demo fallback. Defaults: lesson `fortune-teller-v1`, hub `${HANDOVER_HUB:-localhost:8000}`. Runs `server.replay` with `--select`, prints the exact command it runs, fails clearly when the file or lesson is missing.
- `CONTRACT.md` gets "Superseded by docs/CONTRACT_V2.md" at the top.
Verify:
- `.venv/bin/python -m server.test_server` (new tests for info shape, qr errors `text required` and `text too long`, shutdown 403 from a non-local client, LAN order, `/join` both with a temp static dir that has `join.html` and one that does not).
- Base hub running: `.venv/bin/python scripts/smoke.py --base http://localhost:8000` shows PASS for info, qr, lessons, assets MIME.
- `curl -s 'http://localhost:8000/api/qr?text=http://192.168.1.20:8000/join' -o /tmp/qr.svg` then open the SVG with the Read tool and look at it.
- `scripts/demo_replay.sh lessons/demo-v1/norm.mp4 demo-v1` while `smoke.py watch --press-next-on-manual 3` runs in another shell: advances appear and the lesson reaches done.

### Sync 1 (Sat 4:30 PM): contract smoke (M2, M3)
See section 7. Flip M2 and M3 items to EXISTS in the contract.

### M4. Camera hello and active camera
Done when: hello, welcome, `camera_status`, close code 4000, no-hello defaults, repeated hello on an open socket updates `name`, `platform`, `source`, `model` and broadcasts state if that camera is active, active camera and takeover rules (6.3), `state.camera`, `state.cameras`, broadcast on active change, frames only from the active camera go to checks and viewers, camera socket receives `state`, `advance`, `mistake` and accepts `next` and `back` after hello (P1, cheap to do now), frames over 2 MB ignored, `/ws/ui?frames=0` sends no binary. Replay sends hello.
Verify:
- Tests with `TestClient` websockets: hello then welcome; second socket with the same `device_id` closes the first with 4000; two cameras, newest active, the idle one gets `camera_status {active:false}`; takeover after 5 s silence (patch the clock); plain-binary camera still works and shows `Camera <n>`; camera `next` with a stale `from` is ignored; hello as `source:"phone"` then hello as `source:"glasses"` on the same socket and a viewer sees `state.camera.source == "glasses"`; a `?frames=0` viewer receives no binary message while a camera streams.
- Base hub: `.venv/bin/python scripts/smoke.py --base http://localhost:8000` all PASS.

### M12 (part 1). Minimal CI, before Sync 2
Land `.github/workflows/build.yml` with `web`, `android` and `ios` jobs only (same job bodies as M12 below; `android` and `ios` skip with a clear message while their `ci.sh` does not exist). Triggers (lead CI policy, PLAN Lead decisions): `on: push` (all branches) plus `workflow_dispatch`; `web` runs on every push; `android` and `ios` carry `if: github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'`, so a dev branch push never starts them and a developer can run their branch by hand, sparingly, with `gh workflow run build.yml --ref <branch>`. Add `concurrency: {group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true}`. Tell the human it exists. It grows into the full set in M12.

### M1. Gemini gate (measure now; official run at 6 PM on the hotspot)
Done when: 20 calls measured with the command in section 5, p50 and p90 recorded, decision applied (pass, wider gate, or one yes plus local).

### M5. Motion gate (`server/gate.py`)
Done when: the gate in section 5 runs before every Gemini call, heartbeat every 6 s, `HANDOVER_GATE=0` disables it, mock mode bypasses it.
Verify: unit tests with synthetic frames (still, moving, still again but different) in `server/tests/test_gate.py`; a replay of `lessons/demo-v1/norm.mp4` in `HANDOVER_CHECK=gemini` mode logs calls per minute with the gate on and off (record both numbers).

### M6. Breaker, check modes, honest state
Done when: `HANDOVER_CHECK` = `gemini` / `local` / `mock`; breaker per section 5; `check_source`, `check_offline`, `check_offline_reason`; no key at startup gives `local` with reason `no_key`; `last_check.source` and `last_check.reason` (reason up to 8 words, added to the Gemini answer schema, null when absent); `/api/info` `check` block matches.
Verify: tests that fake the Gemini call: 3 timeouts open the breaker with `errors`, a 429 opens it with `rate_limited`, a trial success after the open time closes it. Live, each hub shown in `smoke.py watch` (unset `GOOGLE_API_KEY`, and keep the repo `.env` out of the no-key run):
```
env -u GOOGLE_API_KEY GEMINI_API_KEY= HANDOVER_DATA="$PWD/build/nokey" HANDOVER_LESSONS="$PWD/lessons" HANDOVER_CHECK=gemini .venv/bin/python -m server.main     # check_offline_reason "no_key"
env -u GOOGLE_API_KEY GEMINI_API_KEY=invalid-key HANDOVER_CHECK=gemini .venv/bin/python -m server.main     # "errors" after 3 failed calls
```

### Sync 2 (Sat 6:30 PM): first live loop with the iPhone app, camera assertions
`smoke.py` all PASS on the mock hub (this is where the M4 camera assertions are judged). Then you keep the hub up on the hotspot and run `watch`. Dev 2 drives the phone. Flip M4 items to EXISTS.

### M8. Clean references, step 1 manual, better questions, HDR
Done when:
- Teach writes `ref_time` per step (the stillest hands-free frame in the last 15% of the clip; "stillest" = lowest motion score from the gate's function over frames sampled at 4 fps) and grabs that frame from norm.mp4; absent `ref_time` keeps the last frame. Step 1 is manual for **new extractions only**; recut keeps the stored `check_type`. Never re-cut `demo-v1`. The teach prompt asks for questions by shape and seam count, never by color, plus `common_mistake` and `mistake_question` per step.
- **HDR:** today HDR input is only matrix converted and tagged bt709, with no tone mapping, so iPhone HDR looks washed out. Detect filters at runtime (`<ffmpeg> -hide_banner -filters`). When `zscale` exists, use `zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p`; otherwise keep the current conversion and log one line saying tone mapping is unavailable. Note: the Homebrew ffmpeg on this Mac has `tonemap` but **no `zscale`** (checked); check whether the static ffmpeg you bundle has it (`<ffmpeg> -hide_banner -filters`, look for zscale) and record the answer.
Verify: tests for `ref_time` selection on a generated clip whose last 15% has one still segment; recut keeps `ref_time` and `check_type`; for HDR, generate a PQ-tagged test clip (`-color_primaries bt2020 -color_trc smpte2084 -colorspace bt2020nc` on a testsrc2 encode), normalize it with each ffmpeg you have, extract a frame and look at it with the Read tool. Say plainly which path was verified.

### M9. Mistake check (`server/mistake.py`)
Done when: behind and ahead per contract section 7.2 and section 5 above; `mistake` message and `state.mistake`; cleared on step change, `dismiss_mistake`, and a yes on this step; local scores stand in while the breaker is open; message text exactly `This still looks like step <looks_like + 1>.` or the step's `common_mistake`, and `You're ahead.` The real check never runs in mock mode. **Mock test hook (contract P1, test only):** with `HANDOVER_CHECK=mock` and `HANDOVER_MOCK_MISTAKE=behind:<step index>` or `ahead:<step index>`, after 4 s on that step the hub sends `mistake` exactly as contract 7.2 with `source: "mock"` (behind: `looks_like` = step - 1; ahead: `looks_like` = step + 1, then the normal ahead jump). Dev 2 uses it for the banner; Devpost screenshots of the banner must come from a real Gemini run.
Verify: tests with a faked multiple-choice answer for A, B, C, none; ahead with and without confirmation (`to - from == 2` only when confirmed); rate limit once per 10 s per step; the mock hook sends one `mistake` with `source: "mock"` after 4 s and nothing without the env var.

### M14 (part 1). Fortune teller lesson
The humans hand over the take by 6:30 PM. Copy it to `recordings/` (gitignored), cut with `.venv/bin/python -m server.teach <file> --id fortune-teller-v1 --title "Fold a fortune teller"`, review every step in the web app, fix timestamps by editing lesson.json and `POST /api/lessons/fortune-teller-v1/recut`. Step 5 (the flip) gets `common_mistake` `"Flip it over first."` and a `mistake_question` whose yes means the paper is still unflipped (for example "Are the folded flaps still facing up, so the paper has not been turned over?"). Commit the lesson folder (check its size first; if over about 100 MB, ask the human before committing). Never invent a take; if none exists yet, keep going and say so.

### Sync 3 (Sat 8:00 PM): glasses gate and drop check
Dev 2's gate; you keep the hub up and run `watch`. Drop check: if M9 is not green now, M7 shrinks now to "breaker shows Checks off, use Next".

### M7. Local OpenCV check (`server/local_check.py`)
Done when: the algorithm and thresholds in section 5 (opencv-python-headless and numpy are in the lock since M2); `unsure` on scenes it is not tuned for; veto rule while Gemini is up; `HANDOVER_CHECK=local` finishes a clean replay.
Verify: unit tests on the demo lesson frames (each reference scores best against itself); `HANDOVER_CHECK=local .venv/bin/python -m server.main` plus `scripts/demo_replay.sh lessons/demo-v1/norm.mp4 demo-v1` reaches done with `smoke.py watch --press-next-on-manual 3`, every camera step advanced with reason `camera`; record per-step scores and separation in `docs/DECISIONS_DEV1.md`. If shrunk at the 8 PM drop check, build only "breaker shows Checks off, use Next" (PLAN drop order).

### M11. Launcher and Mac app
Done when:
- `server/launcher.py`: before importing `server.main`, set data env vars and, when `sys.stdout` or `sys.stderr` is None (windowed builds), point both at `<data>/logs/hub.log`; start the hub with `start_hub()` on a background thread; wait for `/api/info`; open `http://localhost:8000/` unless `HANDOVER_OPEN_BROWSER=0`; Tk window on the main thread; `--headless` runs until SIGTERM or `POST /api/shutdown`; if Tk fails to import, fall back to headless and log why.
- Tk window, calm and Apple-native: system font (`TkDefaultFont`), `ttk` with the native theme, generous padding, no custom colors, no gradients. Contents: hub name as the title, the QR (from segno, crisp at integer scale), the join URL in selectable text, buttons "Open in Browser", "Copy Address", "Quit". On Windows, one short line with the firewall and SmartScreen steps from section 4. "Quit" and the Dock quit both call `stop_hub()` and exit within 1 s.
- First frozen run with an empty lessons folder copies the bundled seed lessons (`demo-v1`, and the real lessons once cut).
- **Icons:** Dev 2's W9 delivers `assets/icon/icon.svg` and a 1024 PNG. Convert the PNG to `build/icon/HandOver.icns` (`sips` to the iconset sizes, then `iconutil -c icns`) and `build/icon/HandOver.ico` (Pillow, sizes 16 to 256). Until W9 lands, build without an icon.
- `packaging/handover.spec`: onedir; Mac `BUNDLE` to `HandOver.app`, windowed; datas `web/dist`, `server/static`, seed lessons, ffmpeg and ffprobe plus license text; `collect_submodules("uvicorn")`, `collect_all("google.genai")`; Info.plist with `NSLocalNetworkUsageDescription`, `NSBonjourServices = ["_handover._tcp"]`, `CFBundleShortVersionString = "0.2.0"`; icon from `build/icon/` when it exists.
- `packaging/ffmpeg/fetch.sh` (static arm64 build, pinned SHA256, refuses on mismatch) and `fetch.ps1` (gyan.dev essentials, pinned SHA256). Homebrew ffmpeg is not relocatable; never bundle it. The bundled ffmpeg is GPL: ship its license text and a link to the exact source release in `packaging/licenses/`, and include that folder in the app.
Verify (load check first):
```
uv pip install --python .venv/bin/python -r packaging/requirements-build.txt
npm --prefix web run build
packaging/ffmpeg/fetch.sh
.venv/bin/pyinstaller packaging/handover.spec --noconfirm --clean
export HANDOVER_DATA="$PWD/build/data-test"
HANDOVER_CHECK=mock HANDOVER_MOCK_PASS_SECONDS=3 HANDOVER_OPEN_BROWSER=0 dist/HandOver.app/Contents/MacOS/HandOver --headless &
.venv/bin/python scripts/smoke.py --base http://localhost:8000
curl -s -X POST http://localhost:8000/api/shutdown
```
Then run the `.app` once with the window, `HANDOVER_DATA` pointing at `build/data-test`, and look at it: capture only the window region (have the launcher print its screen geometry under a `--debug` flag, then `screencapture -x -R<x>,<y>,<w>,<h> build/window.png`) and read the PNG. Never capture the whole screen. `screencapture` needs the Screen Recording permission for the terminal; if it is missing or the PNG is blank, ask the human for a screenshot of the window instead, and never change that permission yourself. Check that Quit exits and the port is free after (`lsof -iTCP:8000 -sTCP:LISTEN` prints nothing). Check `build/data-test/logs/hub.log` exists and has the startup lines.

### Sync 4 (Sat 10:00 PM): Mac app checkpoint
The M11 verify block (PLAN Sync 4 commands). Dev 2 streams the iPhone app to the frozen app if it exists.

### M15. Privacy backed by code
Done when: a test streams frames through `/ws/camera` for a camera step and asserts no file was created anywhere under the data dir, uploads or lessons (snapshot before and after), and that frames are only in memory.
Verify: `.venv/bin/python -m server.test_server`.

### M14 (part 2). Bike lesson and replay recordings
The humans hand over the bike take by 10:00 PM and the clean and skipped-flip replays by 11:00 PM. Cut the bike take the same way (`--id bike-front-wheel-v1`). File the replays as `recordings/fold-clean.mp4` and `recordings/fold-skipped-flip.mp4`. Verify each with `scripts/demo_replay.sh` against a local-mode hub while `smoke.py watch --press-next-on-manual 3 | tee -a build/replays.log` runs: the clean one reaches done with every camera step advanced with reason `camera`; the skipped one produces a `behind` mistake, counted with `grep '"type": "mistake"' build/replays.log | grep -c '"kind": "behind"'`. Record the result honestly, including misses.

### M12. CI (`.github/workflows/build.yml`)
Grow the part 1 workflow (keep the triggers and the `concurrency` block). `web` and `hub-test` (ubuntu, cheap) run on every push; `hub-mac`, `hub-win`, `android` and `ios` run only on pushes to `main` or on `workflow_dispatch` (the `if:` from part 1). Jobs:
- `web`: Node 22, `npm ci`, `npm run build` in web/, upload `web-dist`.
- `hub-test`: ubuntu, `actions/setup-python` 3.12, lock install, apt ffmpeg, `server.test_server`, `server.test_check`, `server.tests`, mock hub plus `scripts/smoke.py`.
- `hub-mac`: macos-latest, `actions/setup-python` 3.12, lock install (smoke needs httpx and websockets), web-dist, fetch.sh, pyinstaller, ad hoc sign, `HANDOVER_FFMPEG` set to the fetched ffmpeg, headless smoke (its replay child needs that ffmpeg). Upload `HandOver.app` zipped (`ditto -c -k --keepParent`) as artifact `hub-mac` so the executable bit survives.
- `hub-win`: windows-latest, `actions/setup-python` 3.12, lock install, web-dist, fetch.ps1, pyinstaller, `HANDOVER_FFMPEG` set to the fetched `ffmpeg.exe`, `HandOver.exe --headless`, smoke in PowerShell, Inno Setup only if `choco install innosetup -y` works.
- `android`: setup-java 17, runs `apps/android/ci.sh` only, uploads the APK; skip with a clear message if the script does not exist yet.
- `ios`: select the newest Xcode first (`sudo xcode-select -s` the highest `/Applications/Xcode_*.app`), `brew install xcodegen`, runs `apps/ios/ci.sh` only.
- `release` on tag `v*`.

Smoke always uses `HANDOVER_CHECK=mock`; CI never calls Gemini and never sees a key. No paid runners.
Verify (needs the GitHub remote; if none exists, ask the human and keep going on other work):
```
gh run list --branch main --limit 1
gh run watch <id> --exit-status
gh run view <id> --json jobs --jq '.jobs[] | [.name, .conclusion]'
gh run view <id> --log-failed
```
Fix every red job you own. A red `android` or `ios` job caused by Dev 2's `ci.sh` gets one message to the human with the log lines, not an edit.

### Sync 5 (Sun 12:00 AM), Sync 6 (2:00 AM): see section 7

### S-P. Export and import (first SHOULD; PLAN puts it right after M12)
Done when: every field, error string and safety rule in contract sections 4.3 and 10 (`server/package.py`); import never overwrites; `video=0` gives `video: null` and recut 409; Windows CI smoke imports a package made on hub-mac (upload as an artifact between jobs).
Verify: tests for each error string (`not a HandOver lesson file`, `unsupported package version <n>`, `unsafe path in package: <name>` for `..`, absolute, backslash, drive letter and symlink entries, `missing file in package: <path>`, `package too large`, clash gives `-2` and `renamed: true`); `smoke.py` round trip PASS with `HANDOVER_DATA` under `build/`.

### After Sync 7 (6:00 AM): SHOULD, in this order, only if every MUST passed its gate
1. S-T check self-test at teach time (own frame yes, previous frame no) written to the step field `self_test` `{"own","prev","ok"}` (contract NEW P2) that Dev 2 badges.
2. S-K `PUT /api/settings` (localhost only, writes `<data>/.env` with mode 600, resets the breaker).
3. S-S safety warnings and tools list from the narration, top-level `safety` and `tools` (contract NEW P2).
4. S-I `packaging/mac/make-dmg.sh` (ad hoc `codesign --force --deep -s -`, `hdiutil create -format UDZO`) and Inno Setup with the firewall rule from architecture.md 9.5.
Stretch only after all of that: mDNS, translations, Playwright on windows-latest.

### Release (Sun 10:30 AM code freeze)
Changelog section in `README.md`, version `0.2.0` in every file you own where it lives (`/api/info`, Info.plist, spec, manifest; Dev 2 bumps web, iOS and Android), `git tag v0.2.0 && git push origin v0.2.0` (with the human's OK), then `gh release view v0.2.0 --json assets --jq '.assets[].name'`. Release whatever is green; list the rest as not shipped.

## 7. Sync points with Developer 2

Each is pass or fail. Before each one: run the merge steps in section 8, then the sync test. Report the result to the human in three lines: pass or fail, what failed, what you do next. If you start late, run missed syncs in order as soon as their milestones are merged (section 1). The exact commands for every sync are the code blocks under the sync table in `docs/PLAN.md` section 6; the ones you run most are repeated here.

| When | Sync | Your pass test | On fail |
|---|---|---|---|
| Sat 4:30 PM | 1. Contract smoke (M2, M3) | `smoke.py` PASS for info (`contract: 2`), qr, lessons, assets MIME (camera checks may FAIL until M4); unit tests pass; Dev 2's web build and `e2e/real-server.mjs` pass against your hub with a looping replay | You fix the hub before anything else |
| Sat 6:00 PM | Gemini gate | 20 calls, p50 2.0 s or less, limits written down | Wider gate, or one yes plus local |
| Sat 6:30 PM | 2. Live loop, iPhone app, camera assertions | `smoke.py` all PASS on the mock hub (replay hello, `state.camera.name` is `Replay: norm.mp4`, `advance` reason `camera`); `watch` shows `camera.platform: "ios"`, one `advance` reason `camera`, phone Next gives `advance` reason `button` | You fix M4 first; Dev 2 switches to capture.html |
| Sat 8:00 PM | 3. Glasses gate, drop check | 60 s of glasses frames, no gap over 5 s, `camera.source: "glasses"`, one camera advance; M9 green or M7 shrinks | Glasses leave the demo |
| Sat 10:00 PM | 4. Mac app | Frozen `.app` starts headless and passes smoke | Demo runs from source |
| Sun 12:00 AM | 5. Midnight full run | Android: `camera.platform: "android"` when a phone exists, else the CI APK, labeled; real Gemini fold to done; planted skipped flip gives `mistake` with `kind: "behind"`; internet down with LAN up gives `check_offline: true` and the lesson still finishes; local-mode clean replay reaches done with `smoke.py watch --press-next-on-manual 3`, every camera step advanced with reason `camera` | Stop SHOULD work; fix the loop |
| Sun 2:00 AM | 6. CI green (you alone, report in writing) | Latest `main` run green on web, hub-test, hub-mac, hub-win, android, ios | A red platform is dropped from the claim; hub-win red means "Windows: not shipped" |
| Sun 6:00 AM | 7. Contract freeze | Smoke passes on the source hub and the CI Mac artifact; tag set; freeze check prints nothing | Both humans approve any fix |
| Sun 8:00 AM | 8. Feature freeze, rehearsal | 20 tries under venue light, at least 18 with a `behind` mistake; per-try caught yes or no in `docs/DECISIONS_DEV1.md` | Step 5 manual, plant a different mistake |
| Sun 10:30 AM | Code freeze, release | Tag pushed, release has the Mac app, the Windows build, the APK | section 6 Release |

**Sync 1** (needs Google Chrome; base hub running):
```
.venv/bin/python scripts/smoke.py --base http://localhost:8000
.venv/bin/python -m server.test_server && .venv/bin/python -m server.test_check && .venv/bin/python -m server.tests
.venv/bin/python -m server.replay lessons/demo-v1/norm.mp4 --loop --select demo-v1 & REPLAY=$!
(cd web && npm run build && APP=http://localhost:8000 node e2e/real-server.mjs); kill $REPLAY
```
Before M2 is merged (the hub does not serve the dist yet), start `npx vite --port 5173 &` in `web/` instead and run `node e2e/real-server.mjs` without `APP`.

**Sync 5** (offline: the human turns off cellular data on the hotspot phone, LAN stays up; without a human use the two M6 hubs, invalid key then empty key; expect `check_offline: true` and the lesson finishing by local check or Next):
```
.venv/bin/python scripts/smoke.py watch --base http://<hub ip>:8000
HANDOVER_CHECK=local .venv/bin/python -m server.main &
scripts/demo_replay.sh recordings/fold-clean.mp4 &
.venv/bin/python scripts/smoke.py watch --press-next-on-manual 3
```

**Sync 6:**
```
gh run list --branch main --limit 1
gh run view <id> --json jobs --jq '.jobs[] | [.name, .conclusion]'
```

**Sync 7:**
```
git tag contract-freeze && git push origin contract-freeze
gh run download <id> -n hub-mac -D build/ci-mac
# unzip the .app under build/ci-mac and run the M11 headless smoke with that path
git diff contract-freeze -- docs/CONTRACT_V2.md | grep '^[+-][^+-]' | grep -v 'EXISTS\|NEW\|Revision'   # later: must print nothing
```

**Sync 8** (one `watch` for the whole rehearsal; a try passes with at least one `behind` mistake):
```
.venv/bin/python scripts/smoke.py watch | tee -a rehearsal.log
echo "TRY $N" >> rehearsal.log                                          # before try N, in a second shell
grep '"type": "mistake"' rehearsal.log | grep -c '"kind": "behind"'
awk '/^TRY /{t=$2} /"type": "mistake"/ && /"kind": "behind"/{c[t]=1} END{print length(c)}' rehearsal.log   # tries passed
```

Dev 1's human sleeps 2:30 to 6:00 AM. While they sleep, keep working on your branch only; merge nothing to main until Sync 7, except a fix for a red CI job you own, after the full merge gate.

## 8. Git

- Work in this clone on branch `dev1/hub` (create it from `main`). No worktrees. Dev 2 works in their own clone on `dev2/clients`. If both developers share one Mac, Dev 2 runs its hub on port 8100 in a separate clone; you keep port 8000.
- Small commits, message `Area: what changed` (for example `Hub: active camera and welcome`, `Teach: recut keeps step fields`, `CI: hub-win headless smoke`). **No attribution lines, no Co-Authored-By trailers, no tool footers, no emoji.** Commit identity is whatever `git config` already has; do not change it.
- **Merge gate** (all must pass, run after the load check; `server.tests` exists from M2):
  ```
  .venv/bin/python -m server.test_server
  .venv/bin/python -m server.test_check
  .venv/bin/python -m server.tests
  npm --prefix web run build
  .venv/bin/python scripts/smoke.py --base http://localhost:8000   # against a fresh mock hub
  git diff origin/main...HEAD | perl -CSD -ne 'print if /^\+.*[\x{2013}\x{2014}]/'   # must print nothing
  ```
- **Merge to main** at each sync point (or for a fix to a red CI job you own, after the full gate):
  ```
  git fetch origin && git rebase origin/main
  # rerun the merge gate
  git push --force-with-lease origin dev1/hub
  git push origin dev1/hub:main
  ```
  If the push to `main` is rejected, fetch, rebase, rerun the gate and push again. Force push only your own branch, **never `main`**.
- Never open a pull request unless the human asks. Never push tags other than `contract-freeze` and `v0.2.0`, and those only at their sync.
- Never commit `.env`, `certs/`, `recordings/`, `build/`, `dist/`, `web/dist/`, `.venv*`, logs, or anything with a key in it. Check `git diff --cached --stat` before every commit.

## 9. Quality bar

- Industry standard, calm, Apple-native. The Tk window looks like a small native utility, not a prototype.
- No fake data, no fake UI, no invented numbers. Every claim in a commit, doc or report matches code you ran. Measurements are written with how they were taken.
- **No em dashes or en dashes** anywhere: code strings, logs, docs, commit messages, reports. Use commas, colons, "to".
- Error messages are exact (copy them from the contract) and plain.
- Verify every build: run it, look at the output, read screenshots. Say plainly what is unverified ("Windows: built and smoke tested in CI, not tested by hand", "Android phone: not tested by Dev 1", "HDR tone mapping: only the fallback path ran").

## 10. Machine safety

- Before every heavy step (PyInstaller, full tests, web build, long replays, anything multi-minute):
  ```
  while [ "$(sysctl -n vm.loadavg | awk '{print int($2)}')" -gt "$(sysctl -n hw.ncpu)" ]; do sleep 30; done
  ```
- Delete only build output you created (`build/`, `dist/`, `.recut_tmp/`, temp test folders), and say what you removed. No automatic cleanup scripts. Never delete outside the repo.
- Tests and frozen-app runs use `HANDOVER_DATA` inside `build/` so the real `~/Library/Application Support/HandOver` is not touched. If you must test the default path once, say exactly what was created there.
- No paid services, no trials, no billing. Ask the human before large installs (anything system-wide, any Homebrew install, downloads over about 500 MB).
- Never touch the human's personal data, accounts, keychain, browser data, system settings, privacy permissions or network settings. Never take control of the screen (no clicking, no UI automation). One server instance on port 8000 at a time; stop what you start.

## 11. When blocked

Decide the safest honest option yourself, write it in `docs/DECISIONS_DEV1.md` (date and time, the question, the decision, why, how to undo), and keep going on the next item. Only stop for things only a human can do (key, repo, network switch, hardware, money); put those in the humans-only list and continue with other work meanwhile.

## 12. Final report

When everything is done or time runs out, reply with exactly these four parts, short and plain:

1. **Done**: each milestone id with one line.
2. **How verified**: the exact commands and their results (test counts, smoke PASS lines, CI run ids and job conclusions, measured latency).
3. **What is left**: unfinished or unverified items, each with the reason.
4. **Humans only**: one checklist of what only a person can do (for example: create the GitHub remote, record takes by their deadlines, switch to the hotspot, turn off cellular data for the offline test, OK mkcert, trust the unsigned app, grant Screen Recording or send a window screenshot, remove `.venv-old-homebrew`).
