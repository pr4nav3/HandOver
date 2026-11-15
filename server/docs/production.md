# Course production

`server/produce.py` turns a lesson's cut steps into edited tutorial videos. It runs on its own after a take is cut, and the editor can re-run it with a new style at any time. The original clips are never changed, so a player or the editor can switch between the original and the produced version.

## What it makes

| File | What it is |
|---|---|
| `clips_produced/NN.mp4` | One edited clip per step |
| `clips_produced/NN.vtt` | That clip's captions, shifted to its timeline |
| `produced/course.mp4` | Intro card, every step with 300 ms crossfades, outro card |
| `produced/course.vtt` | Captions for the whole course |
| `produced/chapters.vtt` | One chapter per step, for chapter navigation |
| `produced/cover.jpg` | Lesson title beside the best frame (the finished result) |
| `produced/assist.json` | Action regions and key moments, reused by re-renders |

Each produced step has:

- **Title card**: 1.2 s on solid theme paper. A small sharp thumbnail of the step's first frame (12 px corners, hairline edge) sits above "Step N" and the title, then the card crossfades into the clip. Can instead be laid over the clip, or turned off.
- **Step label**: "Step N of M" and the title, bottom left, for the first 2.5 s. Fades in with a small rise.
- **Progress bar**: a thin bar along the bottom showing where this moment sits in the whole course.
- **Push-in**: a slow ease in-out zoom toward the action region, at most 1.3x. The zoom stops early enough that the region and a margin around it stay in view, so hands are never cut off. With no known region it is a gentle 1.08x toward the center.
- **Highlight**: a rounded ring around the action region at the step's key moment, for 1 s, with a soft scale-in. It only shows when the region is known and compact. A ring around most of the frame points at nothing, so it is skipped.
- **Instructional guides**: optional timed crease lines, fold arrows, and pulsing targets authored as normalized coordinates. They draw on over 650 ms, fade cleanly, inherit the theme accent, and move through the same push-in as the paper beneath them.
- **Captions**: burned in when the style asks for it. Soft captions are always written.
- **Audio**: the clip's current mix (voiceover included), normalized to -16 LUFS with two-pass loudnorm.

All text is drawn with Pillow in the system San Francisco font and composited by ffmpeg. No drawtext or libass is needed.

## Style

The style lives in `lesson.json` under `"production"`. The editor changes it there or passes it to `produce()`, which merges it in and saves it.

| Key | Values | Default |
|---|---|---|
| `theme` | A theme id from `apps/design/THEMES.md` (`system`, `night`, `ivory`, `mono`, ...). Add `-light` or `-dark` to pick a look. `dark` and `light` also work | `system` |
| `title_cards` | `card`, `overlay` or `off` | `card` |
| `zoom` | `true` or `false` | `true` |
| `highlight` | `true` or `false` | `true` |
| `burn_captions` | `true` or `false` | `false` |
| `accent` | `"#RRGGBB"`, or `null` for the theme's accent | `null` |

Colors follow the design docs:

- Cards, the intro, the outro and the cover use the theme's look.
- Anything over video (step label, progress bar, ring) uses the theme's dark look, the same way the apps force dark controls over video.
- Captions are always white semibold text on black at 72%.

Captions stay soft by default because the players already draw `captions/NN.vtt`. Turn on burning for exports and sharing.

### Per-step overrides

The editor can fix one step without touching the rest:

```json
"production": {
  "theme": "system",
  "steps": { "3": {
    "region": [0.30, 0.20, 0.65, 0.80], "key_time": 2.4, "zoom": false, "highlight": true,
    "guides": [{
      "start": 1.0, "end": 3.2,
      "creases": [[[0.30, 0.50], [0.65, 0.50]]],
      "arrows": [[[0.30, 0.75], [0.48, 0.50]]],
      "targets": [[0.48, 0.50]]
    }]
  } }
}
```

`region` is `[x0, y0, x1, y1]` as fractions of the frame. `key_time` is seconds into the step's clip.
Guide coordinates use the same normalized frame space; their `start` and `end` are seconds into that clip.

## Where regions and key moments come from

In order:

1. A per-step override in `production.steps`.
2. `rubric.json` in the lesson folder. It holds `{"steps": [{"n": 1, "region": [...]}]}` or `{"1": {"region": ...}}`, with fractions or pixels.
3. One Claude call per lesson (model `HANDOVER_PRODUCE_MODEL`, structured output). It sees each step's start, middle and end frames at 512 px. The answer is cached in `produced/assist.json` and only asked again when a clip changes.
4. Nothing. The push-in goes to the center and there is no ring.

The key moment is the override, then the step's `ref_time`, then Claude's guess, then 60% of the way through the clip.

The Claude call asks `server/spend.py` first and records its cost after. It makes no call when `HANDOVER_NO_NETWORK=1`, when there is no key, or when the budget is used up. A typical lesson costs well under a cent ($0.0008 for 8 steps).

## Running it

```
python -m server.produce lessons/<id> [--no-zoom] [--no-cards] [--title-cards overlay]
    [--no-highlight] [--burn-captions] [--soft-captions] [--theme NAME] [--accent #RRGGBB]
    [--steps 2,3] [--no-assist]
```

CLI flags are saved into the style, the same way an editor change is.

From code:

```python
from server import produce
produce.produce(lesson_dir, style={"theme": "ivory", "burn_captions": True})   # render
produce.produce(lesson_dir, steps=[3])   # re-render step 3, rebuild the course
produce.status(lesson_dir)   # {"present", "stale", "style", "output"}
```

`status()` reports `stale` when any clip changed after the last render, for example after a recut or a voiceover.

## Safety and speed

- Everything renders into `.produce_tmp-*` inside the lesson and is swapped in only when every step and the course succeeded. A failure leaves the previous output and style exactly as they were.
- Steps render in parallel, at most 3 ffmpeg processes (`HANDOVER_PRODUCE_JOBS`). It first waits while the 5 minute load average is above 1.5 x the cores.
- Encoding is libx264 veryfast, CRF 20, yuv420p TV range, BT.709 tags, `+faststart`.
- Measured on this Mac: a 33 s, 8 step 1080p course renders in 5 to 12 s, about 9 to 21 s per minute of video.

## Settings

| Name | Default | Meaning |
|---|---|---|
| `HANDOVER_PRODUCE_MODEL` | `claude-haiku-5-5` | Claude model that marks action regions |
| `HANDOVER_PRODUCE_JOBS` | `3` | Steps rendered at once, 1 to 3 |
| `HANDOVER_PRODUCE_FONT` | system SF | A `.ttf` or `.ttc` to draw text with |

## Tests

`python -m server.test_produce` runs offline. It checks overlay image sizes, the filter graph strings, styles and themes, captions, region sources with a fake Claude, the budget block, and a real two-step render of a copy of `lessons/demo-v1` checked with ffprobe.
