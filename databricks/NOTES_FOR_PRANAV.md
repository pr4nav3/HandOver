# Notes for Pranav: server/databricks.py and databricks_init.sql

From reviewing `server/databricks.py` and `server/static/databricks_init.sql` (commit d4c54cf, merged to main in ddcfd29). Nothing in your files was changed. `databricks/01_setup.sql` copies your CREATE statements exactly, checked by script, so the schema has one definition. Ordered by impact on the demo.

## Blocking for the dashboard

1. **Nothing calls the module yet.** No file other than `server/databricks.py` imports it on your branch, and `server/main.py` is Soham's. Somebody has to add the calls, agreed in the group:
   - `start_run(lesson_id)` when a learner run starts. Proposal: on `select_lesson`, and again when the learner goes from done back to step 0. Step 1's learner time is measured from `run_start`, so a run that starts long before the learner touches the paper inflates step 1 (it is a manual step, so this mostly affects one bar).
   - `emit("advance", from_step=, to_step=, reason=)` at every `go()` that changes position, with the same `from`, `to`, `reason` as the `advance` broadcast. This is the one event every chart depends on.
   - `emit("check", step=, done=, confidence=, latency_ms=, reason=)` for each check result.
   - `emit("mistake", step=, kind=, looks_like=, confidence=)` when the mistake broadcast fires.
   - `emit("check_offline", reason=)` when the breaker opens.
   - `end_run()` on finishing (advance to `total`) and on lesson change.
2. **`upload_lesson_files()` has no caller and no CLI flag.** Without it `lessons` and `steps` stay empty, and every per-step query returns nothing because events join to steps on `n = step + 1`. Suggest a `--upload <lesson_id>` flag that calls it and waits for the worker. Fallback in the meantime: `databricks/05_load_lesson_from_volume.sql` (upload `lesson.json` to the Volume in the UI, then MERGE from `read_files`). Its derivations match `_upload_worker` (seconds parsing, `n` fallback, `duration_s` = max end).

## Correctness

3. **`--selftest` writes to the real tables.** With credentials it flushes a run with `lesson_id = 'selftest'` into `workspace.handover`. It has no steps rows, so most charts skip it, but it is counted in `runs`. `databricks/04_cleanup_test_data.sql` deletes it, and the Genie instructions ignore it. Cleaner: a `DATABRICKS_SCHEMA` override for the selftest, or skip the remote flush unless `--remote` is passed.
4. **Replays look like live runs.** `server.replay` feeds real frames, so its runs produce real events. The hello `source: "file"` is not recorded anywhere in the events. If replays are used in rehearsal or the demo, the dashboard mixes them with live folds. Suggest `start_run(lesson_id, learner=...)` with a label, or `emit("run_start", ..., source="file")` (lands in `extra`), so a query can exclude them. Honesty matters here: the pitch says the data is from real runs.
5. **Dashboard query 1 (time per step)** in `databricks_init.sql`:
   - It matches each entry to the first forward exit after it. When a learner presses Back out of step k and then comes forward into k again, the first entry's time runs until the later forward exit, so it includes time spent on step k-1, and the second entry counts that span again.
   - The percentile is over visits, not runs, while `runs` counts distinct runs.
   - `databricks/02_dashboard_datasets.sql` (`ds_time_per_step`) instead sums the time spent at each position per run, over all visits, for runs that left the step forward, then takes the median across runs. On the synthetic data the two agree except on steps with a Back (step 6: 34.2 s vs 44.8 s).
6. **Query 2 (manual-advance rate)** filters `to_step = from_step + 1`, so the "ahead" catch (`go(k + 2, "camera")`, CONTRACT.md 7.2) is dropped: a camera success at step k that never counts. `ds_manual_rate` uses `to_step > from_step`.
7. **Query 3 (false passes)** uses `count(*)` after a LEFT JOIN to back moves: two Back presses within 60 s of one camera pass count that pass twice in `camera_passes`. `false_passes` is already distinct. `ds_false_passes` flags each pass once before counting.

## Robustness (no change needed for the demo, worth knowing)

8. `on_wait_timeout: CONTINUE` without polling means a statement that fails after 30 s (a cold warehouse, then a schema error) is counted as sent. The rows survive only in `logs/events.jsonl`. Fine for the quota; after `--selftest` on a cold warehouse, confirm with a `SELECT count(*)` rather than trusting "SELFTEST OK".
9. `_ddl_statements()` splits the file on every `;`. A future COMMENT containing `;` would split a statement. None does today.
10. A scoped PAT needs the `sql` scope (Statement Execution) and `files` scope (Files API for the Volume). The runbook says so. If uploads fail with 403 while inserts work, that is the cause.
11. `emit` keeps `_run["step"] = to_step` after the final advance, so the `run_end` event has `step = total`, one past the last step. Harmless: no steps row matches, and no query reads `run_end.step`. Worth a comment in the contract section of your header.
12. `.env.example` lists HOST, TOKEN and WAREHOUSE_ID. `DATABRICKS_CATALOG` and `DATABRICKS_SCHEMA` are optional with defaults, so leaving them out is fine.

## Checked and fine

- Table and column names and types are the same in `TABLES`, the DDL and these queries.
- The MERGE keys (`lessons.lesson_id`, `steps.(lesson_id, n)`, `runs.run_id`), in-batch dedup, and the `coalesce` on `runs.ended_at`.
- Flush order lessons, steps, runs, events; one parameterised statement per table per batch; nothing sent when idle.
- Volume path `/Volumes/<catalog>/<schema>/lessons/<lesson_id>/<rel>` via `PUT /api/2.0/fs/files...?overwrite=true`, which matches `01_setup.sql`.
- Token never printed: `_scrub` covers the token, `dapi...` patterns and Bearer headers.
