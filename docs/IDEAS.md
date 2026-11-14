# HandOver ideas (deduplicated)

Owner: lead. Sources: research/features-learner.md (L), research/features-expert.md (E), research/red-team.md (R), research/design.md (D), plus items from research/architecture.md and research/ai.md (A). Status follows [PLAN.md](PLAN.md): MUST, SHOULD, STRETCH, LATER (after this weekend), CUT. IDs in brackets point to PLAN.md rows.

## Checking and coaching (learn side)

| Idea | Source | Status | Why |
|---|---|---|---|
| `reason` on each check, shown at confidence 0.7 or more | L1, R-S6 | MUST [M6, W5] | Turns a bare "no" into visible intelligence; answers "just a video player" |
| Mistake catch: live frame still matches the previous step ("flip it over") | L2, R-S6, A | MUST [M9, W6] | The demo's memorable moment, at the spec's known failure point |
| Jump ahead when the learner is a step ahead, confirmed by one check | R-S7, A | MUST [M9] | Fast judges otherwise feel the clips lag |
| Spoken mistake and "ahead" messages via `speechSynthesis` | L10 | MUST [W6] | Hands are full; the judge hears the catch |
| Motion gate before each Gemini call, 6 s heartbeat | R-S4, A | MUST [M5] | Cuts calls under unpublished free-tier limits |
| Circuit breaker plus local OpenCV check, "Offline check" badge | R-S4, A, L21 | MUST [M6, M7] | Survives outage or 429 without faking anything |
| Local check vetoes Gemini when it strongly names another step | A | MUST [M7] | Cheap second opinion against false passes |
| Latency in small text | R-S4, L8 | MUST [W5] | Honest about speed; helps tuning |
| Confidence ring | L8 | SHOULD [S-F] | Nice trust signal, not needed for the loop |
| Target frame toggle ("this is what done looks like") | L5 | SHOULD [S-F] | Shows what the check compares against |
| "Why": play narration around the step from norm.mp4 | L3 | SHOULD [S-W] | Client only, low risk |
| "Show me again" and slow replay with pitch kept | L4 | SHOULD [S-W] | Client only, low risk |
| Done screen: time vs expert, steps checked, mistakes caught | L11, D, R-S6 | SHOULD [S-D] | Real payoff for training managers, from real events |
| Filmstrip of the learner's verified frames | L12 | STRETCH | Strong closing image, but after the Done screen |
| Final-state compare with the expert's last frame | L13 | LATER | Overlaps the last step's check |
| Ghost overlay of the reference at 35% | L6 | LATER | Camera angles differ, looks misaligned |
| Hand ghost with MediaPipe | L7 | CUT | High setup and alignment risk for low use |
| More voice commands (again, slower, why, pause) | L9 | LATER | Hall noise and Chrome only; voice is off by default |
| Voice "next" requires the word plus a pause | R-S8 | LATER | Voice is off by default this weekend |
| Voice "next" on by default | SPEC | CUT | Loud hall causes false and missed triggers (R-S8) |
| Gemini rewrites hints in the expert's words | L10 | LATER | Extra call per hint, unclear gain |
| Voice cloning of the expert | L10 | CUT | Costs money and would be a fake voice |
| Stuck assist after 20 s with no progress | L17 | LATER | Mistake catch covers the demo case |
| Left-hand mirror of the clip | L16 | LATER | Cheap but no demo value; captions need a rework |
| Step card with callouts and a quote | L22 | LATER | Authoring work with no live payoff |
| Ask the expert, answered from the transcript | L23 | CUT | Spec says no chat this weekend |
| Multiple learners with a grid dashboard | L20 | CUT | Contract rewrite and rate limits |
| Offline service worker caching clips | L21 | CUT | The hub is local already; no gain |
| Gemini Live API as the checker | A | CUT | Session limits and no step state; flash-lite two-image check is enough |

## Learn screen states and accessibility

| Idea | Source | Status | Why |
|---|---|---|---|
| Camera lost: last frame dimmed, "keep going with Next" | D, R-S2 | MUST [W5] | A disconnect reads as handled, not broken |
| "Recording" banner whenever replay feeds frames | SCOPE, R-S2 | MUST [W5] | Never pass a recording off as live |
| Recording dot on every camera client and a privacy line | R-S10 | MUST [W4, W5, W8, W11] | Honest about capture; backed by code |
| Learn frames never written to disk, with a test | R-S10 | MUST [M15] | The privacy line must be true |
| Mistake banner buttons "Show step n" and "I'm fine" | D | MUST [W6] | Lets the learner recover or dismiss |
| Camera device name in the top bar | D | MUST [W2] | Shows which device is streaming in the every-OS beat |
| Keyboard map, `aria-live`, reduced motion, caption size | L15, D | SHOULD [S-A] | Cheap, real polish |
| Contrast check on design tokens | D | SHOULD [S-A] | Tokens are estimated, not measured |
| Neutral timeline tints, accent for the selected step | D | SHOULD | Calmer than a rainbow timeline; polish only |
| Light theme for teach and library | D | LATER | Learn is dark for projectors; one theme is enough now |
| Multilingual caption tracks | L14, E12, A | STRETCH | Good story, but after the loop is safe |
| Pre-generated translated speech (Gemini TTS) | A | LATER | SDK path never run |

## Pairing and cross-platform

| Idea | Source | Status | Why |
|---|---|---|---|
| One hub, one web UI, thin native camera apps on one contract | R-S1, A | MUST | The only way 2 devs cover every OS |
| QR of `/join` plus address in text | L18, E6, D | MUST [M3, W2, W3] | One scan pairs any phone with any laptop |
| "Wrong network?" LAN address picker | D | MUST [W2] | Laptops often have several networks |
| Camera `hello` with device name and source | D, A | MUST [M4, W4, W8, W11] | UI can say "iPhone connected"; replay is identifiable |
| Spectator mirror on any phone browser | L19 | MUST [W7] | Judges watch on their own phones |
| iPhone app with phone camera | SCOPE | MUST [W8] | Main camera path in the demo |
| Android app with phone camera | SCOPE | MUST [W11] | Every-OS claim on the camera side |
| Ray-Ban Meta source in the iPhone app | SPEC | SHOULD [S-G], 8 PM gate | Wow factor, but developer preview and Developer Mode risks |
| Glasses source in the Android app | A | STRETCH | Needs a real Android phone and the glasses |
| Glasses audio over Bluetooth HFP | A | CUT | Sounds like a phone call; audio stays on the laptop |
| In-app QR scanner | A | SHOULD [S-Q] | System camera plus join.html already works |
| mDNS discovery | A, D | STRETCH | Both scope docs cut it; hotspots drop multicast |
| 4-digit pairing code | D | CUT | Unenforced, it protects nothing and adds a step |
| Certificate help copy for browser capture | D | SHOULD | Native apps are the main path; copy goes on join.html if time |
| cloudflared quick tunnel as browser capture backup | R-S2, E | SHOULD | Last resort for Android Chrome; test once |
| Desktop app: frozen hub, Tk window, system browser | A | MUST [M11, M12] | A windowless app cannot be quit; webviews break voice |
| Native shell look (macOS sidebar, Windows Mica) | D | CUT | No webview shell this weekend |
| Tauri or Electron | A | CUT | Rust and sidecar setup; voice fails in webviews |
| `.dmg` and Inno Setup installer with firewall rule | A | SHOULD [S-I] | Nicer install, not needed to run |
| Paid code signing | A | CUT | Costs money |
| Desktop first run: welcome, key, connect | D | LATER | The key field (S-K) and the Connect panel cover the need |
| Gemini key field in the app | D, A | SHOULD [S-K] | Saves editing `.env` on an installed copy |
| iPhone and Android Settings screen (frame interval, name) | D | LATER | Defaults are fine for the demo |
| Android dynamic color | D | LATER | Material 3 defaults are enough |
| Playwright on windows-latest loading the hub | lead | STRETCH | Only automated Windows browser evidence possible without hardware |

## Expert side and lessons

| Idea | Source | Status | Why |
|---|---|---|---|
| Better reference frames: stillest hands-free frame in the last 15% | E2, R-S5, A | MUST [M8] | The literal last frame often has hands in it |
| Step 1 manual ("camera sees paper") | R-S5 | MUST [M8] | Otherwise it passes the moment paper appears |
| Questions by shape and seam count, not color | R-S5 | MUST [M8] | Judge's paper may differ from the expert's |
| Pre-cut bike and fortune teller lessons | R-S11, SCOPE | MUST [M14] | Never teach live over venue Wi-Fi |
| Recut keeps unknown step fields | A | MUST [M2] | New fields would be lost on every re-cut |
| Check self-test at teach time | E3 | SHOULD [S-T] | Catches bad questions before the live fold |
| Mark a step manual when adjacent references look alike | A | SHOULD [S-T] | Same mechanism as the self-test |
| `.handover` export and import | E7, A | SHOULD [S-P, S-PB] | Mac-made lesson on Windows; Dev 1 is over capacity |
| Import from another hub by URL | A | LATER | File import covers it |
| Safety warnings and tools list from the narration | E5 | SHOULD [S-S] | Visible gain in the bike lesson |
| Review editor: rename and drag boundaries | E4, D | STRETCH | 5 h and drag bugs; editing lesson.json plus recut works today |
| Merge and split steps in the editor | E4 | LATER | After rename and drag |
| `/record` page and multi-file upload | E1 | STRETCH | Takes come in by file this weekend |
| Snap boundaries to transcript gaps; flag very short or long steps | E2 | LATER | Fix by hand for two lessons |
| Per-lesson share QR to `/learn/<id>` | E6 | LATER | One active lesson per hub makes it moot |
| Lesson version history with restore | E8 | LATER | Low demo value |
| Learner run log and heat strip on the teach timeline | E9 | LATER | Needs several runs to mean anything |
| Expert tip clip for the hardest step | E10 | LATER | Depends on the run log |
| Printable one-page guide | E11 | STRETCH | Cheap handout, after everything else |
| Re-record one step | E13 | CUT | Re-timing risk; re-cut covers fixes |
| faster-whisper transcript fallback | SPEC | LATER | Kept out of the bundle for size; Gemini gives the transcript |
| gemini-3.1-pro-preview for better boundaries | SPEC | CUT | No free tier |

## Demo and operations

| Idea | Source | Status | Why |
|---|---|---|---|
| Own hotspot plus a backup hotspot | R-S2 | MUST (humans) | Venue Wi-Fi may isolate devices |
| Pre-trust certs on every demo device | R-S2 | MUST (humans) | Browser capture needs HTTPS |
| Replay command plus clean and skipped-flip recordings | R-S2, SCOPE | MUST [M14] | Fallback when cameras or network fail |
| Separate rehearsal and demo Gemini projects | R-S4, A | MUST (humans) | Limits are per project |
| Rehearse the planted flip 20 times, need 18 | R-S5 | MUST (Sync 8) | Measured, not hoped |
| Desk lamp, black board, matte duo-color paper, earbuds | R-S8, R-S9 | MUST (humans) | Lighting and noise are the likely live failures |
| Pitch "works with any phone, glasses optional" | R-S3 | MUST | A glasses failure is then not a demo failure |
| Never claim multi-learner | R-S11 | MUST | One global engine |
| Name only competitors with fetched sources | R-S11, market | MUST | Retrocausal and Dozuki; not DeepSight |
| Show a teach upload live in the pitch | R-S6 | CUT | Venue upload risk; show the pre-cut lesson and its lesson.json instead |
| Slide with the tested device matrix | SCOPE | MUST [W10] | Claims match what was run |
| Backup demo video, introduced as a recording | judging | MUST (humans) | Last resort |
