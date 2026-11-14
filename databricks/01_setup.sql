-- HandOver / Databricks Free Edition: schema, tables and Volume.
--
-- Source of truth: server/static/databricks_init.sql on branch pranav/web-capture-dbx.
-- The CREATE statements below are copied from it verbatim (same names, types, comments).
-- If Pranav changes his file, re-copy; do not edit columns here.
--
-- Run: SQL editor, warehouse "Serverless Starter Warehouse", catalog `workspace`.
--      Select all, Run all. Every statement is IF NOT EXISTS, so running it twice is safe.
-- Equivalent from the Mac once the module is merged: python -m server.databricks --init
--
-- Conventions (from CONTRACT.md and Pranav's header)
--   events.step   0-based step index (the hub's state.step)
--   steps.n       1-based step number (lesson.json n). Join: steps.n = events.step + 1
--   ts, *_at      UTC
--   events.kind   run_start, run_end, step_enter, check, advance, mistake, check_offline
--   advance       from_step -> to_step (0-based); reason camera | button | voice;
--                 to_step = step count means the learner finished
--   check         done yes | no | unsure, confidence 0..1, latency_ms, reason (what differs, may be null)
--   mistake       mistake_kind behind | ahead, looks_like = 0-based step the frame resembles
--   check_offline reason no_key | rate_limited | errors
--   extra         JSON string with any other fields the server sent


-- 1. Schema --------------------------------------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS workspace.handover
  COMMENT 'HandOver: expert lessons cut from one video, and learner runs on the glasses';


-- 2. Lessons: one row per lesson, written by upload_lesson_files() (MERGE on lesson_id) -----------------

CREATE TABLE IF NOT EXISTS workspace.handover.lessons (
  lesson_id  STRING    COMMENT 'Lesson folder id, e.g. fortune-teller-v1',
  title      STRING    COMMENT 'Lesson title',
  expert     STRING    COMMENT 'Who recorded the lesson, if known',
  duration_s DOUBLE    COMMENT 'Expert time for the whole task in seconds (end of the last step)',
  created_at TIMESTAMP COMMENT 'When the lesson was uploaded to Databricks (UTC)'
) COMMENT 'One row per lesson cut from an expert video';


-- 3. Steps: one row per lesson step, written by upload_lesson_files() (MERGE on lesson_id, n) ----------

CREATE TABLE IF NOT EXISTS workspace.handover.steps (
  lesson_id      STRING COMMENT 'Lesson id',
  n              INT    COMMENT '1-based step number; events.step + 1',
  title          STRING COMMENT 'Step title shown to the learner',
  start_s        DOUBLE COMMENT 'Step start in the expert video, seconds',
  end_s          DOUBLE COMMENT 'Step end in the expert video, seconds; end_s - start_s is the expert time',
  check_type     STRING COMMENT 'camera (checked against a reference frame) or manual (learner taps Next)',
  check_question STRING COMMENT 'Yes/no question the camera check asks'
) COMMENT 'Steps of each lesson with the expert timing';


-- 4. Runs: one row per learner attempt, written by start_run() / end_run() (MERGE on run_id) ----------

CREATE TABLE IF NOT EXISTS workspace.handover.runs (
  run_id     STRING    COMMENT 'One learner attempt at one lesson',
  lesson_id  STRING    COMMENT 'Lesson id',
  learner    STRING    COMMENT 'Learner label, if given',
  started_at TIMESTAMP COMMENT 'Run start (UTC)',
  ended_at   TIMESTAMP COMMENT 'Run end (UTC), null while running or if abandoned'
) COMMENT 'Learner runs';


-- 5. Events: append-only, one row per emit() ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workspace.handover.events (
  event_id     STRING    COMMENT 'Client-side uuid4',
  run_id       STRING    COMMENT 'Run id, null outside a run',
  lesson_id    STRING    COMMENT 'Lesson id',
  step         INT       COMMENT '0-based step index the event belongs to',
  ts           TIMESTAMP COMMENT 'Event time (UTC)',
  kind         STRING    COMMENT 'run_start, run_end, step_enter, check, advance, mistake, check_offline',
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


-- 6. Volume: lesson files under /Volumes/workspace/handover/lessons/<lesson_id>/ -------------------------

CREATE VOLUME IF NOT EXISTS workspace.handover.lessons
  COMMENT 'Lesson files: lesson.json, frames/*.jpg, captions/*.vtt, clips/*.mp4 under <lesson_id>/';


-- 7. Verify (run each separately; expected results in the comments) ------------------------------------

-- Expect 4 rows: events, lessons, runs, steps.
SHOW TABLES IN workspace.handover;

-- Expect 1 row: lessons, MANAGED.
SHOW VOLUMES IN workspace.handover;

-- Expect 15 columns, in the order above.
DESCRIBE TABLE workspace.handover.events;

-- Expect four zeros before the first run.
SELECT
  (SELECT count(*) FROM workspace.handover.lessons) AS lessons,
  (SELECT count(*) FROM workspace.handover.steps)   AS steps,
  (SELECT count(*) FROM workspace.handover.runs)    AS runs,
  (SELECT count(*) FROM workspace.handover.events)  AS events;
