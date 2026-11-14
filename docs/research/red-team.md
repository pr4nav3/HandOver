HandOver red team report (ranked by severity, attack then mitigation)

Sources checked today: docs/SPEC.md, CONTRACT.md, server/check.py, server/main.py, server/teach.py, web/src/useVoice.ts, server/static/capture.html, lessons/demo-v1/lesson.json. I edited no files.

**S1. The scope is the biggest risk to the demo.** Four native apps plus web, with every OS working with every other, is far more than 2 devs can finish before judging.
- Fact: madhacks.io lists judging 1:00 to 2:30 PM Sunday at Morgridge Hall, not noon (verified, https://madhacks.io). No judging criteria are published there.
- Mitigation: make "every platform" mean one web client served by the laptop. Any phone browser (iOS Safari, Android Chrome) can be the camera through /capture. Any laptop browser (Mac, Windows, Linux) can be the learn screen. The same Python server runs on Mac or Windows. Only the Meta glasses app is truly native (iOS, and per Meta also Android 10+, verified https://wearables.developer.meta.com/docs/develop/). Desktop "apps" become a Tauri or PWA wrapper only if time is left over. Interop then comes for free, because the only shared language is JPEG over WebSocket plus the REST API in CONTRACT.md.
- Can be verified from the Mac: Mac host, iPhone Safari capture, the Android emulator if Android Studio is installed (inferred), and Chrome/Safari/Firefox on the Mac. Cannot be verified from the Mac: a real Windows host (firewall, ffmpeg on PATH, Windows codecs) and real Android camera permissions over LAN. A Windows ARM VM in UTM is possible but unverified. Say plainly in the pitch which pairs were actually tested.

**S2. Venue network (likely the most common live failure).** University Wi-Fi often blocks devices on the same network from reaching each other (client isolation; inferred, not checked for UW). Phone hotspots drop. iOS Safari needs HTTPS for getUserMedia, so the phone must install and manually trust the mkcert root CA under Settings > General > About > Certificate Trust Settings (inferred). Android Chrome needs the same, or a chrome://flags insecure-origin exception (inferred). A Windows host shows a Defender Firewall prompt for python on 8000/8443 (inferred).
- Mitigation: put the laptop on its own hotspot, with a second phone as backup. Pre-trust certs on every demo device Saturday night. Keep a cloudflared tunnel URL ready. Keep replay mode one keypress away. Show `camera_connected` big on screen so a disconnect reads as handled, not broken.

**S3. Glasses app has hidden iOS blockers.** The spec says ws:// to the laptop IP on port 8000. iOS App Transport Security blocks unencrypted connections unless Info.plist sets NSAllowsLocalNetworking. iOS also shows a Local Network permission prompt (needs NSLocalNetworkUsageDescription), and the stream dies if the app leaves the foreground or the screen locks (all inferred). Developer Mode is a hidden tap sequence in the Meta AI app plus minimum firmware (verified, Meta docs above). A free Apple ID provisioning profile expires in 7 days (inferred), which is fine for this weekend.
- Mitigation: keep the 8 PM go/no-go. Add both plist keys and turn off auto-lock. Pitch the chest-mounted phone as the universal path ("works with any phone, glasses are optional") so a glasses failure is not a demo failure.

**S4. Gemini cost limits, outage, latency.** Limits apply per project, not per API key (verified, https://aistudio.google.com/docs/rate-limits). That page did not list free-tier numbers for the Flash or Flash-Lite models, so assume a low daily cap (inferred). At 1 check/s with a 0.6 s floor, rehearsals burn about 3,600 requests per hour of camera time. check.py fails closed (timeout gives unsure), so an outage looks like "it stopped working."
- Mitigation: check only when the frame changes (a cheap pixel-difference gate before calling Gemini). Use a separate project for rehearsals versus the demo. Show check latency on screen. Add a local fallback check (compare against the reference with a color mask or histogram for the 6 camera steps; works offline) that turns on automatically after N errors. Pitch it honestly: "cloud check, local fallback."

**S5. Check passes that look fake, or false passes.**
- Step 1 (flat square) passes the moment paper enters the frame. That proves nothing and looks scripted.
- The reference is the last frame of the expert clip, so it may include hands, a different angle, or a different paper color than the judge's sheet.
- Step 5 (flip) vs step 6: a low-detail, low-resolution check may not tell seams from a smooth face, and that is the exact moment the pitch claims "the check catches it."
- Mitigation: make step 1 manual or a "camera sees paper" handshake. In teach, pick the reference frame as the clearest frame of the last 1.5 s with no hands, not the literal last frame. Phrase questions by shape and seam count, not color. Use the same paper as the expert.
- Rehearse the planted mistake 20 times and record the pass rate. If below 18 out of 20, script the demo around a mistake that reliably fails.

**S6. "Isn't this just a video player with a timer? YouTube exists."** This is the strongest objection.
- Turn it around: add a one-line `reason` field to the check JSON ("I see seams facing up; flip the paper") and show it in the badge. Then the "no" is visible intelligence. YouTube cannot say "you skipped step 5."
- Wire prerequisite skip detection (Later feature 1) into the demo: one spoken alert when the live frame matches step N+2 before N+1.
- Show the teach step live in the pitch: upload 1 take, get 8 captioned clips with checks, with zero editing. The value is authoring cost going to near zero, not playback.
- Show the end screen with the learner's time vs the expert's per step. It is real data and a believable payoff for training managers.

**S7. Judge folds too fast or too slow, or blocks the camera.** At 1 check/s with 2 consecutive yes answers plus the verified hold, advancing lags 2 to 4 s (inferred from code). A fast judge is two folds ahead and the clips feel behind.
- Mitigation: allow jumping ahead. If the live frame passes a later step's check, go there with a "nice, you're ahead" chime. Big Next button always works. Prefer a chest mount over glasses for judges (no fitting, steady angle).

**S8. Audio in a loud hall.** Chrome's speech recognition sends audio to a Google server and does not work offline (verified, https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition). Firefox lacks it (inferred). Hall noise will cause misses and false "next"s. The expert's narration is inaudible from laptop speakers.
- Mitigation: captions are the primary channel (already planned). Put the voice toggle off by default and enable it only in quiet booths. Bring a cheap clip-on mic or earbuds. Require a word plus a pause ("next" alone) to avoid false triggers.

**S9. Lighting.** Overhead hall glare washes out matte paper, and shadows of hands and head confuse the check.
- Mitigation: bring a USB desk lamp and black foam board (spec already says dark mat). Rehearse under the venue lights Sunday morning and record the pass rate.

**S10. Privacy of recording.** Glasses record bystanders. Frames go to Google's unpaid tier, where "human reviewers may read, annotate, and process your API input and output," and the terms advise against sending personal information (verified, https://aistudio.google.com/docs/terms).
- Mitigation: stay honest. Say it on a slide: frames are checked and then discarded, nothing is stored on the learn side, and the camera points down at the hands. Add a visible recording indicator. Name a production path (paid tier with no training on data, or on-device check) without claiming it is built.

**S11. Smaller technical weak points.**
- teach.py falls back to /opt/homebrew/bin/ffmpeg. On Windows, ffmpeg must be on PATH or teaching fails. Document `winget install ffmpeg` (inferred) or error out clearly at startup.
- A single global Engine means one learner per server. Two judges opening the learn screen share one state. Fine for the demo; do not claim multi-user.
- Model ids in the spec (gemini-3.8-flash, gemini-3.5-flash-lite) were not verified today. Run `check.py` benchmark mode against the real model before the demo.
- The teach upload of a 3 minute 1080p take goes through Gemini file upload. Pre-make the bike lesson and never teach live over venue Wi-Fi.
- Competitor claims (DeepSight, Retrocausal) are not verified here. Check them before saying them to judges, or drop the names.

**Top 5 actions**
1. Collapse "every platform" into one web client plus server. Test the matrix pairs that can be tested and list the rest as untested.
2. Pre-trust certs and set up a personal hotspot. Keep replay mode as a hotkey.
3. Add the `reason` field and jump-ahead. Rehearse the planted flip mistake for a measured pass rate.
4. Add a pixel-difference gate plus a local fallback check to survive rate limits or an outage.
5. Bring a lamp, a mat, matched paper and earbuds. Test under venue lights Sunday morning.