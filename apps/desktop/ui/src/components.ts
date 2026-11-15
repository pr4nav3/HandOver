// Pieces shared by the screens: covers, lesson cards, empty states, avatars, rings, sheets.

import { hubFileUrl, type CourseSummary } from "./api";
import { icons } from "./icons";
import { esc, html, raw, type Raw } from "./util";

/** "1:05" from seconds; "12 s" under a minute when `short`. */
export function mmss(seconds: number | null | undefined, short = false): string {
  if (seconds === null || seconds === undefined || !isFinite(seconds)) return "";
  if (short && seconds < 59.5) return `${Math.round(seconds)} s`;
  const t = Math.round(seconds);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = String(t % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export const STATUS_WORD: Record<string, string> = { draft: "Draft", published: "Published", unlisted: "Unlisted" };

export function cover(url: string | null | undefined, cls = "cover"): Raw {
  const src = hubFileUrl(url);
  return src
    ? html`<span class="${cls}"><img src="${src}" alt="" loading="lazy" /></span>`
    : html`<span class="${cls} empty-cover">${icons.film}</span>`;
}

/** A lesson card (section 5): cover, title, meta, a Draft or Unlisted badge for owners. */
export function lessonCard(c: CourseSummary, opts: { meta?: string; progress?: number; showStatus?: boolean } = {}): Raw {
  const meta = opts.meta ?? [c.steps ? `${c.steps} ${c.steps === 1 ? "step" : "steps"}` : "", mmss(c.duration)].filter(Boolean).join(", ");
  return html`<button class="lesson-card" data-go="${JSON.stringify({ name: "course", id: c.id })}">
    <span class="lesson-card-cover">
      ${cover(c.cover_url)}
      ${opts.showStatus && c.status !== "published" ? html`<span class="cover-badge">${STATUS_WORD[c.status]}</span>` : ""}
      ${opts.progress !== undefined ? html`<span class="cover-ring">${ring(opts.progress, 26)}</span>` : ""}
    </span>
    <span class="lesson-card-title">${c.title || c.id}</span>
    <span class="lesson-card-meta">${meta}${c.org ? html` <span class="dot-sep"></span> ${c.org.name}` : ""}</span>
  </button>`;
}

export function empty(symbol: Raw, title: string, message: string, action?: Raw): Raw {
  return html`<div class="empty-state">
    <span class="empty-symbol">${symbol}</span>
    <p class="empty-title">${title}</p>
    ${message ? html`<p class="empty-message">${message}</p>` : ""}
    ${action ?? ""}
  </div>`;
}

export function loading(text: string): Raw {
  return html`<div class="empty-state"><span class="spinner"></span><p class="empty-message">${text}</p></div>`;
}

/** Initials for an avatar. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] ?? "")).toUpperCase();
}

/** DESIGN 7.4 person hues. */
export const HUES = ["#4F78A8", "#3F8A86", "#7E62A0", "#A85E78", "#8C7E2E", "#5E6B7A", "#A8643E", "#5E8B62"];
export const HUE_NAMES = ["Blue", "Teal", "Violet", "Berry", "Olive", "Slate", "Rust", "Green"];

export function personAvatar(name: string, size = 36, hue?: number): Raw {
  const i = hue ?? [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % HUES.length;
  return html`<span class="avatar person" style="width:${size}px;height:${size}px;font-size:${Math.round(size * 0.4)}px;background:${HUES[i]}">${initials(name)}</span>`;
}

export function orgAvatar(name: string, size = 44): Raw {
  return html`<span class="avatar org" style="width:${size}px;height:${size}px;font-size:${Math.round(size * 0.42)}px;border-radius:${Math.round(size * 0.28)}px">${initials(name)}</span>`;
}

export const ORG_ROLE: Record<string, string> = { org_admin: "Admin", teacher: "Teacher", learner: "Member" };

/** A progress ring, `p` from 0 to 1. */
export function ring(p: number, size = 28, tone = "var(--accent)", label = ""): Raw {
  const stroke = size >= 90 ? 10 : 3.5;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, p));
  return raw(`<svg class="ring" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="var(--panel-2)" stroke-width="${stroke}"/>
    <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${tone}" stroke-width="${stroke}" stroke-linecap="round"
      stroke-dasharray="${(c * v).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
    ${label ? `<text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle">${esc(label)}</text>` : ""}
  </svg>`);
}

/** Five stars, read only or settable (`data-stars`). */
export function stars(value: number, settable = false, size = 16): Raw {
  return html`<span class="stars ${settable ? "settable" : ""}" role="${settable ? "radiogroup" : "img"}"
    aria-label="Rating, ${value} of 5 stars">${[1, 2, 3, 4, 5].map((n) =>
      settable
        ? html`<button type="button" class="star ${n <= value ? "on" : ""}" data-act="star" data-stars="${n}" aria-label="${n} stars"
            style="font-size:${size}px">${n <= value ? icons.starFill : icons.star}</button>`
        : html`<span class="star ${n <= Math.round(value) ? "on" : ""}" style="font-size:${size}px">${n <= Math.round(value) ? icons.starFill : icons.star}</span>`,
    )}</span>`;
}

/** Page header with a large title and optional trailing actions. */
export function pageHead(title: string, actions: Raw | string = "", sub = ""): Raw {
  return html`<header class="page-head">
    <div><h1>${title}</h1>${sub ? html`<p class="page-sub">${sub}</p>` : ""}</div>
    <div class="page-actions">${actions}</div>
  </header>`;
}

export function section(title: string, body: Raw, trailing: Raw | string = ""): Raw {
  return html`<section class="block">
    <div class="block-head"><h2>${title}</h2>${trailing}</div>
    ${body}
  </section>`;
}

// ---- Sheets: one modal at a time over the window ----

export interface Sheet {
  title: string;
  body: () => Raw;
  wide?: boolean;
  onAction?: (action: string, el: HTMLElement) => void;
  onSubmit?: (form: HTMLFormElement) => void;
  onInput?: (el: HTMLInputElement) => void;
  /** Runs when the sheet closes (not when another sheet replaces it). */
  onClose?: () => void;
}

let current: Sheet | null = null;

export function openSheet(s: Sheet) {
  current = s;
  drawSheet();
  const first = document.querySelector<HTMLInputElement>("#sheet input:not([type=hidden]), #sheet textarea");
  first?.focus();
}

export function closeSheet() {
  const closing = current;
  current = null;
  closing?.onClose?.();
  const el = document.getElementById("sheet")!;
  el.hidden = true;
  el.innerHTML = "";
}

export const sheetOpen = () => !!current;

/** Redraws the open sheet, keeping what was typed in its fields. */
export function drawSheet() {
  const el = document.getElementById("sheet")!;
  if (!current) return;
  const values = new Map<string, string>();
  el.querySelectorAll<HTMLInputElement>("input[name], textarea[name], select[name]").forEach((i) => {
    if (i.type !== "checkbox" && i.type !== "radio") values.set(i.name, i.value);
  });
  const focusName = (document.activeElement as HTMLInputElement | null)?.name;
  el.hidden = false;
  el.innerHTML = String(html`<div class="sheet-backdrop" data-sheet="close"></div>
    <div class="sheet ${current.wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${current.title}">
      <header class="sheet-head">
        <h2>${current.title}</h2>
        <button class="icon-button" data-sheet="close" title="Close (Esc)" aria-label="Close">${icons.close}</button>
      </header>
      <div class="sheet-body">${current.body()}</div>
    </div>`);
  el.querySelectorAll<HTMLInputElement>("input[name], textarea[name], select[name]").forEach((i) => {
    const v = values.get(i.name);
    if (v !== undefined && i.type !== "checkbox" && i.type !== "radio" && !i.dataset.fixed) i.value = v;
  });
  if (focusName) el.querySelector<HTMLInputElement>(`[name="${focusName}"]`)?.focus();
}

export function bindSheet() {
  const el = document.getElementById("sheet")!;
  el.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t.closest("[data-sheet=close]")) return closeSheet();
    const a = t.closest<HTMLElement>("[data-act]");
    if (a && current?.onAction) current.onAction(a.dataset.act!, a);
  });
  el.addEventListener("submit", (e) => {
    e.preventDefault();
    current?.onSubmit?.(e.target as HTMLFormElement);
  });
  el.addEventListener("input", (e) => current?.onInput?.(e.target as HTMLInputElement));
}
