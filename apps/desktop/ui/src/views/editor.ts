// The course editor (section 14): step list, player and timeline with draggable boundaries,
// and the step inspector. Every change goes to the hub's editor routes (library.md, Editor),
// which keep undo and redo. Publish opens the publish sheet (section 15.2).

import { hub, lessonUrl, toSeconds, type CourseDetail, type FullLesson, type Step } from "../api";
import { closeSheet, drawSheet, empty, loading, openSheet, orgAvatar, STATUS_WORD } from "../components";
import { icons } from "../icons";
import { app, back, errorText, learn, rerender, toast } from "../state";
import { html, paint } from "../util";
import { reloadCourse } from "./course";
import { resetHome } from "./home";
import { resetTeach } from "./teach";

const ed = {
  id: "",
  d: null as CourseDetail | null,
  error: "",
  sel: 0,
  saving: "" as "" | "Saving" | "Updating clips" | "Saved" | "Could not save",
  banner: "",
  busy: false,
  /** Changes after every edit, so frames and clips are fetched fresh. */
  stamp: Date.now(),
};

/** The player survives repaints so playback does not restart on every change. */
let player: HTMLVideoElement | null = null;
let playerFor = "";

async function load(id: string) {
  Object.assign(ed, { id, d: null, error: "", sel: 0, saving: "", banner: "", busy: false });
  try {
    ed.d = await hub<CourseDetail>("GET", `/api/courses/${id}`);
  } catch (e) {
    ed.error = errorText(e);
  }
  rerender();
}

const secs = (t: string) => toSeconds(t);
const fmt = (s: number) => {
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return `${String(m).padStart(2, "0")}:${r.toFixed(1).padStart(4, "0")}`;
};

function lessonEnd(l: FullLesson) {
  return l.steps.length ? secs(l.steps[l.steps.length - 1].end) : 0;
}

/** Runs one editor operation and takes the hub's new lesson and history. */
async function op(path: string, body: unknown, recut: boolean) {
  if (ed.busy || !ed.d) return;
  ed.busy = true;
  ed.saving = recut ? "Updating clips" : "Saving";
  ed.banner = "";
  rerender();
  try {
    const r = await hub<{ lesson: FullLesson; history: { undo: number; redo: number } }>("POST", `/api/courses/${ed.id}/edit/${path}`, { body });
    ed.d.lesson = r.lesson;
    ed.d.history = r.history;
    ed.sel = Math.min(ed.sel, r.lesson.steps.length - 1);
    ed.saving = "Saved";
    ed.stamp = Date.now();
    reloadCourse();
    resetHome();
    resetTeach();
  } catch (e) {
    ed.saving = "Could not save";
    ed.banner = errorText(e);
  }
  ed.busy = false;
  rerender();
}

export function renderEditor(el: HTMLElement, id: string) {
  if (ed.id !== id) {
    void load(id);
  }
  if (!app.library) {
    paint(el, html`<div class="page"><button class="secondary" data-act="ed-back">Back to Lessons</button>${empty(icons.filmBig, "Editing needs a newer hub", "Update the hub, then try again.")}</div>`);
    return;
  }
  if (ed.error) return paint(el, html`<div class="page"><button class="secondary" data-act="ed-back">Back to Lessons</button>${empty(icons.filmBig, "Could not open the editor", ed.error)}</div>`);
  if (!ed.d) return paint(el, html`<div class="page"><button class="secondary" data-act="ed-back">Back to Lessons</button>${loading("Loading the lesson")}</div>`);
  const { course, lesson, permissions, history } = ed.d;
  const steps = lesson.steps;
  const s = steps[ed.sel];
  const end = Math.max(lessonEnd(lesson), 0.1);
  const canEdit = permissions.can_edit;
  paint(
    el,
    html`<div class="editor">
      <header class="editor-bar">
        <button class="icon-button" data-act="ed-back" title="Back" aria-label="Back">${icons.back}</button>
        <div class="editor-title"><strong>${course.title || id}</strong>
          <span class="badge-soft ${course.status}">${STATUS_WORD[course.status]}</span></div>
        <span class="editor-status ${ed.saving === "Could not save" ? "bad" : ""}">${ed.saving}</span>
        <button class="icon-button" data-act="ed-undo" title="Undo" aria-label="Undo" ${history?.undo && !ed.busy ? "" : "disabled"}>${icons.undo}</button>
        <button class="icon-button" data-act="ed-redo" title="Redo" aria-label="Redo" ${history?.redo && !ed.busy ? "" : "disabled"}>${icons.redo}</button>
        <button class="secondary" data-act="ed-details">Details</button>
        <button class="secondary" data-act="ed-preview">Preview</button>
        ${permissions.can_publish ? html`<button class="primary" data-act="ed-publish">${course.status === "published" ? "Update" : "Publish"}</button>` : ""}
      </header>
      ${ed.banner ? html`<div class="banner bad" role="alert">${ed.banner}</div>` : ""}
      <div class="editor-grid">
        <aside class="ed-steps">
          <div class="ed-step-list scroll">
            ${steps.map(
              (st, i) => html`<button class="ed-step ${i === ed.sel ? "on" : ""}" data-act="ed-select" data-step="${i}">
                <span class="ed-hue" style="background:${i === ed.sel ? "var(--accent)" : "var(--border-strong)"}"></span>
                <img src="${lessonUrl(id, st.ref_frame, ed.stamp)}" alt="" />
                <span class="ed-step-text"><span class="ed-step-title">${i + 1}. ${st.title || "Untitled step"}</span>
                  <span class="ed-step-meta">${fmt(secs(st.start))} to ${fmt(secs(st.end))}${st.check_type === "manual" ? ", manual" : ""}</span></span>
              </button>`,
            )}
          </div>
          <div class="ed-step-tools">
            <button class="ghost" data-act="ed-split" ${canEdit && !ed.busy ? "" : "disabled"} title="Split the selected step at the playhead">${icons.scissors}Split</button>
            <button class="ghost" data-act="ed-merge" ${canEdit && !ed.busy && ed.sel < steps.length - 1 ? "" : "disabled"} title="Merge with the next step">${icons.merge}Merge</button>
            <button class="ghost" data-act="ed-delete" ${canEdit && !ed.busy && steps.length > 1 ? "" : "disabled"} title="Delete the selected step">${icons.trash}Delete</button>
          </div>
        </aside>
        <section class="ed-center">
          <div class="ed-player" id="ed-player"></div>
          <div class="timeline ${ed.busy ? "busy" : ""}" id="timeline" data-end="${end}">
            ${steps.map((st, i) => {
              const a = secs(st.start);
              const b = secs(st.end);
              return html`<button class="seg-t ${i === ed.sel ? "on" : ""}" data-act="ed-select" data-step="${i}"
                style="left:${(a / end) * 100}%;width:${((b - a) / end) * 100}%;background:${i === ed.sel ? "var(--accent)" : "var(--panel-2)"};border-right:1px solid var(--border-strong)"
                title="Step ${i + 1}: ${st.title}"><span class="seg-pill">${i + 1}</span></button>`;
            })}
            ${canEdit
              ? steps.slice(0, -1).map((st, i) => html`<span class="grip" data-grip="${i}" style="left:${(secs(st.end) / end) * 100}%"
                  title="Drag to move the boundary between steps ${i + 1} and ${i + 2}"></span>`)
              : ""}
            <span class="playhead" id="playhead"></span>
            <span class="drag-label" id="drag-label" hidden></span>
          </div>
          <div class="timeline-scale"><span>00:00</span><span>${fmt(end)}</span></div>
        </section>
        <aside class="ed-inspector scroll">
          ${s
            ? html`<form class="form" id="ed-form" data-step="${s.n}">
                <p class="eyebrow">Step ${ed.sel + 1} of ${steps.length}</p>
                <label class="field"><span>Step title</span>
                  <input name="title" id="ed-title" value="${s.title}" maxlength="120" placeholder="Fold the corners to the center" ${canEdit ? "" : "disabled"} /></label>
                <p class="hint">Short and doable. Start with a verb.</p>
                <div class="field"><span>Time</span>
                  <p class="time-line"><span class="mono">${fmt(secs(s.start))} to ${fmt(secs(s.end))}</span><span class="muted">Length ${fmt(secs(s.end) - secs(s.start))}</span></p></div>
                <div class="field"><span>How it is checked</span>
                  <div class="segmented">
                    <button type="button" class="${s.check_type !== "manual" ? "on" : ""}" data-act="ed-check" data-type="camera" ${canEdit ? "" : "disabled"}>Camera</button>
                    <button type="button" class="${s.check_type === "manual" ? "on" : ""}" data-act="ed-check" data-type="manual" ${canEdit ? "" : "disabled"}>Manual</button>
                  </div></div>
                ${ed.sel === 0 && s.check_type !== "manual" ? html`<p class="hint caution">Step 1 is often better as Manual: the camera has nothing to compare to yet.</p>` : ""}
                ${s.check_type !== "manual"
                  ? html`<label class="field"><span>Check question</span>
                      <textarea name="check_question" id="ed-question" rows="3" maxlength="300" placeholder="Is the paper folded into a small square with four flaps?" ${canEdit ? "" : "disabled"}>${s.check_question ?? ""}</textarea></label>
                      <p class="hint">Ask about shape and folds you can see, not color.</p>
                      <div class="ref-frame"><img src="${lessonUrl(id, s.ref_frame, ed.stamp)}" alt="Reference frame for this step" /><span>Reference frame</span></div>`
                  : ""}
                <label class="field"><span>What do people get wrong here?</span>
                  <input name="common_mistake" id="ed-mistake" value="${s.common_mistake ?? ""}" maxlength="300" placeholder="Flip it over first." ${canEdit ? "" : "disabled"} /></label>
                <p class="hint">Shown and spoken when the learner is still on the step before.</p>
              </form>`
            : ""}
        </aside>
      </div>
    </div>`,
  );
  attachPlayer(el, lessonUrl(id, lesson.video || "norm.mp4"));
}

function placePlayhead() {
  const ph = document.getElementById("playhead");
  const tl = document.getElementById("timeline");
  if (!ph || !tl || !player) return;
  const end = Number(tl.dataset.end) || 1;
  ph.style.left = `${Math.min(100, (player.currentTime / end) * 100)}%`;
}

function attachPlayer(el: HTMLElement, src: string) {
  if (!player || playerFor !== src) {
    player = document.createElement("video");
    player.id = "ed-video";
    player.controls = true;
    player.preload = "auto";
    player.playsInline = true;
    player.crossOrigin = "anonymous";
    player.src = src;
    player.addEventListener("timeupdate", placePlayhead);
    player.addEventListener("seeked", placePlayhead);
    playerFor = src;
  }
  const slot = el.querySelector("#ed-player");
  if (slot && player.parentElement !== slot) slot.appendChild(player);
  placePlayhead();
}

/** Boundary dragging: moves the grip live, then sends the new times on release. */
export function editorPointerDown(e: PointerEvent) {
  const grip = (e.target as HTMLElement).closest<HTMLElement>(".grip");
  if (!grip || !ed.d || ed.busy) return;
  e.preventDefault();
  const tl = grip.parentElement as HTMLElement;
  const end = Number(tl.dataset.end) || 1;
  const i = Number(grip.dataset.grip);
  const steps = ed.d.lesson.steps;
  const lo = secs(steps[i].start) + 0.5;
  const hi = secs(steps[i + 1].end) - 0.5;
  const label = tl.querySelector<HTMLElement>("#drag-label")!;
  let at = secs(steps[i].end);
  const move = (ev: PointerEvent) => {
    const r = tl.getBoundingClientRect();
    at = Math.round(Math.max(lo, Math.min(hi, ((ev.clientX - r.left) / r.width) * end)) * 10) / 10;
    grip.style.left = `${(at / end) * 100}%`;
    label.hidden = false;
    label.style.left = grip.style.left;
    label.textContent = fmt(at);
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    label.hidden = true;
    if (Math.abs(at - secs(steps[i].end)) < 0.05) return rerender();
    void op("boundaries", { steps: [{ n: steps[i].n, end: at }, { n: steps[i + 1].n, start: at }] }, true);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

/** Text fields save when they lose focus or Return is pressed. */
export function editorChange(t: HTMLInputElement) {
  if (!ed.d || !t.closest("#ed-form")) return;
  const s = ed.d.lesson.steps[ed.sel];
  const key = t.name as keyof Step;
  const value = t.value.trim();
  if (!s || (s[key] ?? "") === value) return;
  if (key === "title" && !value) {
    t.value = s.title;
    return toast("A step needs a title.");
  }
  void op("step", { n: s.n, [key]: value }, false);
}

function publishSheet() {
  if (!ed.d) return;
  const { course, lesson } = ed.d;
  const orgs = app.orgs.filter((o) => o.role === "org_admin" || o.role === "teacher");
  const isOwner = app.me?.user?.role === "owner";
  let choice = course.visibility === "org" && course.org ? `org:${course.org.id}` : course.visibility;
  let unlisted = course.status === "unlisted";
  let err = "";
  let busy = false;
  const cams = lesson.steps.filter((s) => s.check_type === "camera");
  const warnings = lesson.steps
    .map((s, i) => {
      const st = s as Step & { self_test?: { ok?: boolean } };
      if (s.check_type === "camera" && !s.check_question) return `Step ${i + 1} has no check question.`;
      if (st.self_test && st.self_test.ok === false) return `Step ${i + 1} failed its test.`;
      return "";
    })
    .filter(Boolean);
  const radio = (value: string, title: string, detail: string, avatar = "") =>
    html`<button type="button" class="radio-row ${choice === value ? "on" : ""}" data-act="pub-choice" data-value="${value}" role="radio" aria-checked="${choice === value}">
      ${avatar ? orgAvatar(avatar, 32) : ""}<span class="radio-text"><span>${title}</span>${detail ? html`<span class="hint">${detail}</span>` : ""}</span>
      <span class="radio-dot"></span></button>`;
  openSheet({
    title: `Publish ${course.title}`,
    body: () => html`<div class="form">
      <p class="field-label">Who can find it</p>
      <div class="radio-list">
        ${radio("only_me", "Only Me", "")}
        ${radio("shared", "People with Access", "")}
        ${orgs.map((o) => radio(`org:${o.id}`, `Publish to ${o.name}`, (() => { const n = typeof o.members === "number" ? o.members : o.members.length; return `${n} ${n === 1 ? "member" : "members"}`; })(), o.name))}
        ${isOwner || course.visibility === "everyone" ? radio("everyone", "Everyone on This Hub", "") : ""}
      </div>
      ${choice.startsWith("org:") ? html`<p class="hint">Members of ${orgs.find((o) => `org:${o.id}` === choice)?.name ?? "the organization"} see it on their Home and on the org page.</p>` : ""}
      <label class="toggle-row"><span class="toggle-text"><span>Unlisted</span><span class="toggle-detail">Not shown in Library. Share the link instead.</span></span>
        <input type="checkbox" role="switch" data-act="pub-unlisted" ${unlisted ? "checked" : ""} /></label>
      <div class="checklist">
        <p>${lesson.steps.length} steps</p><p>${cams.length} checked by camera</p><p>${lesson.steps.length - cams.length} manual</p>
        ${warnings.map((w) => html`<p class="caution">${w}</p>`)}
      </div>
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Cancel</button>
        <button type="button" class="primary" data-act="pub-go" ${busy ? "disabled" : ""}>${course.status === "published" ? "Update" : "Publish"}</button></div>
    </div>`,
    onAction: async (act, el) => {
      if (act === "pub-choice") {
        choice = el.dataset.value!;
        return drawSheet();
      }
      if (act === "pub-unlisted") {
        unlisted = (el as HTMLInputElement).checked;
        return;
      }
      if (act !== "pub-go" || !ed.d) return;
      busy = true;
      drawSheet();
      try {
        const body: Record<string, unknown> = { status: unlisted ? "unlisted" : "published" };
        if (choice.startsWith("org:")) Object.assign(body, { visibility: "org", org_id: choice.slice(4) });
        else body.visibility = choice;
        ed.d.course = await hub("POST", `/api/courses/${ed.id}/publish`, { body });
        closeSheet();
        toast("Published");
        reloadCourse();
        resetHome();
        resetTeach();
        rerender();
      } catch (e) {
        busy = false;
        err = errorText(e);
        drawSheet();
      }
    },
  });
}

/** Section 14.2: the lesson's title and description. */
function detailsSheet() {
  if (!ed.d) return;
  const c = ed.d.course;
  let err = "";
  openSheet({
    title: "Lesson Details",
    body: () => html`<form class="form">
      <label class="field"><span>Title</span><input name="title" value="${c.title}" maxlength="120" placeholder="Fold a fortune teller" /></label>
      <label class="field"><span>Description</span><textarea name="description" rows="4" maxlength="300" placeholder="What learners will make, and what they need.">${c.description ?? ""}</textarea></label>
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Cancel</button><button type="submit" class="primary">Save</button></div>
    </form>`,
    onSubmit: async (form) => {
      const title = (form.querySelector("[name=title]") as HTMLInputElement).value.trim();
      const description = (form.querySelector("[name=description]") as HTMLTextAreaElement).value.trim();
      if (!title) {
        err = "A lesson needs a title.";
        return drawSheet();
      }
      try {
        const body: Record<string, string> = {};
        if (title !== c.title) body.title = title;
        if (description !== (c.description ?? "")) body.description = description;
        if (Object.keys(body).length && ed.d) ed.d.course = { ...ed.d.course, ...(await hub("PATCH", `/api/courses/${ed.id}`, { body })) };
        closeSheet();
        reloadCourse();
        resetHome();
        resetTeach();
        rerender();
      } catch (e) {
        err = errorText(e);
        drawSheet();
      }
    },
  });
}

export function editorAction(act: string, t: HTMLElement) {
  if (!ed.d) return;
  const steps = ed.d.lesson.steps;
  const s = steps[ed.sel];
  const v = document.querySelector<HTMLVideoElement>("#ed-video");
  if (act === "ed-back") back();
  else if (act === "ed-select") {
    ed.sel = Number(t.dataset.step);
    if (v) v.currentTime = secs(steps[ed.sel].start);
    rerender();
  } else if (act === "ed-undo") void op("undo", {}, true);
  else if (act === "ed-redo") void op("redo", {}, true);
  else if (act === "ed-check" && s && s.check_type !== t.dataset.type) void op("step", { n: s.n, check_type: t.dataset.type }, false);
  else if (act === "ed-split" && s) {
    const at = v ? Math.round(v.currentTime * 10) / 10 : 0;
    if (at <= secs(s.start) + 0.3 || at >= secs(s.end) - 0.3) return toast("Move the playhead inside the selected step to split it there.");
    void op("split", { n: s.n, at }, true);
  } else if (act === "ed-merge" && s) void op("merge", { n: s.n }, true);
  else if (act === "ed-delete" && s) {
    openSheet({
      title: `Delete Step ${ed.sel + 1}?`,
      body: () => html`<div class="form"><p class="sheet-lede">Its time joins the step before it.</p>
        <div class="form-actions"><button class="quiet" data-sheet="close">Cancel</button><button class="danger" data-act="del">Delete Step</button></div></div>`,
      onAction: (a) => {
        if (a !== "del") return;
        closeSheet();
        void op("delete", { n: s.n }, true);
      },
    });
  } else if (act === "ed-details") detailsSheet();
  else if (act === "ed-preview") learn.start(ed.id, ed.sel, true);
  else if (act === "ed-publish") publishSheet();
}
