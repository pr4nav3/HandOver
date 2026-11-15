// The window's state and navigation. Screens read `app` and call `go`, `rerender` and `toast`.

import type {
  CameraLink,
  CourseSummary,
  HubState,
  Invite,
  LinkStatus,
  Me,
  ProfileAnalytics,
  OrgSummary,
  Snapshot,
} from "./api";

export type CameraChoice = "computer" | "phone" | "glasses";

export type Route =
  | { name: "onboarding" }
  | { name: "home" }
  | { name: "browse"; filter?: string; org?: string; q?: string }
  | { name: "course"; id: string }
  | { name: "teach" }
  | { name: "processing"; job: string; id: string; title: string; route: string }
  | { name: "editor"; id: string }
  | { name: "orgs" }
  | { name: "org"; id: string }
  | { name: "profile" }
  | { name: "learn"; id: string };

export const app = {
  snap: null as unknown as Snapshot,
  link: { link: "idle", hub: "", label: "", attempt: 0, retry_in_ms: null, close_code: null } as LinkStatus,
  state: null as HubState | null,
  /** The link has been down past the grace period. */
  down: false,
  /** `/api/me`, or null on a hub without the library routes. */
  me: null as Me | null,
  /** Signed-in learner aggregates. undefined while loading, null when unavailable. */
  analytics: undefined as ProfileAnalytics | null | undefined,
  /** The hub serves the library, accounts and organizations routes. */
  library: false,
  orgs: [] as OrgSummary[],
  invites: [] as Invite[],
  route: { name: "home" } as Route,
  history: [] as Route[],
  settingsOpen: false,
  /** This computer's webcam link to the hub, while Learn sends it. */
  cameraLink: "off" as CameraLink,
};

let renderer: () => void = () => {};
export const setRenderer = (r: () => void) => (renderer = r);
export const rerender = () => renderer();

let onRoute: (r: Route) => void = () => {};
export const setRouteHook = (f: (r: Route) => void) => (onRoute = f);

/** Opens a screen. `push` keeps the current one for Back. */
export function go(route: Route, push = true) {
  if (push && JSON.stringify(route) !== JSON.stringify(app.route)) app.history.push(app.route);
  if (app.history.length > 30) app.history.shift();
  app.route = route;
  onRoute(route);
  rerender();
}

export function back() {
  const r = app.history.pop();
  go(r ?? { name: "home" }, false);
}

/** True when the hub has accounts and this device is signed in. */
export const signedIn = () => !!app.me?.user;

/** Section 24: who may make lessons. */
export function canTeach(): boolean {
  if (!app.library) return true;
  const u = app.me?.user;
  if (!u) return app.me?.auth === "optional";
  if (u.role === "owner" || u.role === "teacher") return true;
  return app.orgs.some((o) => o.role === "org_admin" || o.role === "teacher");
}

/** Opens Learn on a lesson, optionally at a step (set by main.ts). */
export const learn = { start: (_id: string, _step?: number, _restart?: boolean) => {} };

let toastTimer = 0;
export function toast(text: string) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = text;
  el.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => (el.hidden = true), 4000);
}

export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

// ---- This device's learning progress (section 4.3: kept locally on hubs without accounts) ----

export interface LocalProgress {
  id: string;
  title: string;
  step: number;
  total: number;
  done: boolean;
  updated: number;
  runs: number;
  /** How each step was finished in the latest run: camera, hand, skipped, or null. */
  how?: (string | null)[];
}

const progressKey = () => `handover.progress.${app.link.hub}`;

export function localProgress(): Record<string, LocalProgress> {
  try {
    return JSON.parse(localStorage.getItem(progressKey()) ?? "{}");
  } catch {
    return {};
  }
}

export function saveProgress(p: LocalProgress) {
  const all = localProgress();
  all[p.id] = p;
  localStorage.setItem(progressKey(), JSON.stringify(all));
}

/** Lessons in progress on this device, newest first. */
export function continueList(courses: CourseSummary[]): { course: CourseSummary; p: LocalProgress }[] {
  const all = localProgress();
  return courses
    .map((c) => ({ course: c, p: all[c.id] }))
    .filter((x) => x.p && !x.p.done && x.p.step > 0)
    .sort((a, b) => b.p.updated - a.p.updated);
}

// ---- Onboarding progress and preferences kept on this device ----

export const prefs = {
  get welcomed() {
    return localStorage.getItem("handover.welcomed") === "1";
  },
  set welcomed(v: boolean) {
    localStorage.setItem("handover.welcomed", v ? "1" : "0");
  },
  get homeFirst(): "learn" | "teach" | "both" {
    return (localStorage.getItem("handover.homeFirst") as "learn" | "teach" | "both") ?? "learn";
  },
  set homeFirst(v) {
    localStorage.setItem("handover.homeFirst", v);
  },
  /** How HandOver sees the learner's hands, remembered on this device. */
  get camera(): CameraChoice | null {
    const v = localStorage.getItem("handover.camera");
    return v === "computer" || v === "phone" || v === "glasses" ? v : null;
  },
  set camera(v: CameraChoice | null) {
    if (v) localStorage.setItem("handover.camera", v);
    else localStorage.removeItem("handover.camera");
  },
  /** The "How it works" card on Home was closed. */
  get howDismissed(): boolean {
    return localStorage.getItem("handover.howDismissed") === "1";
  },
  set howDismissed(v: boolean) {
    localStorage.setItem("handover.howDismissed", v ? "1" : "0");
  },
  get avatarHue(): number {
    return Number(localStorage.getItem("handover.avatarHue") ?? "0");
  },
  set avatarHue(v: number) {
    localStorage.setItem("handover.avatarHue", String(v));
  },
};
