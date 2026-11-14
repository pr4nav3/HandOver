// Profile (section 4.3) and signing in (4.1, 4.5). Progress here is this device's own record
// of finished runs: real events only, never sample numbers.

import { hub, type Me, type User } from "../api";
import { closeSheet, drawSheet, empty, mmss, openSheet, pageHead, personAvatar } from "../components";
import { icons } from "../icons";
import { app, errorText, localProgress, prefs, rerender, toast } from "../state";
import { html, paint } from "../util";
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
  await loadOrgs();
  resetHome();
  resetTeach();
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
    title: setup ? "Set up your hub" : "Sign In to Your Hub",
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

export function renderProfile(el: HTMLElement) {
  const u = app.me?.user;
  const s = deviceStats();
  const all = Object.values(localProgress());
  const inProgress = all.filter((p) => !p.done && p.step > 0).sort((a, b) => b.updated - a.updated);
  const completed = all.filter((p) => p.runs > 0).sort((a, b) => b.updated - a.updated);
  const header = u
    ? html`<div class="card profile-card">${personAvatar(u.name, 56, prefs.avatarHue)}
        <div><p class="profile-name">${u.name} <span class="badge-soft">${ROLE_WORD[u.role] ?? u.role}</span></p>
          <p class="muted">Signed in on this hub</p></div>
        <button class="secondary" data-act="sign-out">Sign Out</button></div>`
    : app.library
      ? html`<div class="card profile-card"><span class="avatar person placeholder">${icons.person}</span>
          <div><p class="profile-name">Not signed in</p><p class="muted">${app.me?.setup_needed ? "This hub has no owner yet." : "Sign in to keep your lessons and organizations."}</p></div>
          <button class="primary" data-act="sign-in">${app.me?.setup_needed ? "Set Up Hub" : "Sign In"}</button></div>`
      : html`<div class="card profile-card"><span class="avatar person placeholder">${icons.person}</span>
          <div><p class="profile-name">This device</p><p class="muted">Progress is kept on this device because the hub has no accounts.</p></div></div>`;
  const stats = s.lessons
    ? html`<div class="stat-row card">
        <div><span class="numeral">${s.lessons}</span><span class="stat-label">Lessons done</span></div>
        <div><span class="numeral">${s.camera}</span><span class="stat-label">Steps checked by camera</span></div>
        <div><span class="numeral">${s.mistakes}</span><span class="stat-label">Mistakes caught</span></div>
      </div>`
    : empty(icons.grid, "No progress yet", "Finish a lesson and your results show up here.");
  paint(
    el,
    html`<div class="page narrow">
      ${pageHead("Profile")}
      ${header}
      <section class="block"><div class="block-head"><h2>Progress</h2></div>${stats}</section>
      ${inProgress.length
        ? html`<section class="block"><div class="block-head"><h2>In Progress</h2></div><div class="rows">${inProgress.map(
            (p) => html`<button class="row" data-go="${JSON.stringify({ name: "course", id: p.id })}"><span class="row-text">
              <span class="row-title">${p.title}</span><span class="row-meta">Step ${p.step + 1} of ${p.total}</span></span><span class="chev">${icons.chevron}</span></button>`,
          )}</div></section>`
        : ""}
      ${completed.length
        ? html`<section class="block"><div class="block-head"><h2>Completed</h2></div><div class="rows">${completed.map((p) => {
            const t = s.times[p.id];
            return html`<button class="row" data-go="${JSON.stringify({ name: "course", id: p.id })}"><span class="row-text">
              <span class="row-title">${p.title}</span><span class="row-meta">${p.runs} ${p.runs === 1 ? "run" : "runs"}</span></span>
              ${t ? html`<span class="row-trail">You ${mmss(t.you)}${t.expert ? `, Expert ${mmss(t.expert)}` : ""}</span>` : ""}<span class="chev">${icons.chevron}</span></button>`;
          })}</div></section>`
        : ""}
    </div>`,
  );
}

export function profileAction(act: string) {
  if (act === "sign-in") signInSheet();
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
