# HandOver

An expert records a task once on Meta glasses while narrating. HandOver cuts that take into captioned step clips and plays the expert's own clip for each step, moving on only when the learner's camera shows the step is done.

Where to read next:

- `docs/project.md`: what HandOver does and how it is built
- `CONTRACT.md`: the wire contract between the hub and every client
- `server/README.md`: the hub, its pipeline and its tests
- `docs/privacy.md`: what happens to camera frames
- `docs/voice.md`: the narration voice and the app's spoken cues

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

## Run (Windows)
PowerShell, from the repo root. ffmpeg must be on PATH (`winget install Gyan.FFmpeg`).
```
uv venv --python 3.12 .venv            # or: py -3.12 -m venv .venv
.venv\Scripts\pip install -r server\requirements.lock
copy .env.example .env                 # add ANTHROPIC_API_KEY and/or GEMINI_API_KEY
winget install FiloSottile.mkcert      # or: choco install mkcert   (once)
mkcert -install                        # once; trusts the mkcert root on this PC
mkcert -cert-file certs/cert.pem -key-file certs/key.pem <laptop IP> localhost 127.0.0.1
npm --prefix web ci; npm --prefix web run build
scripts\run_server.ps1                 # or scripts\run_server.cmd; http :8000, https :8443
```
With `web/dist` built, the hub serves the laptop UI itself at `http://<laptop IP>:8000/` (no Vite needed). The runner prints the LAN address and the phone camera page. Rerun the `mkcert -cert-file` line when the laptop IP changes; for the iPhone, trust the root from `mkcert -CAROOT` as `scripts/certs.sh` explains.
