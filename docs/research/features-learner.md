## Learner experience ideas for HandOver (learn mode)

**Bottom line:** the best learner features are web-only and live in `web/src/Learn.tsx`, plus small additions to `server/check.py`. They work on any laptop host (Mac or Windows) and with any phone that sends frames (iPhone, Android or glasses), so they don't affect whether the platforms work together. Top pick: "mistake hint plus skip alert". It catches the most common failure, the skipped or doubled flip at step 5, and tells the learner what went wrong.

**What was checked in the repo:**
- `CONTRACT.md` already sends `last_check.confidence` and `latency_ms` on `/ws/ui`.
- `useVoice.ts` handles only "next" and "back".
- `lessons/demo-v1/lesson.json` has `prerequisites`.
- At the time of writing, none of the ideas below had been built.

**How to read the ratings:**
- **Wow** = how much it stands out to a new user, 1 to 5.
- **Use** = real usefulness, 1 to 5.
- **Hrs** = effort in focused hours.
- **Risk** = risk of misbehaving in use: L low, M medium, H high.

### Ideas, rated

| # | Idea | Wow | Use | Hrs | Risk |
|---|---|---|---|---|---|
| 1 | **Mistake hint.** Extend the check's answer format to `{done, confidence, hint}`, where hint is up to 8 words saying what differs from the reference, e.g. "paper not flipped yet". Show and speak it after 3 "no" answers in a row. | 5 | 5 | 2.5 | M (a wrong hint looks bad; only show it at confidence >= 0.7) |
| 2 | **Skip alert from prerequisites.** After 2 "no" answers, also compare the live frame against the next step's reference frame. If it matches, say "Looks like you skipped: Flip it over" (title of the missed step). This doubles calls only during misses. | 5 | 5 | 3 | M (free tier rate limits are unverified) |
| 3 | **"Why".** Play the narration around the step, from 5 s before to 5 s after, from `norm.mp4`. Uses a media fragment (`#t=start,end`) or `currentTime`. No server work. | 3 | 4 | 1 | L |
| 4 | **"Show me again" and "slower".** Voice or button restarts the clip, or sets `playbackRate=0.5` with `preservesPitch` on so narration stays understandable. | 3 | 4 | 1 | L |
| 5 | **Target frame toggle.** Show the step's `frames/NN.jpg` ("this is what done looks like") next to or over the live view. | 4 | 4 | 1 | L |
| 6 | **Ghost overlay.** The reference frame at 35% opacity on top of the live view, like an onion skin. | 4 | 3 | 1.5 | M (camera angles differ, so it can look misaligned) |
| 7 | **Hand ghost.** MediaPipe HandLandmarker (a free Google library that finds hand joint positions in video) draws the expert's hand skeleton from the clip over the learner's view. | 5 | 2 | 5 | H (alignment, CPU, setup time) |
| 8 | **Confidence ring.** A badge that fills to `last_check.confidence`, with latency in small text. The data already arrives. | 3 | 3 | 0.5 | L |
| 9 | **More voice commands.** Add again, slower, why, pause, back, "what step". | 4 | 4 | 1.5 | M (room noise; Chrome only) |
| 10 | **Spoken coaching.** `speechSynthesis` (the browser's built-in text to speech) reads step titles and hints aloud. "Expert style" = Gemini rewrites the hint in the expert's own words from the transcript. Avoid voice cloning: ElevenLabs costs money past its free tier, and a cloned expert voice is misleading. Playing the expert's real audio is more honest. | 4 | 4 | 2 | L |
| 11 | **End screen stats vs expert.** Time per step (yours vs the clip length), total time, retries, mistakes caught, a bar chart. Built from the `advance` events. | 4 | 4 | 2.5 | L |
| 12 | **Filmstrip of your verified moments.** Keep the live frame at each camera-verified step, then show your fold next to the expert's reference on the end screen. | 5 | 4 | 1.5 | L |
| 13 | **Final-state compare.** The learner's last frame vs the expert's final frame, with a yes/no match from Gemini. | 4 | 3 | 1 | L |
| 14 | **Multilingual captions.** At teach time (or on demand), Gemini translates each VTT file to `captions/NN.<lang>.vtt`; add a language picker, and TTS speaks hints in that language. | 4 | 4 | 2 | L |
| 15 | **Accessibility pack.** Caption size control, high-contrast theme, an `aria-live` region that announces step changes to screen readers, keyboard keys (Space next, Left back, R repeat, W why), `prefers-reduced-motion`. | 2 | 5 | 1.5 | L |
| 16 | **Left-hand mirror.** Flip the clip horizontally. Captions must move into a separate div or they mirror too. | 3 | 3 | 0.5 | L |
| 17 | **Stuck assist.** No progress for 20 s: replay the clip in slow motion and offer the target frame. | 3 | 4 | 1 | L |
| 18 | **QR code to join.** The learn screen shows a QR code for the capture page URL, so any iPhone or Android phone becomes the camera in one scan. This is the main cross-platform enabler. | 4 | 5 | 1 | M (see HTTPS note below) |
| 19 | **Spectator mirror.** A second device opens a read-only learn view, so others can watch on a phone or projector. `/ws/ui` already sends updates to every connected screen. | 3 | 3 | 1 | L |
| 20 | **Multiple learners.** A learner id per camera socket, separate step state for each, and a grid dashboard. | 4 | 4 | 6+ | H (contract rewrite, rate limits) |
| 21 | **Offline mode.** A service worker (a script that caches files in the browser) keeps the clips; a local image-similarity check replaces Gemini. | 2 | 3 | 4+ | M (the local check is weaker; skip it) |
| 22 | **Step card.** The frame plus arrow callouts and a quote from the transcript. | 3 | 3 | 3 | M |
| 23 | **Ask the expert by voice,** answered from the transcript. | 4 | 3 | 3 | M (a chat box is out of scope) |

### Contract changes these need
- `last_check` gains `"hint": str|null`.
- New server message: `{"type":"alert","kind":"skip|hint|stuck","text":str,"step":int}`.
- Optional field on `advance`: `"frame_saved": "<url>"` for the filmstrip. Or the client grabs the latest binary frame itself, which needs no contract change.
- Again, why, slower, mirror and language stay on the client, so no contract change.

### Platform facts and what a Mac can verify
- **Voice input** (verified today, https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition): "limited availability". In Chrome, audio is sent to a server, so it needs internet. A `processLocally` property exists, but its support isn't documented. Inferred: Chrome and Edge on Windows behave the same way. Firefox has no support. Keep the Next button and the keyboard keys as the guaranteed path.
- **Text to speech** (verified today, https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesis): Baseline widely available since September 2018. The voices come from the device, so a Windows host will sound different from a Mac. Wait for the `voiceschanged` event before picking a voice.
- **MediaPipe HandLandmarker** (verified today, https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/web_js): npm package `@mediapipe/tasks-vision`, model file `hand_landmarker.task`, VIDEO mode on the web, `numHands` defaults to 1.
- **`preservesPitch`** on video (inferred, https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/preservesPitch): supported in current Chrome, Edge and Safari.
- **Verifiable on this Mac:** every web feature in Chrome and Safari, plus the replay script (`server/replay.py`) to test mistake and skip alerts with a recording that has a deliberately skipped flip.
- **Not verifiable on this Mac:**
  - Windows Edge voices, and the voice commands on a Windows host. Needs a Windows machine.
  - The Android Chrome capture page. This needs a physical Android phone, not the SDK. Inferred: Android won't trust a mkcert certificate (a locally made HTTPS certificate) without installing its root certificate by hand, so use the free `cloudflared` quick tunnel's real certificate for Android.
  - Multilingual TTS quality on each operating system.

### Top 8, in priority order
1. **Mistake hint plus skip alert (#1 and #2).** Catches the step 5 flip. Test it with a replay of a skipped-flip recording.
2. **Spoken coaching via speechSynthesis (#10).** Speaks hints, skip alerts and step titles, so it's hands-free and the learner hears the mistake named.
3. **More voice commands plus slow motion and why (#9, #4, #3).** Shows the "I can't touch the laptop, my hands are full" story.
4. **End screen: stats vs expert plus filmstrip plus final compare (#11, #12, #13).** A strong closing visual, and the risk is low.
5. **Target frame toggle plus confidence ring (#5, #8).** Shows the learner what the check is looking at, which builds trust in the AI.
6. **QR code to join (#18).** Any phone works with any laptop host, in one scan.
7. **Multilingual captions (#14).** One toggle; good for the "knowledge transfer across a workforce" story.
8. **Accessibility pack plus left-hand mirror (#15, #16).** Cheap and real, and it reads as polish.

Left out for now: hand ghost (#7), multiple learners (#20), offline (#21), ask the expert (#23).