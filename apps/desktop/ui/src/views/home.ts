// Home is a one-screen launch surface: two primary actions, an active lesson when there is one,
// and a small set of useful lessons. The complete catalog lives in Lessons.

import { call, hub, type CourseSummary, type LessonSummary } from "../api";
import { lessonCard, loading, pageHead } from "../components";
import { icons } from "../icons";
import { userFacingLessons } from "../lesson_visibility";
import { app, canTeach, continueList, errorText, learn, prefs, rerender, signedIn } from "../state";
import { html, paint, type Raw } from "../util";

interface HomeData {
  everyone: CourseSummary[];
  mine: CourseSummary[];
  byOrg: { id: string; name: string; courses: CourseSummary[] }[];
  error: string;
}

let data: HomeData | null = null;
let loadingNow = false;

/** Lessons from a hub without the library routes, shaped like course summaries. */
export const fromLessons = (ls: LessonSummary[]): CourseSummary[] =>
  userFacingLessons(ls).map((l) => ({
    id: l.id,
    title: l.title,
    steps: l.steps,
    cover_url: l.cover_url ?? `/lessons/${l.id}/frames/01.jpg`,
    duration: null,
    status: "published",
    visibility: "everyone",
    owner: null,
    org: null,
    updated: "",
    legacy: true,
    version: 0,
    progress: null,
  }));

const HOW = [
  { title: "Pick a lesson", line: "An expert recorded the task once. HandOver cut it into short steps." },
  { title: "Point a camera at your hands", line: "This computer's webcam, a phone, or Meta glasses." },
  { title: "Follow each clip", line: "When your work matches the step, the next clip starts." },
];

function howCard(): Raw | string {
  if (prefs.howDismissed) return "";
  return html`<section class="card how" aria-label="How it works">
    <div class="how-head"><h2>How it works</h2>
      <button class="icon-button" data-act="how-close" title="Hide" aria-label="Hide How it works">${icons.close}</button></div>
    <ol class="how-steps">${HOW.map(
      (h, i) => html`<li><span class="how-num">${i + 1}</span><span class="how-text"><span class="how-title">${h.title}</span><span class="how-line">${h.line}</span></span></li>`,
    )}</ol>
  </section>`;
}

export async function loadHome() {
  if (loadingNow) return;
  loadingNow = true;
  try {
    if (!app.library) {
      const ls = await call<LessonSummary[]>("lessons");
      data = { everyone: fromLessons(ls), mine: [], byOrg: [], error: "" };
      app.analytics = undefined;
    } else {
      const [everyone, mine] = await Promise.all([
        hub<CourseSummary[]>("GET", "/api/courses", { query: { filter: "all" } }),
        signedIn() ? hub<CourseSummary[]>("GET", "/api/courses", { query: { filter: "mine" } }) : Promise.resolve([]),
      ]);
      const visibleEveryone = userFacingLessons(everyone);
      const visibleMine = userFacingLessons(mine);
      const byOrg = app.orgs.map((o) => ({ id: o.id, name: o.name, courses: visibleEveryone.filter((c) => c.org?.id === o.id) }));
      data = { everyone: visibleEveryone, mine: visibleMine, byOrg, error: "" };
    }
  } catch (e) {
    data = { everyone: [], mine: [], byOrg: [], error: errorText(e) };
  }
  loadingNow = false;
  rerender();
}

export const resetHome = () => (data = null);

function startCards(): Raw {
  return html`<div class="option-cards home-actions">
    <button class="option-card" data-go='{"name":"browse"}'>
      <span class="tile">${icons.grad}</span>
      <span class="role-text"><span class="option-title">Start learning</span>
      <span class="option-line">Choose a lesson and follow it step by step.</span></span>
    </button>
    ${canTeach()
      ? html`<button class="option-card" data-go='{"name":"teach"}'>
          <span class="tile">${icons.teachBig}</span>
          <span class="role-text"><span class="option-title">Make a lesson</span>
          <span class="option-line">Turn one expert recording into clear steps.</span></span>
        </button>`
      : html`<button class="option-card" data-act="pair-phone">
          <span class="tile">${icons.phone}</span>
          <span class="role-text"><span class="option-title">Pair a Phone</span>
          <span class="option-line">Use a phone as the camera that watches your hands.</span></span>
        </button>`}
  </div>`;
}

/** The hub's current lesson, when one is under way and this window is not in it. */
function runningCard(d: HomeData): Raw | string {
  const s = app.state;
  if (!s?.lesson_id || s.status === "done" || app.link.link !== "connected") return "";
  const c = d.everyone.find((x) => x.id === s.lesson_id);
  const title = c?.title || s.lesson_id;
  return html`<div class="card running">
    <span class="running-dot dot ok"></span>
    <span class="running-text"><span class="running-title">${title}</span>
      <span class="running-meta">Running on the hub, step ${s.step + 1} of ${s.total}</span></span>
    <button class="secondary small" data-act="home-open-running">Open</button>
  </div>`;
}

const pairButton = html`<button class="secondary small" data-act="pair-phone">${icons.qr}<span>Pair a Phone</span></button>`;

function featuredLessons(d: HomeData): Raw {
  const continued = continueList(d.everyone);
  const picked: { course: CourseSummary; progress?: { step: number; total: number } }[] = [];
  const seen = new Set<string>();
  for (const item of continued) {
    if (seen.has(item.course.id)) continue;
    seen.add(item.course.id);
    picked.push({ course: item.course, progress: item.p });
  }
  for (const course of [...d.mine, ...d.everyone]) {
    if (seen.has(course.id)) continue;
    seen.add(course.id);
    picked.push({ course });
  }
  const visible = picked.slice(0, 4);
  if (!visible.length)
    return html`<section class="home-empty"><span>No lessons yet.</span>${canTeach() ? html`<button class="primary small" data-go='{"name":"teach"}'>Make one</button>` : ""}</section>`;
  return html`<section class="home-lessons" aria-labelledby="home-lessons-title">
    <div class="block-head"><h2 id="home-lessons-title">${continued.length ? "Continue learning" : "Lessons"}</h2>
      <button class="quiet" data-go='{"name":"browse"}'>View all</button></div>
    <div class="home-lessons-grid count-${visible.length}">${visible.map(({ course }) =>
      lessonCard(course, { meta: "" }),
    )}</div>
  </section>`;
}

export function renderHome(el: HTMLElement) {
  const actions = html`${pairButton}<button class="search-button" data-go='{"name":"browse"}'>${icons.search}<span>Search lessons</span></button>`;
  if (!data) {
    void loadHome();
    paint(el, html`<div class="page home-page">${pageHead("Home", actions)}<main class="home-main">${howCard()}${startCards()}${loading("Loading lessons")}</main></div>`);
    return;
  }
  const d = data;
  paint(
    el,
    html`<div class="page home-page">
      ${pageHead("Home", actions)}
      <main class="home-main">
        ${howCard()}
        ${startCards()}
        ${runningCard(d)}
        ${d.error
          ? html`<section class="home-error" role="alert"><span>${d.error}</span><button class="secondary small" data-act="home-retry">Try again</button></section>`
          : featuredLessons(d)}
      </main>
    </div>`,
  );
}

export function homeAction(act: string) {
  if (act === "how-close") {
    prefs.howDismissed = true;
    rerender();
  } else if (act === "home-retry") {
    data = null;
    rerender();
  } else if (act === "home-open-running" && app.state?.lesson_id) learn.start(app.state.lesson_id, app.state.step);
}
