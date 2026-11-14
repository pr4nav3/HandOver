// Puts a theme from the core's catalog (core/src/themes.rs, read from apps/design/THEMES.md) on
// :root as CSS custom properties. A theme with two looks shows the one the Appearance setting
// picks (System follows the computer, live); a theme with one look keeps it. With the system's
// Increase Contrast on, the High Contrast values are used in the current appearance without
// changing the stored choice (THEMES.md, Catalog).

import type { Catalog, Look, Settings, Theme } from "./api";

const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const contrastQuery = window.matchMedia("(prefers-contrast: more)");
let current: { catalog: Catalog; settings: Settings } | null = null;

/** Which look a theme shows under the given appearance. */
export function lookOf(theme: Theme, appearance: Settings["appearance"]): { dark: boolean; look: Look } | null {
  if (theme.looks === "light" && theme.light) return { dark: false, look: theme.light };
  if (theme.looks === "dark" && theme.dark) return { dark: true, look: theme.dark };
  const dark = appearance === "dark" || (appearance === "system" && darkQuery.matches);
  const look = dark ? theme.dark : theme.light;
  return look ? { dark, look } : null;
}

export function applyTheme(catalog: Catalog, settings: Settings) {
  current = { catalog, settings };
  let theme = catalog.themes.find((t) => t.id === settings.theme) ?? catalog.themes[0];
  if (!theme) return;
  const chosen = lookOf(theme, settings.appearance);
  if (!chosen) return;
  let look = chosen.look;
  const hc = contrastQuery.matches ? catalog.themes.find((t) => t.id === "highContrast") : undefined;
  if (hc) {
    const l = chosen.dark ? hc.dark : hc.light;
    if (l) look = l;
  }
  const root = document.documentElement;
  for (const [k, v] of Object.entries(look)) root.style.setProperty(`--${k}`, v);
  root.dataset.appearance = chosen.dark ? "dark" : "light";
  root.style.colorScheme = chosen.dark ? "dark" : "light";
  // Grain: a fine noise over the paper, strength from the theme (0 = none).
  const grain = Number(look.grain) || 0;
  root.style.setProperty("--grain-opacity", String(Math.min(0.2, grain * 3)));
  root.classList.toggle("grain", grain > 0);
}

const reapply = () => current && applyTheme(current.catalog, current.settings);
darkQuery.addEventListener("change", reapply);
contrastQuery.addEventListener("change", reapply);
