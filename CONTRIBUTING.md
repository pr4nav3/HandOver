# Contributing to HandOver

Thank you for helping make hands-on instruction easier to build and use. This guide gets a change running locally, points to the right test slice, and makes the project's evidence standards explicit.

## Start with an offline hub

Install Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js 20+, npm, and ffmpeg. From the repository root:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r server/requirements.lock
npm --prefix web ci
npm --prefix web run build
HANDOVER_CHECK=mock HANDOVER_NO_NETWORK=1 scripts/run_server.sh
```

Open <http://localhost:8000>. The checked-in lessons are enough to develop the player without uploading media. A replay can stand in for a camera:

```sh
.venv/bin/python -m server.replay lessons/fortune-teller-v2/norm.mp4 \
  --select fortune-teller-v2
```

`HANDOVER_NO_NETWORK=1` prevents model clients from being created even if your shell or `.env` contains a key. Use it for tests and deterministic UI work.

### Windows

In PowerShell, with Python 3.12, Node.js 20+, npm, and ffmpeg on `PATH`:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\pip install -r server\requirements.lock
npm --prefix web ci
npm --prefix web run build
$env:HANDOVER_CHECK = "mock"
$env:HANDOVER_NO_NETWORK = "1"
scripts\run_server.ps1
```

The built web app is served by the hub at `http://localhost:8000`. A browser phone camera also needs a trusted HTTPS certificate; see `scripts/certs.sh` for the equivalent macOS flow and `scripts/run_server.ps1` for the Windows certificate layout.

## Choose the right surface

| Area | Start here | Main boundary |
| --- | --- | --- |
| Hub and learn engine | [server/README.md](server/README.md) | `server/main.py`, check/gate modules, REST/WebSocket contract |
| Lesson creation | [server/docs/teach.md](server/docs/teach.md) | expert media in, portable lesson folder out |
| Web client | `web/src/` | browser UI and `/capture` fallback |
| Apple client | `apps/apple/project.yml` | SwiftUI client for iPhone, iPad, and Mac |
| Android client | `apps/android/` | Compose client and phone/wearable camera source |
| Desktop client | [apps/desktop/README.md](apps/desktop/README.md) | Tauri UI over a Rust protocol core |
| Accounts and courses | [server/docs/library.md](server/docs/library.md) | local hub identity, organizations, editing, progress |
| Analytics | [docs/analytics.md](docs/analytics.md) | local metadata first; optional Databricks export |

Before changing a message, endpoint, lesson field, or compatibility rule, read [CONTRACT.md](CONTRACT.md). Additive fields must remain optional for readers; behavior changes require a contract revision and tests on both sides of the boundary.

## Test the slice you changed

All server tests run as Python modules and should be forced offline:

```sh
export HANDOVER_NO_NETWORK=1
.venv/bin/python -m server.test_engine
.venv/bin/python -m server.test_contract
.venv/bin/python -m server.test_library
.venv/bin/python -m server.test_config
```

Client and end-to-end commands are listed in [docs/validation.md](docs/validation.md). Run focused tests while iterating, then the relevant platform row before handing off a change. Model-backed, signed-device, and physical-glasses tests are manual evidence and must never be implied by a mock or snapshot result.

## Project rules

- Keep `HANDOVER_NO_NETWORK=1` on automated tests. No test should make a paid provider call.
- Never commit `.env`, tokens, local certificates, learner event logs, uploads, or unreviewed real-person media.
- Learner camera frames are memory-only. Do not add frame, audio, IP, camera-name, auth-token, or stable-device fields to event payloads.
- Keep Databricks and other optional sinks outside the live lesson path. A slow or failed sink must not delay checks or advancement.
- Label synthetic, replay, seed, and mock data in UI, screenshots, analytics, and documentation.
- Preserve a manual learner fallback when checks are offline or uncertain.
- Add bounds and documentation for new `HANDOVER_*` settings in `server/config.py`.
- Avoid drive-by formatting or generated-file churn outside the area you changed.

## Before opening a change

- The relevant validation row passes locally.
- `git diff --check` is clean.
- New links and image paths resolve from the Markdown file that contains them.
- Protocol and configuration changes update their source-of-truth docs.
- Screenshots state whether they use demo data and do not claim unperformed hardware validation.
- Privacy, failure, empty, and offline states have been considered.

The complete documentation map is in [docs/README.md](docs/README.md).
