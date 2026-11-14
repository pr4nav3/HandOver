// Teach home (section 11), the upload sheet, and Make Course processing (section 13): honest
// per-stage progress, a stage is done only when the hub says so, no invented percentages.

import { hub, pickVideo, uploadVideo, type CourseSummary, type Job, type LessonSummary, call } from "../api";
import { closeSheet, drawSheet, empty, loading, openSheet, pageHead, STATUS_WORD, cover, mmss } from "../components";
import { icons } from "../icons";
import { app, errorText, go, learn, rerender, signedIn } from "../state";
import { html, paint } from "../util";
import { fromLessons, resetHome } from "./home";

let mine: CourseSummary[] | null = null;
let mineError = "";

async function loadMine() {
  try {
    if (!app.library) mine = fromLessons(await call<LessonSummary[]>("lessons"));
    else if (signedIn()) mine = await hub<CourseSummary[]>("GET", "/api/courses", { query: { filter: "mine" } });
    else mine = (await hub<CourseSummary[]>("GET", "/api/courses", { query: { filter: "all" } })).filter((c) => c.legacy);
    mineError = "";
  } catch (e) {
    mineError = errorText(e);
    mine = [];
  }
  rerender();
}

export const resetTeach = () => (mine = null);

export function renderTeach(el: HTMLElement) {
  if (mine === null) void loadMine();
  const list =
    mine === null
      ? loading("Loading your lessons")
      : mineError
        ? empty(icons.filmBig, "Could not load your lessons", mineError)
        : !mine.length
          ? empty(icons.filmBig, "No lessons yet", "Record a task once while you talk through it. HandOver cuts it into steps.")
          : html`<div class="rows">${mine.map(
              (c) => html`<button class="row" data-go="${JSON.stringify({ name: "editor", id: c.id })}">
                ${cover(c.cover_url, "row-cover")}
                <span class="row-text"><span class="row-title">${c.title || c.id}</span>
                  <span class="row-meta">${c.steps} ${c.steps === 1 ? "step" : "steps"}${c.duration ? `, ${mmss(c.duration)}` : ""}${c.org ? `, ${c.org.name}` : ""}</span></span>
                <span class="badge-soft ${c.status}">${STATUS_WORD[c.status]}</span>
                <span class="chev">${icons.chevron}</span>
              </button>`,
            )}</div>`;
  paint(
    el,
    html`<div class="page">
      ${pageHead("Teach")}
      <div class="option-cards">
        <button class="option-card" data-act="teach-pick">
          <span class="tile">${icons.folder}</span>
          <span class="option-title">Choose a File</span>
          <span class="option-line">Pick a video of the whole task. Talk through each step as you do it.</span>
        </button>
        <div class="option-card static">
          <span class="tile">${icons.record}</span>
          <span class="option-title">Record a Take</span>
          <span class="option-line">Record on the HandOver iPhone app or Ray-Ban Meta glasses, then it shows up here.</span>
        </div>
      </div>
      <section class="block">
        <div class="block-head"><h2>Your Lessons</h2></div>
        ${list}
      </section>
    </div>`,
  );
}

// ---- Upload sheet ----

export async function startTeach(orgId?: string) {
  const picked = await pickVideo();
  if (!picked) return;
  const base = picked.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  const title = base ? base[0].toUpperCase() + base.slice(1) : "";
  const orgs = app.orgs.filter((o) => o.role === "org_admin" || o.role === "teacher");
  let err = "";
  openSheet({
    title: "Make a Lesson",
    body: () => html`<form class="form">
      <div class="file-chip">${icons.film}<span><strong>${picked.name}</strong><br />${(picked.size / 1e6).toFixed(1)} MB</span></div>
      <label class="field"><span>Title</span><input name="title" value="${title}" placeholder="Fold a fortune teller" maxlength="120" /></label>
      ${app.library && orgs.length
        ? html`<label class="field"><span>Organization</span><select name="org_id">
            <option value="">None (only me until I publish)</option>
            ${orgs.map((o) => html`<option value="${o.id}" ${o.id === orgId ? "selected" : ""}>${o.name}</option>`)}
          </select></label>`
        : ""}
      <p class="hint">One video of the whole task works best. Talk through each step as you do it.</p>
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Cancel</button>
        <button type="submit" class="primary">Make Course</button></div>
    </form>`,
    onSubmit: (form) => {
      const t = (form.querySelector("[name=title]") as HTMLInputElement).value.trim();
      if (!t) {
        err = "Give the lesson a title.";
        return drawSheet();
      }
      const org = (form.querySelector("[name=org_id]") as HTMLSelectElement | null)?.value || undefined;
      closeSheet();
      upload.start(picked.path, picked.name, picked.size, t, org);
    },
  });
}

// ---- Processing ----

type Phase = "uploading" | "polling" | "done" | "error";

const upload = {
  phase: "uploading" as Phase,
  name: "",
  size: 0,
  title: "",
  sent: 0,
  total: 0,
  job: "",
  id: "",
  status: null as Job | null,
  error: "",
  misses: 0,
  timer: 0,
  args: null as null | { path: string; title: string; route: string; org_id?: string },

  async start(path: string, name: string, size: number, title: string, org?: string) {
    Object.assign(this, { phase: "uploading", name, size, title, sent: 0, total: size, job: "", id: "", status: null, error: "", misses: 0 });
    this.args = { path, title, route: app.library ? "/api/courses" : "/api/lesson", org_id: org };
    go({ name: "processing", job: "", id: "", title, route: this.args.route });
    await this.send();
  },

  async send() {
    if (!this.args) return;
    this.phase = "uploading";
    this.error = "";
    rerender();
    try {
      const r = await uploadVideo(this.args);
      this.job = r.job;
      this.id = r.id;
      this.phase = "polling";
      this.poll();
    } catch (e) {
      this.phase = "error";
      const msg = errorText(e);
      this.error = msg === "too many jobs" ? "The hub is busy with other lessons. Try again when one finishes." : msg;
    }
    rerender();
  },

  poll() {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(async () => {
      try {
        this.status = await hub<Job>("GET", `/api/jobs/${this.job}`);
        this.misses = 0;
        if (this.status.status === "done") {
          this.phase = "done";
          resetTeach();
          resetHome();
        } else if (this.status.status === "error") {
          this.phase = "error";
          this.error = this.status.message || "The hub could not make this lesson.";
        } else this.poll();
      } catch (e) {
        const status = (e as { status?: number }).status;
        if (status === 404) {
          this.phase = "error";
          this.error = "The hub restarted and lost this job. Upload the video again.";
        } else if (++this.misses >= 30) {
          this.phase = "error";
          this.error = "Lost contact with the hub. Check that it is running, then upload again.";
        } else this.poll();
      }
      rerender();
    }, 1000);
  },
};

export function onUploadProgress(sent: number, total: number) {
  upload.sent = sent;
  upload.total = total;
  if (app.route.name === "processing") rerender();
}

const STAGES: { key: string; active: string; done: string }[] = [
  { key: "upload", active: "Uploading", done: "Uploaded" },
  { key: "queued", active: "Waiting for the hub", done: "" },
  { key: "normalizing", active: "Preparing video", done: "Video prepared" },
  { key: "extracting", active: "Finding steps", done: "Steps found" },
  { key: "cutting", active: "Cutting clips", done: "Clips cut" },
];

export function renderProcessing(el: HTMLElement) {
  const u = upload;
  const order = ["upload", "queued", "normalizing", "extracting", "cutting", "done"];
  const at = u.phase === "uploading" ? 0 : u.phase === "done" ? 5 : Math.max(1, order.indexOf(u.status?.status ?? "queued"));
  const failedAt = u.phase === "error" ? (u.job ? at : 0) : -1;
  const rows = STAGES.filter((s) => s.key !== "queued" || at === 1).map((s) => {
    const i = order.indexOf(s.key);
    const state = i === failedAt ? "bad" : i < at ? "done" : i === at && u.phase !== "error" ? "active" : "todo";
    const pct = u.total ? Math.floor((u.sent / u.total) * 100) : 0;
    const text = state === "done" ? s.done || s.active : s.key === "upload" && state === "active" ? `Uploading ${pct}%` : s.active;
    return html`<li class="stage ${state}">
      <span class="stage-mark">${state === "done" ? icons.checkFill : state === "active" ? html`<span class="spinner small"></span>` : state === "bad" ? icons.close : icons.ring0}</span>
      <span class="stage-text">${text}
        ${s.key === "upload" && state === "active" ? html`<span class="bar"><span style="width:${pct}%"></span></span>` : ""}
        ${state === "active" && s.key !== "upload" && u.status?.message ? html`<span class="stage-note">${u.status.message}</span>` : ""}
        ${state === "bad" ? html`<span class="stage-note bad">${u.error}</span>` : ""}
      </span>
    </li>`;
  });
  paint(
    el,
    html`<div class="page center">
      <div class="process-card card">
        <p class="eyebrow">${u.name}${u.size ? `, ${(u.size / 1e6).toFixed(1)} MB` : ""}</p>
        <h1>${u.phase === "done" ? "Your lesson is ready" : u.title}</h1>
        <ul class="stages">${rows}</ul>
        ${u.phase === "done"
          ? html`<div class="form-actions"><button class="secondary" data-act="process-learn">Try It as a Learner</button>
              <button class="primary" data-act="process-edit">Review Steps</button></div>`
          : u.phase === "error"
            ? html`<div class="form-actions"><button class="secondary" data-act="process-close">Done</button>
                <button class="primary" data-act="process-retry">Try Again</button></div>`
            : html`<p class="hint">You can leave this screen. The hub keeps working.</p>
                <div class="form-actions"><button class="secondary" data-act="process-close">Done</button></div>`}
      </div>
    </div>`,
  );
}

export function teachAction(act: string) {
  if (act === "teach-pick") void startTeach();
  else if (act === "process-retry") void upload.send();
  else if (act === "process-close") go({ name: "teach" });
  else if (act === "process-edit") go({ name: "editor", id: upload.id });
  else if (act === "process-learn") learn.start(upload.id, 0, true);
}
