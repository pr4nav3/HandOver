# Genie space: HandOver learner runs

Genie space id `01f1e086eb621d8d990021c7016818de`: https://dbc-a03072b4-3eeb.cloud.databricks.com/genie/rooms/01f1e086eb621d8d990021c7016818de

This file is what is live, saved through the Genie API (serialized space version 2). Demo question: "Which step do people get stuck on?"

## Settings

- Title: `HandOver learner runs`
- Description: "Learner runs of HandOver lessons. An expert recorded each task once; HandOver cut it into steps, and a camera checks each step before the next clip plays. Ask where learners get stuck, which steps they pass with Next instead of the camera, and what mistakes the camera caught. Live runs only; test lessons are left out unless you ask."
- Warehouse: the one Free Edition warehouse.
- Data: `workspace.handover.events_real`, `workspace.handover.runs_real`, `workspace.handover.lessons`, `workspace.handover.steps`. The raw `events` and `runs` tables are not in the space, so answers never include replay, mock or selftest runs.
- Sample questions (shown as buttons, in this order as the API returns them): "Which step do people get stuck on?"; "How fast is the camera check?"; "How many runs finished, and how long did a finished run take?"; "Which camera steps do learners skip with Next most often?"; "How long does each step take learners compared with the expert?".

## Joins

All many to one.

| Left | Right | Condition |
|---|---|---|
| events_real | steps | `events_real.lesson_id = steps.lesson_id AND steps.n = events_real.step + 1` |
| events_real | runs_real | `events_real.run_id = runs_real.run_id` |
| runs_real | lessons | `runs_real.lesson_id = lessons.lesson_id` |
| steps | lessons | `steps.lesson_id = lessons.lesson_id` |

## General instructions

```
HandOver data. An expert recorded a task once; HandOver cut it into numbered steps. A learner does the task while a camera checks each step before the next clip plays. One run = one learner attempt at one lesson.

Tables. Use events_real and runs_real for anything about learner runs: they are the events and runs tables without replay runs (recorded video), mock checks and selftest rows. Use lessons and steps for the lesson and its expert timing. Do not query the raw events or runs tables.

Test lessons. Leave out every lesson whose lesson_id starts with synthetic-, test-, TEST- or e2e-, and lesson_id selftest, unless the user asks about test or synthetic data. Filter with lower(lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'. If nothing is left after the filter, say there are no real learner runs yet for that question, and offer to show the test data.

Lessons. fortune-teller-v2 (9 steps, a new take of the same fold) is the live demo lesson; fortune-teller-v1 is the older take of the same fold. front-wheel-v1 (bike front wheel check) is a recorded showcase and may have no rows; if a lesson the user names has no rows yet, say so plainly instead of guessing.

Lesson names. Users name lessons in words ("the fortune teller", "the bike wheel"). Match them with lessons.title or lesson_id LIKE '%fortune-teller%' (or '%front-wheel%'), not one exact id. When several versions match (fortune-teller-v1, fortune-teller-v2), use the newest version that has runs in runs_real and say which lesson_id you used.

Step numbering. events_real.step, from_step, to_step and looks_like are 0-based. steps.n is 1-based and is what people call "step 3". Always join events_real to steps with steps.lesson_id = events_real.lesson_id AND steps.n = events_real.step + 1 (for advances use from_step + 1). Always name a step as "Step <n>: <title>", never by the 0-based index.

Event kinds (events_real.kind): run_start, run_end, run_done, run_stop, step_enter, check, advance, mistake, check_offline.
- advance: the learner moved from from_step to to_step. reason = camera (the camera confirmed the step), button or voice (the learner pressed Next or said it). reason_detail keeps the hub's original reason (ahead_confirm and understand_override count as camera). to_step > from_step is forward; to_step < from_step is Back. to_step at least the lesson's step count means the learner finished.
- check: one camera check. done = yes, no or unsure; confidence 0 to 1; latency_ms; reason = what the model saw differ. get_json_object(extra, '$.error_kind') is null for an answered check and 'timeout', 'rate_limited', 'error', 'no_key' or 'budget' otherwise; leave errored checks out of latency.
- mistake: the camera caught a mistake on the current step. mistake_kind behind = the work still looks like the previous step; ahead = it already looks like the next step; live = a live mistake label.
- check_offline: camera checks were switched off (reason no_key, rate_limited, errors) and the learner used Next. A row with a null reason means checks came back on.

Definitions.
- Expert time of a step = steps.end_s - steps.start_s.
- Learner time on a step = time from entering the step until the next advance, summed over revisits, for runs that went forward from that step. Use the median across runs. Step 1 starts at run_start, so it includes setup time.
- Manual-advance rate = forward advances with reason button or voice / all forward advances, on steps with check_type = 'camera'. Steps with check_type = 'manual' always advance by Next; leave them out of that rate.
- "Stuck", "hardest", "slowest", "where people struggle": the step with the largest learner median / expert time, backed by the manual-advance rate and mistakes caught. Report the learner median and expert seconds, the manual-advance rate and the mistakes, and say how many runs it is based on.
- Finished run: has an advance whose to_step is at least the lesson's step count.
- False pass: a camera advance the learner undid with Back to the same step within 60 seconds.

Times are stored in UTC. Show times in America/Chicago. Round seconds to one decimal and rates to whole percent. With fewer than 5 runs, say the numbers come from a few runs.
```

## Example SQL queries

Eight examples, each run once on the warehouse against the current views (all succeeded). Each filters out test lessons with `lower(lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'`.

### Q1. Which step do people get stuck on?

The demo question. Ranks steps by learner median / expert time, top 3, with the manual-advance rate and mistakes.

```sql
WITH ev AS (
  SELECT * FROM workspace.handover.events_real
  WHERE run_id IS NOT NULL AND lower(lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
),
timeline AS (
  SELECT run_id, lesson_id, kind, ts,
         CASE WHEN kind = 'run_start' THEN 0 WHEN kind = 'advance' THEN to_step END AS position,
         lead(ts) OVER (PARTITION BY run_id ORDER BY ts) AS next_ts
  FROM ev
  WHERE kind IN ('run_start', 'advance', 'run_end')
),
fwd AS (
  SELECT run_id, lesson_id, from_step AS step, reason
  FROM ev
  WHERE kind = 'advance' AND to_step > from_step
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
  SELECT lesson_id, step, percentile(learner_s, 0.5) AS learner_median_s, count(*) AS runs
  FROM learner_time GROUP BY lesson_id, step
),
manual AS (
  SELECT lesson_id, step, avg(CASE WHEN reason IN ('button', 'voice') THEN 1.0 ELSE 0.0 END) AS manual_rate
  FROM fwd GROUP BY lesson_id, step
),
mistakes AS (
  SELECT lesson_id, step, count(*) AS mistakes_caught
  FROM ev WHERE kind = 'mistake' GROUP BY lesson_id, step
)
SELECT
  l.title                                                         AS lesson,
  concat('Step ', s.n, ': ', s.title)                             AS step,
  round(t.learner_median_s, 1)                                    AS learner_median_s,
  round(s.end_s - s.start_s, 1)                                   AS expert_s,
  round(t.learner_median_s / nullif(s.end_s - s.start_s, 0), 1)   AS times_expert,
  CASE WHEN s.check_type = 'camera' THEN round(100 * m.manual_rate) END AS manual_advance_pct,
  coalesce(k.mistakes_caught, 0)                                  AS mistakes_caught,
  t.runs
FROM time_agg t
JOIN workspace.handover.steps s   ON s.lesson_id = t.lesson_id AND s.n = t.step + 1
JOIN workspace.handover.lessons l ON l.lesson_id = s.lesson_id
LEFT JOIN manual m   ON m.lesson_id = t.lesson_id AND m.step = t.step
LEFT JOIN mistakes k ON k.lesson_id = t.lesson_id AND k.step = t.step
ORDER BY times_expert DESC, manual_advance_pct DESC NULLS LAST
LIMIT 3
```

### Q2. How long does each step take learners compared with the expert?

```sql
WITH ev AS (
  SELECT * FROM workspace.handover.events_real
  WHERE run_id IS NOT NULL AND lower(lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
),
timeline AS (
  SELECT run_id, lesson_id, kind, ts,
         CASE WHEN kind = 'run_start' THEN 0 WHEN kind = 'advance' THEN to_step END AS position,
         lead(ts) OVER (PARTITION BY run_id ORDER BY ts) AS next_ts
  FROM ev
  WHERE kind IN ('run_start', 'advance', 'run_end')
),
fwd AS (
  SELECT DISTINCT run_id, from_step AS step
  FROM ev
  WHERE kind = 'advance' AND to_step > from_step
),
learner_time AS (
  SELECT t.lesson_id, t.position AS step, t.run_id,
         sum((unix_millis(t.next_ts) - unix_millis(t.ts)) / 1000.0) AS learner_s
  FROM timeline t
  JOIN fwd f ON f.run_id = t.run_id AND f.step = t.position
  WHERE t.kind <> 'run_end' AND t.next_ts IS NOT NULL
  GROUP BY t.lesson_id, t.position, t.run_id
)
SELECT s.lesson_id,
       concat('Step ', s.n, ': ', s.title)          AS step,
       round(s.end_s - s.start_s, 1)               AS expert_s,
       round(percentile(lt.learner_s, 0.5), 1)     AS learner_median_s,
       count(lt.run_id)                            AS runs
FROM workspace.handover.steps s
LEFT JOIN learner_time lt ON lt.lesson_id = s.lesson_id AND lt.step = s.n - 1
WHERE lower(s.lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
GROUP BY s.lesson_id, s.n, s.title, s.start_s, s.end_s
ORDER BY s.lesson_id, s.n
```

### Q3. Which camera steps do learners skip with Next most often?

```sql
SELECT s.lesson_id,
       concat('Step ', s.n, ': ', s.title)              AS step,
       count(*)                                         AS forward_advances,
       count_if(e.reason IN ('button', 'voice'))        AS by_next,
       round(100 * avg(CASE WHEN e.reason IN ('button', 'voice') THEN 1.0 ELSE 0.0 END)) AS manual_advance_pct
FROM workspace.handover.events_real e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.from_step + 1
WHERE e.kind = 'advance' AND e.to_step > e.from_step AND e.run_id IS NOT NULL
  AND s.check_type = 'camera'
  AND lower(e.lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
GROUP BY s.lesson_id, s.n, s.title
ORDER BY manual_advance_pct DESC, forward_advances DESC
```

### Q4. How many runs finished, and how long did a finished run take?

```sql
WITH total AS (
  SELECT lesson_id, count(*) AS steps FROM workspace.handover.steps GROUP BY lesson_id
),
finish AS (
  SELECT e.run_id, min(e.ts) AS finished_at
  FROM workspace.handover.events_real e
  JOIN workspace.handover.runs_real r ON r.run_id = e.run_id
  JOIN total t ON t.lesson_id = r.lesson_id
  WHERE e.kind = 'advance' AND e.to_step >= t.steps
  GROUP BY e.run_id
)
SELECT r.lesson_id,
       count(*)                                    AS runs,
       count(f.run_id)                             AS finished,
       round(percentile((unix_millis(f.finished_at) - unix_millis(r.started_at)) / 1000.0, 0.5), 1) AS median_finish_s,
       round(max(l.duration_s), 1)                 AS expert_total_s
FROM workspace.handover.runs_real r
LEFT JOIN finish f ON f.run_id = r.run_id
LEFT JOIN workspace.handover.lessons l ON l.lesson_id = r.lesson_id
WHERE lower(r.lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
GROUP BY r.lesson_id
ORDER BY r.lesson_id
```

### Q5. What mistakes did the camera catch, and on which steps?

```sql
SELECT s.lesson_id,
       concat('Step ', s.n, ': ', s.title) AS step,
       e.mistake_kind,
       count(*)                       AS mistakes,
       round(avg(e.confidence), 2)    AS avg_confidence
FROM workspace.handover.events_real e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.kind = 'mistake' AND e.run_id IS NOT NULL
  AND lower(e.lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
GROUP BY s.lesson_id, s.n, s.title, e.mistake_kind
ORDER BY mistakes DESC
```

### Q6. How fast is the camera check?

Latency without errored checks; timed out from `error_kind = 'timeout'`.

```sql
SELECT lesson_id,
       count(*)                                                                          AS checks,
       round(percentile(CASE WHEN get_json_object(extra, '$.error_kind') IS NULL THEN latency_ms END, 0.5)) AS p50_ms,
       round(percentile(CASE WHEN get_json_object(extra, '$.error_kind') IS NULL THEN latency_ms END, 0.9)) AS p90_ms,
       round(100 * avg(CASE WHEN get_json_object(extra, '$.error_kind') = 'timeout' THEN 1.0 ELSE 0.0 END), 1) AS timed_out_pct
FROM workspace.handover.events_real
WHERE kind = 'check' AND latency_ms IS NOT NULL
  AND lower(lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
GROUP BY lesson_id
ORDER BY lesson_id
```

### Q7. Where do people give up?

```sql
WITH total AS (
  SELECT lesson_id, count(*) AS steps FROM workspace.handover.steps GROUP BY lesson_id
),
moves AS (
  SELECT run_id, ts, CASE WHEN kind = 'run_start' THEN 0 ELSE to_step END AS position
  FROM workspace.handover.events_real
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance')
),
last_pos AS (
  SELECT run_id, max_by(position, ts) AS step FROM moves GROUP BY run_id
),
state AS (
  SELECT r.run_id, r.lesson_id, r.ended_at, lp.step,
         max(e.ts) AS last_event_at,
         max(CASE WHEN e.kind = 'advance' AND e.to_step >= t.steps THEN 1 ELSE 0 END) AS finished
  FROM workspace.handover.runs_real r
  JOIN last_pos lp ON lp.run_id = r.run_id
  JOIN total t     ON t.lesson_id = r.lesson_id
  LEFT JOIN workspace.handover.events_real e ON e.run_id = r.run_id
  WHERE lower(r.lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
  GROUP BY r.run_id, r.lesson_id, r.ended_at, lp.step
)
SELECT s.lesson_id, concat('Step ', s.n, ': ', s.title) AS step, count(*) AS runs_stopped_here
FROM state st
JOIN workspace.handover.steps s ON s.lesson_id = st.lesson_id AND s.n = st.step + 1
WHERE st.finished = 0
  AND (st.ended_at IS NOT NULL OR st.last_event_at < current_timestamp() - INTERVAL 15 MINUTES)
GROUP BY s.lesson_id, s.n, s.title
ORDER BY runs_stopped_here DESC
```

### Q8. When were camera checks switched off, and why?

Rows with a null reason (checks back on) are left out.

```sql
SELECT from_utc_timestamp(ts, 'America/Chicago') AS time_cst,
       lesson_id,
       reason,
       step + 1                                    AS step_n
FROM workspace.handover.events_real
WHERE kind = 'check_offline' AND reason IS NOT NULL
  AND lower(lesson_id) NOT RLIKE '^(synthetic-|test-|e2e-|selftest)'
ORDER BY ts DESC
```

## Rehearsal, Sunday about 2:30 AM

Run through the conversation API. At that time the only runs were the 5 synthetic test runs, so a correct answer says there is no real data yet.

| Question | SQL Genie ran | Answer |
|---|---|---|
| Which step do people get stuck on? | The Q1 example (plus `WHERE t.runs > 0`) | "There are no real learner runs available, so it is not possible to determine which step people get stuck on. If you would like, I can show results using test or synthetic data instead." |
| How fast is the camera check? | Q6 without the test-lesson filter | "For lesson ID synthetic-fortune-teller-v1, the camera check had a median speed of 1109.0 ms and a 90th percentile speed of 1290.0 ms across 16 checks. The timeout rate was 0.0% ... This data is based on synthetic lesson data only." |
| How many people finished the fortune teller? | Q4, filtered to `fortune-teller-v1` | "There were 0 people who finished the lesson with lesson_id 'fortune-teller-v1'. This count excludes any test or synthetic data." |

After this, the "Lesson names" paragraph was added to the instructions, so "the fortune teller" now matches `fortune-teller-v2` once it has runs. On Sunday about 3 AM a "Lessons" paragraph was added above it: `fortune-teller-v1` is the one lesson in the `lessons` table now; `fortune-teller-v2` and `front-wheel-v1` arrive when the hub uploads them, and Genie should say a named lesson has no rows yet rather than guess. Three examples (Q1 stuck, Q7 give up, Q2 time per step) were re-run against the warehouse then and succeed; Q2 returns all 9 v1 steps with expert seconds and no learner runs yet.

## Rehearse again on real runs (before judges)

1. Open the space, start a **new chat**, click "Which step do people get stuck on?" (clicking avoids typos).
2. Pass: **Show code** shows the Q1 SQL, the table has up to three rows named "Step n: title", and the summary names one step with learner and expert seconds.
3. Ask one rephrasing, "What's the hardest step?", and one off-script question, "How many people finished the fortune teller?".
4. Wrong answer: fix the instructions or examples, never the data. If the step it names differs from what the team saw, trust the data and say so.
5. Screenshot the answer as the fallback. Start a new chat right before the judges arrive.

Demo line, with the numbers read off the screen: "Anyone can ask it: which step do people get stuck on? Genie says step N, [title]: N seconds against the expert's M, and the camera caught K mistakes there."
