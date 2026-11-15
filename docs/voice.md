# Voice

One voice for everything the product says: lesson narration and the app's own cues. It should sound like a calm person coaching you, not a screen reader.

## The voice

- Default engine: Kokoro, voice `af_heart` (`HANDOVER_VOICE`), speed 0.95 (`HANDOVER_VOICE_SPEED`), with a short breath between sentences. Kokoro runs locally and needs no network.
- Optional engine: ElevenLabs. Set `HANDOVER_TTS_PROVIDER=elevenlabs` and `ELEVENLABS_API_KEY` in `.env` (the free tier, about 10k characters a month, covers several lessons and the cues). The default ElevenLabs voice is Sarah; set `HANDOVER_ELEVEN_VOICE` to another voice id and `HANDOVER_ELEVEN_MODEL` to change the model. Mixing, caption timing and cues work the same way with either engine. If the key or the network is missing, Kokoro is used instead.

## Choosing or changing the voice

1. Audition: `python -m server.voice --audition "That's it. Next step. Fold the top corner down to meet the bottom one, and press the crease flat." --voices af_heart,af_bella,af_nicole,am_adam,bm_george --out audition` renders the same line once per Kokoro voice into `audition/<voice>.mp3`, so you can pick by ear.
2. Write the choice into `.env`: `HANDOVER_VOICE=<kokoro voice>`, or the ElevenLabs settings above.
3. Re-voice each lesson (`scripts/make_lesson.ps1 -Id <id> -Recut`, or `python -m server.voice lessons/<id> --script ... --mode replace`) and regenerate the cues (`python -m server.voice --cues web/public/voice`), so lessons and cues share one voice.

## Rules for every line

- Second person, present tense, one action per sentence. "Fold the top corner down to the bottom one."
- Sounds like a person next to you: contractions are fine ("that's it", "you're"), short pauses between sentences, calm, never hyped.
- One or two sentences, at most 22 words, about 2.5 words per second of clip.
- Name shapes and counts, never colors. Never read the check question aloud.
- No "please", no "simply", no exclamation marks, no "great job" or other praise words. Acknowledge with a plain "that's it".
- The first word is the verb when possible.

## App cues

The fixed cues are pre-rendered in the lesson voice (`APP_CUES` in `server/voice.py`) and played by the Learn screen (`web/src/cues.ts`).

| Event | Line | When |
|---|---|---|
| Camera verified a step | "That's it. Next step." | on `advance` with reason camera, right after the chime |
| Learner pressed Next | nothing | the click is the acknowledgment |
| Mistake, behind, with no message | "Not quite yet. Take another look at the clip." | once per mistake |
| Mistake, ahead | "You're ahead of me. Let's go back one step." | once |
| Lesson complete | "That's the whole thing. Nicely done." | on done |
| Checks off | "I can't see well right now. Tap Next when you're done." | once when the breaker opens |
| Camera lost | "I lost the camera. Keep going with Next." | once |

When a mistake carries its own message (a step's `common_mistake`), that text is spoken by the browser's own speech synthesis, not the lesson voice, because it is per-lesson text with no pre-rendered file. Cue files live in `web/public/voice/` and are served by the hub; the browser also falls back to its own speech if a cue file is missing. A toggle in the Learn ⋯ popover turns cues off.

## Example narration: front wheel check

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

A step's `common_mistake` follows the same rules, for example "The lever is pointing forward. Fold it back along the fork."
