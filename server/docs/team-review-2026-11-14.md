# Cross-team review, 2026-11-14 evening

Read-only review of origin/main (9371631) and origin/prayush/story-dbx (c3d29f0). Builds: web passes (250.8 KB JS), iOS simulator build passes against MWDAT 1.0.1. No secrets in any branch or history. No XSS found.
Status column: "fix branch" = being fixed on soham/pranav-fixes for Pranav to review; "hub" = Soham's server; "owner" = needs the file owner.

## Pranav (web, ios, capture.html, databricks.py)
| # | Finding | Status |
|---|---|---|
| 1 | "Start over" sends goto 0, so the second attempt has no run_id in Databricks. Send select_lesson instead | fix branch |
| 2 | UI ignored check_mode: mock looks like real checks | fixed on soham/pranav-fixes (Mock checks pill) |
| 3 | No "budget" reason; "No Gemini key" when provider is Claude | fixed on soham/pranav-fixes |
| 4 | Mistake type misses kind "live", label; looks_like should be optional | fix branch |
| 5 | next_clip not preloaded | fixed on soham/pranav-fixes (7.5 ms first frame) |
| 6 | Missing clip/captions/ref_frame paths crash the page; apply contract defaults | fix branch |
| 7 | Space on a focused button triggers Next | fix branch |
| 8 | Pulsing status dot breaks DESIGN principle 8 | fix branch |
| 9 | --faint text about 2.6:1 contrast; captions should be 72% black | fix branch |
| 10 | Databricks flushes every 5 s while a camera is connected; quota risk | fix branch (flush 60 s, on run_end) |
| 11 | Retries can duplicate events; use MERGE on event_id | fix branch |
| 12 | run_start source not wired end to end; mock/replay mixed into dashboards | hub + fix branch |
| 13 | capture.html camera revive gaps (failure leaves running; track mute/ended) | fix branch |
| 14 | capture.html: cap long side, status casing, device name, show mistakes | fix branch |
| 15 | Upload errors hide the hub's detail text | fix branch |
| 16 | Done stats can drift on skipped states; count unique mistakes | fix branch |
| 17 | Hub restart resets the learner to step 0 | fix branch |
| 18 | iOS README omits that glasses streaming needs a paid Apple team (verified: free team rejected) | fix branch |
| 19 | iOS hello claims glasses before any glasses frame | fix branch |
| 20 | iOS small UI items (error style, raw status, accessibility labels) | fix branch |
| 21 | databricks.py: validate lesson id in --upload; rotate local JSONL; .env inline comments | fix branch |

## Prayush (databricks/, docs/pitch.md, docs/devpost.md, poster/)
Please update (owner):
1. Copy says Gemini runs checks. Measured provider is Claude Haiku (about 1.1 s p50, synthetic images). Say "Claude Haiku runs each check, Gemini as fallback; Gemini or Claude plus local Whisper cuts the video". No "temperature 0"; the check sends three images (before, done, live). Add anthropic to Built with.
2. "Two confident yeses" is not always true: one yes at 0.92+ with no difference advances (fast path on by default).
3. "You're ahead ... and moves on" is wrong: ahead only shows a banner (HANDOVER_AHEAD_SKIP off by default).
4. Accuracy: only synthetic numbers exist. 0 to 2 false passes in 12 per run with the before image; no real paper or device test yet.
5. Cost: Claude calls are paid; there is a spend ledger and a $20/day, $50 total cap. Quote per-check cost from `python -m server.check --bench`.
6. Screenshots 11 and the poster images come from mock checks on a test pattern. Reshoot on a real lesson or caption "Test lesson, simulated check".
7. "Commit history is all from this weekend": first commits are 13:43 and 13:59, before the 3:30 PM start in the plan. Check the rules and phrase it accurately, or drop it.
8. Dashboard datasets: filter check_offline reason IS NOT NULL; exclude mock and errored checks from latency; timed_out_rate should use error_kind = 'timeout'; exclude replay runs once source is sent.
9. Step 1 time includes idle time before start; note it or start the clock at the first check.
10. NOTES_FOR_PRANAV.md cites commits no longer on main; refresh it.
11. Pitch Q16: add the budget reason and that no_key never retries.

## Process
origin/main was force-pushed (f5e1b13 to 9371631) to remove a co-author line. TEAM_RULES forbids force pushes; the owner should confirm nothing was lost. origin/pranav/web-capture-dbx is fully merged and can be deleted.
