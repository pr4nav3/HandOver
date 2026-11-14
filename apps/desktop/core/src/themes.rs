//! The theme catalog, read from the shared `apps/design/THEMES.md` (one catalog for every
//! HandOver app). `build.rs` embeds that file at compile time; without it the core ships one
//! built-in theme with a light and a dark look that match the web app.
//!
//! THEMES.md has a Catalog table (id, name, group, looks, one line) and one section per theme
//! with a Role table: `paper`, `raised`, `well`, `ink`, `ink2`, `ink3`, `line`, `lineStrong`,
//! `accent`, `onAccent`, `accentInk`, the tones `good`, `caution`, `bad`, `idle`, and grain. A
//! theme either has two looks (follows the system, columns Light and Dark) or keeps one look
//! (column Value). The rules section's defaults fill any role a theme leaves out.

use serde::Serialize;
use std::collections::BTreeMap;

/// THEMES.md as it was at build time, or empty when the file did not exist.
const EMBEDDED: &str = include_str!(concat!(env!("OUT_DIR"), "/THEMES.md"));

/// The CSS custom properties the UI reads (ui/src/styles/app.css). Every look sets all of them.
pub const TOKENS: &[&str] = &[
    "bg",
    "panel",
    "panel-2",
    "border",
    "border-strong",
    "text",
    "muted",
    "faint",
    "accent",
    "on-accent",
    "accent-ink",
    "green",
    "amber",
    "red",
    "grey",
    "grain",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Looks {
    /// Two looks; the Appearance setting (or the computer) picks one.
    System,
    /// Always the light look.
    Light,
    /// Always the dark look.
    Dark,
}

pub type Look = BTreeMap<String, String>;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Theme {
    /// Stored id; never changes.
    pub id: String,
    pub name: String,
    /// Picker section: Classic, Grain, Color or Mono.
    pub group: String,
    /// The one line under the name in the picker.
    pub detail: String,
    pub looks: Looks,
    /// Token name (without `--`) to CSS value. Present when the theme has that look.
    pub light: Option<Look>,
    pub dark: Option<Look>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Catalog {
    /// Where the themes came from: `THEMES.md` or `built-in`.
    pub source: &'static str,
    /// Picker sections in order.
    pub groups: Vec<String>,
    pub themes: Vec<Theme>,
}

impl Catalog {
    pub fn get(&self, id: &str) -> Option<&Theme> {
        self.themes.iter().find(|t| t.id == id)
    }
}

/// The catalog the app uses: THEMES.md when it was there at build time and has usable themes,
/// else the built-in theme. `system` (the default) is always present and first.
pub fn catalog() -> Catalog {
    catalog_from(EMBEDDED)
}

pub fn catalog_from(markdown: &str) -> Catalog {
    let mut themes = parse_markdown(markdown);
    let source = if themes.is_empty() { "built-in" } else { "THEMES.md" };
    if !themes.iter().any(|t| t.id == "system") {
        themes.insert(0, builtin());
    }
    if let Some(i) = themes.iter().position(|t| t.id == "system") {
        let t = themes.remove(i);
        themes.insert(0, t);
    }
    let mut groups: Vec<String> = Vec::new();
    for t in &themes {
        if !groups.contains(&t.group) {
            groups.push(t.group.clone());
        }
    }
    Catalog { source, groups, themes }
}

/// The web app's dark palette and a light counterpart, used when THEMES.md is missing.
pub fn builtin() -> Theme {
    let look = |pairs: &[(&str, &str)]| -> Look { pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect() };
    Theme {
        id: "system".into(),
        name: "Default".into(),
        group: "Classic".into(),
        detail: "Follows the system".into(),
        looks: Looks::System,
        light: Some(look(&[
            ("bg", "#f5f5f7"),
            ("panel", "#ffffff"),
            ("panel-2", "#f0f0f2"),
            ("border", "rgba(0, 0, 0, 0.08)"),
            ("border-strong", "rgba(0, 0, 0, 0.16)"),
            ("text", "#1d1d1f"),
            ("muted", "rgba(29, 29, 31, 0.7)"),
            ("faint", "rgba(29, 29, 31, 0.5)"),
            ("accent", "#1d1d1f"),
            ("on-accent", "#ffffff"),
            ("accent-ink", "#1d1d1f"),
            ("green", "#186629"),
            ("amber", "#934000"),
            ("red", "#b80011"),
            ("grey", "#6e6e73"),
            ("grain", "0"),
        ])),
        dark: Some(look(&[
            ("bg", "#0b0b0c"),
            ("panel", "#141416"),
            ("panel-2", "#1b1b1e"),
            ("border", "rgba(255, 255, 255, 0.08)"),
            ("border-strong", "rgba(255, 255, 255, 0.14)"),
            ("text", "#f5f5f7"),
            ("muted", "rgba(235, 235, 245, 0.56)"),
            ("faint", "rgba(235, 235, 245, 0.32)"),
            ("accent", "#f5f5f7"),
            ("on-accent", "#000000"),
            ("accent-ink", "#f5f5f7"),
            ("green", "#30d158"),
            ("amber", "#ff9f0a"),
            ("red", "#ff6961"),
            ("grey", "#8e8e93"),
            ("grain", "0"),
        ])),
    }
}

// ---- Reading THEMES.md ----

fn is_row(l: &str) -> bool {
    let l = l.trim();
    l.len() > 1 && l.starts_with('|') && l.ends_with('|')
}

fn is_rule(l: &str) -> bool {
    is_row(l) && l.trim().chars().all(|c| matches!(c, '|' | '-' | ':' | ' '))
}

fn cells(l: &str) -> Vec<String> {
    let l = l.trim();
    l[1..l.len() - 1].split('|').map(|c| c.trim().to_string()).collect()
}

/// Reads the table that starts at `lines[i]` (header, rule, rows). Returns the header, the rows
/// and the index after the table.
fn table(lines: &[&str], i: usize) -> Option<(Vec<String>, Vec<Vec<String>>, usize)> {
    if !(is_row(lines[i]) && i + 1 < lines.len() && is_rule(lines[i + 1])) {
        return None;
    }
    let head = cells(lines[i]);
    let mut rows = Vec::new();
    let mut j = i + 2;
    while j < lines.len() && is_row(lines[j]) {
        rows.push(cells(lines[j]));
        j += 1;
    }
    Some((head, rows, j))
}

fn unquote(s: &str) -> String {
    s.trim().trim_matches('`').trim().to_string()
}

/// `#RRGGBB` (or `#RGB`) to its channels.
fn rgb(hex: &str) -> Option<(u8, u8, u8)> {
    let h = hex.trim().strip_prefix('#')?;
    let full: String = match h.len() {
        3 => h.chars().flat_map(|c| [c, c]).collect(),
        6 => h.to_string(),
        _ => return None,
    };
    let v = u32::from_str_radix(&full, 16).ok()?;
    Some(((v >> 16) as u8, (v >> 8) as u8, v as u8))
}

fn rgba(hex: &str, alpha_percent: f64) -> Option<String> {
    let (r, g, b) = rgb(hex)?;
    let a = (alpha_percent / 100.0).clamp(0.0, 1.0);
    Some(format!("rgba({r}, {g}, {b}, {})", trim_float(a)))
}

fn trim_float(v: f64) -> String {
    let s = format!("{v:.3}");
    s.trim_end_matches('0').trim_end_matches('.').to_string()
}

/// One cell of a Role table, split for rows that name several roles.
#[derive(Debug, Clone, PartialEq)]
enum Cell {
    Hex(String),
    /// A percentage, with an optional base word (`ink`, `white`).
    Alpha(f64, Option<String>),
    Number(f64),
    /// `default`, `defaults`, `none` and anything else that sets nothing.
    Skip,
}

fn parse_parts(cell: &str) -> Vec<Cell> {
    let mut base: Option<String> = None;
    cell.split(',')
        .map(|part| {
            let p = unquote(part);
            let lower = p.to_ascii_lowercase();
            if rgb(&p).is_some() {
                return Cell::Hex(p);
            }
            if let Some(pct) = lower.strip_suffix('%') {
                // "ink at 70", "white 12", "70": the base word carries to later parts.
                let mut words = pct.split_whitespace().collect::<Vec<_>>();
                let num = words.pop().and_then(|n| n.parse::<f64>().ok());
                if let Some(w) = words.first() {
                    base = Some(w.to_string());
                }
                return num.map(|n| Cell::Alpha(n, base.clone())).unwrap_or(Cell::Skip);
            }
            if let Ok(n) = lower.split_whitespace().next().unwrap_or("").parse::<f64>() {
                return Cell::Number(n);
            }
            Cell::Skip
        })
        .collect()
}

/// The role names in a Role table's first cell: "line, lineStrong" gives two.
fn roles(cell: &str) -> Vec<String> {
    cell.split(',').map(|r| r.trim().to_string()).filter(|r| !r.is_empty()).collect()
}

/// What one look's Role column says, before defaults: role to cell.
type Raw = BTreeMap<String, Cell>;

fn raw_look(rows: &[Vec<String>], col: usize) -> Raw {
    let mut out = Raw::new();
    for row in rows {
        let (Some(names), Some(value)) = (row.first(), row.get(col)) else { continue };
        let names = roles(names);
        let parts = parse_parts(value);
        for (i, name) in names.iter().enumerate() {
            // One value for several roles applies to all of them ("accent, accentInk | #8AA8FF").
            let cell = parts.get(i).or(if parts.len() == 1 { parts.first() } else { None });
            if let Some(c) = cell.filter(|c| **c != Cell::Skip) {
                out.insert(name.clone(), c.clone());
            }
        }
    }
    out
}

/// Turns one look's roles into the UI's tokens, with the THEMES.md defaults for that look.
fn finish_look(raw: &Raw, dark: bool) -> Option<Look> {
    let hex = |k: &str| match raw.get(k) {
        Some(Cell::Hex(h)) => Some(h.to_ascii_lowercase()),
        _ => None,
    };
    let paper = hex("paper")?;
    let ink = hex("ink")?;
    let raised = hex("raised").unwrap_or_else(|| paper.clone());
    let well = hex("well").unwrap_or_else(|| raised.clone());
    let alpha_of = |k: &str, default: f64, default_base: &str| -> String {
        let (pct, base) = match raw.get(k) {
            Some(Cell::Alpha(p, b)) => (*p, b.clone()),
            Some(Cell::Hex(h)) => return h.to_ascii_lowercase(),
            _ => (default, None),
        };
        let base_hex = match base.as_deref().unwrap_or(default_base) {
            "white" => "#ffffff".to_string(),
            "black" => "#000000".to_string(),
            _ => ink.clone(),
        };
        rgba(&base_hex, pct).unwrap_or_default()
    };
    let line_base = if dark { "white" } else { "ink" };
    let (d_good, d_caution, d_bad, d_idle) =
        if dark { ("#30d158", "#ff9f0a", "#ff6961", "#8e8e93") } else { ("#186629", "#934000", "#b80011", "#6e6e73") };
    let accent = hex("accent").unwrap_or_else(|| ink.clone());
    let grain = match raw.get("grain amount") {
        Some(Cell::Number(n)) => trim_float(*n),
        _ => "0".into(),
    };
    let mut look = Look::new();
    let mut put = |k: &str, v: String| {
        look.insert(k.to_string(), v);
    };
    put("bg", paper);
    put("panel", raised);
    put("panel-2", well);
    put("text", ink.clone());
    put("muted", alpha_of("ink2", if dark { 68.0 } else { 70.0 }, "ink"));
    put("faint", alpha_of("ink3", if dark { 46.0 } else { 50.0 }, "ink"));
    put("border", alpha_of("line", if dark { 10.0 } else { 9.0 }, line_base));
    put("border-strong", alpha_of("lineStrong", if dark { 17.0 } else { 16.0 }, line_base));
    put("accent-ink", hex("accentInk").unwrap_or_else(|| accent.clone()));
    put("accent", accent);
    put("on-accent", hex("onAccent").unwrap_or_else(|| if dark { "#000000".into() } else { "#ffffff".into() }));
    put("green", hex("good").unwrap_or_else(|| d_good.into()));
    put("amber", hex("caution").unwrap_or_else(|| d_caution.into()));
    put("red", hex("bad").unwrap_or_else(|| d_bad.into()));
    put("grey", hex("idle").unwrap_or_else(|| d_idle.into()));
    put("grain", grain);
    Some(look)
}

struct Entry {
    name: String,
    group: String,
    detail: String,
    looks: Looks,
}

fn looks_of(text: &str) -> Looks {
    let t = text.to_ascii_lowercase();
    if t.contains("always dark") || t == "dark" {
        Looks::Dark
    } else if t.contains("always light") || t == "light" {
        Looks::Light
    } else {
        Looks::System
    }
}

/// The id in a theme heading: "### Night (`night`), always dark".
fn heading_id(line: &str) -> Option<String> {
    let rest = line.strip_prefix("### ")?;
    let start = rest.find("(`")? + 2;
    let end = start + rest[start..].find("`)")?;
    Some(rest[start..end].to_string())
}

/// Reads every theme in THEMES.md that has a catalog row and a Role table with at least paper
/// and ink. Themes come out in catalog order.
pub fn parse_markdown(markdown: &str) -> Vec<Theme> {
    let lines: Vec<&str> = markdown.lines().collect();
    let mut order: Vec<String> = Vec::new();
    let mut entries: BTreeMap<String, Entry> = BTreeMap::new();
    let mut sections: BTreeMap<String, (Vec<String>, Vec<Vec<String>>)> = BTreeMap::new();
    let mut current: Option<String> = None;
    let mut i = 0;
    while i < lines.len() {
        let line = lines[i].trim();
        if line.starts_with('#') {
            current = heading_id(line);
            i += 1;
            continue;
        }
        let Some((head, rows, next)) = table(&lines, i) else {
            i += 1;
            continue;
        };
        i = next;
        let lower: Vec<String> = head.iter().map(|h| h.to_ascii_lowercase()).collect();
        let col = |name: &str| lower.iter().position(|h| h == name);
        if let (Some(id_c), Some(name_c)) = (col("id"), col("name")) {
            for row in &rows {
                let get = |c: Option<usize>| c.and_then(|c| row.get(c)).map(|v| unquote(v)).unwrap_or_default();
                let id = get(Some(id_c));
                if id.is_empty() || entries.contains_key(&id) {
                    continue;
                }
                let detail_c = lower.iter().position(|h| h.starts_with("one line") || h == "detail");
                entries.insert(
                    id.clone(),
                    Entry {
                        name: get(Some(name_c)),
                        group: get(col("group")),
                        detail: get(detail_c),
                        looks: looks_of(&get(col("looks"))),
                    },
                );
                order.push(id);
            }
        } else if lower.first().map(String::as_str) == Some("role") {
            if let Some(id) = &current {
                sections.entry(id.clone()).or_insert((lower.clone(), rows));
            }
        }
    }
    let mut themes = Vec::new();
    for id in order {
        let (Some(e), Some((head, rows))) = (entries.get(&id), sections.get(&id)) else { continue };
        let col = |name: &str| head.iter().position(|h| h == name);
        let (light, dark) = match (col("light"), col("dark"), col("value")) {
            (Some(l), Some(d), _) => (finish_look(&raw_look(rows, l), false), finish_look(&raw_look(rows, d), true)),
            (_, _, Some(v)) => match e.looks {
                Looks::Light => (finish_look(&raw_look(rows, v), false), None),
                _ => (None, finish_look(&raw_look(rows, v), true)),
            },
            _ => continue,
        };
        let looks = match (&light, &dark) {
            (Some(_), Some(_)) => Looks::System,
            (Some(_), None) => Looks::Light,
            (None, Some(_)) => Looks::Dark,
            (None, None) => continue,
        };
        let group = if e.group.is_empty() { "Classic".to_string() } else { e.group.clone() };
        themes.push(Theme { id, name: e.name.clone(), group, detail: e.detail.clone(), looks, light, dark });
    }
    themes
}
