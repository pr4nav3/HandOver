-- HandOver: Databricks Free Edition tables, Volume and dashboard queries.
-- Paste into the SQL editor (serverless warehouse), or run: python -m server.databricks --init
-- `python -m server.databricks --init` runs only the CREATE statements below, one by one, and replaces
-- `workspace.handover` with DATABRICKS_CATALOG.DATABRICKS_SCHEMA when those are set.
--
-- Conventions
--   events.step   0-based step index (same as the hub's `state.step`)
--   steps.n       1-based step number (same as lesson.json `n`), so join with  steps.n = events.step + 1
--   ts / *_at     UTC
--   events.kind   run_start/end/done/stop, step_enter, check, advance, mistake, check_offline,
--                 camera_connect/hello/first_frame/active/disconnect, auto_advance_hold
--   advance       from_step -> to_step; reason camera | button | voice; to_step = total means finished
--   check         done yes | no | unsure, confidence 0..1, latency_ms, reason (what differs, may be null)
--   mistake       mistake_kind behind | ahead, looks_like = 0-based step the frame resembles
--   extra         JSON string with any other fields the server sent

CREATE SCHEMA IF NOT EXISTS workspace.handover
  COMMENT 'HandOver: expert lessons cut from one video, and learner runs on the glasses';

CREATE TABLE IF NOT EXISTS workspace.handover.lessons (
  lesson_id  STRING    COMMENT 'Lesson folder id, e.g. fortune-teller-v1',
  title      STRING    COMMENT 'Lesson title',
  expert     STRING    COMMENT 'Who recorded the lesson, if known',
  duration_s DOUBLE    COMMENT 'Expert time for the whole task in seconds (end of the last step)',
  created_at TIMESTAMP COMMENT 'When the lesson was uploaded to Databricks (UTC)'
) COMMENT 'One row per lesson cut from an expert video';

CREATE TABLE IF NOT EXISTS workspace.handover.steps (
  lesson_id      STRING COMMENT 'Lesson id',
  n              INT    COMMENT '1-based step number; events.step + 1',
  title          STRING COMMENT 'Step title shown to the learner',
  start_s        DOUBLE COMMENT 'Step start in the expert video, seconds',
  end_s          DOUBLE COMMENT 'Step end in the expert video, seconds; end_s - start_s is the expert time',
  check_type     STRING COMMENT 'camera (checked against a reference frame) or manual (learner taps Next)',
  check_question STRING COMMENT 'Yes/no question the camera check asks'
) COMMENT 'Steps of each lesson with the expert timing';

CREATE TABLE IF NOT EXISTS workspace.handover.runs (
  run_id     STRING    COMMENT 'One learner attempt at one lesson',
  lesson_id  STRING    COMMENT 'Lesson id',
  learner    STRING    COMMENT 'Learner label, if given',
  started_at TIMESTAMP COMMENT 'Run start (UTC)',
  ended_at   TIMESTAMP COMMENT 'Run end (UTC), null while running or if abandoned'
) COMMENT 'Learner runs';

CREATE TABLE IF NOT EXISTS workspace.handover.events (
  event_id     STRING    COMMENT 'Client-side uuid4',
  run_id       STRING    COMMENT 'Run id, null outside a run',
  lesson_id    STRING    COMMENT 'Lesson id',
  step         INT       COMMENT '0-based step index the event belongs to',
  ts           TIMESTAMP COMMENT 'Event time (UTC)',
  kind         STRING    COMMENT 'Run, step/check/mistake, and privacy-safe camera lifecycle event kind',
  done         STRING    COMMENT 'check: yes, no or unsure',
  confidence   DOUBLE    COMMENT 'check or mistake confidence 0..1',
  latency_ms   INT       COMMENT 'check latency in ms',
  reason       STRING    COMMENT 'advance: camera, button or voice; check: what differs; check_offline: no_key, rate_limited, errors',
  from_step    INT       COMMENT 'advance: 0-based step left',
  to_step      INT       COMMENT 'advance: 0-based step entered; equals the step count when finished',
  mistake_kind STRING    COMMENT 'mistake: behind or ahead',
  looks_like   INT       COMMENT 'mistake: 0-based step the live frame resembles',
  extra        STRING    COMMENT 'Other fields as a JSON string'
) COMMENT 'Everything that happened during learner runs, one row per event';

CREATE VOLUME IF NOT EXISTS workspace.handover.lessons
  COMMENT 'Lesson files: lesson.json, frames/*.jpg, captions/*.vtt, clips/*.mp4 under <lesson_id>/';


-- ---------------------------------------------------------------- dashboard queries (not run by --init)

-- 1. Time per step: learners vs the expert (median seconds from entering a step to leaving it).
WITH entered AS (
  SELECT run_id, lesson_id, to_step AS step, ts AS t_in
  FROM workspace.handover.events WHERE kind = 'advance' AND run_id IS NOT NULL
  UNION ALL
  SELECT run_id, lesson_id, 0 AS step, ts AS t_in
  FROM workspace.handover.events WHERE kind = 'run_start'
),
left_step AS (
  SELECT run_id, lesson_id, from_step AS step, ts AS t_out
  FROM workspace.handover.events WHERE kind = 'advance' AND to_step > from_step AND run_id IS NOT NULL
),
per_run AS (
  SELECT e.run_id, e.lesson_id, e.step,
         min(unix_millis(l.t_out) - unix_millis(e.t_in)) / 1000.0 AS learner_s
  FROM entered e JOIN left_step l
    ON l.run_id = e.run_id AND l.step = e.step AND l.t_out > e.t_in
  GROUP BY e.run_id, e.lesson_id, e.step, e.t_in
)
SELECT p.lesson_id, s.n, s.title,
       round(percentile(p.learner_s, 0.5), 1) AS learner_median_s,
       round(s.end_s - s.start_s, 1)          AS expert_s,
       count(DISTINCT p.run_id)               AS runs
FROM per_run p
JOIN workspace.handover.steps s ON s.lesson_id = p.lesson_id AND s.n = p.step + 1
GROUP BY p.lesson_id, s.n, s.title, s.start_s, s.end_s
ORDER BY p.lesson_id, s.n;

-- 2. Manual-advance rate per step: share of forward advances on camera steps that the learner forced
--    with Next (button or voice) instead of the camera check passing.
SELECT e.lesson_id, s.n, s.title,
       count(*)                                                  AS advances,
       sum(CASE WHEN e.reason IN ('button', 'voice') THEN 1 ELSE 0 END) AS manual,
       round(avg(CASE WHEN e.reason IN ('button', 'voice') THEN 1.0 ELSE 0.0 END), 2) AS manual_rate
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.from_step + 1
WHERE e.kind = 'advance' AND e.to_step = e.from_step + 1 AND s.check_type = 'camera'
GROUP BY e.lesson_id, s.n, s.title
ORDER BY manual_rate DESC;

-- 3. False passes per step: the camera advanced the learner, and they came back to that step
--    (back button) within 60 seconds, i.e. the check said done when it was not.
WITH cam AS (
  SELECT run_id, lesson_id, from_step AS step, ts
  FROM workspace.handover.events WHERE kind = 'advance' AND reason = 'camera'
),
back AS (
  SELECT run_id, to_step AS step, ts
  FROM workspace.handover.events WHERE kind = 'advance' AND to_step < from_step
)
SELECT c.lesson_id, s.n, s.title,
       count(*) AS camera_passes,
       count(DISTINCT CASE WHEN b.run_id IS NOT NULL THEN c.run_id || ':' || cast(c.ts AS STRING) END) AS false_passes
FROM cam c
LEFT JOIN back b
  ON b.run_id = c.run_id AND b.step = c.step AND b.ts > c.ts AND b.ts <= c.ts + INTERVAL 60 SECONDS
JOIN workspace.handover.steps s ON s.lesson_id = c.lesson_id AND s.n = c.step + 1
GROUP BY c.lesson_id, s.n, s.title
ORDER BY false_passes DESC;

-- Main Genie question:
--   "Which step do people get stuck on?"

-- 4. Camera readiness and stability. camera_number is ephemeral; names and device ids are never collected.
SELECT date_trunc('day', ts) AS day,
       coalesce(get_json_object(extra, '$.source'), 'unknown')   AS source,
       coalesce(get_json_object(extra, '$.platform'), 'other')  AS platform,
       count_if(kind = 'camera_first_frame')                    AS ready_sessions,
       round(percentile_approx(try_cast(get_json_object(extra, '$.connect_latency_ms') AS DOUBLE), 0.5))
                                                                  AS median_ready_ms,
       round(percentile_approx(try_cast(get_json_object(extra, '$.connect_latency_ms') AS DOUBLE), 0.95))
                                                                  AS p95_ready_ms,
       count_if(kind = 'camera_disconnect')                     AS disconnects,
       count_if(kind = 'camera_disconnect' AND get_json_object(extra, '$.had_frame') = 'false')
                                                                  AS disconnected_before_video
FROM workspace.handover.events
WHERE kind IN ('camera_first_frame', 'camera_disconnect')
GROUP BY day, source, platform
ORDER BY day DESC, ready_sessions DESC;

-- 5. Vision-check health by lesson and step. Stale results are recorded for operations but excluded here.
SELECT e.lesson_id, e.step + 1 AS step, s.title,
       count(*) AS checks,
       round(avg(CASE WHEN e.done = 'yes' THEN 1.0 ELSE 0.0 END), 3) AS pass_rate,
       round(avg(CASE WHEN get_json_object(e.extra, '$.error_kind') IS NOT NULL THEN 1.0 ELSE 0.0 END), 3)
                                                                    AS error_rate,
       round(percentile_approx(e.latency_ms, 0.5))                  AS median_latency_ms,
       round(percentile_approx(e.latency_ms, 0.95))                 AS p95_latency_ms,
       count_if(e.done = 'no')                                     AS no_answers,
       count_if(e.done = 'unsure')                                 AS unsure_answers
FROM workspace.handover.events e
LEFT JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.kind = 'check' AND coalesce(get_json_object(e.extra, '$.stale'), 'false') = 'false'
GROUP BY e.lesson_id, e.step, s.title
ORDER BY error_rate DESC, p95_latency_ms DESC;

-- 6. Completion/replay/interruption funnel. Ratios are only over runs that emitted run_start.
WITH starts AS (
  SELECT run_id, lesson_id, ts,
         coalesce(get_json_object(extra, '$.attempt_kind'), 'new') AS attempt_kind,
         get_json_object(extra, '$.source') AS source
  FROM workspace.handover.events WHERE kind = 'run_start'
), outcomes AS (
  SELECT run_id,
         max(CASE WHEN kind = 'run_done' THEN 1 ELSE 0 END) AS completed,
         max(CASE WHEN kind = 'run_stop' THEN 1 ELSE 0 END) AS interrupted,
         max(try_cast(get_json_object(extra, '$.completion_ratio') AS DOUBLE)) AS completion_ratio,
         max(try_cast(coalesce(get_json_object(extra, '$.total_seconds'),
                               get_json_object(extra, '$.elapsed_seconds')) AS DOUBLE)) AS elapsed_seconds
  FROM workspace.handover.events
  WHERE kind IN ('run_done', 'run_stop')
  GROUP BY run_id
)
SELECT date_trunc('day', s.ts) AS day, s.lesson_id, s.source,
       count(*) AS runs,
       sum(coalesce(o.completed, 0)) AS completed,
       round(avg(coalesce(o.completed, 0)), 3) AS completion_rate,
       sum(CASE WHEN s.attempt_kind = 'replay' THEN 1 ELSE 0 END) AS replays,
       sum(coalesce(o.interrupted, 0)) AS interruptions,
       round(avg(o.completion_ratio), 3) AS average_completion,
       round(percentile_approx(o.elapsed_seconds, 0.5), 1) AS median_run_seconds
FROM starts s LEFT JOIN outcomes o ON o.run_id = s.run_id
GROUP BY day, s.lesson_id, s.source
ORDER BY day DESC, runs DESC;
