// Profile (section 4.3) and signing in (4.1, 4.5). Signed-in activity comes from the hub's private,
// aggregate-only analytics route. Hubs without accounts keep showing this Mac's local record.

import { hub, type CourseSummary, type Me, type ProfileAnalytics, type User } from "../api";
import { closeSheet, drawSheet, empty, loading, mmss, openSheet, pageHead, personAvatar } from "../components";
import { icons } from "../icons";
import { activityDetails, percent, practiceTime } from "../profile_metrics";
import { app, errorText, localProgress, prefs, rerender, toast } from "../state";
import { html, paint, type Raw } from "../util";
import { resetHome } from "./home";
import { loadOrgs } from "./orgs";
import { resetTeach } from "./teach";

const ROLE_WORD: Record<string, string> = { owner: "Owner", teacher: "Teacher", learner: "Learner" };

export interface DeviceStats {
  lessons: number;
  camera: number;
  mistakes: number;
  times: Record<string, { you: number; expert: number }>;
}

const statsKey = () => `handover.stats.${app.link.hub}`;

let profileKey = "";
let profileCourses: CourseSummary[] | null | undefined;
let profileError = "";
let loadingProfile = false;

export function deviceStats(): DeviceStats {
  try {
    return { lessons: 0, camera: 0, mistakes: 0, times: {}, ...JSON.parse(localStorage.getItem(statsKey()) ?? "{}") };
  } catch {
    return { lessons: 0, camera: 0, mistakes: 0, times: {} };
  }
}

export function recordRun(id: string, camera: number, mistakes: number, you: number, expert: number) {
  const s = deviceStats();
  s.lessons += 1;
  s.camera += camera;
  s.mistakes += mistakes;
  s.times[id] = { you, expert };
  localStorage.setItem(statsKey(), JSON.stringify(s));
}

/** After signing in or out: everything that depends on who is signed in loads again. */
export async function refreshMe() {
  try {
    app.me = await hub<Me>("GET", "/api/me");
    app.library = true;
  } catch {
    app.me = null;
    app.library = false;
  }
  resetProfile();
  await loadOrgs();
  resetHome();
  resetTeach();
  rerender();
}

export function resetProfile() {
  profileKey = "";
  profileCourses = undefined;
  profileError = "";
  loadingProfile = false;
  app.analytics = undefined;
}

export async function loadProfile(force = false) {
  const user = app.me?.user;
  if (!user) return resetProfile();
  const key = `${app.link.hub}|${user.id}`;
  if (!force && profileKey === key && (loadingProfile || app.analytics !== undefined)) return;
  profileKey = key;
  loadingProfile = true;
  profileError = "";
  profileCourses = undefined;
  app.analytics = undefined;
  rerender();

  const [activity, courses] = await Promise.allSettled([
    hub<ProfileAnalytics>("GET", "/api/profile/analytics"),
    hub<CourseSummary[]>("GET", "/api/courses"),
  ]);
  if (profileKey !== key) return;
  app.analytics = activity.status === "fulfilled" ? activity.value : null;
  profileCourses = courses.status === "fulfilled" ? courses.value : null;
  const failures = [activity, courses].filter((answer) => answer.status === "rejected") as PromiseRejectedResult[];
  profileError = failures.length ? errorText(failures[0].reason) : "";
  loadingProfile = false;
  rerender();
}

export async function signIn(name: string, passcode: string): Promise<User> {
  const r = await hub<{ user: User }>("POST", "/api/auth/login", { body: { name, passcode } });
  await refreshMe();
  return r.user;
}

export async function setupOwner(name: string, passcode: string): Promise<User> {
  const r = await hub<{ user: User }>("POST", "/api/auth/setup", { body: { name, passcode } });
  await refreshMe();
  return r.user;
}

/** Sign in, or the owner setup when the hub has no accounts yet. */
export function signInSheet(after?: () => void) {
  const setup = !!app.me?.setup_needed;
  let err = "";
  let busy = false;
  openSheet({
    title: setup ? "Set Up Your Hub" : "Sign In to Your Hub",
    body: () => html`<form class="form">
      ${setup ? html`<p class="sheet-lede">You are the first person here, so you become the hub owner. Owners manage accounts and organizations.</p>` : ""}
      <label class="field"><span>Name</span><input name="name" autocomplete="username" placeholder="Sam Rivera" maxlength="40" /></label>
      <label class="field"><span>Passcode</span><input name="passcode" type="password" autocomplete="current-password" maxlength="128" /></label>
      ${setup ? html`<label class="field"><span>Confirm Passcode</span><input name="confirm" type="password" maxlength="128" /></label>` : ""}
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Cancel</button>
        <button type="submit" class="primary" ${busy ? "disabled" : ""}>${setup ? "Finish Setup" : "Sign In"}</button></div>
      <p class="hint">Passcodes stay on this hub. HandOver has no cloud account.</p>
    </form>`,
    onSubmit: async (form) => {
      const v = (n: string) => (form.querySelector(`[name=${n}]`) as HTMLInputElement | null)?.value ?? "";
      if (setup && v("passcode") !== v("confirm")) {
        err = "Passcodes do not match.";
        return drawSheet();
      }
      busy = true;
      drawSheet();
      try {
        const u = setup ? await setupOwner(v("name").trim(), v("passcode")) : await signIn(v("name").trim(), v("passcode"));
        closeSheet();
        toast(setup ? "Your hub is ready. You are the hub owner." : `Signed in as ${u.name}.`);
        after?.();
      } catch (e) {
        busy = false;
        const m = errorText(e);
        err = m === "wrong name or passcode" ? "That name and passcode do not match." : m.startsWith("too many login") ? "Too many tries. Wait a minute, then try again." : m;
        drawSheet();
      }
    },
  });
}

const metric = (value: string | number, label: string): Raw =>
  html`<div class="profile-metric"><span class="numeral">${value}</span><span class="stat-label">${label}</span></div>`;

function activityPanel(value: ProfileAnalytics | null | undefined): Raw {
  if (value === undefined) return loading("Loading your activity");
  if (value === null)
    return empty(
      icons.grid,
      "Could not load activity",
      profileError || "The hub did not return activity insights.",
      html`<button class="secondary" data-act="profile-retry">Try Again</button>`,
    );
  if (!value.known)
    return empty(icons.grid, "No activity yet", "Finish your first lesson and truthful practice insights will appear here.");

  const metrics: Raw[] = [metric(value.runs, value.runs === 1 ? "Run" : "Runs")];
  if (value.completed_runs !== undefined)
    metrics.push(metric(value.completed_runs, value.completed_runs === 1 ? "Completed run" : "Completed runs"));
  if (value.minutes_practiced !== undefined) metrics.push(metric(practiceTime(value.minutes_practiced), "Practiced"));
  if (value.current_streak_days !== undefined) metrics.push(metric(value.current_streak_days, "Day streak"));
  if (value.courses_completed !== undefined) metrics.push(metric(value.courses_completed, "Courses completed"));
  if (value.completion_rate !== null && value.completion_rate !== undefined)
    metrics.push(metric(percent(value.completion_rate), "Run completion"));

  const details = activityDetails(value);
  return html`<div class="profile-activity">
    <div class="profile-metrics">${metrics}</div>
    ${details.length
      ? html`<div class="profile-details" aria-label="Practice details">${details.map(
          (detail) => html`<div class="profile-detail"><span class="profile-detail-mark ${detail.kind}"></span><span>${detail.text}</span></div>`,
        )}</div>`
      : ""}
    <p class="profile-privacy">Private to you · aggregate activity only</p>
  </div>`;
}

function remoteLessonSections(courses: CourseSummary[] | null | undefined): Raw {
  if (courses === undefined) return loading("Loading your lessons");
  if (courses === null)
    return empty(
      icons.filmBig,
      "Could not load lessons",
      profileError || "The hub did not return your lesson progress.",
      html`<button class="secondary" data-act="profile-retry">Try Again</button>`,
    );
  const tracked = courses.filter((course) => course.progress);
  if (!tracked.length) return empty(icons.filmBig, "No lesson progress yet", "Open a lesson from Home. Your progress will appear here.");
  const inProgress = tracked.filter((course) => {
    const p = course.progress!;
    return (p.last_steps_done ?? 0) > 0 && (p.last_steps_done ?? 0) < (p.total || course.steps);
  });
  const completed = tracked.filter((course) => (course.progress?.completed ?? 0) > 0 && !inProgress.includes(course));
  const rows = (items: CourseSummary[], done: boolean) =>
    items.length
      ? html`<section class="block profile-lessons"><div class="block-head"><h2>${done ? "Completed" : "In Progress"}</h2></div>
          <div class="rows">${items.map((course) => {
            const p = course.progress!;
            const meta = done
              ? `${p.completed} completed ${p.completed === 1 ? "run" : "runs"}`
              : `${p.last_steps_done ?? 0} of ${p.total || course.steps} steps complete`;
            return html`<button class="row" data-go="${JSON.stringify({ name: "course", id: course.id })}"><span class="row-text">
              <span class="row-title">${course.title}</span><span class="row-meta">${meta}</span></span>
              ${done ? html`<span class="profile-done" aria-label="Completed">${icons.checkFill}</span>` : ""}<span class="chev">${icons.chevron}</span></button>`;
          })}</div></section>`
      : html``;
  return html`${rows(inProgress, false)}${rows(completed, true)}`;
}

function localActivity(): Raw {
  const s = deviceStats();
  if (!s.lessons) return empty(icons.grid, "No progress yet", "Finish a lesson and your results show up here.");
  return html`<div class="profile-activity"><div class="profile-metrics">
      ${metric(s.lessons, s.lessons === 1 ? "Lesson done" : "Lessons done")}
      ${metric(s.camera, s.camera === 1 ? "Camera-verified step" : "Camera-verified steps")}
      ${metric(s.mistakes, s.mistakes === 1 ? "Mistake caught" : "Mistakes caught")}
    </div><p class="profile-privacy">Saved on this computer</p></div>`;
}

function localLessonSections(): Raw {
  const all = Object.values(localProgress());
  const inProgress = all.filter((p) => !p.done && p.step > 0).sort((a, b) => b.updated - a.updated);
  const completed = all.filter((p) => p.done && p.runs > 0).sort((a, b) => b.updated - a.updated);
  const active = inProgress.length
    ? html`<section class="block profile-lessons"><div class="block-head"><h2>In Progress</h2></div><div class="rows">${inProgress.map(
        (p) => html`<button class="row" data-go="${JSON.stringify({ name: "course", id: p.id })}"><span class="row-text">
          <span class="row-title">${p.title}</span><span class="row-meta">Step ${p.step + 1} of ${p.total}</span></span><span class="chev">${icons.chevron}</span></button>`,
      )}</div></section>`
    : html``;
  const done = completed.length
    ? html`<section class="block profile-lessons"><div class="block-head"><h2>Completed</h2></div><div class="rows">${completed.map((p) => {
        const t = deviceStats().times[p.id];
        return html`<button class="row" data-go="${JSON.stringify({ name: "course", id: p.id })}"><span class="row-text">
          <span class="row-title">${p.title}</span><span class="row-meta">${p.runs} ${p.runs === 1 ? "run" : "runs"}</span></span>
          ${t ? html`<span class="row-trail">You ${mmss(t.you)}${t.expert ? ` · Expert ${mmss(t.expert)}` : ""}</span>` : ""}<span class="chev">${icons.chevron}</span></button>`;
      })}</div></section>`
    : html``;
  return html`${active}${done}`;
}

export function renderProfile(el: HTMLElement) {
  const u = app.me?.user;
  if (u) void loadProfile();
  const header = u
    ? html`<div class="card profile-card">${personAvatar(u.name, 64, prefs.avatarHue)}
        <div><p class="profile-name">${u.name} <span class="badge-soft">${ROLE_WORD[u.role] ?? u.role}</span></p>
          <p class="muted">Signed in on ${app.link.label || "this hub"}</p></div>
        <button class="secondary" data-act="sign-out">Sign Out</button></div>`
    : app.library
      ? html`<div class="card profile-card"><span class="avatar person placeholder">${icons.person}</span>
          <div><p class="profile-name">Not signed in</p><p class="muted">${app.me?.setup_needed ? "This hub has no owner yet." : "Sign in to keep your lessons and organizations."}</p></div>
          <button class="primary" data-act="sign-in">${app.me?.setup_needed ? "Set Up Hub" : "Sign In"}</button></div>`
      : html`<div class="card profile-card"><span class="avatar person placeholder">${icons.person}</span>
          <div><p class="profile-name">This device</p><p class="muted">Progress is kept on this device because the hub has no accounts.</p></div></div>`;
  const activity = u
    ? activityPanel(app.analytics)
    : app.library
      ? empty(icons.grid, "Sign in to see your activity", "Your private learning insights stay attached to your hub account.")
      : localActivity();
  const lessons = u ? remoteLessonSections(profileCourses) : app.library ? html`` : localLessonSections();
  paint(
    el,
    html`<div class="page narrow">
      ${pageHead("Profile")}
      ${header}
      <section class="block"><div class="block-head"><h2>Activity</h2></div>${activity}</section>
      ${lessons}
    </div>`,
  );
}

export function profileAction(act: string) {
  if (act === "sign-in") signInSheet();
  else if (act === "profile-retry") void loadProfile(true);
  else if (act === "sign-out")
    openSheet({
      title: "Sign out of this hub?",
      body: () => html`<div class="form"><p class="sheet-lede">Your progress stays on the hub.</p>
        <div class="form-actions"><button class="quiet" data-sheet="close">Cancel</button><button class="danger" data-act="out">Sign Out</button></div></div>`,
      onAction: async (a) => {
        if (a !== "out") return;
        await hub("POST", "/api/auth/logout").catch(() => {});
        closeSheet();
        await refreshMe();
        toast("Signed out.");
      },
    });
}
