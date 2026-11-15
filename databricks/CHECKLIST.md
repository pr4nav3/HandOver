# Databricks checklist (demo day, Sunday Nov 15)

On the demo laptop (Pranav's Windows laptop, `C:\Users\karth\Projects\HandOver-soham`), PowerShell, repo root. Details: README.md, section in brackets.

## Done already (live in the workspace)
- [x] Schema `workspace.handover`, four tables, Volume `lessons`
- [x] 29 views: `events_real`, `runs_real`, `runs_excluded`, 13 `ds_<name>`, 13 `ds_<name>_real`
- [x] Dashboard "HandOver: learner runs" on the `_real` views, two pages, published with embedded credentials
- [x] Genie space "HandOver learner runs" on `events_real`, `runs_real`, `lessons`, `steps`; 8 examples tested; demo question rehearsed

## Credentials [1]
- [ ] Token handed over in person or by direct message, never in the group chat
- [ ] `.env` on the demo laptop has HOST, TOKEN, WAREHOUSE_ID; `.env.example` still has empty values
- [ ] `.venv\Scripts\python scripts\databricks_setup.py --check` reports nothing missing
- [ ] `git status` does not list `.env`

## Setup, once [2, 3]
- [ ] `.venv\Scripts\python scripts\databricks_setup.py --with-history` ends with every step ok
- [ ] Counts show the real lessons with their steps (`fortune-teller-v1` is there now; `fortune-teller-v2`, the live demo, and `front-wheel-v1` once uploaded)
- [ ] `.venv\Scripts\python -m server.databricks --selftest --remote` says `SELFTEST OK`
- [ ] One real run on the hub, then the dashboard's Runs counter goes up for that lesson
- [ ] Optional: `--teardown-test-data`, first check row all zeros

## Before judges, 12:40 PM [4]
- [ ] Warm: open the published dashboard, or `.venv\Scripts\python -m server.databricks --warm` says `warm: ok`
- [ ] Dashboard tab open on the published link, Lesson filter on the real lesson
- [ ] Genie tab open, new chat, "Which step do people get stuck on?" answered from real runs
- [ ] Screenshots of dashboard page 1 and the Genie answer saved on the laptop
- [ ] Warm again if judges are more than 10 minutes apart
- [ ] No edits to the dashboard, Genie or views during judging; no refresh schedule

## If Databricks fails [5]
- [ ] Demo goes on: events stay in `logs\events.jsonl`, the UI never waits on Databricks
- [ ] Show the screenshots, say they are from this morning, move on
