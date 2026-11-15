# Privacy: what HandOver does with the camera

The one-line version for the demo and the Devpost: **the hub never saves your camera frames.** It holds the newest frame in memory, asks the model whether the step is done, and throws the frame away.

## What happens to a learner's camera frames

| Where | What | Kept? |
|---|---|---|
| Phone or laptop camera | JPEG frames, about 12 a second, long side 640 px | sent over the local network only (HTTPS on the phone page, the hub's own certificate) |
| Hub, in memory | only the newest frame per camera; older ones are dropped | never written to disk; `server/test_engine.py::test_privacy_learn_frames_never_touch_disk` asserts it on every run |
| Vision model (Claude Haiku, or Gemini) | one live frame plus the step's reference frame, about once a second when the picture is still and changed | sent for the check and not stored by us; the model provider's API terms apply (no training on API data) |
| Learn screen in the browser | the live picture, drawn on a canvas | never stored |
| Event log (`logs/events.jsonl`) and Databricks | run id, lesson id, step numbers, check answers, confidence, latency, timestamps | kept; contains no images and no names |

Nothing identifies the learner: there are no accounts in the demo build, and the event rows carry a random run id.

## What the expert's take becomes

The expert's recording is the product content: it is cut into step clips, reference frames and captions in `lessons/<id>/`, and the narration is synthesized from the step titles. It stays on the laptop (and in the team repo). Lesson files can be copied to a Databricks Volume for the dashboard; that is the expert's video, never a learner's camera.

## What the screens say

- Phone camera page: "Frames go to the hub on this network, which sends them to the AI model for each check. The hub never saves them."
- Learn screen, when a replay is the source: a Recording tag, so a recorded video is never mistaken for a live camera.
- Checks off: the badge says so and Next always works, so nothing is ever decided silently.

## Demo line (last 20 seconds)

"The hub never saves your camera frames. It keeps one in memory, asks whether the step is done, and lets it go. What we keep is the expert's take and a log of which steps the camera confirmed, which is what the dashboard shows."
