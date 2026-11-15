# Genie space: HandOver learner runs

One Genie space, one demo question: "Which step do people get stuck on?"

Databricks renamed Genie spaces to **Genie Agents** in the current docs and UI; same feature. Steps and labels below follow [Create and manage a Genie Agent](https://docs.databricks.com/aws/en/genie-agents/set-up) and [Tune Genie Agent quality](https://docs.databricks.com/aws/en/genie-agents/tune-quality). Labels that might differ in your workspace are marked (unverified).

Build it by midnight (README step 9). Needs real or test rows in all four tables, and the steps rows for each lesson.

## 1. Create

1. Sidebar > **Genie Agents** (may still read **Genie**) > **New**.
2. Data sources: `workspace.handover.lessons`, `workspace.handover.steps`, `workspace.handover.runs`, `workspace.handover.events`. Click **Create**.
3. Genie Code may suggest table descriptions and example queries. Reject them. The column comments from `01_setup.sql` are already in Unity Catalog, and the examples below are tested.
4. **Configure > Settings**:
   - Title: `HandOver learner runs`
   - Default warehouse: `Serverless Starter Warehouse` (the only one on Free Edition)
   - Description (Markdown):

     ```
     Learner runs of HandOver lessons. An expert recorded each task once; HandOver cut it into steps
     and a camera checks each step before the next clip plays. Ask where learners slow down, which
     steps they skip with Next, and what mistakes the camera caught.
     ```
   - Common questions, in this order:
     1. `Which step do people get stuck on?`
     2. `How long does each step take learners compared with the expert?`
     3. `Which camera steps do learners skip with Next most often?`
     4. `What mistakes did the camera catch, and on which steps?`

## 2. Joins

**Configure > Examples > Add > Joins**, one per row. If **Join condition** only takes simple equalities, use **Use SQL expression** for the first one.

| Left | Right | Join condition | Relationship |
|---|---|---|---|
| events | steps | `events.lesson_id = steps.lesson_id AND steps.n = events.step + 1` | Many to one |
| events | runs | `events.run_id = runs.run_id` | Many to one |
| runs | lessons | `runs.lesson_id = lessons.lesson_id` | Many to one |
| steps | lessons | `steps.lesson_id = lessons.lesson_id` | Many to one |

## 3. General instructions

**Configure > Text** (the General instructions block). Paste as is:

```
HandOver data. An expert recorded a task once; it was cut into numbered steps. Learners do the task while
a camera checks each step. One run = one learner attempt at one lesson.

Step numbering. events.step, events.from_step, events.to_step and events.looks_like are 0-based.
steps.n is 1-based and is what people call "step 3". Always join events to steps with
steps.lesson_id = events.lesson_id AND steps.n = events.step + 1 (for advances use from_step + 1).
Always show steps to the user as steps.n and steps.title, never the 0-based index.

Event kinds (events.kind): run_start, run_end, step_enter, check, advance, mistake, check_offline.
- advance: the learner moved from from_step to to_step. reason = camera (the camera check passed),
  button or voice (the learner pressed Next). to_step > from_step is forward; to_step < from_step is Back.
  to_step equal to the lesson's step count means the learner finished.
- check: one camera check. done = yes, no or unsure; confidence 0 to 1; latency_ms. done = unsure with
  confidence 0 is a timeout or error, not a real answer.
- mistake: the camera caught a mistake on the current step. mistake_kind behind = the work still looks
  like the previous step (a step was skipped); ahead = it already looks like the next step.
- check_offline: camera checks were switched off for a while (reason no_key, rate_limited, errors); the
  learner used Next instead.

Definitions.
- Expert time of a step = steps.end_s - steps.start_s.
- Learner time on a step = time from entering the step until the next advance, summed over revisits,
  for runs that went forward from that step. Use the median across runs.
- Manual-advance rate = forward advances with reason button or voice / all forward advances, on steps
  with check_type = 'camera'. Steps with check_type = 'manual' always advance by Next; leave them out.
- "Stuck", "hardest", "slowest", "where people struggle": the step with the longest median learner time
  relative to the expert (learner median / expert time), backed by the highest manual-advance rate.
  Report the learner median and expert seconds, the manual-advance rate and the mistakes caught, and
  name the step as "Step <n>: <title>".
- Finished run: has an advance whose to_step is at least the lesson's step count.
- False pass: a camera advance the learner undid with Back to the same step within 60 seconds.

Times are stored in UTC. Show times to people in America/Chicago.
Ignore rows where lesson_id is 'selftest' or learner is 'selftest'.
Round seconds to one decimal and rates to whole percent.
```

The selftest rule matters: the module's `--selftest` writes a 'selftest' run into the real tables (see NOTES_FOR_PRANAV.md). Synthetic rows are deliberately not excluded, so the space can be rehearsed on `03_test_data.sql`; `04_cleanup_test_data.sql` removes them before judging.

## 4. Example SQL queries

**Configure > Examples**, add each as an example SQL query: title = the question, body = the SQL. All are tested against the synthetic data in `03_test_data.sql`. Each counts toward the 100-instruction limit; eight is fine.

### Q1. Which step do people get stuck on?

This is the demo question. Add **Usage guidance**: `Use for any question about where learners get stuck, struggle, slow down, or which step is hardest.`

```sql
WITH timeline AS (
  SELECT run_id, lesson_id, kind, ts,
         CASE WHEN kind = 'run_start' THEN 0 WHEN kind = 'advance' THEN to_step END AS position,
         lead(ts) OVER (PARTITION BY run_id ORDER BY ts) AS next_ts
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance', 'run_end')
    AND lesson_id <> 'selftest'
),
fwd AS (
  SELECT run_id, lesson_id, from_step AS step, reason
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
  SELECT lesson_id, step, percentile(learner_s, 0.5) AS learner_median_s, count(*) AS runs
  FROM learner_time GROUP BY lesson_id, step
),
manual AS (
  SELECT lesson_id, step, avg(CASE WHEN reason IN ('button', 'voice') THEN 1.0 ELSE 0.0 END) AS manual_rate
  FROM fwd GROUP BY lesson_id, step
),
mistakes AS (
  SELECT lesson_id, step, count(*) AS mistakes_caught
  FROM workspace.handover.events WHERE kind = 'mistake' GROUP BY lesson_id, step
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
LIMIT 3;
```

Why "relative to the expert" and not raw seconds: a 17-second fold will always take longer than a 4-second flip. Ranking by raw seconds names the longest step, not the one people struggle with. The query still returns the raw medians, so the answer can quote both.

Expected answer shape (with the synthetic data; real numbers will differ):

| lesson | step | learner_median_s | expert_s | times_expert | manual_advance_pct | mistakes_caught | runs |
|---|---|---|---|---|---|---|---|
| Paper fortune teller (TEST DATA) | Step 5: Flip it over | 21.8 | 4.0 | 5.5 | 36 | 5 | 14 |
| Paper fortune teller (TEST DATA) | Step 8: Push the corners up and open it | 36.8 | 12.0 | 3.1 | 17 | 0 | 12 |
| Paper fortune teller (TEST DATA) | Step 7: Fold it in half | 17.6 | 6.0 | 2.9 | 17 | 0 | 12 |

and a sentence like: "Step 5, Flip it over. Learners take a median 21.8 s against the expert's 4 s, press Next on 36 % of attempts instead of passing the camera check, and the camera caught 5 skipped flips there."

### Q2. How long does each step take learners compared with the expert?

```sql
WITH timeline AS (
  SELECT run_id, lesson_id, kind, ts,
         CASE WHEN kind = 'run_start' THEN 0 WHEN kind = 'advance' THEN to_step END AS position,
         lead(ts) OVER (PARTITION BY run_id ORDER BY ts) AS next_ts
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance', 'run_end')
),
fwd AS (
  SELECT DISTINCT run_id, from_step AS step
  FROM workspace.handover.events
  WHERE kind = 'advance' AND to_step > from_step AND run_id IS NOT NULL
),
learner_time AS (
  SELECT t.lesson_id, t.position AS step, t.run_id,
         sum((unix_millis(t.next_ts) - unix_millis(t.ts)) / 1000.0) AS learner_s
  FROM timeline t
  JOIN fwd f ON f.run_id = t.run_id AND f.step = t.position
  WHERE t.kind <> 'run_end' AND t.next_ts IS NOT NULL
  GROUP BY t.lesson_id, t.position, t.run_id
)
SELECT s.lesson_id, s.n, s.title,
       round(s.end_s - s.start_s, 1)               AS expert_s,
       round(percentile(lt.learner_s, 0.5), 1)     AS learner_median_s,
       count(lt.run_id)                            AS runs
FROM workspace.handover.steps s
LEFT JOIN learner_time lt ON lt.lesson_id = s.lesson_id AND lt.step = s.n - 1
WHERE s.lesson_id <> 'selftest'
GROUP BY s.lesson_id, s.n, s.title, s.start_s, s.end_s
ORDER BY s.lesson_id, s.n;
```

### Q3. Which camera steps do learners skip with Next most often?

```sql
SELECT s.lesson_id, s.n, s.title,
       count(*)                                         AS forward_advances,
       count_if(e.reason IN ('button', 'voice'))        AS by_next,
       round(100 * avg(CASE WHEN e.reason IN ('button', 'voice') THEN 1.0 ELSE 0.0 END)) AS manual_advance_pct
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.from_step + 1
WHERE e.kind = 'advance' AND e.to_step > e.from_step AND e.run_id IS NOT NULL
  AND s.check_type = 'camera'
GROUP BY s.lesson_id, s.n, s.title
ORDER BY manual_advance_pct DESC, forward_advances DESC;
```

### Q4. How many runs finished, and how long did a finished run take?

```sql
WITH total AS (
  SELECT lesson_id, count(*) AS steps FROM workspace.handover.steps GROUP BY lesson_id
),
finish AS (
  SELECT e.run_id, min(e.ts) AS finished_at
  FROM workspace.handover.events e
  JOIN workspace.handover.runs r ON r.run_id = e.run_id
  JOIN total t ON t.lesson_id = r.lesson_id
  WHERE e.kind = 'advance' AND e.to_step >= t.steps
  GROUP BY e.run_id
)
SELECT r.lesson_id,
       count(*)                                    AS runs,
       count(f.run_id)                             AS finished,
       round(percentile((unix_millis(f.finished_at) - unix_millis(r.started_at)) / 1000.0, 0.5), 1) AS median_finish_s,
       round(max(l.duration_s), 1)                 AS expert_total_s
FROM workspace.handover.runs r
LEFT JOIN finish f ON f.run_id = r.run_id
LEFT JOIN workspace.handover.lessons l ON l.lesson_id = r.lesson_id
WHERE coalesce(r.learner, '') <> 'selftest' AND r.lesson_id <> 'selftest'
GROUP BY r.lesson_id
ORDER BY r.lesson_id;
```

### Q5. What mistakes did the camera catch, and on which steps?

```sql
SELECT s.lesson_id, s.n, s.title,
       e.mistake_kind,
       count(*)                       AS mistakes,
       round(avg(e.confidence), 2)    AS avg_confidence
FROM workspace.handover.events e
JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.kind = 'mistake' AND e.run_id IS NOT NULL
GROUP BY s.lesson_id, s.n, s.title, e.mistake_kind
ORDER BY mistakes DESC;
```

### Q6. How fast is the camera check?

```sql
SELECT lesson_id,
       count(*)                                  AS checks,
       round(percentile(latency_ms, 0.5))        AS p50_ms,
       round(percentile(latency_ms, 0.9))        AS p90_ms,
       round(100 * avg(CASE WHEN done = 'unsure' AND confidence = 0 THEN 1.0 ELSE 0.0 END), 1) AS timed_out_pct
FROM workspace.handover.events
WHERE kind = 'check' AND latency_ms IS NOT NULL AND lesson_id <> 'selftest'
GROUP BY lesson_id
ORDER BY lesson_id;
```

### Q7. Where do people give up?

```sql
WITH total AS (
  SELECT lesson_id, count(*) AS steps FROM workspace.handover.steps GROUP BY lesson_id
),
moves AS (
  SELECT run_id, ts, CASE WHEN kind = 'run_start' THEN 0 ELSE to_step END AS position
  FROM workspace.handover.events
  WHERE run_id IS NOT NULL AND kind IN ('run_start', 'advance')
),
last_pos AS (
  SELECT run_id, max_by(position, ts) AS step FROM moves GROUP BY run_id
),
state AS (
  SELECT r.run_id, r.lesson_id, r.ended_at, lp.step,
         max(e.ts) AS last_event_at,
         max(CASE WHEN e.kind = 'advance' AND e.to_step >= t.steps THEN 1 ELSE 0 END) AS finished
  FROM workspace.handover.runs r
  JOIN last_pos lp ON lp.run_id = r.run_id
  JOIN total t     ON t.lesson_id = r.lesson_id
  LEFT JOIN workspace.handover.events e ON e.run_id = r.run_id
  GROUP BY r.run_id, r.lesson_id, r.ended_at, lp.step
)
SELECT s.lesson_id, s.n, s.title, count(*) AS runs_stopped_here
FROM state st
JOIN workspace.handover.steps s ON s.lesson_id = st.lesson_id AND s.n = st.step + 1
WHERE st.finished = 0
  AND (st.ended_at IS NOT NULL OR st.last_event_at < current_timestamp() - INTERVAL 15 MINUTES)
GROUP BY s.lesson_id, s.n, s.title
ORDER BY runs_stopped_here DESC;
```

### Q8. When were camera checks switched off, and why?

```sql
SELECT from_utc_timestamp(ts, 'America/Chicago') AS time_cst,
       lesson_id,
       reason,
       step + 1                                    AS step_n
FROM workspace.handover.events
WHERE kind = 'check_offline'
ORDER BY ts DESC;
```

## 5. Rehearse

Do this once at midnight on whatever data exists, and again after the 8 AM warm-up on real data only.

1. Open the space, click the common question **Which step do people get stuck on?** (clicking avoids typos on stage).
2. Pass: Genie answers from the Q1 example (open **Show code**: the SQL should match Q1), the table has three rows with Step n and title, and the summary names one step.
3. Ask two rephrasings: `Where do learners struggle?` and `What's the hardest step?`. Both should reuse Q1. If one does not, add it as a second example with the same SQL, or extend the Q1 usage guidance.
4. Ask one off-script question a judge might ask, e.g. `How many people finished the fortune teller?`. It should use Q4.
5. Fix wrong answers by editing instructions or examples, never by editing data.
6. Monitoring tab (CAN MANAGE): mark good answers; optionally add Q1 as a benchmark question.
7. Start a **new chat** right before judging so the judge sees a clean thread, and keep the Genie tab open next to the dashboard.

If the answer names a step that does not match what the team saw at the 8 AM rehearsal, trust the data and say it honestly: "the camera data says step N". Do not tune the question to produce a preferred answer.
