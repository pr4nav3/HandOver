## HandOver: ideas for the expert side and the lesson lifecycle

Sources read: CONTRACT.md, server/teach.py (the step-splitting schema and prompt), lessons/demo-v1/lesson.json and web/package.json.

Scores: Wow and Use are out of 5. Effort is focused hours. Risk means how likely it is to break in use (L = low, M = medium, H = high).

### External facts
- getUserMedia (the browser camera API) only works on HTTPS or localhost. Verified today: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- `<input type=file accept=video/* capture=environment>` opens the rear camera on phones. Desktops just show a file picker, and the feature is not supported everywhere ("Limited availability"). Verified today: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Attributes/capture
- My guess, not checked: a plain file upload does not need HTTPS, so phone recording works over the hotspot on plain http.
- mkcert certificates only work on a phone after you install its root certificate. iOS needs Settings > Profile Downloaded plus full trust. On Android, mkcert only says to install the CA and then enable user roots in the app's development build; it does not cover Chrome. Verified today: https://github.com/FiloSottile/mkcert
- My guess, not checked: Chrome on Android may not trust a user-installed certificate. A cloudflared quick tunnel avoids the problem.
- cloudflared quick tunnels are free and need no account. Uptime is not guaranteed, there is a limit of 200 requests in flight, there is no SSE support, the URL changes on every start, and the page does not mention WebSockets. Verified today: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/
  - Inferred: WebSockets do work through cloudflared. Needs a test.
- QR libraries, both free with no extra dependencies:
  - segno 1.6.6 (Python, BSD license, writes SVG and PNG). Verified today: https://pypi.org/project/segno/
  - node-qrcode (MIT license, outputs canvas, SVG or a data URL in the browser). Verified today: https://github.com/soldair/node-qrcode
- CSS `@page { size: letter; margin }` works in all current browsers (Baseline 2024). Verified today: https://developer.mozilla.org/en-US/docs/Web/CSS/@page
- Gemini structured output accepts Pydantic schemas. Very nested schemas fail with 400 INVALID_ARGUMENT, so keep new fields flat. The docs now call the parameter `response_format`, while teach.py uses `response_json_schema`. That is a possible drift: check that the installed google-genai still accepts it. Verified today: https://aistudio.google.com/docs/structured-output

### Ideas

1. **Record on any phone or the glasses.** A `/record` page served by FastAPI with a rear-camera file input and multi-file upload to `POST /api/lesson`. teach.py already joins several files into one (`concat`), which covers the glasses' 3-minute clip limit. For the glasses: export from the Meta AI app, then AirDrop or share to this page.
   - Works on iPhone and Android with no app.
   - Wow 3, Use 5, Effort 1.5, Risk L.
2. **Better reference frames and boundaries.** Each step's reference frame is currently its literal last frame, which is often blurred or blocked by a hand.
   - Instead, pick the sharpest, stillest frame from the last 15% of the clip (OpenCV blur score plus frame difference, or ffmpeg).
   - Snap step boundaries to the nearest gap between transcript sentences, within 1 s.
   - Flag steps shorter than 3 s or longer than 60 s.
   - Wow 2, Use 5, Effort 2.5, Risk L.
3. **Check self-test (strongest reliability idea).** After cutting, run the check question for each step against its own frame (should say yes) and the previous step's frame (should say no).
   - Show a green, amber or red badge per step.
   - Suggest switching a step to "manual" when the check cannot tell the two frames apart.
   - It shows the system checking itself, and it catches bad questions before a learner sees them.
   - Wow 4, Use 5, Effort 2, Risk L.
4. **Light review editor** on the teach screen. Drag the boundary handles on the colored timeline, rename steps inline, merge with the next step, split at the playhead, switch camera/manual, edit the check question, then Save. Save needs a new `PUT /api/lessons/{id}`, then calls the existing recut.
   - Wow 3, Use 5, Effort 5, Risk M (dragging bugs). Ship rename and drag first, merge and split second.
5. **Safety warnings and a tools/parts list from the narration.** A flat schema addition: a per-step `warning: str` (empty if none) and a top-level `tools: list[str]`, with prompt rules to quote only hazards the expert actually says.
   - Learn screen: amber banner on that step, plus a "You need" card before step 1.
   - The bike lesson shows it well ("watch the rotor, keep fingers out of the spokes") if the expert says it while recording.
   - Wow 3, Use 4, Effort 2 for both, Risk L. Needs a contract change to lesson.json, and old lessons must read the fields as optional.
6. **Shareable link and QR code.** Add `GET /api/info` returning the LAN IPs and the tunnel URL if one is running. Each lesson card shows a QR code for `/learn/<id>`.
   - The learn screen also shows a "Use your phone as the camera" QR that opens `/capture`.
   - Anyone scans with their own iPhone or Android phone, and that phone becomes the camera for a laptop on any OS.
   - Wow 5, Use 5, Effort 2, Risk M (shared Wi-Fi may block devices from reaching each other: use a hotspot or the tunnel).
7. **Lesson package (`.handover` file).** A zip holding `manifest.json` (format version, app version, created time) plus lesson.json, clips, captions and frames; norm.mp4 is optional.
   - Endpoints: `GET /api/lessons/{id}/export` and `POST /api/lessons/import`.
   - Python's built-in zipfile with no compression for the videos. Reject `..` paths and absolute paths on import. Store forward-slash relative paths. Rename on id clash.
   - Why it works across OSes: H.264 mp4 plays everywhere and the paths are relative, so a lesson made on a Mac runs on a Windows host.
   - Wow 2, Use 5, Effort 2, Risk L.
8. **Versioning.** Add `version: int` to lesson.json. Every save copies the old lesson.json to `history/<version>.json`, with a Restore button.
   - Wow 1, Use 3, Effort 1.5, Risk L.
9. **Where learners get stuck, fed back to the expert.** The server appends one line per event to `lessons/<id>/runs/<timestamp>.jsonl`: step entered, how many checks, runs of "no" answers, back presses, how each step advanced.
   - The teach timeline shows a heat strip: median learner time per step against the expert's clip length, with the worst step labeled (for origami, likely step 5, the flip).
   - Right after a learner finishes, show their run next to the expert's (end screen stats).
   - Wow 4, Use 4, Effort 3, Risk L.
10. **Expert tip clip for the problem step.** From the heat strip, the expert records a 10 s tip on their phone, attached as `tip_clip`. It plays when a learner gets "no" three times on that step.
    - Wow 4, Use 4, Effort 2.5 on top of idea 9, Risk M.
11. **Printable one-page guide.** A `/print/<id>` page: a grid of reference frames with step titles, checks, warnings, the tools list and the QR code, using `@page size: letter`. Chrome or Safari "Save as PDF" makes the PDF for free.
    - Wow 3, Use 4, Effort 2, Risk L.
12. **Translated caption tracks.** One Gemini call translates the transcript into extra caption files, chosen from the standard captions menu.
    - Wow 3, Use 3, Effort 1.5, Risk L.
13. **Re-record one step.** The expert re-shoots a single step on their phone, and only that clip is replaced and re-timed.
    - Wow 3, Use 4, Effort 3.5, Risk M.

### What can and cannot be checked from the Mac
- **Can check:** web pages in Safari, Chrome and Firefox. Playwright's Chromium engine is close to Edge on Windows. Export and import round trips. An iPhone over USB or the hotspot. The iOS Simulator for layout only, since it has no camera.
- **Cannot check without more hardware:**
  - Android: needs a real device; remote debugging over USB needs adb from the Android platform-tools, which are free. Without the SDK, test only that the page loads.
  - Windows host: ffmpeg must be on PATH, `uv` works on Windows, and the path rules are the export/import rules above. Unverified without a Windows machine. Mitigation: no HEVC, use pathlib, no `:` in ids.

### Contract changes these ideas need
- `PUT /api/lessons/{id}`
- export and import endpoints
- `GET /api/info`
- the runs event log
- optional `warning`, `tools`, `version` and `tip_clip` fields in lesson.json

### Top 8 picks, in priority order
1. **#6 QR link and phone-as-camera pairing:** any phone works with any laptop.
2. **#3 Check self-test, with #2's better reference frames:** directly protects the live check.
3. **#1 Record on any phone or the glasses, with multi-file upload:** the expert side works on every OS.
4. **#7 `.handover` package:** meets the "made on a Mac, hosted on Windows" requirement.
5. **#4 Light review editor (rename and drag first):** the fix path the spec promises for bad boundaries.
6. **#5 Safety warnings and tools list:** one prompt change, visible gain in the bike lesson.
7. **#9 Stuck analytics and the learner's run vs the expert's:** closes the loop back to the expert.
8. **#11 Printable guide with QR:** cheap, real, and leaves a physical handout.