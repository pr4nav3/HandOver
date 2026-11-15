// Home is a one-screen launch surface: two primary actions, an active lesson when there is one,
// and a small set of useful lessons. The complete catalog lives in Lessons.

import { call, hub, type CourseSummary, type LessonSummary } from "../api";
import { lessonCard, loading, pageHead } from "../components";
import { icons } from "../icons";
import { userFacingLessons } from "../lesson_visibility";
import { app, canTeach, errorText, learn, rerender, signedIn } from "../state";
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
  const picked = [...new Map([...d.mine, ...d.everyone].map((course) => [course.id, course])).values()]
    .sort((a, b) => b.updated.localeCompare(a.updated));
  const visible = picked.slice(0, 4);
  if (!visible.length)
    return html`<section class="home-empty"><span>Nothing here yet</span>${canTeach() ? html`<button class="primary small" data-go='{"name":"teach"}'>Make a Lesson</button>` : ""}</section>`;
  return html`<section class="home-lessons" aria-labelledby="home-lessons-title">
    <div class="block-head"><h2 id="home-lessons-title">Lessons</h2>
      <button class="quiet" data-go='{"name":"browse"}'>See All</button></div>
    <div class="home-lessons-grid count-${visible.length}">${visible.map((course) => lessonCard(course))}</div>
  </section>`;
}

export function renderHome(el: HTMLElement) {
  const actions = pairButton;
  if (!data) {
    void loadHome();
    paint(el, html`<div class="page home-page">${pageHead("Home", actions)}<main class="home-main">${loading("Loading lessons")}</main></div>`);
    return;
  }
  const d = data;
  paint(
    el,
    html`<div class="page home-page">
      ${pageHead("Home", actions)}
      <main class="home-main">
        ${runningCard(d)}
        ${d.error
          ? html`<section class="home-error" role="alert"><span>${d.error}</span><button class="secondary small" data-act="home-retry">Try Again</button></section>`
          : featuredLessons(d)}
      </main>
    </div>`,
  );
}

export function homeAction(act: string) {
  if (act === "home-retry") {
    data = null;
    rerender();
  } else if (act === "home-open-running" && app.state?.lesson_id) learn.start(app.state.lesson_id, app.state.step);
}
