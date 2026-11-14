# HandOver scope decision (Founder, Sat 2026-11-14), lean

Supersedes the earlier scope. Red-team ids S1 to S11 refer to docs/research/red-team.md. Hours are estimates.

## 1. Thesis and hook
- Thesis: the expert does the task once on camera; HandOver turns that take into a lesson that plays their own clip for each step and moves on only when the learner's camera shows the step is done.
- Hook: "Experts teach the same task over and over. With HandOver they do it once, and the lesson watches the next person."
- Never say "first", "only", or a training-time savings figure. Name Dozuki and Retrocausal only, with market.md sources.

## 2. Scope
MUST: real Gemini check with a 6 PM latency gate; motion gate; breaker with an honest "Checks off, use Next" badge; clean reference frames and shape-based questions; two real lessons from takes recorded today plus two replay recordings; privacy test; web served by the hub; honest live states; iPhone app with phone camera first and glasses second behind the 8 PM gate.

SHOULD, in order, only after the live fold works at 6:30 PM: the skipped-flip catch; done screen; Databricks tables, dashboard and one Genie question; check self-test; safety and tools list.

STRETCH: review editor, printable guide, translated captions, hand ghost.

CUT (founder decision): Android, Windows exe, Mac desktop packaging, installers, CI builds, QR pairing and join page, spectator view, export/import, local OpenCV offline checker, icons, interoperability matrix, TESTED.md, mDNS, Gemini Live API, accounts, cloud deploy, paid models. Voice "next" stays built, off by default.

Why: four people, 24 hours, one laptop at the table. Every cut item is platform coverage or packaging that no judge sees in a four-minute table visit, and each one competes for hours with making the fold demo fast and clean. The founder's call: the fold demo wins.

## 3. Platforms
- Mac: the hub and the learn screen in Chrome. Demoed from source via `scripts/run_server.sh`.
- iPhone: native capture app (phone camera; glasses if the 8 PM gate passes); Safari `/capture` as fallback.
- Anything else: not built, not claimed.

## 4. Must-not-fail demo
1. Mac hub on its own hotspot, backup hotspot ready. Bike lesson pre-cut. Teach timeline, click a clip.
2. Judge folds on the black board under a lamp, iPhone on a stand or chest mount (glasses only if gated in). Clips advance by camera.
3. Judge skips the flip on purpose: the banner names the step (if the catch shipped; else Next and say so).
4. Done screen; Databricks dashboard and one Genie question (if shipped).
Fallback ladder: glasses, iPhone app, Safari capture, replay with a "Recording" banner. Gemini down: "Checks off, use Next". Wi-Fi: second hotspot. Last resort: the backup video, introduced as a recording.

## 5. Gates
- Sat 6:00 PM: Gemini latency measured; over 2.5 s median changes the debounce rule.
- Sat 6:30 PM: live fold end to end with the phone, mock or real check. Nothing in SHOULD starts before this.
- Sat 8:00 PM: glasses stream through the iPhone app, else glasses out of the demo and never claimed. Ten live folds by a novice; tune.
- Sun 12:00 AM: full fold on real Gemini to done, planted flip caught, breaker path works. Else stop SHOULD work.
- Sun 6:00 AM: feature and contract freeze.
- Sun 8:00 AM: venue-light rehearsal, 18 of 20 catches or step 5 goes manual.
- Sun 10:30 AM: code freeze, tag. 11:30 AM: Devpost submitted.

## 6. Humans only
See docs/PLAN.md section 9.
