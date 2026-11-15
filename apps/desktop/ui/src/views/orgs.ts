// Organizations (section 22): my organizations with invitations, join with a code, create,
// the org page with lessons and members, invites and member management for admins.

import { hub, type Invite, type Org, type OrgSummary } from "../api";
import { closeSheet, drawSheet, empty, lessonCard, loading, openSheet, orgAvatar, ORG_ROLE, pageHead, personAvatar } from "../components";
import { icons } from "../icons";
import { app, canTeach, errorText, go, rerender, signedIn, toast } from "../state";
import { html, paint } from "../util";
import { resetHome } from "./home";
import { startTeach } from "./teach";

/** Reloads the org list and invitations into `app` (also used by the nav pane). */
export async function loadOrgs() {
  if (!app.library || !signedIn()) {
    app.orgs = [];
    app.invites = [];
    return;
  }
  try {
    const r = await hub<{ orgs: OrgSummary[]; invites: Invite[] }>("GET", "/api/orgs");
    app.orgs = r.orgs.sort((a, b) => a.name.localeCompare(b.name));
    app.invites = r.invites ?? [];
  } catch {
    // Keep what we had; the screen shows its own error when opened.
  }
}

const memberCount = (o: OrgSummary | Org) => (typeof o.members === "number" ? o.members : o.members.length);

export function renderOrgs(el: HTMLElement) {
  if (!signedIn()) {
    paint(el, html`<div class="page">${pageHead("Organizations")}${empty(icons.peopleBig, "Sign in to see organizations", "Organizations group people and lessons, like a team or a class.", html`<button class="primary" data-act="sign-in">Sign In</button>`)}</div>`);
    return;
  }
  const canCreate = app.me?.can_create_org ?? signedIn();
  const actions = html`<button class="secondary" data-act="join-code">${icons.key}Join with a Code</button>
    ${canCreate ? html`<button class="primary" data-act="org-new">${icons.plus}New Organization</button>` : ""}`;
  const invites = app.invites.length
    ? html`<section class="block"><div class="block-head"><h2>Invitations</h2></div><div class="rows">
        ${app.invites.map(
          (i) => html`<div class="row static">
            ${orgAvatar(i.org?.name ?? "?", 44)}
            <span class="row-text"><span class="row-title">${i.org?.name ?? "An organization"}</span>
              <span class="row-meta">Joins as ${ORG_ROLE[i.role]}</span></span>
            <button class="quiet" data-act="invite-decline" data-org="${i.org?.id ?? ""}" data-invite="${i.id}">Decline</button>
            <button class="primary small" data-act="invite-accept" data-invite="${i.id}">Join</button>
          </div>`,
        )}</div></section>`
    : "";
  const list = app.orgs.length
    ? html`<div class="rows">${app.orgs.map(
        (o) => html`<button class="row" data-go="${JSON.stringify({ name: "org", id: o.id })}">
          ${orgAvatar(o.name, 44)}
          <span class="row-text"><span class="row-title">${o.name}</span><span class="row-meta">${memberCount(o)} ${memberCount(o) === 1 ? "member" : "members"}</span></span>
          ${o.role && o.role !== "learner" ? html`<span class="badge-soft">${ORG_ROLE[o.role]}</span>` : ""}
          <span class="chev">${icons.chevron}</span>
        </button>`,
      )}</div>`
    : app.invites.length
      ? ""
      : empty(icons.peopleBig, "No organizations yet", "Organizations group people and lessons, like a team or a class.", html`<div class="empty-actions">
          <button class="primary" data-act="join-code">Join with a Code</button>${canCreate ? html`<button class="secondary" data-act="org-new">Create Organization</button>` : ""}</div>`);
  paint(el, html`<div class="page">${pageHead("Organizations", app.orgs.length ? actions : "")}${invites}${list}</div>`);
}

// ---- Org page ----

let org: { id: string; o: Org | null; error: string } | null = null;

async function loadOrg(id: string) {
  org = { id, o: null, error: "" };
  try {
    const o = await hub<Org>("GET", `/api/orgs/${id}`);
    if (org?.id === id) org.o = o;
  } catch (e) {
    if (org?.id === id) org.error = errorText(e);
  }
  rerender();
}

export function renderOrg(el: HTMLElement, id: string) {
  if (!org || org.id !== id) {
    void loadOrg(id);
    return paint(el, html`<div class="page">${loading("Loading the organization")}</div>`);
  }
  if (org.error) return paint(el, html`<div class="page">${empty(icons.peopleBig, "Could not open this organization", org.error)}</div>`);
  if (!org.o) return paint(el, html`<div class="page">${loading("Loading the organization")}</div>`);
  const o = org.o;
  const admin = o.role === "org_admin" || app.me?.user?.role === "owner";
  const teaches = admin || o.role === "teacher";
  const admins = o.members.filter((m) => m.role === "org_admin");
  const lastAdmin = o.role === "org_admin" && admins.length === 1;
  const published = o.courses.filter((c) => c.status !== "draft");
  const drafts = teaches ? o.courses.filter((c) => c.status === "draft") : [];
  const group = (role: string, title: string) => {
    const ms = o.members.filter((m) => m.role === role);
    if (!ms.length) return "";
    return html`<p class="group-title">${title}</p>
      ${ms.map(
        (m) => html`<div class="member">
          ${personAvatar(m.name, 32)}<span class="member-name">${m.name}${m.user_id === app.me?.user?.id ? html` <span class="muted">(you)</span>` : ""}</span>
          ${admin && !(m.role === "org_admin" && admins.length === 1)
            ? html`<select class="role-select" data-act-change="member-role" data-user="${m.user_id}" aria-label="Role for ${m.name}">
                ${(["org_admin", "teacher", "learner"] as const).map((r) => html`<option value="${r}" ${m.role === r ? "selected" : ""}>${ORG_ROLE[r]}</option>`)}
              </select>
              ${m.user_id !== app.me?.user?.id ? html`<button class="icon-button" data-act="member-remove" data-user="${m.user_id}" data-name="${m.name}" title="Remove ${m.name}" aria-label="Remove ${m.name}">${icons.close}</button>` : ""}`
            : html`<span class="muted small">${ORG_ROLE[m.role]}</span>`}
        </div>`,
      )}
      ${role === "org_admin" && admin && admins.length === 1 ? html`<p class="hint">Every organization needs at least one admin.</p>` : ""}`;
  };
  paint(
    el,
    html`<div class="page">
      <header class="org-head">
        ${orgAvatar(o.name, 72)}
        <div class="org-head-text"><h1>${o.name}</h1>
          <p class="page-sub">${o.members.length} ${o.members.length === 1 ? "member" : "members"}, ${published.length} ${published.length === 1 ? "lesson" : "lessons"}${o.role ? html` <span class="dot-sep"></span> You are ${o.role === "learner" ? "a member" : `${o.role === "org_admin" ? "an" : "a"} ${ORG_ROLE[o.role]}`}` : ""}</p></div>
        <div class="page-actions">
          ${teaches ? html`<button class="primary" data-act="org-teach">${icons.teach}Teach</button>` : ""}
          ${admin ? html`<button class="secondary" data-act="org-invite">Invite</button>` : ""}
          ${admin || (o.role && !lastAdmin) ? html`<details class="org-more"><summary>More</summary><div class="org-more-menu">
            ${o.role && !lastAdmin ? html`<button class="quiet" data-act="org-leave">Leave</button>` : ""}
            ${admin ? html`<button class="quiet danger-text" data-act="org-delete">Delete</button>` : ""}
          </div></details>` : ""}
        </div>
      </header>
      <div class="org-cols">
        <section class="block">
          ${drafts.length ? html`<div class="block-head"><h2>Drafts</h2></div><div class="card-grid">${drafts.map((c) => lessonCard(c, { showStatus: true }))}</div>` : ""}
          <div class="block-head"><h2>Lessons</h2></div>
          ${published.length
            ? html`<div class="card-grid">${published.map((c) => lessonCard(c, { showStatus: teaches }))}</div>`
            : teaches
              ? empty(icons.filmBig, "No lessons yet", `Make the first lesson for ${o.name}.`, html`<button class="primary" data-act="org-teach">Teach</button>`)
              : empty(icons.filmBig, "No lessons yet", "When teachers publish here, lessons show up in this list.")}
        </section>
        <section class="block members-col">
          <div class="block-head"><h2>Members</h2></div>
          <div class="card members">${group("org_admin", "Admins")}${group("teacher", "Teachers")}${group("learner", "Members")}</div>
          ${admin && o.invites?.length
            ? html`<div class="block-head"><h2>Active Codes</h2></div>
                <div class="card members">${o.invites.map(
                  (i) => html`<div class="member">
                    <span class="code-chip">${i.kind === "code" ? icons.key : icons.person}</span>
                    <span class="member-name">${i.kind === "code" ? `Code, joins as ${ORG_ROLE[i.role]}` : `Invited ${typeof i.user === "object" ? i.user.name : i.user ?? ""} as ${ORG_ROLE[i.role]}`}
                      <span class="muted small">${i.kind === "code" ? `${i.uses ?? 0} used${i.max_uses ? ` of ${i.max_uses}` : ""}` : ""}${i.expires ? `, expires ${new Date(i.expires).toLocaleDateString()}` : ""}</span></span>
                    <button class="quiet small" data-act="invite-revoke" data-invite="${i.id}">Revoke</button>
                  </div>`,
                )}</div>`
            : ""}
        </section>
      </div>
    </div>`,
  );
}

export const reloadOrg = () => org && void loadOrg(org.id);

// ---- Sheets ----

export function joinSheet(after?: (o: OrgSummary) => void) {
  let err = "";
  let busy = false;
  openSheet({
    title: "Join with a Code",
    body: () => html`<form class="form">
      <label class="field"><span>Invite code</span><input name="code" class="code-input" placeholder="Paste the code" autocapitalize="off" spellcheck="false" /></label>
      <p class="hint">Ask an admin for the code from the organization's page.</p>
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Cancel</button>
        <button type="submit" class="primary" ${busy ? "disabled" : ""}>Join</button></div>
    </form>`,
    onSubmit: async (form) => {
      const code = (form.querySelector("[name=code]") as HTMLInputElement).value.trim();
      if (!code) return;
      busy = true;
      drawSheet();
      try {
        const o = await hub<OrgSummary>("POST", "/api/orgs/join", { body: { code } });
        closeSheet();
        toast(`You joined ${o.name}.`);
        await loadOrgs();
        resetHome();
        if (after) after(o);
        else go({ name: "org", id: o.id });
      } catch (e) {
        busy = false;
        const msg = errorText(e);
        err = msg === "invite code is not valid" ? "That code does not work. Check it with the admin." : msg.startsWith("you are already a member") ? "You are already in that organization." : msg;
        drawSheet();
      }
    },
  });
}

function createSheet() {
  let err = "";
  openSheet({
    title: "New Organization",
    body: () => html`<form class="form">
      <label class="field"><span>Name</span><input name="name" placeholder="Bike Shop Crew" maxlength="40" /></label>
      <p class="hint">You become the admin. You can invite people next.</p>
      <p class="form-error" role="alert">${err}</p>
      <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Cancel</button><button type="submit" class="primary">Create</button></div>
    </form>`,
    onSubmit: async (form) => {
      const name = (form.querySelector("[name=name]") as HTMLInputElement).value.trim();
      if (name.length < 2) {
        err = "A name needs at least 2 characters.";
        return drawSheet();
      }
      try {
        const o = await hub<Org>("POST", "/api/orgs", { body: { name } });
        closeSheet();
        await loadOrgs();
        go({ name: "org", id: o.id });
        inviteSheet(o.id, o.name);
      } catch (e) {
        err = errorText(e) === "that slug is taken" ? "An organization with that name already exists." : errorText(e);
        drawSheet();
      }
    },
  });
}

function inviteSheet(id: string, name: string) {
  let tab: "code" | "user" = "code";
  let code = "";
  let err = "";
  openSheet({
    title: `Invite to ${name}`,
    body: () => html`<div class="form">
      <div class="segmented"><button type="button" class="${tab === "code" ? "on" : ""}" data-act="tab" data-tab="code">Invite Code</button>
        <button type="button" class="${tab === "user" ? "on" : ""}" data-act="tab" data-tab="user">By Username</button></div>
      ${tab === "code"
        ? html`<div class="field-grid">
              <label class="field"><span>Joins as</span><select name="role"><option value="learner">Member</option><option value="teacher">Teacher</option><option value="org_admin">Admin</option></select></label>
              <label class="field"><span>Expires</span><select name="expires"><option value="0.0417">In 1 Hour</option><option value="1">In 1 Day</option><option value="7" selected>In 7 Days</option><option value="30">In 30 Days</option><option value="90">In 90 Days</option></select></label>
              <label class="field"><span>Uses</span><select name="uses"><option value="1">1</option><option value="10">10</option><option value="50">50</option><option value="" selected>No Limit</option></select></label>
            </div>
            ${code ? html`<div class="invite-code"><span class="code-big">${code}</span><span class="hint">Share it with the people you invite. It is shown only now.</span>
                <button type="button" class="secondary small" data-act="copy">Copy Code</button></div>` : ""}
            <p class="form-error" role="alert">${err}</p>
            <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Done</button><button type="button" class="primary" data-act="make-code">Create Code</button></div>`
        : html`<label class="field"><span>Username</span><input name="username" placeholder="sam" spellcheck="false" /></label>
            <label class="field"><span>Joins as</span><select name="urole"><option value="learner">Member</option><option value="teacher">Teacher</option><option value="org_admin">Admin</option></select></label>
            <p class="form-error" role="alert">${err}</p>
            <div class="form-actions"><button type="button" class="quiet" data-sheet="close">Done</button><button type="button" class="primary" data-act="send-invite">Send Invite</button></div>`}
    </div>`,
    onAction: async (act, el) => {
      const sheet = document.getElementById("sheet")!;
      const val = (n: string) => (sheet.querySelector(`[name=${n}]`) as HTMLInputElement | null)?.value ?? "";
      if (act === "tab") {
        tab = el.dataset.tab as "code" | "user";
        err = "";
        return drawSheet();
      }
      try {
        if (act === "make-code") {
          const uses = val("uses");
          const inv = await hub<Invite>("POST", `/api/orgs/${id}/invites`, { body: { role: val("role"), expires_days: Number(val("expires")), max_uses: uses ? Number(uses) : null } });
          code = inv.code ?? "";
          err = "";
          reloadOrg();
        } else if (act === "copy") {
          await navigator.clipboard.writeText(code).catch(() => {});
          toast("Code copied.");
        } else if (act === "send-invite") {
          await hub("POST", `/api/orgs/${id}/invites`, { body: { username: val("username").replace(/^@/, ""), role: val("urole") } });
          toast(`Invited ${val("username")}.`);
          err = "";
          reloadOrg();
        }
      } catch (e) {
        const m = errorText(e);
        err = m === "user not found" ? "No one on this hub has that username." : m === "that user is already a member" ? `${val("username")} is already in ${name}.` : m;
      }
      drawSheet();
    },
  });
}

function confirmSheet(title: string, message: string, button: string, run: () => Promise<void>) {
  let err = "";
  openSheet({
    title,
    body: () => html`<div class="form"><p class="sheet-lede">${message}</p><p class="form-error">${err}</p>
      <div class="form-actions"><button class="quiet" data-sheet="close">Cancel</button><button class="danger" data-act="ok">${button}</button></div></div>`,
    onAction: async (a) => {
      if (a !== "ok") return;
      try {
        await run();
        closeSheet();
      } catch (e) {
        err = errorText(e);
        drawSheet();
      }
    },
  });
}

export function orgsAction(act: string, t: HTMLElement) {
  const o = org?.o;
  if (act === "join-code") joinSheet();
  else if (act === "org-new") createSheet();
  else if (act === "invite-accept")
    void hub<OrgSummary>("POST", "/api/orgs/join", { body: { invite_id: t.dataset.invite } })
      .then(async (r) => {
        toast(`You joined ${r.name}.`);
        await loadOrgs();
        resetHome();
        rerender();
      })
      .catch((e) => toast(errorText(e)));
  else if (act === "invite-decline")
    void hub("DELETE", `/api/orgs/${t.dataset.org}/invites/${t.dataset.invite}`)
      .then(async () => {
        await loadOrgs();
        rerender();
      })
      .catch((e) => toast(errorText(e)));
  else if (!o) return;
  else if (act === "org-teach") {
    if (canTeach()) void startTeach(o.id);
  } else if (act === "org-invite") inviteSheet(o.id, o.name);
  else if (act === "invite-revoke")
    void hub("DELETE", `/api/orgs/${o.id}/invites/${t.dataset.invite}`).then(reloadOrg).catch((e) => toast(errorText(e)));
  else if (act === "member-remove")
    confirmSheet(`Remove ${t.dataset.name} from ${o.name}?`, "They lose access to this organization's lessons. Lessons they made stay in the org.", "Remove", async () => {
      await hub("DELETE", `/api/orgs/${o.id}/members/${t.dataset.user}`);
      reloadOrg();
    });
  else if (act === "org-leave")
    confirmSheet(`Leave ${o.name}?`, "You lose access to its lessons. Your progress stays on the hub.", "Leave", async () => {
      await hub("POST", `/api/orgs/${o.id}/leave`);
      await loadOrgs();
      resetHome();
      go({ name: "orgs" });
    });
  else if (act === "org-delete")
    confirmSheet(`Delete ${o.name}?`, "Members lose access to its lessons. Lessons go back to their owners as Only Me.", "Delete Organization", async () => {
      await hub("DELETE", `/api/orgs/${o.id}`);
      await loadOrgs();
      resetHome();
      go({ name: "orgs" });
    });
}

export function orgsChange(t: HTMLSelectElement) {
  const o = org?.o;
  if (!o || t.dataset.actChange !== "member-role") return;
  void hub("PATCH", `/api/orgs/${o.id}/members/${t.dataset.user}`, { body: { role: t.value } })
    .then(() => {
      const m = o.members.find((x) => x.user_id === t.dataset.user);
      toast(`${m?.name ?? "They"} ${m ? "is" : "are"} now a ${ORG_ROLE[t.value]}.`);
      reloadOrg();
    })
    .catch((e) => {
      toast(errorText(e));
      reloadOrg();
    });
}
