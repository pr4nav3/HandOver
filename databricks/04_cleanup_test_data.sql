-- HandOver / Databricks: remove synthetic and self-test rows.
--
-- Run with: .venv\Scripts\python scripts\databricks_setup.py --teardown-test-data (it runs every statement
-- here and prints the check rows), or paste into the SQL editor.
-- Deletes exactly the rows 03_test_data.sql inserts (lesson test-fortune-teller), plus the rows that
-- python -m server.databricks --selftest --remote writes (lesson_id and learner selftest). Real lessons and
-- runs are never touched: every condition matches a tag the hub never produces.
--
-- Not deleted here: runs of rendered test lessons such as synthetic-fortune-teller-v1. The _real views keep
-- them (only mock, replay and selftest are dropped); Genie leaves them out by its instructions; on the
-- dashboard, pick the real lesson in the Lesson filter. Section 3 below deletes them if the team agrees.
--
-- Safe to run more than once. Run all, then check the first verify query returns all zeros.

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


-- 2. Module self-test rows (python -m server.databricks --selftest --remote) ------------------------------
-- The self-test starts a run for lesson 'selftest' with learner 'selftest'. Those rows have no steps, so
-- most charts ignore them, but they inflate the Runs counter.

DELETE FROM workspace.handover.events
WHERE lesson_id = 'selftest'
   OR run_id IN (SELECT run_id FROM workspace.handover.runs WHERE learner = 'selftest');

DELETE FROM workspace.handover.runs
WHERE lesson_id = 'selftest' OR learner = 'selftest';


-- 3. Optional, by hand only: rendered test lessons (lesson ids starting synthetic-). Commented out so the
--    setup script never runs it. Paste the two DELETEs without the leading dashes to remove those runs.
-- DELETE FROM workspace.handover.events WHERE lesson_id LIKE 'synthetic-%';
-- DELETE FROM workspace.handover.runs   WHERE lesson_id LIKE 'synthetic-%';


-- 4. Verify: every column must be 0 ------------------------------------------------------------------------

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
