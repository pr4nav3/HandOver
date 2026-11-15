// Lesson detail and course view (section 6): cover, title, description, meta, safety and tools,
// Start or Continue, the rating summary, and the steps with this device's latest results.

import { call, hub, lessonUrl, toSeconds, type CourseDetail, type Lesson, type Ratings, type Step } from "../api";
import { cover, empty, loading, mmss, openSheet, closeSheet, drawSheet, ring, stars, STATUS_WORD } from "../components";
import { icons } from "../icons";
import { app, errorText, learn, localProgress, rerender, toast } from "../state";
import { html, paint, type Raw } from "../util";
import { cameraRow } from "./pair";
import { insightsSheet } from "./insights";
import { editStep } from "./editor";

let detail: { id: string; d: CourseDetail | null; ratings: Ratings | null; error: string } | null = null;

async function load(id: string) {
  detail = { id, d: null, ratings: null, error: "" };
  try {
    if (app.library) {
      const [d, ratings] = await Promise.all([
        hub<CourseDetail>("GET", `/api/courses/${id}`),
        hub<Ratings>("GET", `/api/courses/${id}/ratings`).catch(() => null),
      ]);
      if (detail?.id === id) detail = { id, d, ratings, error: "" };
    } else {
      const lesson = await call<Lesson>("lesson", { id });
      const d = {
        course: {
          id,
          title: lesson.title,
          description: lesson.description ?? "",
          cover_url: `/lessons/${id}/${lesson.production?.output?.cover ?? "frames/01.jpg"}`,
          status: "published",
          owner: null,
          org: null,
        },
        lesson,
        permissions: { can_edit: true, can_rate: false, can_publish: false },
        history: null,
      } as unknown as CourseDetail;
      if (detail?.id === id) detail = { id, d, ratings: null, error: "" };
    }
  } catch (e) {
    if (detail?.id === id) detail = { id, d: null, ratings: null, error: errorText(e) };
  }
  rerender();
}

export const reloadCourse = () => detail && void load(detail.id);

const expert = (s: Step) => Math.max(0, toSeconds(s.end) - toSeconds(s.start));

/** DESIGN 3.20 status symbol for a step. */
export function stepStatus(how: string | null | undefined, current: boolean): Raw {
  if (current) return html`<span class="st current" title="Current">${icons.play}</span>`;
  if (how === "camera") return html`<span class="st good" title="Checked by camera">${icons.checkFill}</span>`;
  if (how === "hand") return html`<span class="st hand" title="Marked done">${icons.tap}</span>`;
  if (how === "skipped") return html`<span class="st caution" title="Skipped">${icons.skipped}</span>`;
  return html`<span class="st idle" title="Not started">${icons.ring0}</span>`;
}

/** One course step row: status, thumbnail, number and title, expert time (and yours). */
export function stepRow(lessonId: string, s: Step, i: number, rev: number | undefined, how: string | null | undefined, current: boolean, yours?: number | null, act = "course-step"): Raw {
  return html`<button class="step-row ${current ? "current" : ""}" data-act="${act}" data-step="${i}">
    ${stepStatus(how, current)}
    <span class="step-thumb"><img src="${lessonUrl(lessonId, s.ref_frame, rev)}" alt="" /></span>
    <span class="step-text">
      <span class="step-name"><span class="step-num">${i + 1}</span>${s.title}</span>
      <span class="step-meta">Expert ${mmss(expert(s))}${yours ? html` <span class="dot-sep"></span> You ${mmss(yours)}` : ""}</span>
    </span>
  </button>`;
}

export function renderCourse(el: HTMLElement, id: string) {
  if (!detail || detail.id !== id) {
    void load(id);
    paint(el, html`<div class="page">${loading("Loading the lesson")}</div>`);
    return;
  }
  if (detail.error) {
    paint(el, html`<div class="page">${empty(icons.filmBig, "This lesson cannot be opened", detail.error, html`<button class="secondary" data-go='{"name":"browse"}'>Back to Lessons</button>`)}</div>`);
    return;
  }
  if (!detail.d) {
    paint(el, html`<div class="page">${loading("Loading the lesson")}</div>`);
    return;
  }
  const { course, lesson, permissions } = detail.d;
  const steps = lesson.steps;
  const total = steps.reduce((a, s) => a + expert(s), 0);
  const cams = steps.filter((s) => s.check_type === "camera").length;
  const p = localProgress()[id];
  const doneCount = p ? (p.done ? steps.length : p.step) : 0;
  const r = detail.ratings;
  const meta = [`${steps.length} ${steps.length === 1 ? "step" : "steps"}`, total ? `${mmss(total)} expert time` : "", `${cams} checked by camera`].filter(Boolean);
  paint(
    el,
    html`<div class="page detail">
      <div class="detail-left">
        <div class="detail-intro">
          ${cover(course.cover_url, "cover detail-cover")}
          <div class="detail-title">
            ${course.status !== "published" ? html`<span class="badge-soft">${STATUS_WORD[course.status]}</span>` : ""}
            <h1>${course.title || id}</h1>
            ${course.owner ? html`<p class="detail-by">By ${course.owner.name}${course.org ? html` in ${course.org.name}` : ""}</p>` : ""}
            ${course.description ? html`<p class="detail-desc">${course.description}</p>` : ""}
            <p class="detail-meta">${meta.map((m, i) => html`${i ? html`<span class="dot-sep"></span>` : ""}${m}`)}</p>
          </div>
        </div>
        <div class="detail-start">
          ${lesson.safety?.length || lesson.tools?.length
            ? html`<div class="card before">
                <p class="card-title">Before you start</p>
                ${(lesson.safety ?? []).map((s) => html`<p class="safety">${icons.shield}<span>${s}</span></p>`)}
                ${lesson.tools?.length ? html`<p class="tools"><strong>Tools</strong> ${lesson.tools.join(", ")}</p>` : ""}
              </div>`
            : ""}
          ${steps.length ? cameraRow() : ""}
          <div class="detail-actions">
            ${p && !p.done && p.step > 0
              ? html`<button class="primary large" data-act="course-continue">Continue at Step ${p.step + 1}</button>
                  <button class="secondary large" data-act="course-restart">Start Over</button>`
              : html`<button class="primary large" data-act="course-start" ${steps.length ? "" : "disabled"}>Start Lesson</button>`}
          </div>
          <div class="detail-foot">
            <div class="detail-quiet">
              ${permissions.can_edit ? html`<button class="quiet" data-go="${JSON.stringify({ name: "editor", id })}">Edit Lesson</button>` : ""}
              ${permissions.can_see_insights ? html`<button class="quiet" data-act="course-insights">Insights</button>` : ""}
              ${permissions.can_rate ? html`<button class="quiet" data-act="course-rate">${r?.mine ? "Edit Your Rating" : "Rate This Lesson"}</button>` : ""}
            </div>
            ${r && r.count
              ? html`<p class="rating-line">${stars(r.average ?? 0)} <span>${(r.average ?? 0).toFixed(1)} from ${r.count} ${r.count === 1 ? "rating" : "ratings"}</span></p>`
              : ""}
          </div>
        </div>
      </div>
      <div class="detail-right">
        <div class="steps-head">
          <h2>Steps</h2>
          <span class="steps-count">${ring(doneCount / Math.max(1, steps.length), 22)}${doneCount} of ${steps.length} done</span>
        </div>
        <div class="steps-list scroll">
          ${steps.map((s, i) => stepRow(id, s, i, undefined, p?.how?.[i], !!p && !p.done && p.step === i && p.step > 0))}
        </div>
      </div>
    </div>`,
  );
}

export function rateSheet(id: string, title: string, mine: { stars: number; comment?: string } | null, after?: () => void) {
  let value = mine?.stars ?? 0;
  let busy = false;
  let err = "";
  openSheet({
    title: "Rate this lesson",
    body: () => html`<form class="form">
      <p class="sheet-lede">${title}</p>
      <div class="stars-big">${stars(value, true, 30)}</div>
      <label class="field"><span>Comment</span>
        <textarea name="comment" rows="3" maxlength="500" placeholder="What helped or got in the way? (optional)">${mine?.comment ?? ""}</textarea>
      </label>
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions">
        <button type="button" class="quiet" data-sheet="close">Not Now</button>
        <button type="submit" class="primary" ${value && !busy ? "" : "disabled"}>Send</button>
      </div>
      <p class="hint">The lesson's owner sees your rating and comment with your name.</p>
    </form>`,
    onAction: (act, el) => {
      if (act !== "star") return;
      value = Number(el.dataset.stars);
      drawSheet();
    },
    onSubmit: async (form) => {
      busy = true;
      drawSheet();
      try {
        const comment = (form.querySelector("textarea") as HTMLTextAreaElement).value.trim();
        await hub("POST", `/api/courses/${id}/rating`, { body: comment ? { stars: value, comment } : { stars: value } });
        closeSheet();
        toast("Thanks. Rating sent.");
        after?.();
      } catch (e) {
        busy = false;
        err = errorText(e);
        drawSheet();
      }
    },
  });
}

export function courseAction(act: string, t: HTMLElement) {
  if (!detail?.d) return;
  const id = detail.id;
  const p = localProgress()[id];
  if (act === "course-insights") insightsSheet(id, detail.d.course.title, (index) => void editStep(id, index));
  else if (act === "course-start") learn.start(id, 0, true);
  else if (act === "course-continue" && p) learn.start(id, p.step);
  else if (act === "course-restart") learn.start(id, 0, true);
  else if (act === "course-step") learn.start(id, Number(t.dataset.step), !p || p.done);
  else if (act === "course-rate") rateSheet(id, detail.d.course.title, detail.ratings?.mine ?? null, () => reloadCourse());
}
