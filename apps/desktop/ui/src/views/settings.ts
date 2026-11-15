// Settings, as a sheet over the window: appearance and theme (apps/design/THEMES.md, Theme
// picker), lesson sound and notices, the hub, and the keyboard.

import type { Catalog, LinkStatus, Look, Settings, Theme } from "../api";
import { html, modLabel, paint, type Raw } from "../util";
import { icons } from "../icons";
import { toast } from "../state";

export interface SettingsModel {
  open: boolean;
  settings: Settings;
  catalog: Catalog;
  link: LinkStatus;
  version: string;
  search: string;
  /** "Camera checks", "Simulated checks" or "Off: <reason>". */
  checks: string;
  /** `state.check_interval_s` from the hub, or null when the hub does not send it. */
  checkInterval: number | null;
  /** The chosen camera in words, or "Not chosen yet". */
  camera: string;
  /** "<name>, <role>" when signed in. */
  account: string;
}

export interface SettingsActions {
  close: () => void;
  set: (patch: Record<string, unknown>) => void;
  /** set_check_interval: for the whole hub session, every screen. */
  checkInterval: (seconds: number) => void;
  disconnect: () => void;
  search: (text: string) => void;
  otherHub: () => void;
  welcome: () => void;
  pair: () => void;
  camera: () => void;
}

/** Extra search words from the Theme picker section of THEMES.md. */
const KEYWORDS: Record<string, string> = {
  system: "auto automatic",
  night: "black oled amoled",
  highContrast: "accessibility contrast bold",
  mono: "black white grayscale",
  matte: "eink e-ink grayscale reader",
};

const LOOKS_WORDS = { system: "follows system", light: "always light", dark: "always dark" };
let wasOpen = false;
let returnFocus: HTMLElement | null = null;

const focusable = (root: HTMLElement) =>
  [...root.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')]
    .filter((node) => !node.hidden && node.getAttribute("aria-hidden") !== "true");

/** "Model sees every" choices, in seconds (CONTRACT.md 7, set_check_interval). */
export const CHECK_INTERVALS = [0.5, 1, 2];

/** The choice that matches the hub's value; a value set elsewhere picks the nearest. */
export function nearestInterval(v: number): number {
  return CHECK_INTERVALS.reduce((best, x) => (Math.abs(x - v) < Math.abs(best - v) ? x : best), CHECK_INTERVALS[0]);
}

const toggle = (key: string, label: string, on: boolean, detail: string) =>
  html`<label class="toggle-row">
    <span class="toggle-text"><span>${label}</span><span class="toggle-detail">${detail}</span></span>
    <input type="checkbox" role="switch" data-setting="${key}" ${on ? "checked" : ""} />
  </label>`;

/** A mini preview drawn with the look's own colors: paper, a raised card, ink, ink2, accent. */
const preview = (look: Look) =>
  html`<span class="tp" style="background:${look.bg}">
    <span class="tp-card" style="background:${look.panel};border-color:${look.border}">
      <span class="tp-ink" style="background:${look.text}"></span>
      <span class="tp-ink2" style="background:${look.muted}"></span>
      <span class="tp-pill" style="background:${look.accent}"></span>
    </span>
  </span>`;

function card(t: Theme, selected: boolean): Raw {
  const looks = [t.light, t.dark].filter((l): l is Look => !!l);
  const label = `${t.name}, ${t.detail}, ${LOOKS_WORDS[t.looks]}.${selected ? " Selected." : ""}`;
  return html`<button class="theme ${selected ? "on" : ""}" role="radio" aria-checked="${selected}" aria-label="${label}"
    data-theme="${t.id}">
    <span class="theme-preview">${looks.map(preview)}</span>
    <span class="theme-name">${t.name}</span>
    <span class="theme-detail">${t.detail}</span>
  </button>`;
}

/** "Model sees every 0.5 / 1 / 2 s", bound to the hub's check_interval_s. */
function interval(v: number): Raw {
  const on = nearestInterval(v);
  return html`<div class="interval-row">
    <span class="toggle-text"><span>Model sees every</span><span class="toggle-detail">A shorter gap catches steps sooner and makes more checks. Applies to everyone on this hub.</span></span>
    <div class="segmented" role="radiogroup" aria-label="Model sees every">
      ${CHECK_INTERVALS.map(
        (x) => html`<button role="radio" aria-checked="${x === on}" class="${x === on ? "on" : ""}" data-interval="${x}">${x} s</button>`,
      )}
    </div>
  </div>`;
}

export function renderSettings(el: HTMLElement, m: SettingsModel) {
  el.hidden = !m.open;
  if (!m.open) {
    if (wasOpen && returnFocus?.isConnected) {
      const restore = returnFocus;
      queueMicrotask(() => restore.focus());
    }
    wasOpen = false;
    returnFocus = null;
    return;
  }
  const opening = !wasOpen;
  if (opening) returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  wasOpen = true;
  const s = m.settings;
  const connected = m.link.link !== "idle";
  const q = m.search.trim().toLowerCase();
  const match = (t: Theme) =>
    !q || [t.name, t.detail, t.group, KEYWORDS[t.id] ?? ""].join(" ").toLowerCase().includes(q);
  const groups = m.catalog.groups
    .map((g) => ({ g, themes: m.catalog.themes.filter((t) => t.group === g && match(t)) }))
    .filter((x) => x.themes.length);
  // A repaint keeps the search field's focus and caret, and the sheet's scroll position.
  const searching = document.activeElement?.id === "theme-search";
  const caret = searching ? (document.activeElement as HTMLInputElement).selectionStart : null;
  const scroll = el.querySelector(".sheet-body")?.scrollTop ?? 0;
  paint(
    el,
    html`<div class="sheet-backdrop" data-close></div>
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header class="sheet-head">
          <h2 id="settings-title">Settings</h2>
          <button class="icon-button" data-close title="Close (Esc)" aria-label="Close">${icons.close}</button>
        </header>
        <div class="sheet-body">
          <section>
            <h3>Connection</h3>
            <dl class="hub-details">
              <div><dt>Mac</dt><dd><span class="dot ${m.link.link === "connected" ? "ok" : "warn"}"></span>${m.link.link === "connected" ? `Ready · ${m.link.label || m.link.hub}` : connected ? "Reconnecting" : "Not paired"}</dd></div>
              ${m.account ? html`<div><dt>Account</dt><dd>${m.account}</dd></div>` : ""}
              <div><dt>Camera</dt><dd>${m.camera}<button class="quiet small" data-camera>Change</button></dd></div>
            </dl>
            ${connected
              ? html`<div class="hub-actions"><button class="primary" data-pair>${icons.qr}<span>Pair iPhone</span></button></div>`
              : html`<div class="hub-actions"><button class="primary" data-other-hub>Connect to a Hub</button></div>`}
          </section>
          <section>
            <h3>Appearance</h3>
            <div class="segmented" role="radiogroup" aria-label="Appearance">
              ${(["system", "light", "dark"] as const).map(
                (a) => html`<button role="radio" aria-checked="${s.appearance === a}" class="${s.appearance === a ? "on" : ""}"
                  data-appearance="${a}">${a[0].toUpperCase() + a.slice(1)}</button>`,
              )}
            </div>
            <p class="hint">Themes with one look keep it.</p>
          </section>
          <section>
            <div class="theme-head">
              <h3>Theme</h3>
              <input class="theme-search" id="theme-search" type="search" placeholder="Search ${m.catalog.themes.length} themes"
                spellcheck="false" />
            </div>
            ${groups.length
              ? groups.map(
                  (x) => html`<div class="theme-group">
                    <h4>${x.g}</h4>
                    <div class="themes" role="radiogroup" aria-label="${x.g}">${x.themes.map((t) => card(t, t.id === s.theme))}</div>
                  </div>`,
                )
              : html`<p class="hint">No theme matches.</p>`}
          </section>
          <section>
            <h3>Lesson</h3>
            ${toggle("chime", "Chime when the camera confirms a step", s.chime, "A soft two note sound.")}
            ${toggle(
              "notifications",
              "Notify me in the background",
              s.notifications,
              "When a lesson finishes or checks go off while the window is hidden.",
            )}
          </section>
          <section>
            <details class="settings-advanced">
              <summary>Advanced hub settings</summary>
              ${connected
                ? html`<dl class="hub-details">
                  <div><dt>Address</dt><dd><code>${m.link.hub}</code><button class="quiet small" data-copy="${m.link.hub}">Copy</button></dd></div>
                  <div><dt>Status</dt><dd><span class="dot ${m.link.link === "connected" ? "ok" : "warn"}"></span>${m.link.link === "connected" ? "Connected" : "Reconnecting"}</dd></div>
                  <div><dt>Checks</dt><dd>${m.checks}</dd></div>
                </dl>
                ${m.checkInterval !== null ? interval(m.checkInterval) : ""}
                <div class="hub-actions"><button class="secondary" data-other-hub>Connect to Another Hub</button>
                  <button class="quiet danger-text" data-disconnect>Disconnect</button></div>`
                : html`<p class="muted">Not connected.</p>`}
              ${toggle("reopenLastHub", "Reconnect to the last hub at launch", s.reopen_last_hub, "Skips the connect screen.")}
            </details>
          </section>
          <section>
            <h3>Keyboard</h3>
            <dl class="keys">
              <div><dt>Next step</dt><dd>Right arrow or Space</dd></div>
              <div><dt>Previous step</dt><dd>Left arrow</dd></div>
              <div><dt>Hide a mistake note</dt><dd>Esc</dd></div>
              <div><dt>Lessons</dt><dd>${modLabel}L</dd></div>
              <div><dt>Connect to another hub</dt><dd>${modLabel}K</dd></div>
              <div><dt>Settings</dt><dd>${modLabel},</dd></div>
            </dl>
            <div class="hub-actions"><span class="hint">HandOver ${m.version}</span><button class="quiet small" data-welcome>Show Welcome Again</button></div>
            <p class="hint">The hub never saves your camera frames. Checks send frames to the hub's check service and nothing is kept.</p>
          </section>
        </div>
      </div>`,
  );
  const input = el.querySelector<HTMLInputElement>("#theme-search");
  if (input && input.value !== m.search) input.value = m.search;
  if (input && searching && document.activeElement !== input) {
    input.focus();
    if (caret !== null) input.setSelectionRange(caret, caret);
  }
  const body = el.querySelector(".sheet-body");
  if (body) body.scrollTop = scroll;
  if (opening) el.querySelector<HTMLElement>("[data-close]")?.focus();
}

export function bindSettings(el: HTMLElement, a: SettingsActions) {
  el.addEventListener("click", (e) => {
    const t = e.target as HTMLElement;
    if (t.closest("[data-close]")) return a.close();
    if (t.closest("[data-disconnect]")) return a.disconnect();
    if (t.closest("[data-other-hub]")) return a.otherHub();
    if (t.closest("[data-welcome]")) return a.welcome();
    if (t.closest("[data-pair]")) return a.pair();
    if (t.closest("[data-camera]")) return a.camera();
    const copy = t.closest<HTMLElement>("[data-copy]")?.dataset.copy;
    if (copy) return void navigator.clipboard.writeText(copy).then(() => toast("Copied address"), () => {});
    const seconds = t.closest<HTMLElement>("[data-interval]")?.dataset.interval;
    if (seconds) return a.checkInterval(Number(seconds));
    const appearance = t.closest<HTMLElement>("[data-appearance]")?.dataset.appearance;
    if (appearance) return a.set({ appearance });
    const theme = t.closest<HTMLElement>("[data-theme]")?.dataset.theme;
    if (theme) a.set({ theme });
  });
  el.addEventListener("change", (e) => {
    const t = e.target as HTMLInputElement;
    if (t.dataset.setting) a.set({ [t.dataset.setting]: t.checked });
  });
  el.addEventListener("input", (e) => {
    const t = e.target as HTMLInputElement;
    if (t.id === "theme-search") a.search(t.value);
  });
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const items = focusable(el);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
}
