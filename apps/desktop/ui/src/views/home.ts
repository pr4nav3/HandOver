// Home (section 21): Continue Learning, From Your Organizations, Everyone on this hub. A section
// with nothing in it is left out. On hubs without the library, the hub's lessons as cards.

import { call, hub, type CourseSummary, type LessonSummary } from "../api";
import { empty, lessonCard, loading, orgAvatar, pageHead, section } from "../components";
import { icons } from "../icons";
import { app, canTeach, continueList, errorText, prefs, rerender, signedIn } from "../state";
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

export function renderHome(el: HTMLElement) {
  if (!data) {
    void loadHome();
    paint(el, html`<div class="page">${pageHead("Home")}${loading("Loading lessons")}</div>`);
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
      body = empty(icons.filmBig, "Nothing here yet", "Record a task once and HandOver turns it into steps.", html`<button class="primary" data-go='{"name":"teach"}'>Make a Lesson</button>`);
    else if (!app.orgs.length)
      body = empty(icons.peopleBig, "Nothing here yet", "Join an organization to see its lessons, or ask someone to share one with you.", html`<button class="primary" data-act="join-code">Join with a Code</button>`);
    else body = empty(icons.filmBig, "Nothing here yet", "When your organizations publish lessons, they show up here.");
  }
  paint(
    el,
    html`<div class="page">
      ${pageHead("Home", html`<button class="search-button" data-go='{"name":"browse"}'>${icons.search}<span>Search lessons</span></button>`)}
      ${body ?? blocks}
    </div>`,
  );
}

export function homeAction(act: string) {
  if (act === "home-retry") {
    data = null;
    rerender();
  }
}
