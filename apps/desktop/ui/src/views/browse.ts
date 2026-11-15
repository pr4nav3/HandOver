// Lessons (section 5): search, filter chips (Everyone, Mine, Shared with Me, one per org)
// and the lesson grid. Hubs without the library get search over the plain lesson list.

import { call, hub, type CourseSummary, type LessonSummary } from "../api";
import { empty, lessonCard, loading, pageHead } from "../components";
import { icons } from "../icons";
import { userFacingLessons } from "../lesson_visibility";
import { app, canTeach, errorText, go, rerender, signedIn } from "../state";
import { html, paint } from "../util";
import { fromLessons } from "./home";

let results: CourseSummary[] | null = null;
let error = "";
let key = "";
let timer = 0;

function current() {
  const r = app.route.name === "browse" ? app.route : { name: "browse" as const };
  return { filter: r.filter ?? (r.org ? "orgs" : "everyone"), org: r.org ?? "", q: r.q ?? "" };
}

async function load() {
  const c = current();
  const k = JSON.stringify(c);
  key = k;
  try {
    let list: CourseSummary[];
    if (!app.library) {
      list = fromLessons(await call<LessonSummary[]>("lessons"));
      const q = c.q.toLowerCase();
      if (q) list = list.filter((l) => `${l.title} ${l.id}`.toLowerCase().includes(q));
    } else {
      const filter = c.org ? "orgs" : c.filter === "everyone" ? "all" : c.filter;
      list = await hub<CourseSummary[]>("GET", "/api/courses", { query: { filter, org: c.org, q: c.q } });
      if (c.filter === "everyone" && !c.org) list = list.filter((x) => x.status !== "draft" || x.owner?.id === app.me?.user?.id);
    }
    list = userFacingLessons(list);
    if (key === k) {
      results = list;
      error = "";
    }
  } catch (e) {
    if (key === k) error = errorText(e);
  }
  rerender();
}

export function renderBrowse(el: HTMLElement) {
  const c = current();
  if (JSON.stringify(c) !== key) {
    results = null;
    void load();
  }
  const chips: { label: string; filter: string; org?: string }[] = [{ label: "Everyone", filter: "everyone" }];
  if (app.library && signedIn()) chips.push({ label: "Mine", filter: "mine" }, { label: "Shared with Me", filter: "shared" });
  for (const o of app.orgs) chips.push({ label: o.name, filter: "orgs", org: o.id });
  let body;
  if (error) body = empty(icons.filmBig, "Could not load lessons", error);
  else if (results === null) body = loading("Loading lessons");
  else if (!results.length) {
    if (c.q) body = empty(icons.search, `No results for "${c.q}"`, "Check the spelling or try fewer words.");
    else if (canTeach())
      body = empty(icons.filmBig, "No lessons yet", "Record a task once and HandOver turns it into steps.", html`<button class="primary" data-go='{"name":"teach"}'>Make a Lesson</button>`);
    else body = empty(icons.filmBig, "No lessons yet", "When someone shares a lesson on this hub, it shows up here.");
  } else body = html`<div class="card-grid">${results.map((x) => lessonCard(x, { showStatus: true }))}</div>`;
  paint(
    el,
    html`<div class="page">
      ${pageHead("Lessons")}
      <div class="browse-bar">
        <label class="search-field">${icons.search}<input id="browse-q" type="search" placeholder="Search lessons" spellcheck="false" /></label>
        ${chips.length > 1
          ? html`<div class="chips" role="tablist">${chips.map((ch) => {
              const on = ch.org ? c.org === ch.org : !c.org && c.filter === ch.filter;
              return html`<button class="chip ${on ? "on" : ""}" role="tab" aria-selected="${on}" data-act="browse-filter"
                data-filter="${ch.filter}" data-org="${ch.org ?? ""}">${ch.label}</button>`;
            })}</div>`
          : ""}
      </div>
      ${body}
    </div>`,
  );
  const input = el.querySelector<HTMLInputElement>("#browse-q");
  if (input && input.value !== c.q && document.activeElement !== input) input.value = c.q;
}

export function browseAction(act: string, t: HTMLElement) {
  if (act === "browse-filter") {
    const c = current();
    go({ name: "browse", filter: t.dataset.filter, org: t.dataset.org || undefined, q: c.q || undefined }, false);
  }
}

export function browseInput(t: HTMLInputElement) {
  if (t.id !== "browse-q") return;
  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    const c = current();
    go({ name: "browse", filter: c.filter, org: c.org || undefined, q: t.value.trim() || undefined }, false);
  }, 250);
}
