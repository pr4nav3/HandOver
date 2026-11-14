# Databricks runbook (HandOver)

Owner: Prayush. Scope (TEAM_RULES.md): data layer only, never in the live loop. Unity Catalog tables, one Volume, one AI/BI dashboard, one Genie space. The hub writes through `server/databricks.py` (Pranav); this folder is everything done in the Databricks UI.

| File | What it is |
|---|---|
| `README.md` | This runbook, in timeline order |
| `CHECKLIST.md` | One-page tick list for the night |
| `01_setup.sql` | Schema, four tables, Volume. Identical to Pranav's DDL. Idempotent |
| `02_dashboard_datasets.sql` | The 13 dashboard datasets, one named query each |
| `03_test_data.sql` | Optional synthetic rows for building before real runs exist. **Delete before judging** |
| `04_cleanup_test_data.sql` | Deletes exactly the synthetic and `--selftest` rows |
| `05_load_lesson_from_volume.sql` | Fallback: fills `lessons` and `steps` from `lesson.json` files in the Volume |
| `dashboard.md` | Dashboard layout, widgets, colors, headline, publish |
| `handover.lvdash.json` | The same dashboard as an importable file (format unverified, see dashboard.md) |
| `genie.md` | Genie space: instructions, joins, 8 tested example queries, the demo question, rehearsal |
| `NOTES_FOR_PRANAV.md` | Issues found in his module and SQL; not fixed here (his folder) |

All SQL in `02`–`05` and `genie.md` was run on local Apache Spark (PySpark 4.3) with the synthetic data in `03` (MERGE, DELETE and `read_files` excepted: Databricks-only). It was not run on a Databricks warehouse yet, so do the verify steps below.

## Names (fixed; the module and every query depend on them)

| Thing | Name |
|---|---|
| Catalog | `workspace` (Free Edition default) |
| Schema | `workspace.handover` |
| Tables | `lessons`, `steps`, `runs`, `events` |
| Volume | `workspace.handover.lessons`, path `/Volumes/workspace/handover/lessons/<lesson_id>/` |
| Warehouse | `Serverless Starter Warehouse` (unverified name; Free Edition has one 2X-Small warehouse) |
| Dashboard | `HandOver learner runs` |
| Genie space | `HandOver learner runs` |

## Timing conflict, and the call

- docs/PLAN.md section 6 puts "Databricks tables" in Prayush's 3:30–6:30 PM slot.
- TEAM_RULES.md: "Nobody starts it until the live fold works end to end", and SCOPE.md: Databricks is SHOULD, after the 6:30 PM gate.

Recommendation: before 6:30, do only steps 1–4 (account, warehouse id, token, `.env`). PLAN.md's humans-only checklist asks for exactly that, and it touches nothing in the repo. Run `01_setup.sql` after the 6:30 gate passes, unless the team says otherwise in the group. Everything else in this folder is ready to paste, so waiting costs about 5 minutes.

## Free Edition facts that shape the plan

Source: [Free Edition limitations](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations).

- Serverless only. **One SQL warehouse, 2X-Small at most.**
- **Daily compute quota.** Going over shuts down workspace compute for the rest of the day, in extreme cases the month. Data is kept, but nothing will query. This is the main demo risk. Keep usage low: the module batches writes (one statement per table every 5 s at most, nothing when idle); never set a dashboard refresh schedule; do not leave Genie or the SQL editor running loops; close the dashboard editor tabs you are not using.
- One workspace, one metastore, no account console.
- Serverless warehouse auto-stop defaults to 10 minutes ([SQL warehouse settings](https://docs.databricks.com/aws/en/compute/sql-warehouse/create)). After 10 idle minutes the first query starts it again (cold start). Hence the warm-up steps.
- Personal access tokens: documented as "legacy" but supported; up to 600 per user, revoked after 90 days unused ([PAT docs](https://docs.databricks.com/aws/en/dev-tools/auth/pat)). Whether a Free Edition workspace has PATs enabled by default is unverified; check in step 3.
- Genie is included in Free Edition ([Free Edition](https://docs.databricks.com/aws/en/getting-started/free-edition)). Dashboards are listed there as "interactive dashboards".

---

## Saturday 3:30 PM: account, warehouse, token (15 min)

### 1. Sign up

1. Open [Databricks Free Edition](https://docs.databricks.com/aws/en/getting-started/free-edition) > sign up (`https://login.databricks.com/?intent=CE_SIGN_UP`). Use the team email that will still be checked on Sunday. Sign-in is email one-time code, Google or Microsoft.
2. Databricks creates a workspace. Note its URL, e.g. `https://dbc-xxxxxxxx-xxxx.cloud.databricks.com`. That is `DATABRICKS_HOST` (with `https://`, no trailing slash, no `?o=` part).

Verify: sidebar shows **SQL Editor**, **Dashboards**, **Genie** (or **Genie Agents**), **Catalog**. In **Catalog**, a catalog named `workspace` exists. If the catalog has another name, stop and tell Pranav: set `DATABRICKS_CATALOG` in `.env` and find/replace `workspace.handover` in these files.

### 2. Warehouse id

1. Sidebar > **SQL Warehouses** > click the one warehouse (expected `Serverless Starter Warehouse`).
2. **Connection details** tab > **HTTP path**, e.g. `/sql/1.0/warehouses/1a2b3c4d5e6f7a8b`. The part after `/warehouses/` is `DATABRICKS_WAREHOUSE_ID` ([compute details](https://docs.databricks.com/aws/en/integrations/compute-details)). The same id is in the browser URL of the warehouse page.
3. Leave auto-stop at the default.

Verify: SQL Editor, pick that warehouse top right, run `SELECT current_catalog(), current_user();`. Expect `workspace` and your email.

### 3. Personal access token

Steps from [PAT docs](https://docs.databricks.com/aws/en/dev-tools/auth/pat):

1. Click your username (top right) > **Settings** > **Developer** > **Access tokens** > **Manage** > **Generate new token**.
2. Comment: `handover-hub`. Lifetime: `7` days.
3. If the dialog asks for a scope type: choose **Other APIs** and add the scopes `sql` and `files` ([API scopes](https://docs.databricks.com/api/workspace/scopes); the module runs SQL statements and uploads files to the Volume). If you cannot find `files`, leave scopes for full access instead.
4. **Generate**, copy the token (starts with `dapi`), **Done**. It is shown once.

Rules: the token goes only into `.env` on the Mac. Never into chat, a commit, a screenshot, Devpost, or this folder. If it leaks, revoke it on the same page and generate a new one.

### 4. `.env` on the Mac

Sit at the Mac (or hand the values to Pranav in person there). In the repo root `.env` (already gitignored), add:

```
DATABRICKS_HOST=https://dbc-xxxxxxxx-xxxx.cloud.databricks.com
DATABRICKS_TOKEN=dapi...
DATABRICKS_WAREHOUSE_ID=1a2b3c4d5e6f7a8b
```

`DATABRICKS_CATALOG` and `DATABRICKS_SCHEMA` default to `workspace` and `handover`; leave them out.

Verify: `git status` on the Mac does not list `.env`. `server/databricks.py` is on main (ddcfd29), but until the hub calls it (NOTES_FOR_PRANAV.md, item 1) nothing sends events, and the hub runs exactly as before.

Then stop Databricks work until the 6:30 gate. Devpost and poster.

---

## Saturday 6:30–8:00 PM (after the gate): tables, Volume, dashboard skeleton

### 5. Tables and Volume (5 min)

1. SQL Editor > new query > warehouse selected > paste all of `01_setup.sql` > **Run all**.
   (Equivalent, now that it is on main: `python -m server.databricks --init` on the Mac. Running both is harmless.)
2. Verify, with the queries at the bottom of `01_setup.sql`:
   - `SHOW TABLES IN workspace.handover;` returns `events`, `lessons`, `runs`, `steps`.
   - `SHOW VOLUMES IN workspace.handover;` returns `lessons`.
   - The counts query returns four zeros.
3. **Catalog** > `workspace` > `handover`: the four tables show column comments. Genie reads these.

If `CREATE SCHEMA` fails with a permission error: unverified on Free Edition, but you should own `workspace`. Run `SHOW GRANTS ON CATALOG workspace;` and tell the group. Do not switch to a different schema without telling Pranav (his module uses `DATABRICKS_SCHEMA`).

### 6. Lesson files and steps rows

The per-step charts need a `steps` row for every lesson (events join to steps on `n = step + 1`). Normal path: the hub calls `upload_lesson_files()`, which uploads the lesson folder to the Volume and writes `lessons` and `steps`. Nothing calls it yet (NOTES_FOR_PRANAV.md, item 2). Until it does, load by hand once a lesson is cut and committed:

1. **Catalog** > `workspace` > `handover` > **Volumes** > `lessons` > **Create directory** named exactly the lesson id (e.g. `fortune-teller-v1`) > open it > **Upload to this volume** > the repo's `lessons/<id>/lesson.json`. (UI labels unverified; the Volume page has an upload button.)
2. Run `05_load_lesson_from_volume.sql`: preview, then the two MERGEs, then the verify query.
3. Verify: one row per lesson with the right step count and one `manual` step (step 1).

Redo after Soham recuts a lesson. It is an upsert, so it is safe to repeat.

### 7. Dashboard skeleton (45 min)

1. Optional, only if there are no real runs yet: run `03_test_data.sql` (synthetic lesson `test-fortune-teller`, 14 runs). Verify: its last query returns `1, 8, 14, 919`. Write "TEST DATA LOADED" on a sticky note on the Mac until step 13 removes it.
2. Build the dashboard per `dashboard.md`: import `handover.lvdash.json`, then the fix list; or build by hand.
3. Verify: every dataset runs; with the Lesson filter on `test-fortune-teller`, Time per step shows step 5 (Flip it over) with the largest learner/expert gap, and How each step was passed shows step 5 with the most grey.
4. Do not publish yet.

---

## Saturday 8:00 PM–midnight: real data, Genie

### 8. Module merged, first real rows

Needs: `server/databricks.py` is on main (done, ddcfd29); the hub still has to call it (NOTES_FOR_PRANAV.md, item 1). Then on the Mac:

```
.venv/bin/python -m server.databricks --init       # prints DDL, runs it; every line "ok"
.venv/bin/python -m server.databricks --selftest   # ends with "SELFTEST OK"
.venv/bin/python -m server.databricks --warm       # "warm: ok in N s"
```

Verify in the SQL editor:

```sql
-- The selftest run arrived (lesson 'selftest'). Remove later with 04_cleanup_test_data.sql.
SELECT kind, count(*) FROM workspace.handover.events WHERE lesson_id = 'selftest' GROUP BY kind;

-- After one real fold on the hub: one run, its events in order, steps joined.
SELECT e.ts, e.kind, e.step + 1 AS step_n, s.title, e.done, e.reason, e.from_step, e.to_step
FROM workspace.handover.events e
LEFT JOIN workspace.handover.steps s ON s.lesson_id = e.lesson_id AND s.n = e.step + 1
WHERE e.run_id = (SELECT run_id FROM workspace.handover.runs ORDER BY started_at DESC LIMIT 1)
ORDER BY e.ts;
```

Expect `run_start`, then `check` and `advance` rows per step, `to_step` of the last advance equal to the step count, and a title on every row. A NULL title means the steps rows are missing (step 6).

### 9. Genie space (30 min, by midnight)

Follow `genie.md`: create, joins, general instructions, 8 example queries, common questions, rehearse. Verify: the common question "Which step do people get stuck on?" returns the Q1 SQL and a three-row table.

### 10. Midnight full run

During the team's full run on real Gemini, watch the latest run with the step 8 query. Every advance should be there within about 10 s of happening. Note anything missing for Pranav.

---

## Sunday 8:00 AM: real data only, warm, rehearse

### 11. Remove test rows

Run `04_cleanup_test_data.sql`. Its check query must return `0, 0, 0, 0`. Remove the sticky note. From now on the dashboard shows real events only (PLAN.md: done screen and data from real events).

### 12. Warm the warehouse

`.venv/bin/python -m server.databricks --warm` on the Mac, or run `SELECT 1;` in the SQL editor. Expect `warm: ok`.

### 13. Rehearse

1. Dashboard: refresh, filter to the fortune teller lesson, check every widget against what the team saw in the 20 rehearsal folds. Numbers that look wrong are a data or wiring bug: tell Pranav, do not change queries to look better.
2. Publish (dashboard.md, Before judging).
3. Genie: rehearse per genie.md section 5.
4. Screenshot page 1 and the Genie answer (PNG, on the Mac). This is the fallback if the quota trips or the venue network fails. If used, say "this is from this morning's runs".

### 14. Before judging (12:00–1:00 PM)

1. 12:40: `--warm` again. Auto-stop is 10 minutes, so warm again if judges have not arrived by 12:55, and between judge visits that are more than 10 minutes apart.
2. Tabs on the Mac, in order: learn screen, published dashboard (page 1, fortune teller selected), Genie space (new chat, no question asked yet), screenshots folder.
3. Do not edit anything in Databricks during judging.

---

## Demo beat: 2:40–3:10 (PLAN.md section 7)

Thirty seconds. Fallback per PLAN.md: skip to the close.

| Time | Screen | Who does what | Say |
|---|---|---|---|
| ~2:30 (judge on the last fold) | Genie tab, in the background | Click the common question "Which step do people get stuck on?" so the answer is ready in 20 s | |
| 2:40 | Learn screen, done screen | Driver stays on the done screen | (done screen line, owned by the pitch) |
| 2:50 | Dashboard, page 1 | Switch tab; click refresh (top right) so the judge's run is in | "Every run lands in Databricks. Grey is the learners' median per step, light grey is the expert's own time. Green is a step the camera verified." Point at the tallest learner bar |
| 3:00 | Genie tab | Show the answer | "And anyone can ask it: which step do people get stuck on? Genie says step N, [title]: N seconds against the expert's M, and the camera caught K mistakes there." Read the real numbers from the screen |
| 3:10 | | Move to the close | |

Rules for the beat:

- Read numbers off the screen. Never quote a number from rehearsal or from memory.
- If the refresh is still spinning at 2:55, talk over it and move to Genie.
- If Genie is slow or wrong, say "Genie answers from the same tables" and show the dashboard's Step by step table instead.
- If compute is down (quota): show the 8 AM screenshots, say they are from this morning, move on.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `--selftest` prints `HTTP 403` | Token scope or token revoked | New token with `sql` and `files` scopes (step 3); update `.env`; restart the hub |
| `HTTP 401` | Wrong host or token | Host must be the workspace URL with `https://`, no `?o=`; token copied whole |
| `HTTP 404` on `/api/2.0/sql/statements` | Host has a path, or wrong workspace | Use only the scheme and host |
| `warehouse ... not found` | Wrong `DATABRICKS_WAREHOUSE_ID` | Copy the id from the HTTP path again (step 2) |
| `TABLE_OR_VIEW_NOT_FOUND` in the module log | Tables not created | Step 5, then restart the hub (failed batches retry 3 times, then stay only in `logs/events.jsonl`) |
| Queries hang 10–60 s then work | Warehouse was stopped (auto-stop 10 min) | Expected once; warm before demos |
| Every query fails, compute "quota exceeded" | Daily Free Edition quota | Nothing to fix today. Use screenshots. Data is kept |
| Charts empty but `events` has rows | No `steps` rows for that lesson, or lesson ids differ | Step 6; compare `SELECT DISTINCT lesson_id FROM workspace.handover.events` with `steps` |
| Step titles one off | A query joined `n = step` | Always `n = step + 1` |
| Times six hours off | Stored UTC, shown raw | Datasets convert with `from_utc_timestamp(..., 'America/Chicago')`; check the widget uses `ts_local` / `started_local` |
| Runs counter includes odd runs | `--selftest` or synthetic rows | `04_cleanup_test_data.sql` |
| Dashboard numbers differ from the done screen | Done screen computes in the browser for one run; dashboard aggregates all runs | Say "across all runs" for the dashboard |
| Genie answers with wrong step numbers | It used `step` (0-based) as the step number | Check the general instructions and joins are saved; ask via the Q1 common question |
| Import of `handover.lvdash.json` fails | Format guessed, not exported | Build by hand per dashboard.md; datasets from `02` |

## Unverified items

- Exact current name of the Free Edition warehouse ("Serverless Starter Warehouse") and whether PATs are enabled by default on Free Edition.
- PAT dialog scope names in the UI (`sql`, `files` are the documented API scope names).
- `handover.lvdash.json` import on Free Edition, the `mark.layout: group` key for grouped bars, hex colors in value mappings, and the `MEDIAN` widget aggregation.
- Volume UI labels "Create directory" and "Upload to this volume".
- `read_files` with a `*` glob over Volume paths in `05` (documented for `read_files`; not run here).
- Genie UI labels after the rename to "Genie Agents" may differ from the docs by release.
