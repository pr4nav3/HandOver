// Onboarding (section 25): four welcome pages, connect to a hub, account, join an organization,
// choose a role, pick a look. Also the Connect page alone when no hub is paired.
// The welcome pages use the bundled sample lesson (synthetic fortune teller, rendered).

import { call, type Connected, type Settings } from "../api";
import { orgAvatar, personAvatar, ring, HUES, HUE_NAMES } from "../components";
import { icons } from "../icons";
import { app, errorText, go, prefs, rerender, signedIn } from "../state";
import { applyTheme, lookOf } from "../themes";
import { ago, html, paint, type Raw } from "../util";
import { refreshMe, setupOwner, signIn } from "./profile";
import { joinSheet, loadOrgs } from "./orgs";

type Page = "w1" | "w2" | "w3" | "w4" | "connect" | "account" | "profile" | "join" | "role" | "theme";

const ob = {
  page: "w1" as Page,
  /** True when only the Connect page is wanted (a later disconnect), not the whole flow. */
  connectOnly: false,
  typed: "",
  connecting: "",
  connected: null as Connected | null,
  fail: null as null | { title: string; message: string },
  accountMode: "signin" as "signin" | "setup",
  accountError: "",
  busy: false,
  role: prefs.homeFirst,
  joinedName: "",
};

export function startOnboarding(connectOnly: boolean) {
  ob.connectOnly = connectOnly;
  ob.page = connectOnly || prefs.welcomed ? "connect" : "w1";
  ob.fail = null;
  ob.connected = null;
  go({ name: "onboarding" }, false);
}

/** The steps after Connect that this person will actually see. */
function laterSteps(): Page[] {
  if (ob.connectOnly) return app.library && !signedIn() ? ["account"] : [];
  const out: Page[] = [];
  if (app.library) out.push("account");
  if (app.library && ob.accountMode === "setup") out.push("profile");
  if (app.library) out.push("join");
  out.push("role", "theme");
  return out;
}

function nextPage() {
  const flow: Page[] = ["w1", "w2", "w3", "w4", "connect", ...laterSteps()];
  let i = flow.indexOf(ob.page) + 1;
  // Skip the join page when already in an organization, and the account page once signed in.
  while (flow[i] === "join" && (!signedIn() || app.orgs.length)) i++;
  if (ob.page !== "account" && flow[i] === "account" && signedIn()) i++;
  if (i >= flow.length) return finish();
  ob.page = flow[i];
  if (ob.page === "connect") prefs.welcomed = true;
  rerender();
}

function prevPage() {
  const flow: Page[] = ["w1", "w2", "w3", "w4", "connect", ...laterSteps()];
  const i = flow.indexOf(ob.page);
  if (i > 0 && !(ob.page === "connect" && ob.connectOnly)) ob.page = flow[i - 1];
  rerender();
}

function finish() {
  prefs.welcomed = true;
  prefs.homeFirst = ob.role;
  go({ name: "home" }, false);
  app.history = [];
}

/** Pairs with a hub (section 3.3). Quiet: a launch-time reconnect, so errors go to Connect. */
export async function connectHub(address: string, quiet = false): Promise<boolean> {
  ob.connecting = address.trim();
  ob.fail = null;
  rerender();
  try {
    const r = await call<Connected>("connect", { address });
    app.snap.recent = r.recent;
    if (app.link.hub !== r.hub || app.link.link === "idle")
      app.link = { link: "connecting", hub: r.hub, label: r.label, attempt: 0, retry_in_ms: null, close_code: null };
    app.state = null;
    await refreshMe();
    ob.connecting = "";
    ob.connected = r;
    ob.typed = "";
    ob.accountMode = app.me?.setup_needed ? "setup" : "signin";
    return true;
  } catch (e) {
    const m = errorText(e);
    const host = address.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
    ob.connecting = "";
    ob.fail = m.includes("No hub answered")
      ? { title: `Cannot reach ${host}`, message: "Make sure this computer and the hub are on the same network, and that the hub is running." }
      : m.includes("not a HandOver hub")
        ? { title: "No hub at that address", message: "Something answered, but it is not HandOver. Check the address and port." }
        : { title: "That address does not work", message: m };
    if (quiet) startOnboarding(true);
    rerender();
    return false;
  }
}

// ---- Pages ----

function chrome(body: Raw, opts: { step?: boolean; skip?: string; back?: boolean; dots?: number } = {}): Raw {
  const flow = laterSteps();
  const i = flow.indexOf(ob.page);
  return html`<div class="ob">
    <div class="ob-top">
      ${opts.back ? html`<button class="icon-button" data-act="ob-back" aria-label="Back">${icons.back}</button>` : html`<span></span>`}
      ${opts.skip ? html`<button class="quiet" data-act="ob-skip">${opts.skip}</button>` : html`<span></span>`}
    </div>
    <div class="ob-card">
      ${opts.step && i >= 0 ? html`<p class="ob-step">Step ${i + 1} of ${flow.length}</p>` : ""}
      ${body}
    </div>
    ${opts.dots !== undefined
      ? html`<div class="ob-dots" aria-hidden="true">${[0, 1, 2, 3].map((d) => html`<span class="${d === opts.dots ? "on" : ""}"></span>`)}</div>`
      : ""}
  </div>`;
}

function welcome(n: number): Raw {
  const pages = [
    {
      title: "An expert does it once",
      line: "They record the task on their phone or Ray-Ban Meta glasses and talk through each step.",
      art: html`<div class="art art1"><div class="art-panel"><video src="/sample/clip02.mp4" muted loop autoplay playsinline></video></div>
        <p class="art-caption">Sample lesson, rendered</p>
        <div class="art-rec"><span class="wave">${icons.wave}</span><span class="rec-capsule"><span class="rec-dot"></span>Recording</span></div></div>`,
      label: "A sample lesson playing, with a recording indicator",
    },
    {
      title: "We turn it into steps",
      line: "HandOver finds where each step starts and ends, cuts a clip for each one, and adds captions.",
      art: html`<div class="art art2"><div class="tiles">${[1, 2, 3, 4, 5, 6, 7, 8].map(
        (i) => html`<span class="tile-f" style="animation-delay:${i * 0.06}s"><img src="/sample/0${i}.jpg" alt="" /><span class="seg-pill">${i}</span></span>`,
      )}</div>
        <div class="art-timeline">${[0, 1, 2, 3, 4, 5, 6, 7].map(
          (i) => html`<span style="background:${["#4F78A8", "#5E8B62", "#A87A3E", "#7E62A0", "#A85E57", "#3F8A86", "#8C7E2E", "#6268A8"][i]};animation-delay:${0.2 + i * 0.12}s"></span>`,
        )}</div></div>`,
      label: "The lesson split into 8 steps on a timeline",
    },
    {
      title: "Your camera follows along",
      line: "Point a phone at your work. When a step looks done, the next clip starts.",
      art: html`<div class="art art3"><div class="panes"><div class="art-pane stage">${icons.viewfinder}</div>
        <div class="art-pane"><img src="/sample/03.jpg" alt="" /></div></div>
        <span class="art-badge"><span class="badge-dot"></span><span class="w">Watching</span><span class="v">Verified</span></span></div>`,
      label: "Your camera beside the expert's clip. The status changes to verified.",
    },
    {
      title: "You get a score and a tip",
      line: "See how each step went against the expert, and what to practice next.",
      art: html`<div class="art art4"><div class="art-ring">${ring(0.7, 120, "var(--green)")}<span>Your score</span></div>
        <div class="art-bars">${[0.8, 0.55, 0.95].map((w, i) => html`<span class="bar-pair"><span class="b1" style="width:${w * 100}%;animation-delay:${0.3 + i * 0.08}s"></span>
          <span class="b2" style="width:${w * 70}%;animation-delay:${0.38 + i * 0.08}s"></span></span>`)}</div>
        <div class="art-tip">${icons.bulb}<span>One tip, from your own run.</span></div></div>`,
      label: "A score ring and a time bar for each step",
    },
  ];
  const p = pages[n];
  return chrome(
    html`<div class="ob-art" role="img" aria-label="${p.label}">${p.art}</div>
      <h1 class="ob-title">${p.title}</h1>
      <p class="ob-line">${p.line}</p>
      <button class="primary large ob-primary" data-act="ob-next">${n === 3 ? "Get Started" : "Continue"}</button>`,
    { skip: "Skip", back: n > 0, dots: n },
  );
}

function connectPage(): Raw {
  if (ob.connected) {
    const n = ob.connected.lessons.length;
    return chrome(
      html`<div class="ob-result"><span class="ob-check">${icons.checkFill}</span>
        <h1 class="ob-title">Connected to ${ob.connected.label}</h1>
        <p class="ob-line">${n ? `${n} ${n === 1 ? "lesson" : "lessons"} on this hub.` : "No lessons on this hub yet."}</p></div>`,
    );
  }
  if (ob.connecting)
    return chrome(html`<div class="ob-result"><span class="spinner large"></span><h1 class="ob-title">Connecting to ${ob.connecting}</h1>
      <p class="ob-line">Checking that a HandOver hub is there.</p></div>`);
  if (ob.fail)
    return chrome(
      html`<div class="ob-result"><span class="ob-warn">${icons.shield}</span><h1 class="ob-title">${ob.fail.title}</h1>
        <p class="ob-line">${ob.fail.message}</p>
        <div class="form-actions center"><button class="secondary" data-act="ob-edit">Edit Address</button>
          <button class="primary" data-act="ob-retry">Try Again</button></div></div>`,
    );
  const recent = app.snap.recent.slice(0, 5);
  return chrome(
    html`<div class="ob-mark">${icons.mark}</div>
      <h1 class="ob-title">Connect to your hub</h1>
      <p class="ob-line">The hub is HandOver running on a computer near you. It keeps your lessons.</p>
      <form class="ob-form" id="ob-connect" autocomplete="off">
        <label class="field"><span>Hub address</span>
          <input id="ob-address" name="address" placeholder="192.168.1.20:8000" spellcheck="false" autocapitalize="off" value="${ob.typed}" /></label>
        <p class="hint">Find it on the hub computer. HandOver uses port 8000 unless you set another.</p>
        <button class="primary large" type="submit">Connect</button>
      </form>
      ${recent.length
        ? html`<div class="recent"><p class="field-label">Recent</p>${recent.map(
            (h) => html`<div class="recent-item"><button class="recent-row" data-act="ob-recent" data-base="${h.base}">
                <span class="recent-icon">${icons.hub}</span><span class="recent-name">${h.label}</span>
                <span class="recent-when">Last connected ${ago(h.last_used)}</span></button>
              <button class="icon-button" data-act="ob-forget" data-base="${h.base}" title="Remove ${h.label}" aria-label="Remove ${h.label}">${icons.close}</button></div>`,
          )}</div>`
        : ""}
      <p class="ob-foot">A hub is the HandOver server running on a computer near you.</p>`,
    { back: !ob.connectOnly },
  );
}

function accountPage(): Raw {
  const setup = ob.accountMode === "setup";
  const optional = app.me?.auth === "optional";
  return chrome(
    html`<h1 class="ob-title">${setup ? "Set up your hub" : "Sign in to your hub"}</h1>
      <p class="ob-line">${setup
        ? "You are the first person here, so you become the hub owner. Owners manage accounts and organizations."
        : "Your account lives on this hub. There is no HandOver cloud account."}</p>
      <form class="ob-form" id="ob-account" autocomplete="off">
        <label class="field"><span>Name</span><input id="ob-name" name="name" placeholder="Sam Rivera" maxlength="40" /></label>
        <label class="field"><span>Passcode</span><input id="ob-pass" name="passcode" type="password" maxlength="128" /></label>
        ${setup ? html`<label class="field"><span>Confirm Passcode</span><input id="ob-confirm" name="confirm" type="password" maxlength="128" /></label>` : ""}
        ${setup ? passStrength() : ""}
        <p class="form-error" role="alert">${ob.accountError}</p>
        <button class="primary large" type="submit" ${ob.busy ? "disabled" : ""}>${setup ? "Finish Setup" : "Sign In"}</button>
        ${!setup ? html`<p class="hint center">No account? The hub owner adds people in Settings on the hub.</p>` : ""}
      </form>`,
    { step: true, back: true, skip: optional ? "Not Now" : undefined },
  );
}

let passValue = "";
function passStrength(): Raw {
  const p = passValue;
  const run = /^(.)\1+$/.test(p) || "0123456789abcdefghijklmnopqrstuvwxyz".includes(p.toLowerCase());
  let level = 0;
  let line = "At least 4 characters.";
  if (p.length >= 8 && /[a-z]/i.test(p) && /\d/.test(p)) [level, line] = [3, "Hard to guess."];
  else if (p.length >= 6 && !run) [level, line] = [2, "OK for a shared workshop hub."];
  else if (p.length >= 4) [level, line] = [1, "Easy to guess. Anyone nearby could try it."];
  const tone = ["", "var(--amber)", "var(--accent)", "var(--green)"][level];
  return html`<div class="strength" aria-live="polite"><span class="strength-bar">${[1, 2, 3].map((i) => html`<span style="background:${i <= level ? tone : "var(--panel-2)"}"></span>`)}</span>
    <span class="hint">${line}</span></div>`;
}

function profilePage(): Raw {
  const u = app.me?.user;
  return chrome(
    html`<h1 class="ob-title">Add a color</h1>
      <p class="ob-line">People see it next to your name. Initials work fine.</p>
      <div class="ob-avatar">${personAvatar(u?.name ?? "You", 96, prefs.avatarHue)}</div>
      <div class="hue-row" role="radiogroup" aria-label="Avatar color">${HUES.map(
        (h, i) => html`<button class="hue ${i === prefs.avatarHue ? "on" : ""}" style="background:${h}" data-act="ob-hue" data-hue="${i}" aria-label="${HUE_NAMES[i]}" role="radio" aria-checked="${i === prefs.avatarHue}"></button>`,
      )}</div>
      <button class="primary large ob-primary" data-act="ob-next">Continue</button>`,
    { step: true, skip: "Not Now" },
  );
}

function joinPage(): Raw {
  return chrome(
    html`<span class="ob-icon">${icons.peopleBig}</span>
      <h1 class="ob-title">Join your team</h1>
      <p class="ob-line">If someone gave you an invite code, enter it. You can do this later from Organizations.</p>
      ${ob.joinedName ? html`<div class="joined card">${orgAvatar(ob.joinedName, 44)}<span>You joined <strong>${ob.joinedName}</strong>.</span></div>` : ""}
      <button class="primary large ob-primary" data-act="${ob.joinedName ? "ob-next" : "ob-join"}">${ob.joinedName ? "Continue" : "Enter Invite Code"}</button>`,
    { step: true, back: true, skip: "Not Now" },
  );
}

function rolePage(): Raw {
  const card = (v: "learn" | "teach", icon: Raw, title: string, line: string) =>
    html`<button class="role-card ${ob.role === v ? "on" : ""}" data-act="ob-role" data-role="${v}" role="radio" aria-checked="${ob.role === v}">
      <span class="tile">${icon}</span><span class="role-text"><span class="option-title">${title}</span><span class="option-line">${line}</span></span>
      <span class="role-check">${ob.role === v ? icons.checkFill : ""}</span></button>`;
  return chrome(
    html`<h1 class="ob-title">What brings you here?</h1>
      <p class="ob-line">This only changes what Home shows first. You can do both anytime.</p>
      <div class="role-list" role="radiogroup">
        ${card("learn", icons.grad, "I Want to Learn", "Lessons to take and where you left off.")}
        ${card("teach", icons.teachBig, "I Want to Teach", "Record a task and turn it into a lesson.")}
        <button class="role-both ${ob.role === "both" ? "on" : ""}" data-act="ob-role" data-role="both">Both</button>
      </div>
      <button class="primary large ob-primary" data-act="ob-next">Continue</button>`,
    { step: true, back: true, skip: "Not Now" },
  );
}

function themePage(): Raw {
  const s = app.snap.settings;
  const cat = app.snap.themes;
  return chrome(
    html`<h1 class="ob-title">Pick a look</h1>
      <p class="ob-line">You can change it anytime in Settings.</p>
      <div class="ob-preview">
        <div class="pv-progress">${[0, 1, 2, 3, 4, 5, 6, 7].map((i) => html`<span class="${i < 3 ? "done" : i === 3 ? "current" : ""}"></span>`)}</div>
        <div class="pv-body"><div class="pv-clip"><img src="/sample/04.jpg" alt="" /><span class="pv-cap">Fold all four corners to center.</span></div>
          <div class="pv-side"><p class="pv-count">Step 4 of 8</p><p class="pv-title">Fold all four corners to center</p>
            <div class="pv-controls"><span class="badge watching live"><span class="badge-dot"></span>Watching</span><span class="pv-next">Next</span></div></div></div>
      </div>
      <div class="segmented center">${(["system", "light", "dark"] as const).map(
        (a) => html`<button class="${s.appearance === a ? "on" : ""}" data-act="ob-appearance" data-appearance="${a}">${a[0].toUpperCase() + a.slice(1)}</button>`,
      )}</div>
      <div class="ob-themes">${cat.themes.map((t) => {
        const look = lookOf(t, s.appearance)?.look ?? {};
        return html`<button class="ob-theme ${t.id === s.theme ? "on" : ""}" data-act="ob-theme" data-theme="${t.id}" title="${t.name}, ${t.detail}">
          <span class="tp" style="background:${look.bg}"><span class="tp-card" style="background:${look.panel};border-color:${look.border}">
            <span class="tp-ink" style="background:${look.text}"></span><span class="tp-pill" style="background:${look.accent}"></span></span></span>
          <span class="ob-theme-name">${t.name}</span></button>`;
      })}</div>
      <button class="primary large ob-primary" data-act="ob-next">Start Using HandOver</button>`,
    { step: true, back: true, skip: "Keep Default" },
  );
}

export function renderOnboarding(el: HTMLElement) {
  let body: Raw;
  switch (ob.page) {
    case "w1":
    case "w2":
    case "w3":
    case "w4":
      body = welcome(Number(ob.page[1]) - 1);
      break;
    case "connect":
      body = connectPage();
      break;
    case "account":
      body = accountPage();
      break;
    case "profile":
      body = profilePage();
      break;
    case "join":
      body = joinPage();
      break;
    case "role":
      body = rolePage();
      break;
    default:
      body = themePage();
  }
  paint(el, body);
}

async function setSettings(patch: Partial<Settings>) {
  app.snap.settings = await call<Settings>("setSettings", patch);
  applyTheme(app.snap.themes, app.snap.settings);
  rerender();
}

export async function onboardingAction(act: string, t: HTMLElement) {
  if (act === "ob-next") nextPage();
  else if (act === "ob-back") prevPage();
  else if (act === "ob-skip") {
    if (ob.page.startsWith("w")) {
      prefs.welcomed = true;
      ob.page = "connect";
      rerender();
    } else if (ob.page === "theme") finish();
    else nextPage();
  } else if (act === "ob-recent") void doConnect(t.dataset.base!);
  else if (act === "ob-forget") {
    app.snap.recent = await call("forgetHub", { base: t.dataset.base });
    rerender();
  } else if (act === "ob-retry") void doConnect(ob.typed || app.snap.recent[0]?.base || "");
  else if (act === "ob-edit") {
    ob.fail = null;
    rerender();
  } else if (act === "ob-hue") {
    prefs.avatarHue = Number(t.dataset.hue);
    rerender();
  } else if (act === "ob-join")
    joinSheet((o) => {
      ob.joinedName = o.name;
      rerender();
    });
  else if (act === "ob-role") {
    ob.role = t.dataset.role as "learn" | "teach" | "both";
    rerender();
  } else if (act === "ob-appearance") void setSettings({ appearance: t.dataset.appearance as Settings["appearance"] });
  else if (act === "ob-theme") void setSettings({ theme: t.dataset.theme });
}

async function doConnect(address: string) {
  if (!address.trim()) {
    ob.fail = { title: "Type the hub's address", message: "Find it on the hub computer. HandOver uses port 8000 unless you set another." };
    return rerender();
  }
  ob.typed = address;
  const ok = await connectHub(address);
  if (!ok) return;
  rerender();
  // Connected: hold the result a moment, then continue by itself.
  window.setTimeout(() => {
    ob.connected = null;
    if (ob.connectOnly && !laterSteps().length) return finish();
    ob.page = "connect";
    nextPage();
  }, 1200);
}

export async function onboardingSubmit(form: HTMLFormElement) {
  if (form.id === "ob-connect") return doConnect((form.querySelector("#ob-address") as HTMLInputElement).value);
  if (form.id !== "ob-account") return;
  const v = (id: string) => (form.querySelector(`#${id}`) as HTMLInputElement | null)?.value ?? "";
  if (ob.accountMode === "setup" && v("ob-pass") !== v("ob-confirm")) {
    ob.accountError = "Passcodes do not match.";
    return rerender();
  }
  ob.busy = true;
  ob.accountError = "";
  rerender();
  try {
    if (ob.accountMode === "setup") await setupOwner(v("ob-name").trim(), v("ob-pass"));
    else await signIn(v("ob-name").trim(), v("ob-pass"));
    await loadOrgs();
    ob.busy = false;
    if (ob.connectOnly) return finish();
    nextPage();
  } catch (e) {
    ob.busy = false;
    const m = errorText(e);
    ob.accountError =
      m === "wrong name or passcode" ? "That name and passcode do not match." : m.startsWith("too many login") ? "Too many tries. Wait a minute, then try again." : m;
    rerender();
  }
}

export function onboardingInput(t: HTMLInputElement) {
  if (t.id === "ob-address") ob.typed = t.value;
  if (t.id === "ob-pass" && ob.accountMode === "setup") {
    passValue = t.value;
    rerender();
  }
}
