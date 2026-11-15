# Analytics

HandOver records small event metadata so a learner can see real progress and an operator can tell whether the
camera/check loop is healthy. Events are appended to `logs/events.jsonl`; when Databricks is configured they are
also batched to `workspace.handover.events`. Analytics never block camera streaming or lesson playback.

## What is measured

| Area | Events and fields |
| --- | --- |
| Run outcome | `run_start`, `run_done`, `run_stop`; attempt kind (`new`, `restart`, `replay`), completion ratio, elapsed time, camera/manual steps and aggregate check counts |
| Step learning | `step_enter`, `advance`, `mistake`; visit number, time on step, advance reason, checks/errors/mistakes on the step |
| Vision checks | `check`; yes/no/unsure, confidence, model, latency, error kind, stale flag, source and frame sequence number |
| Camera readiness | `camera_connect`, `camera_hello`, `camera_first_frame`, `camera_active`, `camera_disconnect`; source/platform, socket-to-hello/video latency, session duration and whether video ever arrived |
| Availability | `check_offline`; breaker open/closed and the coarse failure category |
| Learner control | `auto_advance_hold`; whether the learner paused or resumed camera auto-advance and on which step |

Checks that finish after a step or run changed are kept with `stale: true` for operational diagnosis, but are not
included in run aggregates or learner pass-rate summaries. A run selected over an unfinished run emits
`run_stop` with `restarted` or `switched`; selecting the same completed lesson is a `replay`.

## Privacy boundary

Analytics contain no camera frames, clips, audio, tokens, IP addresses, stable device IDs, or camera/device names.
`camera_number` is only an ephemeral counter for the current hub process. The signed-in learner ID is attached to
the run so progress can be scoped to that person; `GET /api/profile/analytics` returns only aggregates for the
authenticated caller and never returns that ID or raw events. Mock runs stay in the local mirror and are excluded
from profile aggregates and remote Databricks tables. A shared privacy guard drops binary values and sensitive
field names before both in-process sinks and JSONL writes. See `docs/privacy.md` for storage and retention details.

## Profile aggregates

`GET /api/profile/analytics` returns truthful values derived from the caller's event history: runs and completed
runs, completion rate, distinct courses completed, practice minutes, active-day streak, check pass/error rates,
average check latency, camera-verified/manual steps, mistakes caught, replay/interruption counts, used camera
sources, and median camera-ready latency where samples exist. `known: false` means there are no real runs; clients
must show an empty state instead of seed numbers. Demo screenshots may use preset data, but must label it as demo.

## Databricks

Run `python -m server.databricks --init` to create the schema, tables and lesson volume. The queries at the bottom
of `server/static/databricks_init.sql` cover learner-versus-expert time, manual advances, likely false passes,
camera readiness/stability, check latency/errors, and the completion/replay/interruption funnel. All new event
fields travel in the `extra` JSON column, so an existing table does not need a destructive migration.

For local inspection, set `HANDOVER_NO_NETWORK=1` and use `python -m server.databricks --tail`. The current mirror
and its single retained `.1` rotation both feed profiles; corrupt lines are skipped. Never attach either file to bug
reports without reviewing it: they contain lesson/run IDs and, for signed-in runs, learner IDs.
