# Privacy

HandOver is a local hub. Learner camera frames travel from the chosen camera to the hub, are held only as the
newest in-memory frame, and may be sent to the configured vision provider to check the current step. They are not
written to the event log, Databricks, course folders, profile history, or analytics responses.

## What is stored

- Course content intentionally stores the expert's uploaded take, generated clips, captions and reference frames.
- `logs/events.jsonl` stores compact learning and operational metadata: event/run/lesson IDs, timestamps, step
  numbers, check outcomes/confidence/latency and coarse reason text, advances, mistakes, camera source/platform,
  connection timing, and completion totals.
- A signed-in run stores the learner's internal hub user ID so only that person's progress can be aggregated.
- The event mirror rotates at 50 MB and keeps one `.1` file. Both retained files contribute to local profile
  analytics. On POSIX systems the hub sets the mirror to owner-only mode (`0600`).
- When Databricks credentials are configured, non-mock metadata is copied to the configured Unity Catalog tables.
  Course lesson files are uploaded to the configured Volume separately.

Analytics do not store learner camera images, learner audio, stable device IDs, camera/device names, IP addresses,
authorization headers, passcodes, or auth tokens. An event privacy guard drops binary values, sensitive field names,
oversized containers and unsupported objects before any event sink or JSONL write. `camera_number` is an ephemeral
counter that resets with the hub process; `frame_seq` is only a frame counter, not image data.

## Who can read progress

`GET /api/profile/analytics` requires a valid signed-in hub user and always scopes the calculation to that user's
internal ID. It returns aggregate counts/rates only—never raw events, IDs, model reason text or another learner's
data. Course-level insights use the existing course/organization permission checks.

Anyone who can read files as the operating-system account running the hub can still read the local event mirror and
course content. Protect that account and machine, and do not attach the JSONL file to a bug report without reviewing
it. Databricks access is governed by the workspace/catalog permissions configured by its administrator.

## Failure behavior and retention

Analytics are off the live camera path: a slow or unavailable warehouse never delays a check or lesson advance.
The local mirror is the fallback if remote delivery fails. A bounded in-memory upload queue can drop old remote rows
under sustained failure, while the local mirror remains. Corrupt JSONL lines are skipped so the app stays usable;
therefore aggregates can be incomplete after disk corruption or after history ages beyond the two retained files.

Set `HANDOVER_NO_NETWORK=1` for tests/offline development. Mock runs remain in the local mirror for debugging but
are excluded from signed-in profile aggregates and are never uploaded to Databricks.
