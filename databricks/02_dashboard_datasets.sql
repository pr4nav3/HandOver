-- HandOver / Databricks: dashboard datasets.
--
-- One query per dashboard dataset. In the dashboard: Data tab > Add SQL dataset > paste ONE query
-- (from its "-- @dataset" line down to its semicolon) > Run > rename the dataset to the name after
-- "@dataset". dashboard.md says which widget uses which dataset. Genie reuses some of them (genie.md).
--
-- Read-only: nothing here writes. Every query is fully qualified (workspace.handover.*).
--
-- Rules every query follows
--   * events.step, from_step, to_step, looks_like are 0-based; steps.n is 1-based. Join on n = step + 1.
--   * A forward advance is kind = 'advance' AND to_step > from_step. A back move is to_step < from_step.
--     The "ahead" catch advances two steps at once (k -> k + 2, reason camera); it counts as one advance
--     out of step k.
--   * A run is finished when it has an advance with to_step >= the lesson's step count.
--   * A run is abandoned when it is not finished and either has ended_at or has had no event for 15 minutes.
--     Anything else is in progress.
--   * Times shown to people are America/Chicago (Madison). Stored times stay UTC.
--   * Every dataset carries lesson_id so one Lesson filter drives the whole page.
--   * step_label = "05 Flip it over": zero-padded so the x axis sorts in step order.
--
-- Datasets
--   ds_lessons                 lesson list for the filter, plus step counts
--   ds_runs                    one row per run: outcome, duration, advances by camera and by hand
--   ds_time_per_step           learner median vs expert seconds per step (long format, for the bar chart)
--   ds_step_summary            one row per step: time, slowdown, manual rate, mistakes, false passes, drop-offs
--   ds_advance_method          how learners left each step: camera, button, voice (long format)
--   ds_manual_rate             camera steps only: share of advances forced by hand (Pranav's query 2)
--   ds_false_passes            camera passes the learner undid with Back within 60 s (Pranav's query 3)
--   ds_checks                  one row per camera check: verdict, confidence, latency
--   ds_check_latency_by_step   p50 and p90 check latency per step (long format)
--   ds_check_latency_overall   p50 and p90 check latency per lesson
--   ds_mistakes                behind / ahead catches per step
--   ds_abandoned               step where unfinished runs stopped
--   ds_check_offline           "Checks off" incidents (breaker opened)


-- @dataset ds_lessons
-- Lesson list for the Lesson filter. Also used as a small reference table on page 2.
SELECT
  l.lesson_id,
  l.title                                        AS lesson_title,
  round(l.duration_s, 1)                         AS expert_total_s,
  count(s.n)                                     AS steps,
  count_if(s.check_type = 'camera')              AS camera_steps,
  count_if(s.check_type = 'manual')              AS manual_steps
FROM workspace.handover.lessons l
LEFT JOIN workspace.handover.steps s ON s.lesson_id = l.lesson_id
GROUP BY l.lesson_id, l.title, l.duration_s
ORDER BY l.lesson_id;


-- @dataset ds_runs
-- One row per learner run. Counters: SUM(finished), COUNT(run_id), SUM(camera_advances),
-- SUM(manual_advances), SUM(mistakes). Runs-per-hour chart: started_local by hour, color outcome.
WITH step_count AS (
  SELECT lesson_id, count(*) AS total
  FROM workspace.handover.steps
  GROUP BY lesson_id
),
per_run AS (
  SELECT
    run_id,
    count_if(kind = 'advance' AND to_step > from_step AND reason = 'camera')              AS camera_advances,
    count_if(kind = 'advance' AND to_step > from_step AND reason IN ('button', 'voice'))  AS manual_advances,
    count_if(kind = 'advance' AND to_step < from_step)                                    AS back_moves,
    count_if(kind = 'mistake')                                                            AS mistakes,
    count_if(kind = 'check')                                                              AS checks,
    max(ts)                                                                               AS last_event_at
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL
  GROUP BY run_id
),
finish AS (
  SELECT e.run_id, min(e.ts) AS finished_at
  FROM workspace.handover.events e
  JOIN workspace.handover.runs r  ON r.run_id = e.run_id
  JOIN step_count c               ON c.lesson_id = r.lesson_id
  WHERE e.kind = 'advance' AND e.to_step >= c.total
  GROUP BY e.run_id
)
SELECT
  r.run_id,
  r.lesson_id,
  r.learner,
  from_utc_timestamp(r.started_at, 'America/Chicago')                         AS started_local,
  CASE WHEN f.finished_at IS NOT NULL THEN 1 ELSE 0 END                       AS finished,
  CASE
    WHEN f.finished_at IS NOT NULL THEN 'Finished'
    WHEN r.ended_at IS NOT NULL
      OR coalesce(p.last_event_at, r.started_at) < current_timestamp() - INTERVAL 15 MINUTES
      THEN 'Abandoned'
    ELSE 'In progress'
  END                                                                         AS outcome,
  round((unix_millis(f.finished_at) - unix_millis(r.started_at)) / 1000.0, 1) AS run_s,
  coalesce(p.camera_advances, 0)                                              AS camera_advances,
  coalesce(p.manual_advances, 0)                                              AS manual_advances,
  coalesce(p.back_moves, 0)                                                   AS back_moves,
  coalesce(p.mistakes, 0)                                                     AS mistakes,
  coalesce(p.checks, 0)                                                       AS checks
FROM workspace.handover.runs r
LEFT JOIN per_run p ON p.run_id = r.run_id
LEFT JOIN finish f  ON f.run_id = r.run_id;


-- @dataset ds_time_per_step
-- Learner median vs expert seconds per step, long format: one row per (step, series).
-- Learner time on a step = all time spent at that position in a run (revisits included), counted only
-- for runs that left the step forward at least once, so an abandoned step does not inflate the median.
-- Time at step 1 starts at run_start. Expert time = end_s - start_s from the cut lesson.
-- Expert rows exist for every step, so the chart is never empty.
WITH timeline AS (
  SELECT
    run_id, lesson_id, kind, ts,
    CASE WHEN kind = 'run_start' THEN 0 WHEN kind = 'advance' THEN to_step END AS position,
    lead(ts) OVER (PARTITION BY run_id ORDER BY ts)                            AS next_ts
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance', 'run_end')
),
segments AS (
  SELECT run_id, lesson_id, position AS step,
         (unix_millis(next_ts) - unix_millis(ts)) / 1000.0 AS secs
  FROM timeline
  WHERE kind <> 'run_end' AND next_ts IS NOT NULL
),
left_forward AS (
  SELECT DISTINCT run_id, from_step AS step
  FROM workspace.handover.events
  WHERE kind = 'advance' AND to_step > from_step AND run_id IS NOT NULL
),
per_run AS (
  SELECT s.run_id, s.lesson_id, s.step, sum(s.secs) AS learner_s
  FROM segments s
  JOIN left_forward l ON l.run_id = s.run_id AND l.step = s.step
  GROUP BY s.run_id, s.lesson_id, s.step
)
SELECT
  st.lesson_id,
  st.n,
  concat(lpad(cast(st.n AS STRING), 2, '0'), ' ', st.title) AS step_label,
  'Learners (median)'                                        AS series,
  round(percentile(p.learner_s, 0.5), 1)                     AS seconds,
  count(DISTINCT p.run_id)                                   AS runs
FROM per_run p
JOIN workspace.handover.steps st ON st.lesson_id = p.lesson_id AND st.n = p.step + 1
GROUP BY st.lesson_id, st.n, st.title
UNION ALL
SELECT
  lesson_id,
  n,
  concat(lpad(cast(n AS STRING), 2, '0'), ' ', title),
  'Expert',
  round(end_s - start_s, 1),
  CAST(NULL AS BIGINT)
FROM workspace.handover.steps
ORDER BY lesson_id, n, series;


-- @dataset ds_step_summary
-- One row per step with every per-step measure side by side. Table widget on page 1, and the shape
-- of the Genie "stuck" answer. Same definitions as the per-measure datasets below.
--   slowdown          learner median / expert seconds (2.0 = twice as long as the expert)
--   manual_rate       camera steps only: forward advances by button or voice / all forward advances
--   false_passes      camera passes undone with Back within 60 s
--   abandoned_here    unfinished runs whose last position was this step
WITH step_count AS (
  SELECT lesson_id, count(*) AS total FROM workspace.handover.steps GROUP BY lesson_id
),
timeline AS (
  SELECT
    run_id, lesson_id, kind, ts,
    CASE WHEN kind = 'run_start' THEN 0 WHEN kind = 'advance' THEN to_step END AS position,
    lead(ts) OVER (PARTITION BY run_id ORDER BY ts)                            AS next_ts
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance', 'run_end')
),
fwd AS (
  SELECT run_id, lesson_id, from_step AS step, reason, ts, event_id
  FROM workspace.handover.events
  WHERE kind = 'advance' AND to_step > from_step AND run_id IS NOT NULL
),
learner_time AS (
  SELECT t.lesson_id, t.position AS step, t.run_id,
         sum((unix_millis(t.next_ts) - unix_millis(t.ts)) / 1000.0) AS learner_s
  FROM timeline t
  WHERE t.kind <> 'run_end' AND t.next_ts IS NOT NULL
    AND EXISTS (SELECT 1 FROM fwd f WHERE f.run_id = t.run_id AND f.step = t.position)
  GROUP BY t.lesson_id, t.position, t.run_id
),
time_agg AS (
  SELECT lesson_id, step, percentile(learner_s, 0.5) AS learner_median_s, count(*) AS runs_measured
  FROM learner_time
  GROUP BY lesson_id, step
),
adv_agg AS (
  SELECT lesson_id, step,
         count(*)                                        AS forward_advances,
         count_if(reason = 'camera')                     AS by_camera,
         count_if(reason IN ('button', 'voice'))         AS by_hand
  FROM fwd
  GROUP BY lesson_id, step
),
back AS (
  SELECT run_id, to_step AS step, ts
  FROM workspace.handover.events
  WHERE kind = 'advance' AND to_step < from_step AND run_id IS NOT NULL
),
cam_flagged AS (
  SELECT f.event_id, f.lesson_id, f.step,
         max(CASE WHEN b.run_id IS NOT NULL THEN 1 ELSE 0 END) AS came_back
  FROM fwd f
  LEFT JOIN back b
    ON b.run_id = f.run_id AND b.step = f.step
   AND b.ts > f.ts AND b.ts <= f.ts + INTERVAL 60 SECONDS
  WHERE f.reason = 'camera'
  GROUP BY f.event_id, f.lesson_id, f.step
),
false_pass AS (
  SELECT lesson_id, step, count(*) AS camera_passes, sum(came_back) AS false_passes
  FROM cam_flagged
  GROUP BY lesson_id, step
),
mistake_agg AS (
  SELECT lesson_id, step,
         count(*)                                        AS mistakes,
         count_if(mistake_kind = 'behind')               AS behind,
         count_if(mistake_kind = 'ahead')                AS ahead
  FROM workspace.handover.events
  WHERE kind = 'mistake' AND run_id IS NOT NULL
  GROUP BY lesson_id, step
),
last_pos AS (
  SELECT run_id, lesson_id, max_by(position, ts) AS step, max(ts) AS last_move_at
  FROM timeline
  WHERE kind <> 'run_end'
  GROUP BY run_id, lesson_id
),
run_state AS (
  SELECT r.run_id, r.lesson_id, r.ended_at, lp.step,
         max(e.ts) AS last_event_at,
         max(CASE WHEN e.kind = 'advance' AND e.to_step >= c.total THEN 1 ELSE 0 END) AS finished
  FROM workspace.handover.runs r
  JOIN last_pos lp                     ON lp.run_id = r.run_id
  JOIN step_count c                    ON c.lesson_id = r.lesson_id
  LEFT JOIN workspace.handover.events e ON e.run_id = r.run_id
  GROUP BY r.run_id, r.lesson_id, r.ended_at, lp.step
),
abandon_agg AS (
  SELECT lesson_id, step, count(*) AS abandoned_here
  FROM run_state
  WHERE finished = 0
    AND (ended_at IS NOT NULL OR last_event_at < current_timestamp() - INTERVAL 15 MINUTES)
  GROUP BY lesson_id, step
)
SELECT
  s.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title)        AS step_label,
  s.check_type,
  round(s.end_s - s.start_s, 1)                                  AS expert_s,
  round(t.learner_median_s, 1)                                   AS learner_median_s,
  round(t.learner_median_s / nullif(s.end_s - s.start_s, 0), 1)  AS slowdown,
  coalesce(t.runs_measured, 0)                                   AS runs_measured,
  coalesce(a.forward_advances, 0)                                AS forward_advances,
  coalesce(a.by_camera, 0)                                       AS by_camera,
  coalesce(a.by_hand, 0)                                         AS by_hand,
  CASE WHEN s.check_type = 'camera' AND a.forward_advances > 0
       THEN round(a.by_hand / a.forward_advances, 2) END         AS manual_rate,
  coalesce(m.mistakes, 0)                                        AS mistakes,
  coalesce(m.behind, 0)                                          AS behind,
  coalesce(m.ahead, 0)                                           AS ahead,
  coalesce(fp.false_passes, 0)                                   AS false_passes,
  coalesce(ab.abandoned_here, 0)                                 AS abandoned_here
FROM workspace.handover.steps s
LEFT JOIN time_agg t     ON t.lesson_id = s.lesson_id  AND t.step = s.n - 1
LEFT JOIN adv_agg a      ON a.lesson_id = s.lesson_id  AND a.step = s.n - 1
LEFT JOIN false_pass fp  ON fp.lesson_id = s.lesson_id AND fp.step = s.n - 1
LEFT JOIN mistake_agg m  ON m.lesson_id = s.lesson_id  AND m.step = s.n - 1
LEFT JOIN abandon_agg ab ON ab.lesson_id = s.lesson_id AND ab.step = s.n - 1
ORDER BY s.lesson_id, s.n;


-- @dataset ds_advance_method
-- How learners left each step going forward, long format: one row per (step, method).
-- Stacked bar: Camera green, Button and Voice grey. Manual steps (step 1) only ever show Button/Voice.
SELECT
  s.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title) AS step_label,
  s.check_type,
  CASE e.reason WHEN 'camera' THEN 'Camera' WHEN 'voice' THEN 'Voice' ELSE 'Button' END AS method,
  count(*)                                                AS advances
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.from_step + 1
WHERE e.kind = 'advance' AND e.to_step > e.from_step AND e.run_id IS NOT NULL
GROUP BY s.lesson_id, s.n, s.title, s.check_type, method
ORDER BY s.lesson_id, s.n, method;


-- @dataset ds_manual_rate
-- Pranav's query 2, refined: camera steps only; share of forward advances the learner forced with
-- Next (button or voice) instead of the camera check passing. A high rate means the check is too strict
-- for that step, or the step is hard to show to the camera.
-- Change from Pranav's version: counts any forward advance (to_step > from_step), so the "ahead" jump
-- (k -> k + 2 by camera) is counted for step k instead of being dropped.
SELECT
  e.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title)                 AS step_label,
  count(*)                                                                AS advances,
  count_if(e.reason = 'camera')                                           AS by_camera,
  count_if(e.reason IN ('button', 'voice'))                               AS manual,
  round(avg(CASE WHEN e.reason IN ('button', 'voice') THEN 1.0 ELSE 0.0 END), 2) AS manual_rate
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.from_step + 1
WHERE e.kind = 'advance' AND e.to_step > e.from_step AND e.run_id IS NOT NULL
  AND s.check_type = 'camera'
GROUP BY e.lesson_id, s.n, s.title
ORDER BY e.lesson_id, s.n;


-- @dataset ds_false_passes
-- Pranav's query 3, refined: a camera pass is "false" when the learner pressed Back to that same step
-- within 60 s (the check said done when it was not). Lower bound: a learner who just carries on is not
-- counted.
-- Change from Pranav's version: one row per camera pass before counting, so two Back presses after one
-- pass do not count twice, and camera_passes is not inflated by the join.
WITH cam AS (
  SELECT event_id, run_id, lesson_id, from_step AS step, ts
  FROM workspace.handover.events
  WHERE kind = 'advance' AND reason = 'camera' AND to_step > from_step AND run_id IS NOT NULL
),
back AS (
  SELECT run_id, to_step AS step, ts
  FROM workspace.handover.events
  WHERE kind = 'advance' AND to_step < from_step AND run_id IS NOT NULL
),
flagged AS (
  SELECT c.event_id, c.lesson_id, c.step,
         max(CASE WHEN b.run_id IS NOT NULL THEN 1 ELSE 0 END) AS came_back
  FROM cam c
  LEFT JOIN back b
    ON b.run_id = c.run_id AND b.step = c.step
   AND b.ts > c.ts AND b.ts <= c.ts + INTERVAL 60 SECONDS
  GROUP BY c.event_id, c.lesson_id, c.step
)
SELECT
  f.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title) AS step_label,
  count(*)                                                AS camera_passes,
  sum(f.came_back)                                        AS false_passes,
  round(avg(f.came_back), 2)                              AS false_pass_rate
FROM flagged f
JOIN workspace.handover.steps s ON s.lesson_id = f.lesson_id AND s.n = f.step + 1
GROUP BY f.lesson_id, s.n, s.title
ORDER BY f.lesson_id, s.n;


-- @dataset ds_checks
-- One row per camera check. Verdict mix: COUNT(*) by step_label, color verdict.
-- Confidence: AVG(confidence) by step_label. Overall latency counter: MEDIAN(latency_ms).
-- timed_out = 1 for "unsure" at confidence 0: per CONTRACT.md section 8 a timeout or error is recorded
-- as unsure 0, so these are not real model answers.
SELECT
  e.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title)            AS step_label,
  e.run_id,
  from_utc_timestamp(e.ts, 'America/Chicago')                        AS ts_local,
  e.done                                                             AS verdict,
  e.confidence,
  e.latency_ms,
  CASE WHEN e.done = 'unsure' AND e.confidence = 0 THEN 1 ELSE 0 END AS timed_out,
  e.reason                                                           AS what_differs
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.kind = 'check';


-- @dataset ds_check_latency_by_step
-- p50 and p90 check latency per step, long format: one row per (step, stat). Timed-out checks are
-- included: they are what the learner waited for.
WITH c AS (
  SELECT e.lesson_id, s.n, s.title, e.latency_ms
  FROM workspace.handover.events e
  JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
  WHERE e.kind = 'check' AND e.latency_ms IS NOT NULL
),
agg AS (
  SELECT lesson_id, n, title,
         count(*)                     AS checks,
         percentile(latency_ms, 0.5)  AS p50,
         percentile(latency_ms, 0.9)  AS p90
  FROM c
  GROUP BY lesson_id, n, title
)
SELECT lesson_id, n, concat(lpad(cast(n AS STRING), 2, '0'), ' ', title) AS step_label,
       'p50' AS stat, round(p50) AS latency_ms, checks
FROM agg
UNION ALL
SELECT lesson_id, n, concat(lpad(cast(n AS STRING), 2, '0'), ' ', title),
       'p90', round(p90), checks
FROM agg
ORDER BY lesson_id, n, stat;


-- @dataset ds_check_latency_overall
-- p50 and p90 check latency per lesson, plus the timed-out share. Small table on page 2.
SELECT
  lesson_id,
  count(*)                                                                  AS checks,
  round(percentile(latency_ms, 0.5))                                        AS p50_ms,
  round(percentile(latency_ms, 0.9))                                        AS p90_ms,
  round(avg(CASE WHEN done = 'unsure' AND confidence = 0 THEN 1.0 ELSE 0.0 END), 3) AS timed_out_rate
FROM workspace.handover.events
WHERE kind = 'check' AND latency_ms IS NOT NULL
GROUP BY lesson_id
ORDER BY lesson_id;


-- @dataset ds_mistakes
-- Mistakes the camera caught, per step the learner was on, long format: one row per (step, kind).
--   Behind  the live frame still matches the previous step (a step was skipped or undone);
--           the step does not move.
--   Ahead   the live frame matches the next step; the hub confirms and jumps forward.
SELECT
  e.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title) AS step_label,
  CASE e.mistake_kind WHEN 'behind' THEN 'Behind' WHEN 'ahead' THEN 'Ahead'
       ELSE coalesce(e.mistake_kind, 'Unknown') END       AS mistake_kind,
  count(*)                                                AS mistakes,
  round(avg(e.confidence), 2)                             AS avg_confidence
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.kind = 'mistake' AND e.run_id IS NOT NULL
GROUP BY e.lesson_id, s.n, s.title, e.mistake_kind
ORDER BY e.lesson_id, s.n, mistake_kind;


-- @dataset ds_abandoned
-- Where unfinished runs stopped: the step each abandoned run was on at its last move.
-- In-progress runs (an event in the last 15 minutes and no ended_at) are left out.
WITH step_count AS (
  SELECT lesson_id, count(*) AS total FROM workspace.handover.steps GROUP BY lesson_id
),
moves AS (
  SELECT run_id, ts, CASE WHEN kind = 'run_start' THEN 0 ELSE to_step END AS position
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance')
),
last_pos AS (
  SELECT run_id, max_by(position, ts) AS step, max(position) AS furthest
  FROM moves
  GROUP BY run_id
),
run_state AS (
  SELECT r.run_id, r.lesson_id, r.ended_at, lp.step, lp.furthest, c.total,
         max(e.ts) AS last_event_at,
         max(CASE WHEN e.kind = 'advance' AND e.to_step >= c.total THEN 1 ELSE 0 END) AS finished
  FROM workspace.handover.runs r
  JOIN last_pos lp                      ON lp.run_id = r.run_id
  JOIN step_count c                     ON c.lesson_id = r.lesson_id
  LEFT JOIN workspace.handover.events e ON e.run_id = r.run_id
  GROUP BY r.run_id, r.lesson_id, r.ended_at, lp.step, lp.furthest, c.total
)
SELECT
  rs.lesson_id,
  s.n,
  concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title) AS step_label,
  count(*)                                                AS abandoned_runs
FROM run_state rs
JOIN workspace.handover.steps s ON s.lesson_id = rs.lesson_id AND s.n = rs.step + 1
WHERE rs.finished = 0
  AND (rs.ended_at IS NOT NULL OR rs.last_event_at < current_timestamp() - INTERVAL 15 MINUTES)
GROUP BY rs.lesson_id, s.n, s.title
ORDER BY rs.lesson_id, s.n;


-- @dataset ds_check_offline
-- "Checks off, use Next" incidents: one row per check_offline event (the breaker opened).
-- reason: no_key, rate_limited or errors. During these the learner advances by hand, which also
-- shows up as manual advances on camera steps.
SELECT
  e.lesson_id,
  from_utc_timestamp(e.ts, 'America/Chicago')                                        AS ts_local,
  e.reason,
  e.run_id,
  CASE WHEN s.n IS NOT NULL
       THEN concat(lpad(cast(s.n AS STRING), 2, '0'), ' ', s.title) END              AS step_label
FROM workspace.handover.events e
LEFT JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.kind = 'check_offline'
ORDER BY ts_local DESC;
