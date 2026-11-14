# Team rules (read this first; it is one page)

What we are building, in one line: an expert records a task once on Meta glasses; AI cuts it into captioned step clips; a learner wearing a camera sees the right clip at the right moment because the camera confirms each step is done.

Wire contract: CONTRACT.md. Times, gates and drop order: docs/PLAN.md. This page is only how we work together.

## Decisions
- The Mac is the one machine: the server is developed, locked and demoed on it. Everyone else works on branches and pushes through the terminal.
- Native iOS app for the glasses live stream: yes, time-boxed to the 8 PM gate. Safari /capture is the fallback and stays working no matter what.
- Live demo: origami fortune teller, judge folds. Showcase: bike front wheel quick-release, pre-recorded.
- Databricks: data layer only (tables, Volume, dashboard, Genie). Never in the live loop. Nobody starts it until the live fold works end to end.
- Lean first. Anything not needed for the judge to fold with the camera advancing clips waits until that runs.

## Own a folder, not a feature
Edit only your folders. To touch anyone else's, message the group first and wait for an OK. Fill in names at kickoff.

```
TEAM_RULES.md, docs/PLAN.md, CONTRACT.md   lead; contract changes are announced in the group before editing
server/teach.py, scripts/make_demo_lesson.sh, lessons/   ______  (teach pipeline, both finished lessons committed)
server/static/capture.html, scripts/certs.sh, ios/        ______  (phone capture, HTTPS certs, glasses app)
server/check.py, server/main.py, server/replay.py          ______  (check loop, websockets, state; integrator from 6:30 PM)
web/                                                       ______  (learn and teach screens)
server/databricks.py (new)                                 whoever is free after the live loop runs
```
Shared files nobody owns alone: server/requirements.lock, web/package-lock.json, .gitignore. Change them on the Mac, say so in the group.

## Git
- main always runs. Nobody pushes to main directly.
- Work on your own branch, any name, short-lived. Pull main, run the app once, merge, push, delete the branch. At least every two hours, more often from 6:30 PM.
- Commit small and often with real messages. MadHacks cross-checks that every member commits throughout the 24 hours.
- No force push. No rebasing a branch someone else pulled. No stash games. Conflict: the two owners fix it together on the branch, then merge.
- Install Python packages from server/requirements.lock (frozen on the Mac). Need a package? Add it on the Mac, re-freeze, commit. Reason: google-genai shipped a breaking release on Nov 12 and FastAPI released today.
- Committed: code, lockfiles, finished lesson folders, .env.example. Not committed: raw footage, node_modules, venvs, .env, certs (already in .gitignore).
- From 6:30 PM one person integrates: merges capture, check and web to main and runs the live loop. Others keep working on branches.
- After the freeze in docs/PLAN.md, only fixes go to main, each pulled and run on the Mac by the person demoing before it is called done.

## First hour, before building on assumptions
1. Time 20 real two-image Gemini checks on static frames (server/check.py --time). Sets the frame interval and debounce.
2. Normalize one glasses clip; confirm it plays in Chrome on the Mac and cuts cleanly.
3. Developer Mode on; the toolkit CameraAccess sample builds in Xcode. If registration is slow, we know now.
4. Freeze the Python environment on the Mac and commit the lock.
