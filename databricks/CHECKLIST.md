# Databricks checklist (Prayush)

Details for every line: README.md, under the step number in brackets.

## Sat 3:30 PM: account (15 min)
- [ ] Free Edition account created; workspace URL noted [1]
- [ ] Catalog `workspace` exists [1]
- [ ] Warehouse id copied from Connection details > HTTP path [2]
- [ ] `SELECT current_catalog(), current_user();` returns `workspace` [2]
- [ ] PAT generated (name `handover-hub`, 7 days, scopes `sql` + `files`) [3]
- [ ] HOST, TOKEN, WAREHOUSE_ID typed into `.env` **on the Mac only**; `git status` does not show `.env` [4]
- [ ] Token not in chat, commits, screenshots or this folder
- [ ] Stop. Devpost and poster until the 6:30 gate

## Sat 6:30 PM: only after the live fold passes
- [ ] Group agrees Databricks can start (TEAM_RULES: nothing before the live fold works)
- [ ] `01_setup.sql` run; 4 tables + 1 Volume; counts are zeros [5]
- [ ] Each lesson's `lesson.json` in the Volume, `05_load_lesson_from_volume.sql` run, steps counts correct [6]
- [ ] Optional: `03_test_data.sql` loaded; sticky note "TEST DATA LOADED" on the Mac [7]
- [ ] Dashboard imported or built per dashboard.md; all 13 datasets run; fix list done [7]

## Sat 8 PM to midnight
- [x] Pranav: `server/databricks.py` merged to main (ddcfd29)
- [ ] Soham and Pranav: hub calls `start_run`, `emit(advance/check/mistake/check_offline)`, `end_run` (NOTES_FOR_PRANAV.md 1)
- [ ] Pranav: lessons uploaded by `upload_lesson_files`, or I keep using `05` after every recut (NOTES 2)
- [ ] On the Mac: `--init` all ok, `--selftest` SELFTEST OK, `--warm` ok [8]
- [ ] One real fold shows up in the latest-run query with step titles [8]
- [ ] Genie space built: joins, instructions, Q1 to Q8, common questions [9]
- [ ] Genie rehearsal: Q1 plus two rephrasings reuse the Q1 SQL [9]
- [ ] Midnight full run arrives in `events` within about 10 s [10]
- [ ] Anything missing reported to Pranav

## Sun 8 AM
- [ ] `04_cleanup_test_data.sql` run; check query is `0, 0, 0, 0`; sticky note removed [11]
- [ ] `--warm` ok [12]
- [ ] Dashboard refreshed, fortune teller selected, numbers match the 20 rehearsal folds [13]
- [ ] Dashboard published (Share with data permissions) [13]
- [ ] Genie: new chat, demo question answered from real data [13]
- [ ] Screenshots of dashboard page 1 and the Genie answer saved on the Mac [13]

## Sun 12:00 to 1:00 PM
- [ ] Devpost mentions only what shipped (tables, Volume, dashboard, Genie, if each works)
- [ ] 12:40 `--warm`; again whenever 10 minutes pass without a query [14]
- [ ] Tabs: learn screen, published dashboard, Genie new chat, screenshots [14]
- [ ] Team knows the 2:40 to 3:10 beat and the fallback: skip to close [Demo beat]
- [ ] Hands off Databricks settings during judging

## Needed from teammates
| From | What | By |
|---|---|---|
| Pranav | `server/databricks.py` merged to main | done (ddcfd29) |
| Soham + Pranav | Hub calls the module (`server/main.py` is Soham's) | 10 PM |
| Pranav | `--upload` CLI or `upload_lesson_files` called after each cut/recut, else tell me so I use `05` | 10 PM |
| Pranav | Replay runs tagged (`learner` or `source` in `extra`) so they can be filtered | midnight, if time |
| Soham | Final lesson ids and committed `lesson.json` files, and a message after any recut | each cut |
| Whoever drives the Mac | `--init`, `--selftest`, `--warm` runs with me at the Mac | 8 PM, 8 AM, 12:40 PM |
