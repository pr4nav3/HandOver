import { hub } from "../api";
import { closeSheet, drawSheet, loading, mmss, openSheet } from "../components";
import { errorText } from "../state";
import { html, type Raw } from "../util";

interface Measure { value: number | null; n: number }
interface StepInsight {
  n: number; title: string; expert_seconds: number;
  median_seconds: Measure; manual_rate: Measure; mistakes_caught: Measure;
}
interface Insights {
  enough_data: boolean;
  runs: { started: number; finished: number; n: number };
  steps: StepInsight[];
  previous_version_runs?: number;
  sync: { source: "local" | "databricks"; state: "refreshing" | "ready" | "unavailable" | "local"; updated_at: string | null };
}

/** One lesson's actionable aggregates. The editor owns the callback, so a row goes to the right step. */
export function insightsSheet(id: string, title: string, edit: (index: number) => void) {
  let value: Insights | null = null;
  let error = "";
  let open = true;
  let timer = 0;
  let polls = 0;
  const load = async () => {
    try {
      const answer = await hub<Insights>("GET", `/api/courses/${encodeURIComponent(id)}/analytics`);
      if (!open) return;
      value = answer;
      error = "";
      if (answer.sync.state === "refreshing" && ++polls < 35) timer = window.setTimeout(() => void load(), 3000);
    } catch (e) { if (open) error = errorText(e); }
    if (open) drawSheet();
  };
  const body = (): Raw => {
    if (error) return html`<div class="form"><p role="alert">Could not load lesson insights. ${error}</p><button class="secondary" data-act="insights-retry">Try Again</button></div>`;
    if (!value) return loading("Loading lesson insights");
    const { runs, steps, sync } = value;
    const slowest = steps.filter((s) => s.median_seconds.value !== null && s.expert_seconds > 0)
      .sort((a, b) => b.median_seconds.value! / b.expert_seconds - a.median_seconds.value! / a.expert_seconds)[0];
    const completion = runs.started ? `${Math.round(runs.finished / runs.started * 100)}%` : "—";
    return html`<div class="lesson-insights">
      <p class="muted">${title}</p>
      <div class="insights-metrics">
        <div><strong>${runs.started}</strong><span>Attempts</span></div>
        <div><strong>${runs.finished}</strong><span>Finished</span></div>
        <div><strong>${completion}</strong><span>Completion</span></div>
      </div>
      ${runs.started < 5 ? html`<p class="muted">${runs.started ? `Based on ${runs.started} ${runs.started === 1 ? "attempt" : "attempts"}. Treat these as early observations.` : "No learner attempts yet. Complete this lesson with a live camera to see how each step goes."}</p>` : ""}
      ${value.previous_version_runs ? html`<p class="muted">${value.previous_version_runs} ${value.previous_version_runs === 1 ? "attempt from an earlier cut is" : "attempts from earlier cuts are"} excluded so step comparisons match this lesson.</p>` : ""}
      ${slowest ? html`<section class="insights-observation"><h3>Worth reviewing</h3><p>Step ${slowest.n} takes learners ${mmss(slowest.median_seconds.value!)} against the expert's ${mmss(slowest.expert_seconds)}. Review the clip and check question.</p><button class="secondary small" data-act="insights-step" data-step="${slowest.n - 1}">Review Step ${slowest.n}</button></section>` : ""}
      ${steps.length ? html`<div class="insights-table-wrap"><table class="insights-table"><thead><tr><th>Step</th><th>Learner median</th><th>Expert</th><th>Used Next</th><th>Mistakes</th></tr></thead><tbody>${steps.map((s) => html`<tr><th><button class="quiet" data-act="insights-step" data-step="${s.n - 1}">${s.n}. ${s.title}</button><small>${s.median_seconds.n} timed ${s.median_seconds.n === 1 ? "attempt" : "attempts"}</small></th><td>${s.median_seconds.value === null ? "—" : mmss(s.median_seconds.value)}</td><td>${mmss(s.expert_seconds)}</td><td>${s.manual_rate.value === null ? "—" : `${Math.round(s.manual_rate.value * 100)}%`}</td><td>${s.mistakes_caught.value ?? "—"}</td></tr>`)}</tbody></table></div>` : ""}
      <p class="insights-source">${sync.state === "refreshing" ? "Updating from Databricks. Recent activity is shown immediately." : sync.state === "unavailable" ? "Databricks is unavailable. Showing saved activity." : sync.source === "databricks" ? `Databricks and recent hub activity · Updated ${sync.updated_at ? new Date(sync.updated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "just now"}` : "Activity saved on this hub. Databricks export is not configured."}</p>
      <p class="insights-source">Live attempts only. Practice replays and simulated checks are excluded. Used Next applies to camera-checked steps.</p>
    </div>`;
  };
  openSheet({ title: "Lesson Insights", wide: true, body,
    onAction: (action, element) => {
      if (action === "insights-retry") { error = ""; polls = 0; void load(); drawSheet(); }
      if (action === "insights-step") { const n = Number(element.dataset.step); closeSheet(); edit(n); }
    },
    onClose: () => { open = false; window.clearTimeout(timer); },
  });
  void load();
}
