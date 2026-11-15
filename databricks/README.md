# Databricks runbook (HandOver)

Databricks is the data layer only, never in the live loop. The hub writes every learn event to `logs/events.jsonl` first. With credentials, `server/databricks.py` also sends them to the warehouse in batches. If Databricks is down, the learn screen does not change.

Everything below runs on the machine that runs the hub. Commands are PowerShell from the repo root (on a Mac, use `.venv/bin/python` and forward slashes).

## Links

| What | Where |
|---|---|
| Dashboard (published, show this one) | https://dbc-a03072b4-3eeb.cloud.databricks.com/dashboardsv3/01f1e086926f1ffc9624630fda6e58c3/published |
| Dashboard (editor) | https://dbc-a03072b4-3eeb.cloud.databricks.com/dashboardsv3/01f1e086926f1ffc9624630fda6e58c3 |
| Genie space | https://dbc-a03072b4-3eeb.cloud.databricks.com/genie/rooms/01f1e086eb621d8d990021c7016818de |
| Catalog | `workspace.handover` (tables `lessons`, `steps`, `runs`, `events`; Volume `lessons`) |

## What is live

- Tables: `lessons`, `steps`, `runs`, `events` in `workspace.handover`. Volume `workspace.handover.lessons` holds lesson files (expert video, frames, captions), never learner camera frames.
- Views, all made by `scripts/databricks_setup.py`:
  - `runs_excluded`: runs with any replay (`source` file) or mock event.
  - `events_real`, `runs_real`: events and runs without those runs and without `selftest` rows. In `events_real`, advance reasons `ahead_confirm` and `understand_override` count as `camera`; the original is in `reason_detail`.
  - `ds_<name>`: the 13 datasets of `02_dashboard_datasets.sql`, unfiltered.
  - `ds_<name>_real`: the same over `events_real` and `runs_real`, plus the review fixes: checks-off rows need a reason, latency leaves out mock and errored checks, timed out means `error_kind = 'timeout'`.
- Dashboard "HandOver: learner runs": 15 datasets. 13 are `SELECT * FROM workspace.handover.ds_<name>_real`, 2 are small queries over `events_real`. Layout in `dashboard.md`.
- Genie space "HandOver learner runs": `events_real`, `runs_real`, `lessons`, `steps`, 8 tested examples. Details in `genie.md`.

Test data. `synthetic-fortune-teller-v1` is a rendered test lesson, not learners. Its runs pass the `_real` filter, so pick the real lesson in the dashboard's Lesson filter. Genie leaves lesson ids starting `synthetic-`, `test-`, `TEST-` or `e2e-` out unless asked. `synthetic-fortune-teller-v1` has no `steps` rows, so its per-step charts stay empty. The real lessons: `fortune-teller-v2` (origami) and `front-wheel-v1` (bike).

## Files

| File | What it is |
|---|---|
| `README.md` | This runbook |

| `01_setup.sql` | Schema, four tables, Volume. Read by the setup script. Idempotent |
| `02_dashboard_datasets.sql` | The 13 dataset queries. The setup script turns each into `ds_<name>` and `ds_<name>_real` |
| `03_test_data.sql` | Synthetic rows for local layout work. Not loaded in the workspace. Do not run |
| `04_cleanup_test_data.sql` | Deletes `03` rows and `selftest` rows. Run by `--teardown-test-data` |
| `05_load_lesson_from_volume.sql` | Fallback: fills `lessons` and `steps` from a `lesson.json` already in the Volume |
| `dashboard.md` | What each dashboard page and widget shows, colors, publish |
| `handover.lvdash.json` | The live dashboard, as saved in the workspace (exported through the API) |
| `genie.md` | The live Genie space: data, joins, instructions, examples, sample answers |

## 1. Credentials

Keep the token out of commits, screenshots and `.env.example` (that file keeps empty values).

In the repo-root `.env` (gitignored):

```
DATABRICKS_HOST=https://dbc-a03072b4-3eeb.cloud.databricks.com
DATABRICKS_TOKEN=<personal access token, starts with dapi>
DATABRICKS_WAREHOUSE_ID=<from the warehouse page, Connection details>
```

`DATABRICKS_CATALOG` and `DATABRICKS_SCHEMA` default to `workspace` and `handover`; leave them out.

Check with no network:

```
.venv\Scripts\python scripts\databricks_setup.py --check
```

It says exactly what is missing and never prints the token. `git status` must not list `.env`.

## 2. One command: setup

```
.venv\Scripts\python scripts\databricks_setup.py --with-history
```

It starts the warehouse, runs `01_setup.sql`, makes the views, uploads real events from `logs/events.jsonl` (MERGE on `event_id`, so a rerun adds nothing twice), uploads the real lessons (`lessons/<id>/lesson.json`, not `demo-v1` or test ids) and prints counts. Free Edition has a daily compute quota: run it once, not in a loop. Without `--with-history` it skips the old events.

Other flags: `--check` (above), `--teardown-test-data` (runs `04_cleanup_test_data.sql`; the first check row must be all zeros), `--skip-lessons`, `--warehouse-timeout 300`.

After a new lesson is cut or recut, the hub uploads it by itself. By hand: `.venv\Scripts\python -m server.databricks --upload front-wheel-v1`.

## 3. Confirm rows arrive

```
.venv\Scripts\python -m server.databricks --selftest --remote
```

Expect `SELFTEST OK` and a flush. This writes one `selftest` run; the `_real` views and Genie ignore it, and `--teardown-test-data` deletes it. Without `--remote` the selftest stays local.

Then do one real run on the hub and look at the dashboard: Runs goes up by one after the run ends (the uploader flushes at run end, otherwise at most every 60 s).

## 4. Reading the data

1. The warehouse stops after about 10 idle minutes, and the first query after that takes 10 to 60 s. Opening the published dashboard starts it, or `.venv\Scripts\python -m server.databricks --warm` (expect `warm: ok`).
2. Dashboard: open the published link, pick the real lesson in the Lesson filter (`fortune-teller-v2` or `front-wheel-v1`).
3. Genie: open the space, start a new chat, click "Which step do people get stuck on?".
4. No refresh schedule is set; the dashboard reads the views when it is opened.

With only a few runs, the numbers describe those runs, not learners in general.

## 5. If Databricks fails

The learn loop is unaffected: the hub keeps every event in `logs/events.jsonl` and the UI never waits on Databricks (tested with a hung warehouse). Later, `--with-history` uploads the JSONL without duplicates.

| Symptom | Cause | Fix |
|---|---|---|
| `--check` says a value is missing | `.env` not in the repo root, or a typo in the name | Fix `.env`, run `--check` again |
| HTTP 401, "token rejected" | Wrong or expired token | New personal access token (Settings > Developer > Access tokens), update `.env`, restart the hub |
| HTTP 403 on uploads, inserts work | Token scope lacks `files` | New token with `sql` and `files` scopes, or full access |
| First query takes 10 to 60 s | Warehouse was stopped | Expected once; `--warm` starts it ahead of time |
| Every query fails, quota exceeded | Free Edition daily quota | Wait for the quota to reset; events stay in `logs/events.jsonl` |
| Per-step charts empty, Runs counter not | No `steps` rows for that lesson | `python -m server.databricks --upload <id>`, or `05_load_lesson_from_volume.sql` |
| Odd runs in the counters | Lesson filter on all lessons | Pick the real lesson in the filter |
| Step titles off by one | A query joined `n = step` | Always `n = step + 1` |
