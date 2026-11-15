# AI pipeline research (2026-11-14)

## Answer
Keep gemini-3.5-flash-lite two-image check. Add: motion gate, local OpenCV fallback with circuit breaker, pre-generated translations and TTS. No Live API as primary. Measure limits and latency first.

## 1. Flash-lite check
- Stable, free tier (verified aistudio.google.com/docs/models, /pricing). Low media resolution ~280 tokens per image, ~700 input tokens per call (verified /docs/media-resolution). Limits per project, daily reset midnight Pacific (verified /docs/rate-limits).
- Free-tier RPM/RPD not published; see aistudio.google.com/rate-limit. Third-party figures (10/500 or 30/1500) unverified.
- Ungated 1 call per 1 to 2 s = 30 to 60 RPM, 1000+ per day of testing: breaks likely limits. Gating is required.
- Latency guess 0.8 to 2 s (inferred). Measure with `python -m server.check --time`.
- Fix in check.py: timeout 8 s to 3 s; circuit breaker after 3 errors or any 429: local only for 30 s, show "Offline check" badge.
- Motion gate: 160x90 gray, 5x5 blur, absdiff vs previous; motion = fraction of pixels with diff > 25. Hold while > 2%. Call only when < 0.5% for 2 frames and differs > 3% from last checked frame. Heartbeat call every 6 s. Expect 3 to 5x fewer calls.
- Test on a different Google Cloud project key than the one used live. Paid billing costs money.

## 2. Live API
- gemini-3.8-live, free tier; JPEG max 1 fps, 16 kHz PCM; `client.aio.live.connect`, `send_realtime_input` (verified docs and SDK live.py). Audio+video session ends after 2 min without context compression.
- Verdict: trap as primary. Optional push-to-talk "Ask" later.

## 3. Local fallback (OpenCV)
- opencv-python-headless 5.0.0.93 wheels for macOS arm64/x86_64 and Windows amd64 (no Windows arm64). mediapipe 1.2.3 macOS arm64, Windows x64/arm64.
- Algorithm: HSV; paper mask via Otsu on V (bright paper, black mat), largest contour. Features: area ratio, approxPolyDP corners (0.02 perimeter), solidity, HS histogram 36x8 in mask, Canny edge density inside mask eroded 5 px.
- Score vs every step reference: 0.5 histogram CORREL + 0.3 (1 - matchShapes I1, clipped) + 0.2 edge density similarity.
- Thresholds to tune: current step best with lead >= 0.1; hist corr >= 0.75; area ratio 0.7 to 1.4 (normalize by reference contour); 3 consecutive to advance offline.
- Rejected: SSIM (viewpoint), ORB (plain paper), CLIP (coarse). MediaPipe hands only as a gate (skip check if hand covers > 30% of mask).
- Combine: Gemini yes x2 and local not strongly naming another step (lead > 0.2) => advance. Gemini down => local only, 3 in a row. Next always works.

## 4. Extraction and mistakes
- Add `ref_time` per step (finished state visible, hands clear) and grab that frame instead of the clip's last frame.
- Add `common_mistake`, `mistake_question` per step.
- After cut: if local feature distance between adjacent references is small, mark step manual.
- Mistake detection: refs k-1, k, k+1 + live labeled A to C, `{"match":"A|B|C|none","confidence"}`, only after 5 s of settled "no". Still matching step 4 on step 5 => "Flip it over."

## 5. Languages
- Translate cues with one flash-lite call per language at build time; captions/NN.<lang>.vtt.
- TTS: gemini-3.8-flash-lite-tts, 100+ languages, 24 kHz WAV, via client.interactions.create (SDK has it; not run). Pre-generate per step.
- speechSynthesis backup. Chrome speech recognition needs network; keep Next button and keyboard/clicker.

## Measure first
1. Project limits at aistudio.google.com/rate-limit. 2. Latency over 20 calls on hotspot. 3. Per-step yes/no accuracy on recorded frames. 4. Local feature separation between references. 5. Calls per run with gate. 6. TTS via interactions in SDK 3.3.
