-- HandOver / Databricks: remove synthetic and self-test rows.
--
-- Run before judging (CHECKLIST.md, Sunday 8 AM at the latest) and any time you want real-only numbers.
-- Deletes exactly the rows 03_test_data.sql inserted, plus the rows `python -m server.databricks --selftest`
-- writes (lesson_id 'selftest', learner 'selftest'). Real lessons and runs are never touched: every
-- condition below matches a tag that the hub never produces.
--
-- Safe to run more than once. Run all, then check the last query returns all zeros.

-- 1. Synthetic test data (03_test_data.sql) --------------------------------------------------------------

DELETE FROM workspace.handover.events
WHERE event_id LIKE 'TEST-ev-%'
   OR run_id   LIKE 'TEST-run-%'
   OR lesson_id = 'test-fortune-teller';

DELETE FROM workspace.handover.runs
WHERE run_id LIKE 'TEST-run-%'
   OR lesson_id = 'test-fortune-teller'
   OR learner = 'synthetic';

DELETE FROM workspace.handover.steps   WHERE lesson_id = 'test-fortune-teller';
DELETE FROM workspace.handover.lessons WHERE lesson_id = 'test-fortune-teller';


-- 2. Module self-test rows (python -m server.databricks --selftest) ---------------------------------------
-- The self-test starts a run for lesson 'selftest' with learner 'selftest'. Those rows have no steps, so
-- most charts ignore them, but they inflate the Runs counter.

DELETE FROM workspace.handover.events
WHERE lesson_id = 'selftest'
   OR run_id IN (SELECT run_id FROM workspace.handover.runs WHERE learner = 'selftest');

DELETE FROM workspace.handover.runs
WHERE lesson_id = 'selftest' OR learner = 'selftest';


-- 3. Verify: every column must be 0 ------------------------------------------------------------------------

SELECT
  (SELECT count(*) FROM workspace.handover.lessons WHERE lesson_id = 'test-fortune-teller')        AS test_lessons,
  (SELECT count(*) FROM workspace.handover.steps   WHERE lesson_id = 'test-fortune-teller')        AS test_steps,
  (SELECT count(*) FROM workspace.handover.runs
     WHERE run_id LIKE 'TEST-%' OR learner IN ('synthetic', 'selftest')
        OR lesson_id IN ('test-fortune-teller', 'selftest'))                                       AS test_runs,
  (SELECT count(*) FROM workspace.handover.events
     WHERE event_id LIKE 'TEST-%' OR run_id LIKE 'TEST-%'
        OR lesson_id IN ('test-fortune-teller', 'selftest'))                                       AS test_events;

-- And what is left is real: one row per real lesson with its run count.
SELECT l.lesson_id, l.title, count(r.run_id) AS runs
FROM workspace.handover.lessons l
LEFT JOIN workspace.handover.runs r ON r.lesson_id = l.lesson_id
GROUP BY l.lesson_id, l.title
ORDER BY l.lesson_id;
