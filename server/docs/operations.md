# Operations: demo-day runbook

What to run on the Mac, in order, and what to do when something breaks.

Back to [server/README.md](../README.md).

## Demo day on Windows

PowerShell in the repo root. Never set `HANDOVER_CHECK=mock` for the real demo.

| # | Step | Command or action | Expect |
|---|---|---|---|
| 1 | Stop stale hubs | `Get-NetTCPConnection -State Listen -LocalPort 8000,8443 -ErrorAction SilentlyContinue \| select LocalPort,OwningProcess`, then `Stop-Process -Id <PID>` for each | Nothing listens on 8000 or 8443. `run_server.ps1` refuses to start and names the PID otherwise |
| 2 | Preflight | `.venv\Scripts\python.exe scripts\preflight.py` | `READY` or `READY WITH WARNINGS`. The `Ports` rows name any PID still on 8000 or 8443; `cert IP` must cover the laptop IP |
| 3 | Start the hub | `scripts\run_server.ps1` | `Hub: ... LAN: http://<IP>:8000/`, `Phone camera page: https://<IP>:8443/capture`, then `check: claude claude-haiku-5-5`. Ctrl+C stops it cleanly |
| 4 | Open the screens | Laptop: `http://localhost:8000/` (the Learn screen); a second screen or projector: `http://<IP>:8000/` | Lessons list loads; the live pane shows "Connect a camera" with a QR code |
| 5 | Pair the phone | Same Wi-Fi or hotspot as the laptop. Scan the QR code (or open `https://<IP>:8443/capture` in Safari), allow the camera. The HandOver app: enter `http://<IP>:8000` (the hub logs it as `pair a phone: ...`) | The top bar names the camera; frames show on the big screen |
| 6 | Replay fallback | `.venv\Scripts\python.exe -m server.replay lessons\fortune-teller-v1\norm.mp4 --select fortune-teller-v1 --loop` (or a clean fold recording) | The "Recording" banner shows; steps advance from the file |
| 7 | Breaker fallback | Rehearse once: `$env:ANTHROPIC_API_KEY = "sk-ant-invalid"; scripts\run_server.ps1` (the 401 is not billed) | "Checks off, use Next" with reason `no_key`; Next still moves every step. Remove the variable and restart before judging |
| 8 | Last look | `.venv\Scripts\python.exe -m server.spend` | Today and the total are well under $20 and $50 |

Phone pairing, once per laptop and network:

- Trust the mkcert root on the iPhone: `mkcert -CAROOT` shows the folder; AirDrop or mail `rootCA.pem` to the phone, install the profile, then Settings, General, About, Certificate Trust Settings, turn it on.
- The certs must name the laptop IP: rerun `mkcert -cert-file certs/cert.pem -key-file certs/key.pem <laptop IP> localhost 127.0.0.1` after an IP change, then restart the hub.
- Windows Defender Firewall must allow Python on the network in use. A phone hotspot is often a Public network: allow `.venv\Scripts\python.exe` on Public too, or mark the network Private. Test from the phone: `http://<IP>:8000/` must load.

## 1. Start the hub

```sh
scripts/run_server.sh
```

| Check | Expect |
|---|---|
| Log line | `lessons: <path>  check: claude claude-haiku-5-5` or `check: gemini <model>` (says `mock` if `HANDOVER_CHECK=mock` is set: unset it for the demo) |
| Phone line | `Phone camera page: https://<IP>:8443/capture` (only when certs exist) |
| Lessons | `curl -s http://localhost:8000/api/lessons` lists both lessons |

Learn screen: the hub serves the built web app at `http://<IP>:8000/` when `web/dist` exists (`npm --prefix web run build`); otherwise `npm --prefix web run dev`, then `http://localhost:5173`.

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

It reconnects every 2 s if the hub drops. It sends `hello` with `source: "file"` first, so the web app shows the "Recording" banner.

## 4. Smoke and watch

```sh
.venv/bin/python scripts/smoke.py run --lesson demo-v1     # PASS/FAIL table against a running hub
.venv/bin/python scripts/smoke.py watch                    # one line per state, advance, mistake, error
.venv/bin/python scripts/e2e_demo.py                       # full web flow in Chrome against a mock hub
```

`demo-v1` is a synthetic test pattern (colored bars), not a real lesson.

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

## 6. Breaker and the provider down

The breaker turns checks off after 3 errors or timeouts in a row, any 429 (rate limit), or a reached Claude budget cap, for 30 s, then tries one call. The UI shows "Checks off, use Next". This is expected behavior, not a crash. `python -m server.spend` shows what Claude has cost today and in total against the $20 per day and $50 total caps.

If the provider is down or slow:

1. Keep going with Next. Say "the camera check is off, so I'll press Next."
2. Switch provider: set `HANDOVER_CHECK_PROVIDER=gemini` (or `claude`) and restart the hub.
3. Do not switch to `HANDOVER_CHECK=mock` in front of judges. Mock passes on a timer, not on what the camera sees.

The log says `check failed` or `check timed out` for each failed call.

## 7. 8 AM rehearsal count

From docs/PLAN.md: 20 folds under venue light.

| Count | Rule |
|---|---|
| Planted skipped flip caught in 18 or more of 20 | Keep the catch in the demo |
| Fewer than 18 | Step 5 becomes manual and the plant moves |

Also log camera-verified steps, manual steps, false passes and false alarms. Results: not measured yet.

## 8. Privacy

Frames go from the hub to the AI provider (Claude or Gemini, whichever `state.check_mode` names) for each check (with `HANDOVER_UNDERSTAND=1`, also to Claude for the understanding call) and are never written to disk. The test `test_privacy_learn_frames_never_touch_disk` in `server/test_engine.py` runs a full mock session with every file write blocked under the repo and the lessons folder, and fails on any written frame. Learn events (metadata, no images) go to `logs/events.jsonl` and, with credentials, to Databricks.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No `Phone camera page` line at start | No certs | `scripts/certs.sh` |
| Safari will not open the camera | Page opened over http, or root not trusted | Use `https://...:8443/capture`; trust the mkcert root on the phone |
| Capture page worked yesterday, not today | Mac IP changed | Rerun `scripts/certs.sh`, restart the hub |
| Hub exits at start | Port 8000 or 8443 in use (another hub) | The hub logs `port 8000 is already in use`. Mac: `lsof -nP -iTCP:8000 -sTCP:LISTEN`; Windows: `netstat -ano \| findstr :8000` (or preflight's `Ports` rows), then stop that PID |
| Steps never advance by camera | Manual step, no camera connected, or no lesson selected | Check `status` and `camera_connected` in state; select the lesson |
| Log: `reference frame missing` | `frames/NN.jpg` gone | Recut the lesson |
| `last_check` is `unsure`, 0 every time | Provider failing: key, network, model id, budget | Read the `check failed` log line; see section 6 |
| Checks off with reason `no_key` | No key for the active provider | Add `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` to `.env`, restart |
| Checks off with reason `budget` | A Claude cap is reached | `python -m server.spend`; switch to Gemini or raise the cap on purpose |
| Status stays `checking` | Calls take over 1.5 s | Run `server.check --time`; see [checks.md](checks.md#7-timing-a-provider) |
| Advances too early | Question too loose, or debounce too low | Tighten `check_question`, raise `HANDOVER_DEBOUNCE_N` |
| UI shows old clips after a recut | Recut ran from the command line, hub not told | Re-select the lesson, or recut with `POST /api/lessons/<id>/recut` |
| Replay crashes with `FileNotFoundError: 'ffmpeg'` | Replay looks only on PATH (teach also checks Homebrew) | `export PATH=/opt/homebrew/bin:$PATH` |
| Replay: `select_lesson failed: lesson not found` | Wrong id | `curl -s http://localhost:8000/api/lessons` |
| Teach job error: `not ACTIVE after 300 s` | Gemini still processing the upload | Retry; try a shorter take |
| Teach job error: `ffmpeg not found on PATH` | ffmpeg missing | `brew install ffmpeg` |
