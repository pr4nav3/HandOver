# Operations: demo-day runbook

What to run on the Mac, in order, and what to do when something breaks.

Back to [server/README.md](../README.md).

## 1. Start the hub

```sh
scripts/run_server.sh
```

| Check | Expect |
|---|---|
| Log line | `lessons: <path>  check: gemini` (says `mock` if `HANDOVER_CHECK=mock` is set: unset it for the demo) |
| Phone line | `Phone camera page: https://<IP>:8443/capture` (only when certs exist) |
| Lessons | `curl -s http://localhost:8000/api/lessons` lists both lessons |

Learn screen today: `npm --prefix web run dev`, then `http://localhost:5173`. Serving the web app from the hub at `http://<IP>:8000/` (W1) is in progress.

## 2. Camera

```sh
scripts/certs.sh     # once per network; rerun if the Mac's IP changes
```

Open `https://<IP>:8443/capture` in iPhone Safari. The phone and Mac must be on the same network or hotspot. The mkcert root must be trusted on the phone once (the script prints the steps).

## 3. Replay a recording as the camera

```sh
.venv/bin/python -m server.replay recordings/fold.mp4 --select fortune-teller-v1
```

| Option | Default | Use |
|---|---|---|
| `--url` | `ws://localhost:8000/ws/camera` | Another hub |
| `--fps` | 1 | Frames per second sent |
| `--loop` | off | Repeat the file |
| `--start` | 0 | Start offset in seconds |
| `--select` | none | Select this lesson first; exits if the hub refuses |

It reconnects every 2 s if the hub drops. Today replay sends no `hello`, so the "Recording" banner does not show yet (in progress, CONTRACT 9). Until then, say out loud that it is a recording.

## 4. Smoke and watch

Coming in this branch. No smoke or watch script exists yet. Until then:

```sh
.venv/bin/python -m server.test_check && .venv/bin/python -m server.test_server
HANDOVER_CHECK=mock scripts/run_server.sh        # then replay any file against demo-v1
```

## 5. Fallback ladder

Drop one rung only when the one above fails. Next always works.

```mermaid
flowchart TD
  a["Glasses through the iPhone app<br/>(only if the 8 PM gate passed)"] -->|fails| b["iPhone app, phone camera"]
  b -->|fails| c["Safari /capture on the iPhone"]
  c -->|fails| d["server.replay of the clean fold<br/>with the Recording banner"]
  d -->|fails| e["Next button"]
```

The iPhone app lives in `ios/` (Pranav's lane) and is not in this branch.

## 6. Breaker and Gemini down

The breaker (in progress) turns checks off after 3 errors or timeouts in a row, or any 429 (rate limit), for 30 s, then tries one call. The UI shows "Checks off, use Next". This is expected behavior, not a crash.

If Gemini is down or slow:

1. Keep going with Next. Say "the camera check is off, so I'll press Next."
2. Swap to the second key in `.env`, then restart the hub. The hub reads the key once and keeps it until restart.
3. Do not switch to `HANDOVER_CHECK=mock` in front of judges. Mock passes on a timer, not on what the camera sees.

Until the breaker lands, a failing Gemini shows as `last_check: unsure, 0` on every check, and the log says `check failed` or `check timed out`.

## 7. 8 AM rehearsal count

From docs/PLAN.md: 20 folds under venue light.

| Count | Rule |
|---|---|
| Planted skipped flip caught in 18 or more of 20 | Keep the catch in the demo |
| Fewer than 18 | Step 5 becomes manual and the plant moves |

Also log camera-verified steps, manual steps, false passes and false alarms. Results: not measured yet.

## 8. Privacy

Camera frames are held in memory only; the hub has no code that writes them to disk. A test that proves it (M15) is in progress.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `Phone camera page` line at start | No certs | `scripts/certs.sh` |
| Safari will not open the camera | Page opened over http, or root not trusted | Use `https://...:8443/capture`; trust the mkcert root on the phone |
| Capture page worked yesterday, not today | Mac IP changed | Rerun `scripts/certs.sh`, restart the hub |
| Hub exits at start | Port 8000 or 8443 in use (another hub) | `lsof -nP -iTCP:8000 -sTCP:LISTEN`, stop that process |
| Steps never advance by camera | Manual step, no camera connected, or no lesson selected | Check `status` and `camera_connected` in state; select the lesson |
| Log: `reference frame missing` | `frames/NN.jpg` gone | Recut the lesson |
| `last_check` is `unsure`, 0 every time | Gemini failing: key, network, model id | Read the `check failed` log line; see section 6 |
| Log: `no Gemini key` | No key in env or `.env` | Add `GEMINI_API_KEY` to `.env`, restart |
| Status stays `checking` | Calls take over 1.5 s | Run `server.check --time`; see the 6 PM gate in [checks.md](checks.md#7-the-6-pm-gate) |
| Advances too early | Question too loose, or debounce too low | Tighten `check_question`, raise `HANDOVER_DEBOUNCE_N` |
| UI shows old clips after a recut | Recut ran from the command line, hub not told | Re-select the lesson, or recut with `POST /api/lessons/<id>/recut` |
| `common_mistake` gone after a recut | Today's recut drops extra fields | Re-add it; see [teach.md](teach.md#recut-rule) |
| Replay crashes with `FileNotFoundError: 'ffmpeg'` | Replay looks only on PATH (teach also checks Homebrew) | `export PATH=/opt/homebrew/bin:$PATH` |
| Replay: `select_lesson failed: lesson not found` | Wrong id | `curl -s http://localhost:8000/api/lessons` |
| Teach job error: `not ACTIVE after 300 s` | Gemini still processing the upload | Retry; try a shorter take |
| Teach job error: `ffmpeg not found on PATH` | ffmpeg missing | `brew install ffmpeg` |
