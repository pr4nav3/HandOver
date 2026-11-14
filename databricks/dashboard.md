# Dashboard: HandOver learner runs

AI/BI dashboard (formerly Lakeview). Two pages. Page 1 is the only one a judge sees; page 2 is for us and for follow-up questions.

Two ways to build it:

- **Import** `handover.lvdash.json` (5 minutes, then check). The UI path is documented: Dashboards listing > blue caret next to **Create dashboard** > **Import dashboard from file** > **Choose file** > **Import dashboard** ([Export, import, or replace a dashboard](https://docs.databricks.com/aws/en/dashboards/automate/import-export)). The file was generated from `02_dashboard_datasets.sql` and modelled on Databricks' own published `.lvdash.json` examples (databricks/bundle-examples). Not imported into a live workspace yet, so treat it as unverified. If the import errors, or any widget shows a red error, build that widget by hand from the spec below; the datasets in the imported file are still usable.
- **By hand** from the spec below (about 30 minutes). Dataset SQL: `02_dashboard_datasets.sql`. UI steps: [Create a dashboard](https://docs.databricks.com/aws/en/dashboards/tutorials/create-dashboard).

Either way, finish with the checks in "Before judging" at the end.

## Name and headline

- Dashboard name: `HandOver learner runs`
- Page 1 headline (text widget, Markdown):

  ```
  # Where learners slow down
  Every number comes from real HandOver runs: each step's camera check, each Next press, each mistake the camera caught. Expert time is the expert's own take.
  ```
- Legend line (text widget, one line): `Green = verified by the camera. Amber = mistake caught. Times in Madison time (CST).`

Say only what the data supports. With fewer than about 5 runs, say "in our runs tonight", not "learners".

## Colors

One meaning per color, the same in every widget. Everything else is neutral grey.

| Meaning | Hex | Used for |
|---|---|---|
| Camera verified | `#30D158` | method = Camera; verdict = yes |
| Mistake, behind | `#FF9F0A` | mistake_kind = Behind |
| Mistake, ahead | `#FFCC66` | mistake_kind = Ahead |
| Primary neutral | `#3A3A3C` | Learners (median); verdict = no; p50; outcome = Finished |
| Mid grey | `#8E8E93` | method = Button; outcome = In progress; single-series bars |
| Light grey | `#C7C7CC` | Expert; method = Voice; verdict = unsure; p90; outcome = Abandoned |

Do not use green for anything that is not a camera pass, and do not use amber for anything that is not a caught mistake. Set colors per value: widget > **Color** > click the swatch for each value (unverified label).

## Filter

One **Lesson** filter per page: **Add a filter (field/parameter)** > **Single value** > field `lesson_id`, then tick every dataset on that page under fields (each dataset has a `lesson_id` column). Default: no selection (all lessons). For the demo, select the fortune teller lesson.

## Grid

The canvas is 6 columns wide. Positions are (x, y, width, height) in grid units, matching `handover.lvdash.json`.

### Page 1: Overview

| Widget | Type | Dataset | Position | Encoding |
|---|---|---|---|---|
| Headline | Text | | 0, 0, 6, 2 | Markdown above |
| Lesson | Filter, single value | all page-1 datasets | 0, 2, 2, 1 | `lesson_id` |
| Legend | Text | | 2, 2, 4, 1 | legend line above |
| Runs | Counter | ds_runs | 0, 3, 1, 2 | COUNT(`run_id`) |
| Finished | Counter | ds_runs | 1, 3, 1, 2 | SUM(`finished`) |
| Steps passed by camera | Counter | ds_runs | 2, 3, 1, 2 | SUM(`camera_advances`) |
| Steps passed by Next | Counter | ds_runs | 3, 3, 1, 2 | SUM(`manual_advances`) |
| Mistakes caught | Counter | ds_runs | 4, 3, 1, 2 | SUM(`mistakes`) |
| Median check (ms) | Counter | ds_checks | 5, 3, 1, 2 | MEDIAN(`latency_ms`) (if Median is not offered, use ds_check_latency_overall and show `p50_ms` with the lesson filter set) |
| Time per step: learners vs the expert | Bar, grouped | ds_time_per_step | 0, 5, 6, 6 | X `step_label` (categorical, sort A to Z); Y SUM(`seconds`), title "Seconds"; Color `series` (Learners (median) `#3A3A3C`, Expert `#C7C7CC`); layout Group, not Stack |
| How each step was passed | Bar, stacked | ds_advance_method | 0, 11, 3, 6 | X `step_label`; Y SUM(`advances`); Color `method` (Camera green, Button `#8E8E93`, Voice `#C7C7CC`) |
| Mistakes the camera caught | Bar, stacked | ds_mistakes | 3, 11, 3, 6 | X `step_label`; Y SUM(`mistakes`); Color `mistake_kind` (Behind `#FF9F0A`, Ahead `#FFCC66`) |
| Step by step | Table | ds_step_summary | 0, 17, 6, 6 | columns: step_label "Step", check_type "Check", expert_s "Expert s", learner_median_s "Learner median s", slowdown "x expert", manual_rate "Manual rate" (percent), mistakes, false_passes "False passes", abandoned_here "Stopped here", runs_measured "Runs" |
| Runs per hour | Bar, stacked | ds_runs | 0, 23, 6, 4 | X `started_local` by hour (temporal), title "Hour (CST)"; Y COUNT(`run_id`); Color `outcome` (Finished `#3A3A3C`, In progress `#8E8E93`, Abandoned `#C7C7CC`) |

Widget descriptions (turn on "Show description"):

- Time per step: `Median seconds a learner spent on each step, next to the expert's own time in the take.`
- How each step was passed: `Camera = the check saw the step done. Button or Voice = the learner pressed Next.`
- Mistakes: `Behind = still looks like the previous step. Ahead = already on the next step.`

### Page 2: Camera checks

| Widget | Type | Dataset | Position | Encoding |
|---|---|---|---|---|
| Headline | Text | | 0, 0, 6, 2 | `# Camera check quality` + `How often the check said yes, no or unsure, how long it took, and where it let people through too early.` |
| Lesson | Filter, single value | all page-2 datasets | 0, 2, 2, 1 | `lesson_id` |
| Check verdicts per step | Bar, stacked | ds_checks | 0, 3, 3, 6 | X `step_label`; Y COUNT(*); Color `verdict` (yes green, no `#3A3A3C`, unsure `#C7C7CC`) |
| Average check confidence per step | Bar | ds_checks | 3, 3, 3, 6 | X `step_label`; Y AVG(`confidence`), 0 to 1; single color `#8E8E93` |
| Check latency per step (p50, p90) | Bar, grouped | ds_check_latency_by_step | 0, 9, 4, 6 | X `step_label`; Y SUM(`latency_ms`); Color `stat` (p50 `#3A3A3C`, p90 `#C7C7CC`); layout Group |
| Latency per lesson | Table | ds_check_latency_overall | 4, 9, 2, 6 | lesson_id, checks, p50_ms, p90_ms, timed_out_rate (percent) |
| Manual-advance rate (camera steps) | Bar | ds_manual_rate | 0, 15, 3, 6 | X `step_label`; Y AVG(`manual_rate`) as percent; single color `#8E8E93` |
| False passes | Table | ds_false_passes | 3, 15, 3, 6 | step_label, camera_passes, false_passes "Undone within 60 s", false_pass_rate (percent) |
| Where unfinished runs stopped | Bar | ds_abandoned | 0, 21, 3, 5 | X `step_label`; Y SUM(`abandoned_runs`); single color `#C7C7CC` |
| Checks off incidents | Table | ds_check_offline | 3, 21, 3, 5 | ts_local "Time (CST)", reason, step_label |
| Lessons | Table | ds_lessons | 0, 26, 6, 3 | lesson_id, lesson_title, steps, camera_steps, expert_total_s |

## After import: fix list

The import format is reconstructed, not exported from a live workspace. Check these first:

1. Data tab: 13 datasets, named `ds_*`. Click each, **Run**. Every one should run without error (empty results are fine before real data).
2. Both grouped bars (Time per step, Check latency): if the bars are stacked, switch the layout to grouped in the widget's settings. Stacked learner + expert bars are misleading.
3. Colors: every widget uses the table above. Fix any value still in the default palette.
4. Lesson filter: change it and confirm every widget on the page responds. If one does not, open the filter's field list and tick that dataset.
5. X axis order: steps should read 01, 02, 03. If not, set the X sort to ascending by `step_label`.
6. Counter "Median check (ms)": if it shows an error, see the fallback in the page-1 table.

## Before judging

1. Run `04_cleanup_test_data.sql`. Its check query must return all zeros.
2. Open the dashboard, refresh (top right), select the fortune teller lesson. Every number on page 1 must come from tonight's and this morning's real runs.
3. **Publish** > **Share with data permissions (default)** > **Publish** ([docs](https://docs.databricks.com/aws/en/dashboards/tutorials/create-dashboard)). Present the published view, not the draft editor.
4. Leave the tab open on the Mac, zoom so page 1 headline, counters and the time-per-step chart fit one screen at the demo resolution.
