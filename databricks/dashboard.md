# Dashboard: HandOver: learner runs

AI/BI dashboard, id `01f1e086926f1ffc9624630fda6e58c3`. Published with embedded credentials, so the published link works without a warehouse login for the viewer.

- Published: https://dbc-a03072b4-3eeb.cloud.databricks.com/dashboardsv3/01f1e086926f1ffc9624630fda6e58c3/published
- Editor: https://dbc-a03072b4-3eeb.cloud.databricks.com/dashboardsv3/01f1e086926f1ffc9624630fda6e58c3

`handover.lvdash.json` is the saved dashboard exactly as the API returns it. To restore it: Dashboards > Create dashboard caret > Import dashboard from file, or PATCH it through the Lakeview API.

## Data

15 datasets. Every one has `lesson_id`, so one Lesson filter drives a page.

Widget specs follow the current Lakeview schema: bar version 3, counter version 2, table version 2 (columns carry only `fieldName` and `displayName`), filter-single-select version 2, text widgets as `multilineTextboxSpec`. Counters hide their description (`showDescription: false`) because the subtitle was cut off at 1 column wide.

| Dataset | Query |
|---|---|
| `ds_lessons`, `ds_runs`, `ds_time_per_step`, `ds_step_summary`, `ds_advance_method`, `ds_manual_rate`, `ds_false_passes`, `ds_checks`, `ds_check_latency_by_step`, `ds_check_latency_overall`, `ds_abandoned`, `ds_check_offline` | `SELECT * FROM workspace.handover.<name>_real` |
| `ds_mistakes` | The columns of `ds_mistakes_real`, with `mistake_kind` `live` shown as `Live` (Behind and Ahead are already capitalized in the view) |
| `ds_advances` | One row per forward advance in `events_real`, joined to `runs_real`: `run_started` (CST), `method` Camera, Button or Voice, `steps` = 1, `camera_pct` = 100 or 0 |
| `ds_check_latency_rows` | One row per answered check in `events_real`: `latency_s`. Mock checks and errored checks (any `error_kind`) are left out |

The `_real` views leave out replay runs, mock runs and selftest rows. They keep rendered test lessons such as `synthetic-fortune-teller-v1`, so pick the real lesson in the filter. Per-step widgets need `steps` rows for the lesson.

## Page 1: Where learners get stuck

The main page. Positions are (x, y, width, height) on the 6-column grid.

| Widget | Type | Dataset | Position | Shows |
|---|---|---|---|---|
| "Where do learners get stuck?" | Text | | 0, 0, 6, 2 | What the page answers; live camera runs only |
| Lesson | Filter, single | 8 page-1 datasets | 0, 2, 2, 1 | `lesson_id`, labeled Lesson |
| Legend | Text | | 2, 2, 4, 1 | Green = camera, grey = Next, amber = mistake; times in CST |
| Runs | Counter | ds_runs | 0, 3, 1, 2 | COUNT(run_id) |
| Finished | Counter | ds_runs | 1, 3, 1, 2 | SUM(finished) |
| Steps passed | Counter | ds_advances | 2, 3, 1, 2 | SUM(steps) |
| Camera-checked % | Counter | ds_advances | 3, 3, 1, 2 | AVG(camera_pct); manual steps always count as Next |
| Mistakes caught | Counter | ds_runs | 4, 3, 1, 2 | SUM(mistakes) |
| Check p50 (s) | Counter | ds_check_latency_rows | 5, 3, 1, 2 | MEDIAN(latency_s) |
| Time per step: learners vs the expert | Grouped horizontal bar | ds_time_per_step | 0, 5, 6, 7 | Learner median per step next to the expert's time; legend titled Who. Until a live run reaches a step, only the Expert bar shows |
| How each step was passed | Stacked horizontal bar | ds_advance_method | 0, 12, 3, 6 | Advances per step by Camera, Button, Voice |
| Mistakes the camera caught, per step | Stacked horizontal bar | ds_mistakes | 3, 12, 3, 6 | Behind, Ahead, Live |
| Step by step | Table | ds_step_summary | 0, 18, 6, 6 | Step, check type, expert s, learner median s, x expert, Next on camera steps, mistakes, false passes, stopped here, runs |
| Steps per run | Stacked bar | ds_advances | 0, 24, 6, 5 | One bar per run by start time, split by method |

## Page 2: Camera check quality

| Widget | Type | Dataset | Position | Shows |
|---|---|---|---|---|
| "How well does the camera check work?" | Text | | 0, 0, 6, 2 | What the page answers |
| Lesson | Filter, single | 8 page-2 datasets | 0, 2, 2, 1 | `lesson_id` |
| Note | Text | | 2, 2, 4, 1 | Latency counts answered checks only |
| Check answers per step | Stacked horizontal bar | ds_checks | 0, 3, 3, 6 | COUNT by verdict yes, no, unsure |
| Check latency per step (p50, p90) | Grouped horizontal bar | ds_check_latency_by_step | 3, 3, 3, 6 | ms |
| Manual-advance rate (camera steps) | Horizontal bar | ds_manual_rate | 0, 9, 3, 6 | Share of camera-step advances forced with Next |
| Average check confidence per step | Horizontal bar | ds_checks | 3, 9, 3, 6 | AVG(confidence) |
| False passes | Table | ds_false_passes | 0, 15, 3, 5 | Camera passes undone with Back within 60 s |
| Latency per lesson | Table | ds_check_latency_overall | 3, 15, 3, 5 | checks, p50 ms, p90 ms, timed out |
| Where unfinished runs stopped | Horizontal bar | ds_abandoned | 0, 20, 3, 5 | Abandoned runs per step |
| Checks off incidents | Table | ds_check_offline | 3, 20, 3, 5 | Time (CST), reason, step |
| Lessons | Table | ds_lessons | 0, 25, 6, 3 | Lesson, title, steps, camera and manual steps, expert total |

## Colors

One meaning per color, the same in every widget.

| Meaning | Hex |
|---|---|
| Camera (method Camera, verdict yes) | `#30D158` |
| Mistake Behind / Ahead / Live | `#FF9F0A` / `#FFCC66` / `#C27C0E` |
| Learners (median), verdict no, p50 | `#3A3A3C` |
| Button, single-series bars | `#8E8E93` |
| Expert, Voice, verdict unsure, p90 | `#C7C7CC` |

## Verified

- Every widget field exists in its dataset (checked against `information_schema`); all 15 dataset queries run.
- The PATCH saved: a fresh GET returns the same JSON, and the publish has `embed_credentials: true`.
- Every per-step bar chart is horizontal (steps on the y axis, full "05 Title" labels), because 9 long step titles were cut off on a vertical x axis. Steps per run stays vertical (short time labels). Legend titles: Who, Passed by, Kind, Answer, Latency.
- Not checked in a browser: the rendering itself (the `MEDIAN` counter, the order of steps on the y axis). Open the published link once before judging; that also warms the warehouse.

## Before judging

1. Open the published link. Pick the real lesson in the Lesson filter on page 1.
2. Read the numbers off the screen. With few runs, say "in our runs today".
3. Do not edit, and never set a refresh schedule (Free Edition quota).
