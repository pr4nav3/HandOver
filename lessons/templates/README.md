# Lesson step templates

Hand-written step plans for the two demo lessons. Use one when Gemini's step boundaries or check questions come out weak on a real take.

| File | Lesson | Steps | Manual steps |
|---|---|---|---|
| `fortune-teller.steps.json` | Origami fortune teller | 8 | 1, 3, 7 |
| `front-wheel.steps.json` | Bike front wheel, quick release | 9 | 1, 6 |

Each file has the same shape as `Extraction` in `server/teach.py`: `transcript` (empty), `steps`, `safety`, `tools`. Every step has `start`, `end`, `title`, `check_question`, `prerequisites`, `ref_time` and `common_mistake`.

- A step is manual when `check_question` is `"manual"`. The `check_type` field in these files is there so people can read them; the CLI ignores it and writes `check_type` into lesson.json from the question.
- `ref_time` is empty, so the cutter picks the stillest frame in the last 15% of each step as the reference.
- `_note` is ignored by the CLI.

## The times are placeholders

Every `start` and `end` is an even split (12 s per fold, 13 s per bike step). It is not the real take. Retime before you cut, or the clips will not match the expert's hands.

## Cut a lesson from a take

`scripts/new_lesson.sh` has no `--steps-json` option today, so call the teach CLI directly from the repo root:

```sh
cp lessons/templates/fortune-teller.steps.json /tmp/ft.steps.json   # edit the times in the copy
.venv/bin/python -m server.teach take1.mov --id fortune-teller-v1 --title "Fold a fortune teller" \
  --steps-json /tmp/ft.steps.json [--concat take2.mov]
```

- Add `--dry-run` first: it prints the planned cuts and writes nothing.
- Unlike `new_lesson.sh`, the CLI does not refuse an existing id. Pick a new id or remove the old folder by hand.
- With a steps file there is no Gemini call, so the transcript is empty and captions are empty files. `lesson_lint.py` warns "no cues" for every step; that warning is expected.
- A step that falls past the end of the video is dropped, and a step that runs past it is cut short.

## Retime from the take

Watch the normalized take (`norm.mp4` in the lesson folder, or the original) and write down, for each step, the moment the hands start that step's action. Then:

- `start` of step 1: when the task begins (paper on the mat, or hands reaching for the brake).
- `start` of every later step: the moment the hands start the new action. The expert's words ("now flip it over") are the best marker.
- `end` of each step: the same time as the next step's `start`. Steps must not overlap; a gap only warns.
- `end` of the last step: when the finished state is shown with hands clear (fortune teller standing up; wheel spun and brake squeezed).
- Formats: `"MM:SS"` or `"MM:SS.s"`, for example `"01:07.5"`.

Two places to fix times:

1. Before the first cut: edit your copy of the template, then run the command above.
2. After a cut: edit `start` and `end` in `lessons/<id>/lesson.json` and recut. Set `ref_time` to `""` on every step you moved, or recut keeps the old reference frame whenever it still falls inside the step.

```sh
.venv/bin/python -m server.teach --recut lessons/fortune-teller-v1
curl -X POST http://localhost:8000/api/lessons/fortune-teller-v1/recut   # when the hub is running
```

Recut keeps titles, questions, common mistakes, safety and tools, and leaves the old files in place if any time is bad. Then run `.venv/bin/python scripts/lesson_lint.py lessons/<id>` and `.venv/bin/python -m server.teach --self-test lessons/<id>`. If the self-test fails a camera step, reword its question or make it manual.

## Why each question is phrased this way

The live check sees one reference frame, one live frame and the question. A good question has a yes on this step's finished frame and a no on the previous step's frame (that is what the self-test checks). No question mentions color: the paper is two-sided, hall light shifts color, and the lint warns on color words.

Fortune teller:

1. Manual. The starting setup cannot be judged reliably by camera (the plan's step 1 rule).
2. "single triangle with three corners": the previous frame is a square with four corners, so the corner count decides it.
3. Manual. Fold and unfold leaves only faint crease lines, which a low-resolution frame cannot see.
4. "smaller square with four triangular flaps whose points meet at the center": the previous frame is a flat square with no flaps.
5. "plain square with no flaps on it, only crease lines": after the flip the flaps are underneath. This catches the skipped flip, because an unflipped sheet still shows four flaps.
6. "small square with four triangular flaps whose points meet at the center": the previous frame is the plain side from step 5.
7. Manual. Same reason as step 3: the half creases are not visible from above.
8. "stand up in four separate pointed pockets instead of lying flat": the only step where the paper leaves the mat, so 3D against flat is a clear difference.

Bike front wheel:

1. Manual. Starting setup, same rule as the fortune teller. If you want it on camera, use "Are the brake arms spread open, wider than the tire?"
2. "lever swung open, standing out away from the fork blade": the lever's angle to the fork blade is the clearest visible state on the wheel.
3. "nut on the side opposite the lever backed off, with a gap between it and the fork end": a few turns show as a visible gap. This is the weakest camera question at 360x640; make it manual if the self-test fails it.
4. "wheel fully out of the fork, with both fork ends empty": empty dropouts (the slots at the fork ends) against a wheel in place.
5. "axle seated all the way into the slots of both fork ends, with the wheel centered between the fork blades": what a correct install looks like. The previous frame has no wheel.
6. Manual. "Until the lever resists halfway" is felt in the hand, not seen.
7. "lever closed, lying flat along the fork blade": the opposite of step 2, and the safety-critical state.
8. "brake arms closed in, with a pad near the rim on each side": the previous frame has the arms still spread open.
9. "hand squeezing the brake lever on the handlebar": the earlier steps all happen at the wheel, so a hand on the brake lever is a new, visible state. A spinning wheel cannot be judged from one frame.
