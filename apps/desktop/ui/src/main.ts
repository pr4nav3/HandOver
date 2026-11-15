// The window: a navigation pane (Home, Browse All, Organizations, Teach, Profile, the person's
// organizations, Settings at the foot) and one screen at a time, or Learn, the editor and
// onboarding using the whole window. The Rust core owns the hub connection; this file keeps the
// screens in step with its events and turns clicks and keys into core calls.

import { call, hub, invoke, onHub, sendCameraFrame, type HubEvent, type HubState, type Lesson, type LinkStatus, type Settings, type Snapshot } from "./api";
import { unlockAudio } from "./chime";
import { bindSheet, closeSheet, openSheet, sheetOpen, orgAvatar } from "./components";
import { LocalCamera } from "./frames";
import { icons } from "./icons";
import { app, canTeach, go, back, localProgress, prefs, saveProgress, setRenderer, setRouteHook, signedIn, toast, learn as learnHook, type Route } from "./state";
import { applyTheme } from "./themes";
import { html, modKey, paint, typing } from "./util";
import { browseAction, browseInput, renderBrowse } from "./views/browse";
import { courseAction, rateSheet, renderCourse } from "./views/course";
import { editorAction, editorChange, editorPointerDown, renderEditor } from "./views/editor";
import { homeAction, renderHome, resetHome } from "./views/home";
import { LearnView, type RunSummary } from "./views/learn";
import { connectHub, onboardingAction, onboardingInput, onboardingSubmit, renderOnboarding, startOnboarding } from "./views/onboarding";
import { CAMERA_WORD, cameraSheet, pairLive, pairSheet } from "./views/pair";
import { joinSheet, orgsAction, orgsChange, renderOrg, renderOrgs } from "./views/orgs";
import { profileAction, recordRun, refreshMe, renderProfile, signInSheet } from "./views/profile";
import { bindSettings, renderSettings } from "./views/settings";
import { onUploadProgress, renderProcessing, renderTeach, teachAction } from "./views/teach";

/** The link must be down this long before the window says so, so a blip does not flash. */
const DOWN_GRACE_MS = 1500;

const root = document.getElementById("app")!;
root.innerHTML = `<div class="shell">
  <nav class="pane" id="pane" aria-label="HandOver"></nav>
  <main class="main" id="main-content">
    <div class="screen" id="content"></div>
    <div class="screen full" id="learn-screen">
      <header class="learn-bar" id="learn-bar"></header>
      <div class="learn-host" id="learn"></div>
    </div>
  </main>
  <div class="screen overlay-screen" id="onboarding"></div>
  <div class="settings" id="settings" hidden></div>
  <div class="sheet-layer" id="sheet" hidden></div>
  <div class="toast" id="toast" role="status" hidden></div>
</div>`;
const $ = (id: string) => document.getElementById(id)!;

const ui = {
  lesson: null as Lesson | null,
  lessonKey: "",
  /** The lesson this window started, picked again if the hub restarts with none. */
  resumeId: null as string | null,
  resentThisConnection: false,
  /** This connection has seen the hub running our lesson (so losing it means someone ended it). */
  sawLesson: false,
  /** Where Learn should go once the hub has selected the lesson. */
  pendingGoto: null as number | null,
  themeSearch: "",
};
let downTimer = 0;

const learn = new LearnView($("learn"), {
  next: (from) => void call("next", { from, reason: "button" }).catch(showError),
  back: (from) => void call("back", { from }).catch(showError),
  goto: (step) => void call("goto", { step }).catch(showError),
  dismissMistake: () => void call("dismissMistake").catch(() => {}),
  library: () => leaveLearn(),
  pick: () => {
    exitLearn();
    go({ name: "browse" });
  },
  pair: () => pairSheet(),
  chooseCamera: () => cameraSheet(),
  retryCamera: () => {
    stopLocalCamera();
    render();
  },
  hold: (held) => void call("hold", { held }).catch(showError),
  finished: (s) => onFinished(s),
});

// Tauri can hide a native window before its webview is destroyed. Stop at both browser lifecycle boundaries so
// neither the looping clip nor speech survives a closed/minimized lesson window.
window.addEventListener("pagehide", () => learn.stopMedia());
window.addEventListener("beforeunload", () => learn.stopMedia());
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") learn.pauseMedia();
  else if (app.route.name === "learn") learn.resumeMedia();
});

// ---- This computer as the camera ----

const PLATFORM = navigator.userAgent.includes("Mac") ? "macos" : navigator.userAgent.includes("Windows") ? "windows" : "linux";
const CAMERA_NAME = { macos: "Mac camera", windows: "Windows camera", linux: "Linux camera" }[PLATFORM];
const local = new LocalCamera(learn.localVideo, sendCameraFrame);
local.onChange = () => render();

/** Sends this computer's webcam to the hub only while Learn is open with it chosen. */
function syncLocalCamera() {
  const want = app.route.name === "learn" && prefs.camera === "computer" && app.link.link !== "idle";
  if (want && local.state === "off")
    void local.start().then((ok) => {
      if (ok) void call("cameraStart", { name: CAMERA_NAME, platform: PLATFORM }).catch(showError);
    });
  else if (!want && local.state !== "off") stopLocalCamera();
}

function stopLocalCamera() {
  const was = local.state;
  local.stop();
  app.cameraLink = "off";
  if (was === "on" || was === "starting") void call("cameraStop").catch(() => {});
}

function showError(e: unknown) {
  toast(String((e as Error)?.message ?? e));
}

// ---- Navigation pane ----

function hubPill() {
  const l = app.link;
  if (l.link === "idle") return html`<span class="hub-pill off"><span class="dot"></span>Not connected</span>`;
  let cls = "ok";
  let words = "Connected";
  if (l.link === "connecting") [cls, words] = ["wait", "Connecting"];
  else if (l.link === "replaced") [cls, words] = ["warn", "Another window took over"];
  else if (app.down) [cls, words] = ["warn", "Reconnecting"];
  return html`<button class="hub-pill ${cls}" data-act="open-settings" title="${l.label ? `Hub at ${l.label}` : ""}"><span class="dot"></span>${words}</button>`;
}

function renderPane() {
  const r = app.route.name;
  const item = (route: Route, icon: unknown, label: string, on: boolean) =>
    html`<button class="pane-item ${on ? "on" : ""}" data-go="${JSON.stringify(route)}" aria-current="${on ? "page" : "false"}">${icon as never}<span>${label}</span></button>`;
  const orgId = app.route.name === "org" ? app.route.id : "";
  paint(
    $("pane"),
    html`<div class="pane-brand"><span class="pane-mark">${icons.mark}</span><span>HandOver</span></div>
      <div class="pane-items">
        ${item({ name: "home" }, icons.home, "Home", r === "home")}
        ${item({ name: "browse" }, icons.grid, "Browse All", r === "browse" || r === "course")}
        ${app.library && signedIn() ? item({ name: "orgs" }, icons.people, "Organizations", r === "orgs") : ""}
        ${canTeach() ? item({ name: "teach" }, icons.teach, "Teach", r === "teach" || r === "processing") : ""}
        ${item({ name: "profile" }, icons.person, "Profile", r === "profile")}
      </div>
      ${app.orgs.length
        ? html`<p class="pane-section">Organizations</p><div class="pane-items">${app.orgs.map(
            (o) => html`<button class="pane-item org ${orgId === o.id ? "on" : ""}" data-go="${JSON.stringify({ name: "org", id: o.id })}">${orgAvatar(o.name, 20)}<span>${o.name}</span></button>`,
          )}</div>`
        : ""}
      <div class="pane-foot">
        ${hubPill()}
        <button class="pane-item" data-act="open-settings">${icons.gear}<span>Settings</span></button>
      </div>`,
  );
}

function renderLearnBar() {
  const s = app.state;
  const camera = !app.down && s?.camera_connected && s?.camera?.source !== "file" ? s?.camera?.name : "";
  paint(
    $("learn-bar"),
    html`<button class="secondary small end-button" data-act="end-lesson" title="${s?.lesson_id ? "End this lesson" : "Back to Home"}">${icons.close}<span>${s?.lesson_id ? "End" : "Close"}</span></button>
      <span class="learn-title">${ui.lesson?.title ?? ""}</span>
      <span class="learn-bar-right">
        ${camera ? html`<span class="topbar-camera" title="Active camera">${camera}</span>` : ""}
        ${hubPill()}
        <button class="icon-button" data-act="open-settings" title="Settings" aria-label="Settings">${icons.gear}</button>
      </span>`,
  );
}

// ---- Render ----

function render() {
  const r = app.route;
  const learning = r.name === "learn";
  const onboarding = r.name === "onboarding";
  const fullContent = r.name === "editor";
  document.body.dataset.screen = r.name;
  $("pane").hidden = learning || onboarding || fullContent;
  $("content").hidden = learning || onboarding;
  $("learn-screen").hidden = !learning;
  $("onboarding").hidden = !onboarding;
  if (!learning && !onboarding) renderPane();
  const el = $("content");
  switch (r.name) {
    case "home":
      renderHome(el);
      break;
    case "browse":
      renderBrowse(el);
      break;
    case "course":
      renderCourse(el, r.id);
      break;
    case "teach":
      renderTeach(el);
      break;
    case "processing":
      renderProcessing(el);
      break;
    case "editor":
      renderEditor(el, r.id);
      break;
    case "orgs":
      renderOrgs(el);
      break;
    case "org":
      renderOrg(el, r.id);
      break;
    case "profile":
      renderProfile(el);
      break;
    case "onboarding":
      renderOnboarding($("onboarding"));
      break;
  }
  if (learning) renderLearnBar();
  learn.setActive(learning);
  syncLocalCamera();
  const s0 = app.state;
  const phase = s0?.lesson_id ? (ui.lesson?.id === s0.lesson_id ? "running" : "starting") : ui.resumeId && app.link.link !== "idle" ? "starting" : "none";
  learn.update({
    state: app.state,
    lesson: ui.lesson,
    down: app.down,
    chime: app.snap.settings.chime,
    phase,
    camera: { choice: prefs.camera, local: local.state, link: app.cameraLink },
  });
  const s = app.state;
  const off = s?.check_offline ? `Off: ${s.offline_label ?? "checks unavailable"}` : "Camera checks";
  renderSettings($("settings"), {
    open: app.settingsOpen,
    settings: app.snap.settings,
    catalog: app.snap.themes,
    link: app.link,
    version: app.snap.version,
    search: ui.themeSearch,
    checks: off,
    checkInterval: s?.check_interval_s ?? null,
    camera: prefs.camera ? CAMERA_WORD[prefs.camera] : "Not chosen yet",
    account: app.me?.user ? `${app.me.user.name}, ${app.me.user.role}` : "",
  });
}
setRenderer(render);
setRouteHook((r) => {
  if (r.name !== "learn") learn.setActive(false);
});

// ---- Learn ----

/** Opens Learn on a lesson. The first time, asks how HandOver should see the learner's hands. */
function startLesson(id: string, step = 0, restart = false) {
  unlockAudio();
  if (!prefs.camera) return cameraSheet({ then: () => beginLesson(id, step, restart) });
  beginLesson(id, step, restart);
}

function beginLesson(id: string, step: number, restart: boolean) {
  ui.resumeId = id;
  ui.resentThisConnection = false;
  if (restart || app.state?.lesson_id !== id) {
    learn.resetRun();
    ui.pendingGoto = step > 0 ? step : null;
    void call("selectLesson", { id }).catch(showError);
  } else if (step !== app.state?.step) void call("goto", { step }).catch(showError);
  go({ name: "learn", id });
}
learnHook.start = startLesson;

function leaveLearn() {
  ui.resumeId = null;
  ui.pendingGoto = null;
  if (app.history.length) back();
  else go({ name: "home" });
}

/** Leaves Learn for Home. With `end`, tells the hub to stop the run and unload the lesson. */
function exitLearn(end = false) {
  const s = app.state;
  if (end && s?.lesson_id)
    void call("endLesson", { lessonId: s.lesson_id, runId: (s as { run_id?: string | null }).run_id ?? "" }).catch(showError);
  ui.resumeId = null;
  ui.pendingGoto = null;
  app.history = [];
  go({ name: "home" });
}

/** End, with a confirmation while the lesson is under way. */
function endLesson() {
  const s = app.state;
  if (!s?.lesson_id || s.status === "done" || app.route.name !== "learn") return exitLearn(!!s?.lesson_id);
  openSheet({
    title: "End this lesson?",
    body: () => html`<div class="form">
      <p class="sheet-lede">${s.step > 0 ? "Your place is saved on this device, so you can continue from Home." : "You can start it again anytime."}</p>
      <div class="form-actions"><button class="quiet" data-sheet="close">Keep Going</button>
        <button class="danger" data-act="end">End Lesson</button></div>
    </div>`,
    onAction: (a) => {
      if (a !== "end") return;
      closeSheet();
      exitLearn(true);
    },
  });
}

function onFinished(s: RunSummary) {
  const p = localProgress()[s.lessonId];
  saveProgress({ id: s.lessonId, title: s.title, step: 0, total: s.steps.length, done: true, updated: Date.now(), runs: (p?.runs ?? 0) + 1, how: learn.howList() });
  recordRun(s.lessonId, s.camera, s.mistakes, (s.ms ?? 0) / 1000, s.expert);
  resetHome();
  if (app.snap.settings.notifications) void invoke("notify", { title: "Lesson complete", body: s.title }).catch(() => {});
  // Section 9: offer a rating once per lesson, after a moment.
  const asked = `handover.rated.${app.link.hub}.${s.lessonId}`;
  if (app.library && signedIn() && !localStorage.getItem(asked))
    window.setTimeout(async () => {
      if (app.route.name !== "learn" || app.state?.status !== "done") return;
      try {
        const d = await hub<{ permissions: { can_rate: boolean } }>("GET", `/api/courses/${s.lessonId}`);
        if (!d.permissions.can_rate) return;
        localStorage.setItem(asked, "1");
        rateSheet(s.lessonId, s.title, null);
      } catch {
        // No rating prompt when the course cannot be read.
      }
    }, 2000);
}

// The full lesson follows the hub: refetched when it switches lessons or `rev` changes.
async function syncLesson() {
  const id = app.state?.lesson_id ?? null;
  const key = id ? `${id}@${app.state?.rev ?? 0}` : "";
  if (key === ui.lessonKey) return;
  ui.lessonKey = key;
  if (!id) {
    ui.lesson = null;
    render();
    return;
  }
  try {
    const lesson = await call<Lesson>("lesson", { id });
    if (ui.lessonKey === key) ui.lesson = lesson;
  } catch {
    if (ui.lessonKey === key) ui.lesson = null;
  }
  render();
}

// ---- Hub events ----

function onLink(l: LinkStatus) {
  const was = app.link.link;
  app.link = l;
  if (l.link === "connected") {
    window.clearTimeout(downTimer);
    downTimer = 0;
    app.down = false;
    ui.resentThisConnection = false;
    ui.sawLesson = false;
    if (was !== "connected") resetHome();
  } else if (l.link === "idle") {
    window.clearTimeout(downTimer);
    downTimer = 0;
    app.down = false;
    app.state = null;
  } else if (!downTimer && !app.down) {
    downTimer = window.setTimeout(() => {
      downTimer = 0;
      app.down = app.link.link !== "connected";
      render();
    }, DOWN_GRACE_MS);
  }
  if (l.link === "replaced") app.down = true;
  render();
}

function onState(s: HubState) {
  const prev = app.state;
  app.state = s;
  if (s.lesson_id && s.lesson_id === ui.resumeId) ui.sawLesson = true;
  // Someone ended the lesson (End on any screen): Learn says "No lesson running".
  if (!s.lesson_id && ui.resumeId && ui.sawLesson) {
    ui.resumeId = null;
    ui.pendingGoto = null;
    if (app.route.name === "learn") toast("The lesson was ended.");
  }
  // The hub restarted and lost our lesson: pick it again, once per connection.
  if (!s.lesson_id && ui.resumeId && app.route.name === "learn" && !ui.resentThisConnection) {
    ui.resentThisConnection = true;
    learn.resetRun();
    void call("selectLesson", { id: ui.resumeId }).catch(() => {});
  }
  if (s.lesson_id && s.lesson_id === ui.resumeId && ui.pendingGoto !== null && s.step === 0) {
    const g = ui.pendingGoto;
    ui.pendingGoto = null;
    void call("goto", { step: g }).catch(() => {});
  }
  // This device's place in the lesson, for Continue (section 21).
  if (s.lesson_id && s.lesson_id === ui.resumeId && s.status !== "done" && ui.lesson?.id === s.lesson_id) {
    const p = localProgress()[s.lesson_id];
    saveProgress({ id: s.lesson_id, title: ui.lesson.title, step: s.step, total: s.total, done: false, updated: Date.now(), runs: p?.runs ?? 0, how: learn.howList() });
  }
  if (app.snap.settings.notifications && prev && s.check_offline && !prev.check_offline)
    void invoke("notify", { title: "Checks off, use Next", body: s.offline_label ?? "" }).catch(() => {});
  void syncLesson();
  pairLive();
  render();
}

function onEvent(e: HubEvent | { kind: "upload"; sent: number; total: number }) {
  switch (e.kind) {
    case "link":
      return onLink(e.link);
    case "state":
      return onState(e.state);
    case "advance":
      return learn.onAdvance(e.advance);
    case "mistake":
      return learn.onMistake(e.mistake);
    case "frame":
      return learn.onFrame(e.n);
    case "upload":
      return onUploadProgress(e.sent, e.total);
    case "camera":
      app.cameraLink = e.camera;
      return render();
    case "error":
      // A lesson that could not start: Learn says "No lesson running" and offers the list.
      if (app.route.name === "learn" && !app.state?.lesson_id) {
        ui.resumeId = null;
        render();
      }
      return toast(e.message);
  }
}

async function setSettings(patch: Record<string, unknown>) {
  try {
    app.snap.settings = await call<Settings>("setSettings", patch);
    applyTheme(app.snap.themes, app.snap.settings);
    render();
  } catch (e) {
    showError(e);
  }
}

// ---- Clicks, keys, forms ----

function dispatchAction(act: string, t: HTMLElement) {
  if (act === "open-settings") {
    app.settingsOpen = true;
    return render();
  }
  if (act === "leave-learn") return leaveLearn();
  if (act === "end-lesson") return endLesson();
  if (act === "pair-phone") return pairSheet();
  if (act === "camera-change") return cameraSheet();
  if (act === "join-code") return joinSheet();
  if (act === "sign-in") return signInSheet();
  const r = app.route.name;
  if (r === "onboarding") return void onboardingAction(act, t);
  if (r === "home") return homeAction(act);
  if (r === "browse") return browseAction(act, t);
  if (r === "course") return courseAction(act, t);
  if (r === "teach" || r === "processing") return teachAction(act);
  if (r === "editor") return editorAction(act, t);
  if (r === "orgs" || r === "org") return orgsAction(act, t);
  if (r === "profile") return profileAction(act);
}

document.addEventListener("click", (e) => {
  const t = e.target as HTMLElement;
  // Sheets, Settings and Learn handle their own clicks.
  if (t.closest("#sheet, #settings, #learn")) return;
  const goEl = t.closest<HTMLElement>("[data-go]");
  if (goEl) {
    e.preventDefault();
    return go(JSON.parse(goEl.dataset.go!));
  }
  const a = t.closest<HTMLElement>("[data-act]");
  if (a) dispatchAction(a.dataset.act!, a);
});

document.addEventListener("submit", (e) => {
  const form = e.target as HTMLFormElement;
  if (form.closest("#sheet")) return;
  e.preventDefault();
  if (app.route.name === "onboarding") void onboardingSubmit(form);
  else if (app.route.name === "editor") (document.activeElement as HTMLElement | null)?.blur();
});

document.addEventListener("input", (e) => {
  const t = e.target as HTMLInputElement;
  if (t.closest("#sheet") || t.closest("#settings")) return;
  if (app.route.name === "browse") browseInput(t);
  if (app.route.name === "onboarding") onboardingInput(t);
});

document.addEventListener("change", (e) => {
  const t = e.target as HTMLInputElement;
  if (t.closest("#sheet") || t.closest("#settings")) return;
  if (app.route.name === "editor") editorChange(t);
  if (app.route.name === "org") orgsChange(t as unknown as HTMLSelectElement);
});

document.addEventListener("pointerdown", (e) => {
  if (app.route.name === "editor") editorPointerDown(e);
});

bindSheet();
bindSettings($("settings"), {
  close: () => {
    app.settingsOpen = false;
    render();
  },
  set: (patch) => void setSettings(patch),
  checkInterval: (seconds) => void call("setCheckInterval", { seconds }).catch(showError),
  search: (text) => {
    ui.themeSearch = text;
    render();
  },
  disconnect: async () => {
    app.settingsOpen = false;
    ui.resumeId = null;
    await call("disconnect");
    app.me = null;
    app.library = false;
    app.orgs = [];
    startOnboarding(true);
  },
  pair: () => pairSheet(),
  camera: () => cameraSheet(),
  otherHub: () => {
    app.settingsOpen = false;
    startOnboarding(true);
  },
  welcome: () => {
    app.settingsOpen = false;
    localStorage.setItem("handover.welcomed", "0");
    startOnboarding(false);
  },
});

window.addEventListener("keydown", (e) => {
  if (modKey(e) && e.key === ",") {
    e.preventDefault();
    app.settingsOpen = !app.settingsOpen;
    return render();
  }
  if (e.key === "Escape") {
    if (sheetOpen()) return closeSheet();
    if (app.settingsOpen) {
      app.settingsOpen = false;
      return render();
    }
    if (app.route.name === "learn") learn.dismissMistake();
    return;
  }
  if (sheetOpen() || app.settingsOpen) return;
  if (modKey(e) && e.key.toLowerCase() === "l" && app.link.link !== "idle") {
    e.preventDefault();
    return go({ name: "browse" });
  }
  if (modKey(e) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    return startOnboarding(true);
  }
  if (modKey(e) && e.key === "[" && app.route.name !== "learn") {
    e.preventDefault();
    return back();
  }
  if (app.route.name !== "learn" || typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "ArrowRight" || e.key === " ") {
    e.preventDefault();
    learn.next();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    learn.back();
  } else if (e.key.toLowerCase() === "r") {
    e.preventDefault();
    learn.replay();
  } else if (e.key.toLowerCase() === "k") {
    e.preventDefault();
    learn.toggleTutorial();
  } else if (e.key.toLowerCase() === "j") {
    e.preventDefault();
    learn.seekTutorial(-5);
  } else if (e.key.toLowerCase() === "l") {
    e.preventDefault();
    learn.seekTutorial(5);
  } else if (e.key.toLowerCase() === "h") {
    e.preventDefault();
    learn.toggleHold();
  }
});

async function boot() {
  app.snap = await call<Snapshot>("snapshot");
  applyTheme(app.snap.themes, app.snap.settings);
  app.link = app.snap.link;
  app.state = app.snap.state;
  await onHub(onEvent as (e: HubEvent) => void);
  const launch = await invoke<{ hub: string | null; lesson: string | null }>("launch");
  let target = launch.hub ?? (app.snap.settings.reopen_last_hub && localStorage.getItem("handover.welcomed") === "1" ? app.snap.recent[0]?.base : null);
  // Once this Mac has been chosen as the hub, later launches bring that hub back before reconnecting. A remote
  // hub is never started or changed by this app.
  if (target && /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:|\/|$)/i.test(target)) {
    try {
      target = (await invoke<{ address: string }>("ensure_local_hub")).address;
    } catch {
      // connectHub owns the visible recovery screen and its plain-language error.
    }
  }
  if (app.link.link !== "idle") {
    await refreshMe();
    go({ name: "home" }, false);
  } else if (target) {
    go({ name: "home" }, false);
    const ok = await connectHub(target, true);
    if (ok) {
      go({ name: "home" }, false);
      if (launch.lesson) startLesson(launch.lesson, 0, true);
    }
  } else startOnboarding(false);
  render();
}

boot().catch((e) => {
  root.textContent = String(e);
});
