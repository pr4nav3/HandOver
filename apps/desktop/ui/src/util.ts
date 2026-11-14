// Small helpers: escaping, a tagged template for markup, and times in plain words.

const ESC: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escapes text for HTML. Every value from the hub goes through this before it is drawn. */
export function esc(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
}

/** Markup that is already safe. */
export class Raw {
  constructor(public html: string) {}
  toString() {
    return this.html;
  }
}
export const raw = (s: string) => new Raw(s);

/** A tagged template that escapes every value unless it is already `Raw`. */
export function html(strings: TemplateStringsArray, ...values: unknown[]): Raw {
  let out = "";
  strings.forEach((s, i) => {
    out += s;
    if (i < values.length) {
      const v = values[i];
      if (v instanceof Raw) out += v.html;
      else if (Array.isArray(v)) out += v.map((x) => (x instanceof Raw ? x.html : esc(x))).join("");
      else if (v === null || v === undefined || v === false) out += "";
      else out += esc(v);
    }
  });
  return new Raw(out);
}

/** Sets innerHTML only when it changed. A focused field (by id) keeps its focus, value and
 *  caret, and scrolled areas (`.scroll`, by id or class) keep their position. */
const last = new WeakMap<Element, string>();
export function paint(el: HTMLElement, markup: Raw | string) {
  const text = String(markup);
  if (last.get(el) === text) return;
  last.set(el, text);
  const active = document.activeElement as HTMLInputElement | null;
  const focus =
    active && active.id && el.contains(active) && "value" in active
      ? { id: active.id, value: active.value, start: active.selectionStart, end: active.selectionEnd }
      : null;
  // Typed text in other fields with ids survives too (a template leaves them empty).
  const typed = new Map<string, string>();
  el.querySelectorAll<HTMLInputElement>("input[id], textarea[id]").forEach((i) => {
    if (i.type !== "checkbox" && i.type !== "radio" && i.value) typed.set(i.id, i.value);
  });
  const scrolls = new Map<string, number>();
  el.querySelectorAll<HTMLElement>(".scroll").forEach((s, i) => scrolls.set(s.id || `${s.className}#${i}`, s.scrollTop));
  el.innerHTML = text;
  typed.forEach((v, id) => {
    const i = el.querySelector<HTMLInputElement>(`#${CSS.escape(id)}`);
    if (i && !i.value) i.value = v;
  });
  el.querySelectorAll<HTMLElement>(".scroll").forEach((s, i) => {
    const top = scrolls.get(s.id || `${s.className}#${i}`);
    if (top !== undefined) s.scrollTop = top;
  });
  if (focus) {
    const f = document.getElementById(focus.id) as HTMLInputElement | null;
    if (f && "value" in f) {
      f.value = focus.value;
      f.focus();
      try {
        f.setSelectionRange(focus.start, focus.end);
      } catch {
        // Some input types have no selection.
      }
    }
  }
}

/** "just now", "4 min ago", "2 h ago", "3 days ago". */
export function ago(unixSeconds: number): string {
  const s = Date.now() / 1000 - unixSeconds;
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

/** 75000 ms to "1:15", 3725000 ms to "1:02:05". */
export function duration(ms: number): string {
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** True while typing in a field, so shortcuts leave the keys alone. */
export function typing(e: KeyboardEvent): boolean {
  const t = e.target;
  return t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement;
}

/** Ctrl on Windows and Linux, Command on macOS. */
export const isMac = navigator.userAgent.includes("Mac");
export const modKey = (e: KeyboardEvent) => (isMac ? e.metaKey : e.ctrlKey);
export const modLabel = isMac ? "⌘" : "Ctrl+";
