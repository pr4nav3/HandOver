# HandOver

An expert records a task once on Meta glasses while narrating. HandOver cuts that take into captioned step clips and plays the expert's own clip for each step, moving on only when the learner's camera shows the step is done.

Read in this order: `TEAM_RULES.md` (how we work), `docs/PLAN.md` (what and when), `CONTRACT.md` (wire formats), `docs/SCOPE.md` (what is in and out).

## Run (Mac)
```
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r server/requirements.lock
cp .env.example .env   # add GEMINI_API_KEY
npm --prefix web ci
scripts/certs.sh        # once; HTTPS for the phone camera page
scripts/run_server.sh   # http :8000, https :8443
npm --prefix web run dev   # laptop UI at http://localhost:5173 during development
```
Phone camera page: `https://<laptop IP>:8443/capture`. Replay a recording as the camera: `.venv/bin/python -m server.replay recordings/fold.mp4 --select fortune-teller-v1`.
