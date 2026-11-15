# scripts

Run everything from the repo root on the Mac. Python scripts use `.venv/bin/python`. Hub commands default to `http://localhost:8000`; pass `--base` for another port.

| Script | What it does | Example |
|---|---|---|
| [run_server.sh](run_server.sh) | Starts the hub: http on 8000, https on 8443 when certs exist. Prints the phone camera address. | `scripts/run_server.sh` |
| [run_server.ps1](run_server.ps1), [run_server.cmd](run_server.cmd) | Windows twins of run_server.sh (`.venv\Scripts\python.exe -m server.main`). Print the LAN and phone camera addresses. | `scripts\run_server.ps1` |
| [certs.sh](certs.sh) | Makes the HTTPS certs the iPhone camera page needs. Rerun after a hotspot IP change. (Pranav) | `scripts/certs.sh` |
| [make_demo_lesson.sh](make_demo_lesson.sh) | Rebuilds `lessons/demo-v1` from a generated test video, no Gemini. | `scripts/make_demo_lesson.sh` |
| [new_lesson.sh](new_lesson.sh) | Turns one or more takes into a lesson (normalize, join, find steps, cut), then prints the step table and the recut command. Never overwrites an existing id. `--mock` skips Gemini. | `scripts/new_lesson.sh --id fortune-teller-v1 --title "Fold a fortune teller" take1.mov take2.mov` |
| [smoke.py](smoke.py) `run` | End-to-end check against a running hub: lists lessons, selects one, streams its video as a camera, expects a camera advance within 30 s (`--advance-timeout`), presses Next on a manual step, expects done. PASS/FAIL table and exit code. Takes over the learn session. | `.venv/bin/python scripts/smoke.py run --lesson demo-v1` |
| [smoke.py](smoke.py) `watch` | One timestamped line per state, advance, mistake and error. Steps shown 1-based. `--log` appends every message as JSON lines. | `.venv/bin/python scripts/smoke.py watch --log scripts/out/watch.jsonl` |
| [rehearsal.py](rehearsal.py) | 8 AM counter. Shows `watch` lines; keys `t` start try, `c` caught, `m` missed, `u` undo, `q` quit. Tally against 18 of 20. | `.venv/bin/python scripts/rehearsal.py` |
| [gemini_gate.py](gemini_gate.py) | M1 gate: 20 timed Gemini checks on a lesson's frames, plus a compare pass. Writes `scripts/out/gemini-gate-<time>.md` with p50, p90, errors and the 6 PM verdict. Needs a key in `.env`; never prints it. | `.venv/bin/python scripts/gemini_gate.py --also-no` |
| [lesson_lint.py](lesson_lint.py) | Validates a lesson folder against CONTRACT.md. | see the file |
| [eval_checks.py](eval_checks.py) | Scores check questions on labeled frames. | see the file |
| [soak.py](soak.py) | Load-tests the hub with many cameras and viewers. | see the file |

The camera feed used by `smoke.py run` is `server/replay.py`, which you can also run by hand:

```
.venv/bin/python -m server.replay recordings/fold.mp4 --select fortune-teller-v1 --loop
```

It sends hello first (so the web app shows "Recording"), retries a lost connection, and stops on Ctrl+C. `--no-hello` sends frames only.

## Good to know

- `scripts/out/` holds reports and logs. It is not committed.
- Fix a step time: edit `start` and `end` in `lessons/<id>/lesson.json`, then `.venv/bin/python -m server.teach --recut lessons/<id>`. A bad timestamp leaves the old files in place.
- Gate verdict (docs/PLAN.md): median 2.0 s or less passes; 2.0 to 2.5 s widens the motion gate; over 2.5 s means one confident yes plus Next.
- Rehearsal bar: 18 of 20 planted flips caught, else step 5 becomes manual and the plant moves.
- Test a script without touching the demo hub: `HANDOVER_PORT=8040 HANDOVER_HTTPS_PORT=8041 HANDOVER_CHECK=mock HANDOVER_LESSONS=/tmp/lessons scripts/run_server.sh`, then pass `--base http://localhost:8040`.
