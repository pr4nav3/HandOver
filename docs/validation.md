# Validation matrix

HandOver spans a local hub, several clients, model providers, optional analytics, and physical camera hardware. A green unit test in one layer is not evidence for every layer. Use the smallest honest evidence label below.

## Evidence levels

| Label | Meaning |
| --- | --- |
| Automated | Deterministic test or build; network access and paid model calls are disabled |
| Local integration | Multiple real local processes communicate through their production protocol, often with replay or mock checks |
| Manual provider | A configured external model is exercised with reviewed media and timing/error notes |
| Physical device | The named phone, camera, glasses, network, signing identity, and sustained session were actually tested |

Snapshots and synthetic fixtures prove rendering and state handling. They do not prove camera optics, Bluetooth behavior, provider accuracy, signing, app-store distribution, or production learner outcomes.

## Coverage matrix

| Capability | Automated evidence | Local integration | Required before a release claim |
| --- | --- | --- | --- |
| Lesson state, checking, advancement, replay, interruption | `server.test_engine`, `server.test_check` | hub + `server.replay` | representative real course and camera run |
| REST/WebSocket compatibility | `server.test_contract`, client decoding tests | hub + web/native client | mixed-version compatibility when supporting upgrades |
| Accounts, courses, profile aggregation | `server.test_library` | signed-in client against local hub | migration, access-control, and multi-user review |
| Teach, recut, captions, references | `server.test_server`, `server.test_teach` | upload a disposable recording to a local hub | reviewed output from intended recording conditions |
| Web experience | TypeScript production build | `scripts/e2e_demo.py` with hub and replay | target browser/camera/certificate matrix |
| Apple experience | macOS unit/UI/snapshot target | app against local hub | signed iPhone/iPad/Mac build on supported OS versions |
| Android experience | JVM tests, lint, debug build | app against local hub | physical supported Android phone and release build |
| Desktop experience | TypeScript tests/build, Rust tests | devserver or Tauri app against local hub | signed installers on each claimed OS |
| Meta wearable source | adapter and source-state tests | signed iPhone app registered a Ray-Ban Meta Gen 2 in Developer Mode and reached the live HandOver flow | repeatable sustained lessons across the claimed phone/glasses/firmware matrix |
| Privacy boundary | engine no-write test, analytics redaction tests | inspect disposable event log | deployment retention, provider, access, and deletion review |
| Databricks | local adapter/profile tests and local self-test | optional remote self-test | workspace permissions, schema, dashboard filters, retention |

## Commands

Run all automated work without model network access:

```sh
export HANDOVER_NO_NETWORK=1
```

### Hub and protocol

```sh
.venv/bin/python -m server.test_engine
.venv/bin/python -m server.test_contract
.venv/bin/python -m server.test_library
.venv/bin/python -m server.test_check
.venv/bin/python -m server.test_server
.venv/bin/python -m server.test_teach
.venv/bin/python -m server.test_config
.venv/bin/python -m server.databricks --selftest
```

The Databricks self-test stays local unless `--remote` is explicitly supplied. Do not use `--remote` in routine automated validation.

### Web and local end to end

```sh
npm --prefix web ci
npm --prefix web run build
.venv/bin/python scripts/e2e_demo.py
```

### Desktop

```sh
npm --prefix apps/desktop/ui ci
npm --prefix apps/desktop/ui test
npm --prefix apps/desktop/ui run build
cargo fmt --manifest-path apps/desktop/Cargo.toml --check
cargo clippy --manifest-path apps/desktop/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path apps/desktop/Cargo.toml
```

### Apple

Requires Xcode and XcodeGen:

```sh
cd apps/apple
xcodegen generate
xcodebuild -project HandOver.xcodeproj -scheme HandOver \
  -destination 'platform=macOS' test
```

This validates the macOS test host. A successful run is not a substitute for a signed physical iPhone or glasses session.

### Android

Requires JDK 17 and the Android SDK configured for the versions in the Gradle project:

```sh
cd apps/android
./gradlew :app:testDebugUnitTest :app:lintDebug :app:assembleDebug
```

## Release evidence checklist

- Record the commit, platform/OS, app or browser version, hub configuration, course, camera source, and test duration.
- Separate mock, replay, synthetic, and seed runs from human/device results.
- For model-backed checks, record provider/model, timeout/error behavior, and a reviewed set of passes and failures without retaining learner frames in analytics.
- For physical hardware, record the exact device model and connection path; do not generalize beyond what was run.
- Confirm manual Next/Back/End controls and checks-off behavior under disconnect, timeout, and sink failure.
- Review `logs/events.jsonl` or a disposable equivalent for forbidden fields before enabling external export.
- Re-read [privacy.md](privacy.md) for the deployment's provider and retention choices.

This matrix documents what each test can establish. It is not a permanent claim that every command passes on every commit.
