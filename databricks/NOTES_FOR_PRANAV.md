# Notes for Pranav: server/databricks.py (status Sunday Nov 15)

The first review of the uploader, checked again against the current `server/databricks.py`, `server/main.py` and `scripts/databricks_setup.py`. Nothing in those files was changed from here.

| # | Item | Status |
|---|---|---|
| 1 | Nothing called the module | Resolved. `server/main.py` `databricks_sink` (registered in `EVENT_SINKS`) calls `start_run`, `emit` for advance, check, mistake and check_offline, and `end_run` |
| 2 | `upload_lesson_files` had no caller or CLI | Resolved. `publish_lesson_files` in `server/main.py` after a teach job or recut, `server/routes_library.py`, `python -m server.databricks --upload <id>`, and step 5 of `scripts/databricks_setup.py` |
| 3 | `--selftest` wrote to the real tables | Resolved. Only with `--remote`; the `_real` views drop selftest rows; `04_cleanup_test_data.sql` deletes them |
| 4 | Replays looked like live runs | Resolved. `start_run(source=, check_mode=)` puts both in `extra`; mock runs stay local; `runs_excluded` (setup script) drops replay and mock runs from every `_real` view |
| 5 to 7 | Dashboard queries 1 to 3 in `server/static/databricks_init.sql` (Back revisits, percentile over visits, double count) | Still open in that file, but unused: the dashboard and Genie read `02_dashboard_datasets.sql` through the `_real` views, which have the fixes |
| 8 | `on_wait_timeout: CONTINUE` counts a statement that fails later as sent | Still open (`_execute`). Mitigated: rows stay in `logs/events.jsonl`, and `--with-history` re-sends them without duplicates (MERGE on `event_id`) |
| 9 | `_ddl_statements` splits on every `;` | Still open, harmless: no comment in the DDL has a `;`. The setup script uses its own quote-aware splitter |
| 10 | A scoped token needs `sql` and `files` | Still true. In the README troubleshooting table |
| 11 | `run_end` carries `step = total` | Still open, harmless: no `steps` row matches and no query reads `run_end.step` |
| 12 | `.env.example` | Resolved. HOST, TOKEN, WAREHOUSE_ID with empty values |

New since the first review, worth knowing:

- Advance reasons now include `ahead_confirm` and `understand_override`. `events_real` maps both to `camera` and keeps the original in `reason_detail`; the raw `ds_<name>` views count them as neither camera nor Next.
- Mistake kinds now include `live`. The dashboard colors it with the other mistakes.
- Rendered test lessons (`synthetic-...`) reach the tables when the hub runs them with real checks. They pass the `_real` filter. Genie leaves them out by instruction; the dashboard relies on the Lesson filter.
