# Voice sheet

One voice for everything the product says: lesson narration and the app's own cues. Kokoro (local, open source), voice `af_heart` unless we change it here. Alternatives to audition with `python -m server.voice lessons/demo-v1 --voice <name> --dry-run` then for real: `af_bella` (warmer), `af_nicole` (softer), `am_adam`, `am_michael` (male), `bf_emma`, `bm_george` (British). Decide once, write the name in `HANDOVER_VOICE` in `.env`, and re-voice both lessons and the cues.

## Rules for every line

- Second person, present tense, one action per sentence. "Fold the top corner down to the bottom one."
- One or two sentences, at most 22 words, about 2.5 words per second of clip.
- Name shapes and counts, never colors. Never read the check question aloud.
- No "please", no "simply", no exclamation marks, no "great job".
- The first word is the verb when possible.

## App cues (spoken by the Learn screen, pre-rendered in the same voice)

| Event | Line | When |
|---|---|---|
| Camera verified a step | "Done. Moving on." | on `advance` with reason camera, before the next clip starts |
| Learner pressed Next | nothing | the click is the acknowledgment |
| Mistake, behind | the step's `common_mistake`, else "Still step N. Check the clip." | once per mistake |
| Mistake, ahead | "You are ahead. Back to step N." | once |
| Lesson complete | "Lesson complete." | on done |
| Checks off | "Checks are off. Use Next to move on." | once when the breaker opens |
| Camera lost | "Camera lost. Keep going with Next." | once |

Cue files live in `web/public/voice/` and are served by the hub; the browser falls back to its own speech only if a file is missing. A toggle in the Learn ⋯ popover turns cues off.

## Bike lesson: front wheel check (11 steps, drop the ones the take skips)

| # | Title | Narration |
|---|---|---|
| 1 | Squeeze the front brake and watch the pads meet the rim | Squeeze the front brake once and watch both pads land on the rim. |
| 2 | Flip the quick release lever open and unwind the nut three turns | Flip the lever open, then unwind the nut on the other side about three turns. |
| 3 | Lift the front of the bike and drop the wheel out | Lift the front of the bike and let the wheel drop straight out of the fork. |
| 4 | Pull the skewer out and check both springs sit narrow end inward | Slide the skewer out. Each spring points its narrow end toward the hub. |
| 5 | Wipe the braking surface of the rim all the way round | Wipe the flat metal band the pads touch, all the way round. |
| 6 | Pinch pairs of spokes around the wheel to find a loose one | Pinch two spokes together at a time and work round the wheel. A loose one gives more. |
| 7 | Turn the wheel and look along the tire for cuts and glass | Turn the wheel a full circle and look along the tread for cuts or glass. |
| 8 | Slide the skewer back through the hub, lever on the left | Slide the skewer back through, lever on the left side, springs narrow end in. |
| 9 | Lower the fork onto the axle so it seats in both slots | Lower the fork onto the axle until it sits at the top of both slots. |
| 10 | Snug the nut, then close the lever flat along the fork blade | Snug the nut, then fold the lever flat along the fork, pointing up. |
| 11 | Squeeze the brake and spin the wheel to check it runs clear of the pads | Spin the wheel and squeeze the brake. It should run clear of both pads. |

Planted mistake, step 10: "The lever is pointing forward. Fold it back along the fork."

## Origami lesson: fortune teller (fill in from the new take)

| # | Title | Narration |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| 6 | | |
| 7 | | |
| 8 | | |
| 9 | | |

Planted mistake, the flip step: "Flip it over first. The seams should face down."
