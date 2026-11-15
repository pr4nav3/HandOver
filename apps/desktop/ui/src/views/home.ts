// Home (section 21): a dismissible "How it works" card, Learn and Teach, a lesson already running
// on the hub, then Continue Learning, From Your Organizations and Everyone on this hub. A section
// with nothing in it is left out. On hubs without the library, the hub's lessons as cards.

import { call, hub, type CourseSummary, type LessonSummary } from "../api";
import { empty, lessonCard, loading, orgAvatar, pageHead, section } from "../components";
import { icons } from "../icons";
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
  ls.map((l) => ({
    id: l.id,
    title: l.title,
    steps: l.steps,
    cover_url: `/lessons/${l.id}/frames/01.jpg`,
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
    } else {
      const [everyone, mine] = await Promise.all([
        hub<CourseSummary[]>("GET", "/api/courses", { query: { filter: "all" } }),
        signedIn() ? hub<CourseSummary[]>("GET", "/api/courses", { query: { filter: "mine" } }) : Promise.resolve([]),
      ]);
      const byOrg = app.orgs.map((o) => ({ id: o.id, name: o.name, courses: everyone.filter((c) => c.org?.id === o.id) }));
      data = { everyone, mine, byOrg, error: "" };
    }
  } catch (e) {
    data = { everyone: [], mine: [], byOrg: [], error: errorText(e) };
  }
  loadingNow = false;
  rerender();
}

export const resetHome = () => (data = null);

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

function startCards(): Raw {
  return html`<div class="option-cards home-actions">
    <button class="option-card" data-go='{"name":"browse"}'>
      <span class="tile">${icons.grad}</span>
      <span class="role-text"><span class="option-title">Learn a Lesson</span>
      <span class="option-line">Pick a lesson and follow it step by step.</span></span>
    </button>
    ${canTeach()
      ? html`<button class="option-card" data-go='{"name":"teach"}'>
          <span class="tile">${icons.teachBig}</span>
          <span class="role-text"><span class="option-title">Teach a Lesson</span>
          <span class="option-line">Record a task once. HandOver turns it into steps.</span></span>
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

export function renderHome(el: HTMLElement) {
  const actions = html`${pairButton}<button class="search-button" data-go='{"name":"browse"}'>${icons.search}<span>Search lessons</span></button>`;
  if (!data) {
    void loadHome();
    paint(el, html`<div class="page">${pageHead("Home", actions)}${howCard()}${startCards()}${loading("Loading lessons")}</div>`);
    return;
  }
  const d = data;
  const cont = continueList(d.everyone);
  const seeAll = (filter: string) =>
    html`<button class="quiet" data-go="${JSON.stringify({ name: "browse", filter })}">See All</button>`;
  const row = (cs: CourseSummary[], status = false) =>
    html`<div class="card-row">${cs.slice(0, 8).map((c) => lessonCard(c, { showStatus: status }))}</div>`;

  const blocks: Raw[] = [];
  if (cont.length)
    blocks.push(
      section(
        "Continue Learning",
        html`<div class="card-row">${cont.slice(0, 10).map(({ course, p }) =>
          lessonCard(course, { meta: `Step ${p.step + 1} of ${p.total}`, progress: p.step / Math.max(1, p.total) }),
        )}</div>`,
      ),
    );
  const teachBlock =
    canTeach() && (d.mine.length || prefs.homeFirst === "teach")
      ? section(
          "Your Lessons",
          d.mine.length
            ? row(d.mine, true)
            : html`<button class="make-card" data-go='{"name":"teach"}'>${icons.teachBig}<span>Make a Lesson</span></button>`,
          html`<button class="quiet" data-go='{"name":"teach"}'>Teach</button>`,
        )
      : null;
  if (teachBlock) {
    if (prefs.homeFirst === "teach") blocks.unshift(teachBlock);
    else blocks.push(teachBlock);
  }
  for (const o of d.byOrg) {
    if (!o.courses.length) continue;
    blocks.push(
      html`<section class="block">
        <div class="block-head">
          <h2 class="with-avatar">${orgAvatar(o.name, 28)}${o.name}</h2>
          <button class="quiet" data-go="${JSON.stringify({ name: "org", id: o.id })}">See All</button>
        </div>
        ${row(o.courses)}
      </section>`,
    );
  }
  const everyone = d.everyone.filter((c) => c.visibility === "everyone" && c.status === "published");
  if (everyone.length)
    blocks.push(
      section(
        app.library ? "Everyone on This Hub" : "All Lessons",
        html`<div class="card-grid">${everyone.slice(0, 12).map((c) => lessonCard(c))}</div>`,
        app.library ? seeAll("everyone") : "",
      ),
    );

  let body: Raw | null = null;
  if (d.error) body = empty(icons.filmBig, "Could not load lessons", d.error, html`<button class="secondary" data-act="home-retry">Try Again</button>`);
  else if (!blocks.length) {
    if (canTeach())
      body = empty(icons.filmBig, "Nothing here yet", "Record a task once and HandOver turns it into steps. Start with Teach a Lesson above.");
    else if (!app.orgs.length)
      body = empty(icons.peopleBig, "Nothing here yet", "Join an organization to see its lessons, or ask someone to share one with you.", html`<button class="primary" data-act="join-code">Join with a Code</button>`);
    else body = empty(icons.filmBig, "Nothing here yet", "When your organizations publish lessons, they show up here.");
  }
  paint(
    el,
    html`<div class="page">
      ${pageHead("Home", actions)}
      ${howCard()}
      ${startCards()}
      ${runningCard(d)}
      ${body ?? blocks}
    </div>`,
  );
}

export function homeAction(act: string) {
  if (act === "home-retry") {
    data = null;
    rerender();
  } else if (act === "how-close") {
    prefs.howDismissed = true;
    rerender();
  } else if (act === "home-open-running" && app.state?.lesson_id) learn.start(app.state.lesson_id, app.state.step);
}
