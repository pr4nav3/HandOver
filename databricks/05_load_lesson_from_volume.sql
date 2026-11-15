-- HandOver / Databricks: FALLBACK loader for the lessons and steps tables.
--
-- Normal path: the hub calls server.databricks.upload_lesson_files(), which uploads the lesson folder to
-- the Volume and MERGEs the lessons and steps rows. Use this file only if that has not happened for a
-- lesson (see NOTES_FOR_PRANAV.md: nothing calls upload_lesson_files yet). Without steps rows every
-- per-step chart is empty, because events join to steps on n = step + 1.
--
-- Steps
--   1. Catalog > workspace > handover > Volumes > lessons > Create directory "<lesson_id>"
--      (the folder name must equal the "id" in lesson.json, e.g. fortune-teller-v1).
--   2. Open that directory > Upload to this volume > pick lessons/<lesson_id>/lesson.json from the repo.
--      (Clips, frames and captions are optional for the dashboard.)
--   3. Run the three statements below. They read every lesson.json in the Volume and upsert, so running
--      again after a recut is safe and updates the rows.
--
-- Same derivations as upload_lesson_files(): times "MM:SS", "MM:SS.s", "HH:MM:SS" or plain seconds become
-- seconds; n falls back to position + 1; duration_s = latest step end; expert is not in lesson.json (NULL).


-- 1. Preview: expect one row per lesson.json, with the step count you expect. ----------------------------

SELECT id AS lesson_id, title, size(steps) AS steps
FROM read_files('/Volumes/workspace/handover/lessons/*/lesson.json', format => 'json', multiLine => true);


-- 2. Upsert steps. ----------------------------------------------------------------------------------------

MERGE INTO workspace.handover.steps t
USING (
  SELECT
    l.id                                                               AS lesson_id,
    coalesce(st.n, p.pos + 1)                                          AS n,
    st.title                                                           AS title,
    aggregate(split(cast(st.start AS STRING), ':'), CAST(0 AS DOUBLE),
              (acc, x) -> acc * 60 + cast(x AS DOUBLE))                AS start_s,
    aggregate(split(cast(st.`end` AS STRING), ':'), CAST(0 AS DOUBLE),
              (acc, x) -> acc * 60 + cast(x AS DOUBLE))                AS end_s,
    coalesce(st.check_type, 'camera')                                  AS check_type,
    st.check_question                                                  AS check_question
  FROM read_files('/Volumes/workspace/handover/lessons/*/lesson.json', format => 'json', multiLine => true) l
  LATERAL VIEW posexplode(l.steps) p AS pos, st
) s
ON t.lesson_id = s.lesson_id AND t.n = s.n
WHEN MATCHED THEN UPDATE SET
  t.title = s.title, t.start_s = s.start_s, t.end_s = s.end_s,
  t.check_type = s.check_type, t.check_question = s.check_question
WHEN NOT MATCHED THEN INSERT (lesson_id, n, title, start_s, end_s, check_type, check_question)
  VALUES (s.lesson_id, s.n, s.title, s.start_s, s.end_s, s.check_type, s.check_question);


-- 3. Upsert lessons. ---------------------------------------------------------------------------------------

MERGE INTO workspace.handover.lessons t
USING (
  SELECT
    l.id                                                                AS lesson_id,
    first(l.title)                                                      AS title,
    CAST(NULL AS STRING)                                                AS expert,
    max(aggregate(split(cast(st.`end` AS STRING), ':'), CAST(0 AS DOUBLE),
                  (acc, x) -> acc * 60 + cast(x AS DOUBLE)))            AS duration_s,
    current_timestamp()                                                 AS created_at
  FROM read_files('/Volumes/workspace/handover/lessons/*/lesson.json', format => 'json', multiLine => true) l
  LATERAL VIEW OUTER posexplode(l.steps) p AS pos, st
  GROUP BY l.id
) s
ON t.lesson_id = s.lesson_id
WHEN MATCHED THEN UPDATE SET t.title = s.title, t.duration_s = s.duration_s, t.created_at = s.created_at
WHEN NOT MATCHED THEN INSERT (lesson_id, title, expert, duration_s, created_at)
  VALUES (s.lesson_id, s.title, s.expert, s.duration_s, s.created_at);


-- 4. Verify: one row per lesson, steps and expert seconds as in the lesson. --------------------------------

SELECT l.lesson_id, l.title, l.duration_s, count(s.n) AS steps,
       count_if(s.check_type = 'manual') AS manual_steps
FROM workspace.handover.lessons l
LEFT JOIN workspace.handover.steps s ON s.lesson_id = l.lesson_id
GROUP BY l.lesson_id, l.title, l.duration_s
ORDER BY l.lesson_id;
