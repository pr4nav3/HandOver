// The bridge to the Rust core. Every request goes through one Tauri command, `call(cmd, args)`,
// and the core pushes hub events on the `hub` channel. Types mirror core/src (protocol.rs,
// socket.rs, store.rs, themes.rs) and CONTRACT.md.

interface TauriGlobal {
  core: { invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> };
  event: { listen: (name: string, cb: (e: { payload: unknown }) => void) => Promise<() => void> };
}

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

// Outside the app (a browser during development) the same calls go to the development bridge
// (core/src/bin/devserver.rs), which answers with the same engine.
const inApp = typeof window !== "undefined" && !!window.__TAURI__;

async function bridge(path: string, args: Record<string, unknown>): Promise<string> {
  const r = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  const text = await r.text();
  if (!r.ok) throw JSON.parse(text).error ?? `${path} failed`;
  return text;
}

export async function call<T = unknown>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
  const text = inApp ? ((await window.__TAURI__!.core.invoke("call", { cmd, args })) as string) : await bridge(cmd, args);
  return JSON.parse(text) as T;
}

/** The shell's own commands (app/src/main.rs): `launch` and `notify`. */
export async function invoke<T = unknown>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
  if (inApp) return (await window.__TAURI__!.core.invoke(cmd, args)) as T;
  return JSON.parse(await bridge(`__${cmd}`, args)) as T;
}

/** One webcam JPEG for the hub, as raw bytes (app/src/main.rs `camera_frame`). */
export async function sendCameraFrame(jpeg: Uint8Array): Promise<void> {
  if (inApp) {
    await window.__TAURI__!.core.invoke("camera_frame", jpeg as unknown as Record<string, unknown>);
    return;
  }
  const r = await fetch("/api/__camera_frame", { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: jpeg as BodyInit });
  if (!r.ok) throw new Error("camera frame failed");
}

/** What a phone needs to pair with this hub (core/src/phone.rs). All null when this computer
 *  has no address on the local network. */
export interface Pairing {
  hub: string | null;
  label: string | null;
  link: string | null;
  svg: string | null;
  /** Short-lived QR claim. The phone approves it; this Mac redeems it for its own token. */
  handoff?: string | null;
}

/** This computer's webcam link to the hub (core/src/camera.rs). */
export type CameraLink = "connecting" | "sending" | "standby" | "reconnecting" | "replaced" | "off";

export async function onHub(cb: (e: HubEvent) => void) {
  if (inApp) return window.__TAURI__!.event.listen("hub", (e) => cb(e.payload as HubEvent));
  const source = new EventSource("/events");
  source.onmessage = (e) => cb(JSON.parse(e.data) as HubEvent);
  return () => source.close();
}

/** Lesson files and the live frame come over the app's own `hub` scheme (app/src/main.rs). */
export const HUB_ORIGIN = !inApp
  ? "/hub"
  : navigator.userAgent.includes("Windows")
    ? "http://hub.localhost"
    : "hub://localhost";

/** URL of a file inside a lesson folder. `rev` busts the cache after a recut (CONTRACT.md 5). */
export const lessonUrl = (id: string, rel: string, rev?: number) =>
  `${HUB_ORIGIN}/lessons/${encodeURIComponent(id)}/${rel.replace(/^\/+/, "")}${rev ? `?v=${rev}` : ""}`;

export const frameUrl = (n: number) => `${HUB_ORIGIN}/__frame?n=${n}`;

export type Link = "connecting" | "connected" | "reconnecting" | "replaced" | "idle";

export interface LinkStatus {
  link: Link;
  hub: string;
  label: string;
  attempt: number;
  retry_in_ms: number | null;
  close_code: number | null;
}

export type Status = "watching" | "checking" | "verified" | "manual" | "done" | "unknown";

export interface LastCheck {
  done: "yes" | "no" | "unsure";
  confidence: number;
  latency_ms: number;
  reason?: string | null;
}

export interface Camera {
  name: string;
  platform: string;
  source: string;
}

export interface Mistake {
  step: number;
  kind: "behind" | "ahead" | "unknown";
  looks_like: number;
  message: string;
  confidence: number;
  source: string;
}

export interface HubState {
  lesson_id: string | null;
  rev: number;
  step: number;
  total: number;
  status: Status;
  last_check: LastCheck | null;
  camera_connected: boolean;
  /** Absent from older hubs. */
  camera?: Camera | null;
  check_offline: boolean;
  check_offline_reason: string | null;
  /** Absent from older hubs; only an explicit value replaces the one on screen. */
  mistake?: Mistake | null;
  /** Seconds between frames offered to the vision model (Revision 6). Absent from older hubs. */
  check_interval_s?: number;
  /** Live frames per second the hub forwards, at most (Revision 6). Absent from older hubs. */
  ui_fps?: number;
  /** Derived by the core. */
  position: number;
  offline_label: string | null;
  check_reason: string | null;
  /** A learner explicitly paused camera auto-advance on this step. Absent from older hubs. */
  held?: boolean;
  /** Lightweight live feedback from frame intake and the checker. Absent from older hubs. */
  observation?: {
    phase: "idle" | "waiting_camera" | "waiting_frame" | "moving" | "settling" | "checking" | "watching" | "verified" | string;
    frame_age_ms: number | null;
    camera_fps: number | null;
  } | null;
}

export interface Advance {
  from: number;
  to: number;
  reason: "camera" | "button" | "voice" | "other";
}

export type HubEvent =
  | { kind: "link"; link: LinkStatus }
  | { kind: "state"; state: HubState }
  | { kind: "advance"; advance: Advance }
  | { kind: "mistake"; mistake: Mistake }
  | { kind: "error"; message: string }
  | { kind: "frame"; n: number }
  | { kind: "camera"; camera: CameraLink };

export interface LessonSummary {
  id: string;
  title: string;
  steps: number;
  cover_url?: string | null;
}

export interface Step {
  n: number;
  title: string;
  start: string;
  end: string;
  clip: string;
  captions: string;
  ref_frame: string;
  check_type: "camera" | "manual" | "other";
  check_question: string | null;
  common_mistake: string;
}

export interface Lesson {
  id: string;
  title: string;
  description?: string;
  production?: { output?: { cover?: string } };
  steps: Step[];
  safety: string[];
  tools: string[];
}

export interface RecentHub {
  base: string;
  label: string;
  last_used: number;
}

export interface Settings {
  theme: string;
  appearance: "system" | "light" | "dark";
  reopen_last_hub: boolean;
  chime: boolean;
  notifications: boolean;
}

export type Look = Record<string, string>;

export interface Theme {
  id: string;
  name: string;
  group: string;
  detail: string;
  /** `system`: two looks, picked by the Appearance setting. `light` or `dark`: one look, kept. */
  looks: "system" | "light" | "dark";
  light: Look | null;
  dark: Look | null;
}

export interface Catalog {
  source: string;
  groups: string[];
  themes: Theme[];
}

export interface Snapshot {
  version: string;
  link: LinkStatus;
  state: HubState | null;
  recent: RecentHub[];
  settings: Settings;
  themes: Catalog;
}

export interface Connected {
  hub: string;
  label: string;
  lessons: LessonSummary[];
  recent: RecentHub[];
}

/** "01:05" or "1:02:03" to seconds. */
export function toSeconds(ts: string): number {
  return ts
    .split(":")
    .map(Number)
    .reduce((acc, part) => acc * 60 + (Number.isFinite(part) ? part : 0), 0);
}

// ---- Library, accounts and organizations (server/docs/library.md) ----

/** A hub error with its status and the hub's own words. */
export class HubError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

interface ApiAnswer<T> {
  status: number;
  ok: boolean;
  data: T;
}

/** Calls a hub route through the core (which adds this device's token). Throws HubError. */
export async function hub<T = unknown>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  opts: { query?: Record<string, unknown>; body?: unknown } = {},
): Promise<T> {
  const r = await call<ApiAnswer<T>>("api", { method, path, query: opts.query ?? null, body: opts.body ?? null });
  if (!r.ok) {
    const d = r.data as unknown as { detail?: unknown } | string;
    const detail = typeof d === "string" ? d : typeof d?.detail === "string" ? d.detail : `The hub answered ${r.status}.`;
    throw new HubError(r.status, detail || `The hub answered ${r.status}.`);
  }
  return r.data;
}

export interface Picked {
  path: string;
  name: string;
  size: number;
}

export const pickVideo = () => invoke<Picked | null>("pick_video");

export async function uploadVideo(args: { path: string; title: string; route: string; org_id?: string; description?: string }) {
  const r = await call<ApiAnswer<{ job: string; id: string }>>("upload", args);
  if (!r.ok) {
    const d = r.data as unknown as { detail?: string };
    throw new HubError(r.status, d?.detail ?? `The hub answered ${r.status}.`);
  }
  return r.data;
}

export type Role = "owner" | "teacher" | "learner";

export interface User {
  id: string;
  name: string;
  role: Role;
  created?: string;
}

export interface Me {
  user: User | null;
  auth: "optional" | "required";
  setup_needed: boolean;
  can_create_org?: boolean;
}

/** Aggregate-only stats for the signed-in person. Never contains raw frames, event text or identifiers. */
export interface ProfileAnalytics {
  known: boolean;
  reason: string | null;
  runs: number;
  completed_runs?: number;
  completion_rate?: number | null;
  courses_completed?: number;
  minutes_practiced?: number;
  active_days?: number;
  current_streak_days?: number;
  checks?: number;
  check_pass_rate?: number | null;
  check_errors?: number;
  avg_check_latency_ms?: number | null;
  camera_verified_steps?: number;
  manual_steps?: number;
  mistakes_caught?: number;
  replays?: number;
  interruptions?: number;
  camera_sources?: string[];
  median_camera_ready_ms?: number | null;
  time_against_expert?: number | null;
  timed_steps?: number;
}

export interface OrgRef {
  id: string;
  name: string;
  slug: string;
}

export interface CourseSummary {
  id: string;
  title: string;
  cover_url: string | null;
  steps: number;
  duration: number | null;
  status: "draft" | "published" | "unlisted";
  visibility: "only_me" | "shared" | "org" | "everyone";
  owner: { id: string; name: string } | null;
  org: OrgRef | null;
  updated: string;
  legacy: boolean;
  version: number;
  progress: { runs?: number; completed?: number; last_steps_done?: number; total?: number } | null;
}

export interface Course extends CourseSummary {
  description: string;
  access: { user_id: string; name: string; role: string }[];
  created: string | null;
  published_at: string | null;
}

export interface Permissions {
  can_view: boolean;
  can_edit: boolean;
  can_publish: boolean;
  can_unpublish: boolean;
  can_manage: boolean;
  can_transfer: boolean;
  can_see_insights: boolean;
  can_rate: boolean;
}

export interface FullLesson extends Lesson {
  video?: string;
}

export interface CourseDetail {
  course: Course;
  lesson: FullLesson;
  permissions: Permissions;
  history: { undo: number; redo: number } | null;
}

export interface Ratings {
  average: number | null;
  count: number;
  distribution: Record<string, number>;
  mine: { stars: number; comment?: string } | null;
}

export type OrgRole = "org_admin" | "teacher" | "learner";

export interface OrgSummary extends OrgRef {
  created: string;
  members: number | Member[];
  role: OrgRole | null;
}

export interface Member {
  user_id: string;
  name: string;
  role: OrgRole;
  joined: string;
}

export interface Invite {
  id: string;
  kind: "code" | "user";
  role: OrgRole;
  created: string;
  created_by?: string;
  expires: string | null;
  max_uses?: number | null;
  uses?: number;
  user?: { id: string; name: string } | string;
  code?: string;
  org?: OrgRef;
}

export interface Org extends OrgRef {
  created: string;
  members: Member[];
  role: OrgRole | null;
  owner: { id: string; name: string } | null;
  courses: CourseSummary[];
  invites: Invite[] | null;
}

export interface Job {
  status: "queued" | "normalizing" | "extracting" | "cutting" | "done" | "error";
  message: string;
  id: string;
}

/** Cover and frame URLs from the hub (`/lessons/...`) as the app's own scheme. */
export const hubFileUrl = (path: string | null | undefined) =>
  path && path.startsWith("/lessons/") ? `${HUB_ORIGIN}${path}` : "";
