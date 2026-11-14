# Build spec, lean MVP: expert records once, learner sees the right clip at the right moment

Saturday Nov 14, 2026. Hackathon (MadHacks, Madison WI). Submission and judging Sunday Nov 15 around noon. Team of developers; this repo is being split between 2 developers. Nine validator research notes were referenced (research_notes/MadHacks 2026 glasses knowledge transfer/) but are NOT available on this machine. None of the spec's code had been run when written.

## 1. The core, and nothing else until it works
1. Expert records one take on Ray-Ban Meta glasses, narrating while doing the task.
2. Cut into steps. One Gemini call finds step boundaries and the transcript; ffmpeg cuts a clip per step; captions come from the transcript as WebVTT. The expert's clip, in their voice, is the instruction.
3. Learn mode. The learner's camera streams to the laptop at 1 frame/s. The screen shows the live view and the expert's clip for the current step, looping, captioned. A vision check compares the live frame to the last frame of that clip; when it passes, the next clip plays. Next by button or by saying "next" does the same.

## 2. The two tasks
Live judge task: origami fortune teller (cootie catcher). 8 steps, 90 to 150 s for a novice (est), camera pointed down at a dark mat. 6 of 8 steps auto-advance by camera; the two crease-only steps (fold-and-unfold) pass on "next" or a short timer. Paper: duo-color kami, different solid color each side, 20 to 25 cm, matte, bright contrast, on black foam board or dark felt. Backup model: paper cup.
Steps and visible state: (1) square flat, color A up, high; (2) fold diagonal, large triangle, high; (3) unfold, fold other diagonal, unfold, X crease, low so manual; (4) four corners to center, smaller square with four seams, high; (5) flip, smooth face, medium-high; (6) four corners to center again, half-size square, high; (7) fold in half both ways and unfold, low so manual or merged into 8; (8) flip, fingers under flaps, push to center, 3D four-pointed shape, high. Main failure point: skipped or doubled flip at step 5, which is the moment the check visibly catches something.

Showcase task, pre-recorded: bike front wheel quick-release removal and reinstall. 9 steps, about 2 minutes. Steps: open the rim-brake quick release; flip the QR lever open; unscrew the nut 3 to 4 turns past the retention tabs; drop the wheel out; lower the fork onto the axle (guide rotor into caliper if disc); snug the nut until the lever resists halfway (felt, so manual); close the lever flat along the blade; close the brake release; spin and squeeze.

## 3. Teach pipeline
- Glasses footage: Gen 2 records vertical, 3K30, 1440p30 or 1200p60, HEVC on iOS, clips capped at 3 minutes. Normalize every input: `ffmpeg -i in.mov -vf "scale=-2:1080" -r 30 -fps_mode cfr -c:v libx264 -crf 20 -preset veryfast -c:a aac -movflags +faststart out.mp4`. Concat demuxer for multi-clip takes. HEVC will not play in browsers on Windows, so normalizing is required.
- One Gemini call. google-genai 3.3: pass `HttpOptions(api_version="v1beta")`. files.upload, poll files.get until ACTIVE, generate_content with `types.Part(file_data=..., video_metadata=types.VideoMetadata(fps=2))`, response_mime_type application/json, response_json_schema=Model.model_json_schema(). Keep schema flat. Model gemini-3.8-flash; gemini-3.1-pro-preview if boundaries are poor.
- Prompt returns steps[] (start/end MM:SS, 4 to 8 word title, one yes/no visible-state question or "manual", prerequisites) plus transcript segments. Narration is the primary boundary signal; video confirms.
- Cut with re-encode per step; last frame per clip as reference; WebVTT per clip rebased to clip start. Transcript fallback faster-whisper 1.2.1 CPU int8.
- Output lessons/<id>/lesson.json, norm.mp4, clips/NN.mp4, captions/NN.vtt, frames/NN.jpg. No database. Editor = fix timestamps in lesson.json and re-cut.

## 4. Learn pipeline
- Capture fallback (keep regardless): iPhone on head strap or chest mount, Safari capture.html served by FastAPI over HTTPS/WSS on 8443 with mkcert certs for the hotspot IP; getUserMedia rear camera 1280x720, JPEG at 1 fps over WebSocket. Backup: cloudflared quick tunnel.
- Capture primary: Ray-Ban Meta glasses via Meta Wearables Device Access Toolkit iOS 1.0.1 (Xcode 26.4+, iOS 17.2+, Meta AI app v254+, Developer Mode on). API: Wearables.shared.createSession(deviceSelector:), deviceSession.addCamera(config:), camera.stream.videoFramePublisher.listen { $0.makeUIImage() }. Frame rate 2 at .low (360x640), codec .raw, throttle 1 fps, JPEG 0.6, URLSessionWebSocketTask to ws://<laptop IP>:8000/ws/camera. Keep app foreground. Hard go/no-go 8 PM.
- Server: FastAPI. /ws/camera gets binary JPEGs; one check in flight, keep latest frame. Check: ref frame + live frame + question to gemini-3.5-flash-lite, low media resolution, minimal thinking, JSON {done: yes|no|unsure, confidence}. Debounce 2 consecutive yes at >= 0.8; never advance on unsure; manual steps only by Next. Broadcast on /ws/ui.
- Front end: Vite + React + TS, proxy so same-origin. Live frames as img blob swap. video loop with captions track, ::cue styling. Chrome Web Speech for "next"/"back". Chime via Web Audio.
- Replay mode: script feeds a recorded MP4 to /ws/camera at 1 fps.

## 5. Screens
Learn: dark, left 60% live view, right 40% expert clip looping with captions, step title and "Step 4 of 8", thin segmented progress bar, check badge (grey watching, green verified with chime), big Next button "or say next".
Teach: file input, spinner, normalized video with colored step timeline and clip thumbnails; click plays a clip.

## 8. Pitch (4 min)
Teach screen shows the bike lesson made from one take. Then a judge folds the fortune teller while clips advance as the camera sees each fold. "Every task an expert does once becomes a lesson that watches the next person." Competitors named: DeepSight, Retrocausal (they stop at a document, or need fixed cameras and labeled cycles).

## 9. Later features, in order
1. Spoken skip alert from prerequisites. 2. "Why" plays longer narration. 3. End screen with stats vs expert. 4. Step card with callouts and quote. 5. Review editor. 6. Printed one-page guide. 7. End-state check vs expert final frame. 8. Hand ghost with MediaPipe HandLandmarker.
Never this weekend (original spec): all-day capture, task discovery, multi-expert merge, accounts, cloud deploy, chat box.

## 10. Risks
Glasses stream fails -> chest phone. Check latency > 2 s -> longer interval, raise debounce. Misfires under hall light -> brighter paper, darker mat, manual step, Next always works. Bad boundary -> fix timestamps, re-cut. Hotspot or API down -> replay mode and backup recording.

## 11. Unverified
Check latency (1 to 3 s estimate). Gen 2 pixel dimensions and Meta AI app export quality. Developer Mode round trip. Free-tier rate limits. All check reliabilities.
