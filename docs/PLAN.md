# HandOver build plan, lean (Saturday 2026-11-14 afternoon to Sunday noon)

Owner: lead. This replaces the earlier 7,000-word plan. Scope decision: lean MVP wins. Android, Windows, desktop packaging, CI builds, QR pairing, spectator view, export/import and the every-OS demo beat are out (see docs/SCOPE.md). The wire contract is [CONTRACT.md](CONTRACT.md); items in it that only served cut features are optional and nobody has to implement them. Working rules (folder ownership, git) are in TEAM_RULES.md at the repo root. 

Hacking ends **12:00 PM Sunday**. Judging **1:00 to 2:30 PM**. Hours are estimates, not measurements.

## 1. What we are building
An expert does the task once on Meta glasses while narrating. HandOver cuts that take into steps and plays the expert's own clip, captioned, for each step. It moves on only when the learner's camera shows the step is done, or when the learner presses Next.

Hook: "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person." Then the judge skips the flip and the screen says so.

Never say "first", "only", a training-time saving, or a user count. Say "one take" only if the bike lesson really was one take. Name Retrocausal and Dozuki only (sourced in research/market.md).

## 2. What already exists (keep, do not rebuild)
- `server/main.py` hub: REST for lessons and teach jobs, `/ws/camera` (JPEG in), `/ws/ui` (state, advance), static lesson files, `/capture` page, http 8000 and https 8443 with certs.
- `server/teach.py`: normalize, Gemini extraction, cut clips, captions, frames. `server/check.py`: Gemini two-image check with mock mode. `server/replay.py`: feed an MP4 into `/ws/camera`.
- `web/`: Learn and Teach screens, top bar, chime, voice, UI socket hook.
- `lessons/demo-v1`, `scripts/certs.sh`, `scripts/run_server.sh`, `scripts/make_demo_lesson.sh`, tests `server/test_server.py`, `server/test_check.py`.

## 3. Features

### MUST (the demo fails without these)
| ID | Feature | Est. h | Where |
|---|---|---|---|
| M1 | Real Gemini check: confirm model ids, `python -m server.check --time` 20 calls on the hotspot, write down latency and limits. Gate at 6 PM | 0.5 | server |
| M5 | Motion gate: call Gemini only when the frame is still and changed since the last check, heartbeat every 6 s; latency in `last_check` | 1 | server |
| M6 | Breaker: after 3 Gemini errors or any 429, checks off for 30 s and the badge says "Checks off, use Next"; `check_offline` in state | 1 | server, web |
| M8 | Clean reference frames (stillest hands-free frame in the last 15% of each clip); step 1 manual; check questions by shape and seam count, not color | 1 | server |
| M14 | Two real lessons cut from takes recorded this afternoon and evening (fortune teller, bike front wheel) and committed; a clean fold recording and a skipped-flip recording filed for replay | 1 | lessons |
| M15 | Privacy backed by code: a test asserts learn frames never touch disk | 0.25 | server |
| W1 | Web served by the hub at `http://<ip>:8000/` (relative URLs) so the demo runs without Vite | 1 | web |
| W4 | `capture.html`: recording dot, reconnect, idle notice | 0.75 | capture |
| W5 | Honest live states: camera lost (last frame dimmed), "Checks off" badge, latency in small text, "Recording" banner when replay is the source | 1.5 | web |
| W8 | iPhone app: SwiftUI, 1 fps JPEG to `/ws/camera`, typed hub address, step title and Next button, screen awake, local-networking plist keys. W8a phone camera first; W8b glasses source via DAT 1.0.1 with auto fallback to the phone camera, time-boxed, 8 PM gate | 5 + 3 | ios |

### SHOULD (in this order, only after the live fold works end to end at 6:30 PM)
| ID | Feature | Est. h | Where |
|---|---|---|---|
| M9 + W6 | The catch: after 5 s of settled "no", compare live vs refs k-1, k, k+1; amber banner and voice "Still step 4: flip it over"; matching a later step says "You're ahead" | 2.5 + 1.5 | server, web |
| S-D | Done screen: your time vs the expert's per step, camera-checked steps, mistakes caught, from real events | 2 | web |
| DB | Databricks: `server/databricks.py` batches events (run, step, check result, advance) into Unity Catalog tables; clips to a Volume; one AI/BI dashboard; one Genie question. Warm the warehouse before judging | 4 | server, Databricks |
| S-T | Check self-test at teach time: each question vs its own frame (yes) and the previous frame (no); amber steps suggested manual | 2 | server |
| S-S | Safety and tools list from narration (bike) | 2 | server, web |

### STRETCH
Review editor (rename, drag boundaries). Printable one-page guide. Translated captions. Hand ghost.

### CUT (decided by the founder; do not build, do not claim)
Android app, Windows exe, PyInstaller Mac app, installers, GitHub Actions CI, QR pairing and `/join`, spectator view, `.handover` export/import, local OpenCV offline checker, app icons, interoperability matrix, `docs/TESTED.md`, mDNS, multiple cameras arbitration beyond "newest camera wins", Gemini Live API, accounts, cloud deploy, gemini-3.1-pro-preview, voice "next" on by default (stays built, off).

## 4. Architecture (unchanged, smaller)
One FastAPI hub on the Mac. Cameras (iPhone app, glasses through the iPhone app, `capture.html` in Safari, `server.replay`) send JPEGs to `/ws/camera`. The hub runs motion gate, Gemini check, debounce, advance, and broadcasts `state` and `advance` on `/ws/ui`. The web app is the only UI and is served by the hub. One learner per hub; newest camera wins. Lessons are folders on disk.

## 5. Ownership
Folder ownership and git rules: TEAM_RULES.md. Contract changes: say it in the group, one person edits CONTRACT.md and bumps its Revision line, everyone pulls.

## 6. Timeline
| Time | What |
|---|---|
| 3:30 PM | Kickoff on main. `uv pip install -r server/requirements.lock`; `npm --prefix web ci`; Developer Mode on; two Gemini keys (rehearsal, demo) in `.env`. Sikandar buys paper, black board, lamp, chest mount and borrows a bike with a QR front wheel. Prayush asks an organizer about pre-recorded footage as input and creates the Databricks workspace and two Gemini keys |
| 3:30 to 6:30 | Soham (server, lessons): M1 (time 20 calls first), M5, M6, M8; work against `lessons/demo-v1` until the take arrives, then cut the fortune teller (M14). Pranav (web, capture, ios): W1, W5, W4, then W8a. Sikandar: record three glasses takes of the fortune teller by 5:00 PM (narrating, pause after each step, mat and paper in frame) and hand them to Soham. Prayush: Devpost shell, poster draft, Databricks tables |
| 6:00 | **Gemini gate** (M1 numbers): median 2.0 s or less passes; 2.0 to 2.5 s widens the motion gate; over 2.5 s means one confident yes plus Next |
| 6:30 | **Integrate.** First live fortune teller with the phone (Safari or W8a). Ugly is fine. Nothing in SHOULD starts before this passes |
| 6:30 to 8:00 | Pranav: W8b glasses source, time-boxed, then W6. Soham: M9, and M8 reference frames on the real lesson. Sikandar: bike takes prep, novice-run log ready. Prayush: Databricks Volume, dashboard skeleton |
| 8:00 | **Glasses gate.** Frames reach the hub through the iPhone app for 60 s with no gap over 5 s and one camera advance; else glasses leave the demo, pitch and Devpost. Then ten live folds by someone who has never folded one: count camera-verified steps, manual steps, false passes, false alarms. Tune debounce and questions |
| 8:00 to 12:00 | SHOULD in order: catch (Soham, Pranav), done screen (Pranav), Databricks plumbing (Pranav) with Prayush's tables, dashboard and Genie. Sikandar records three glasses takes of the bike front wheel by 9 PM; Soham cuts by 10 PM; Sikandar files replays by 11 PM and runs the ten novice folds. Prayush: poster and pitch draft |
| 12:00 AM | **Midnight full run** on real Gemini: fold to done; planted skipped flip caught; breaker shows "Checks off" with an invalid key and the lesson still finishes by Next. Fail: stop SHOULD, everyone fixes the loop. Two sleep 12:30 to 4:30, two sleep 4:30 to 8 |
| 6:00 AM | **Feature freeze and contract freeze.** Bug fixes only, each run on the Mac before merge |
| 8:00 AM | Venue-light rehearsal: 20 folds, the planted flip must be caught in at least 18, else step 5 becomes manual and the plant moves. Warm the Databricks warehouse |
| 10:00 | Devpost draft, backup demo video recorded. 10:30 code freeze, tag |
| 11:30 | Devpost submitted. 12:00 to 1:00 setup and two run-throughs. 1:00 judging |

## 7. Demo script (4 minutes)
| Time | Beat | Fallback |
|---|---|---|
| 0:00 to 0:20 | Hook line, learn screen idle | none |
| 0:20 to 0:55 | Teach: bike lesson from one take, timeline, click a clip, expert's voice and captions | pre-cut on disk; reload; backup video |
| 0:55 to 2:10 | Judge folds on the black board under the lamp, camera on a stand or chest (glasses only if the 8 PM gate passed). Clips advance as folds are seen, chime on each | ladder: glasses, iPhone app, Safari capture, replay with "Recording" banner. Gemini down: "Checks off, use Next" |
| 2:10 to 2:40 | The catch: judge leaves the paper unflipped at step 5; amber banner and voice name the step | not caught in 10 s: say so, press Next, show the skipped-flip recording labeled "Recording" |
| 2:40 to 3:10 | Done screen with real times; Databricks dashboard and one Genie question ("which step do people get stuck on?") | skip to close |
| 3:10 to 3:40 | Why different: Dozuki turns video into documents; Retrocausal needs a station camera and labeled cycles; HandOver needs one take and any phone | none |
| 3:40 to 4:00 | Privacy line ("the hub never saves your camera frames") and the hook again | none |

## 8. Risks
| Risk | Mitigation |
|---|---|
| Glasses stream fails | 8 PM gate; phone camera is the main path; glasses stay as the expert's recorder in the story |
| Gemini slow or rate limited | Motion gate, 3 s timeout, breaker, rehearsal key separate from demo key, Next always works |
| Checks misfire under hall light | Lamp, black board, matte duo-color paper, step 1 manual, 8 AM count |
| Planted flip not caught | 8 AM count; under 18 of 20 means step 5 manual |
| Hotspot drops | Second hotspot; replay; localhost mode with a USB camera |
| iOS refuses ws to a raw IP | `NSAllowsLocalNetworking`; if still refused, `NSAllowsArbitraryLoads` for this build |
| Dependency drift | `server/requirements.lock` frozen on the Mac; google-genai 3.3 broke defaults on Nov 12 |
| Databricks daily quota | Batch writes, never poll, warm once before judging |

## 9. Humans-only checklist
- [ ] Two Gemini keys (rehearsal, demo) in `.env`; read limits on the AI Studio rate-limit page; no billing.
- [ ] Meta AI app Developer Mode on, glasses charged and paired, before 6:30 PM; recheck Sunday morning.
- [ ] iPhone: free Apple ID signing trusted, mkcert root trusted, auto-lock off.
- [ ] `brew install mkcert`, run `scripts/certs.sh` before 6 PM; rerun after any hotspot IP change.
- [ ] Props: 10+ duo-color kami sheets, pre-folded examples, paper cups, black foam board, desk lamp, phone stand or chest mount, chargers, power strip.
- [ ] Takes to the lessons owner: fortune teller by 5 PM, bike by 9 PM, clean fold and skipped-flip replays by 11 PM.
- [ ] Both hotspots tested with every device.
- [ ] Databricks Free Edition workspace created; PAT in `.env`.
- [ ] 8 AM rehearsal; Devpost by 11:30; ask a judge to fold.
