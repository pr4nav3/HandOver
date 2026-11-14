//! What the app remembers between launches: recent hubs and settings, as small JSON files in
//! the app's data folder. Nothing secret is stored.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

/// How many recent hubs are kept.
pub const RECENT_MAX: usize = 6;

/// The app's data folder: `%APPDATA%\HandOver` on Windows, `~/Library/Application Support/HandOver`
/// on macOS, `$XDG_CONFIG_HOME/handover` (or `~/.config/handover`) on Linux.
/// `HANDOVER_DESKTOP_HOME` overrides it, for tests and demos.
pub fn app_data_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("HANDOVER_DESKTOP_HOME").filter(|v| !v.is_empty()) {
        return PathBuf::from(dir);
    }
    let home = || std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from);
    if cfg!(windows) {
        if let Some(appdata) = std::env::var_os("APPDATA") {
            return PathBuf::from(appdata).join("HandOver");
        }
    } else if cfg!(target_os = "macos") {
        if let Some(h) = home() {
            return h.join("Library/Application Support/HandOver");
        }
    } else if let Some(x) = std::env::var_os("XDG_CONFIG_HOME").filter(|v| !v.is_empty()) {
        return PathBuf::from(x).join("handover");
    } else if let Some(h) = home() {
        return h.join(".config/handover");
    }
    std::env::temp_dir().join("handover-desktop")
}

fn now_secs() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn read_json<T: for<'de> Deserialize<'de> + Default>(path: &Path) -> T {
    std::fs::read(path).ok().and_then(|d| serde_json::from_slice(&d).ok()).unwrap_or_default()
}

/// Writes through a temporary file, so a crash never leaves half a file.
fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let tmp = path.with_extension("json.tmp");
    let data = serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, data).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RecentHub {
    /// `http://host:port`
    pub base: String,
    /// What the list shows: host, plus the port when it is not 8000.
    pub label: String,
    /// Seconds since 1970.
    pub last_used: u64,
}

pub struct Recent {
    path: PathBuf,
}

impl Recent {
    pub fn new(dir: &Path) -> Recent {
        Recent { path: dir.join("recent-hubs.json") }
    }

    /// Most recent first.
    pub fn list(&self) -> Vec<RecentHub> {
        let mut list: Vec<RecentHub> = read_json(&self.path);
        list.sort_by_key(|h| std::cmp::Reverse(h.last_used));
        list.truncate(RECENT_MAX);
        list
    }

    /// Puts a hub at the top, once.
    pub fn touch(&self, base: &str, label: &str) -> Result<Vec<RecentHub>, String> {
        self.touch_at(base, label, now_secs())
    }

    pub fn touch_at(&self, base: &str, label: &str, when: u64) -> Result<Vec<RecentHub>, String> {
        let mut list = self.list();
        list.retain(|h| h.base != base);
        list.insert(0, RecentHub { base: base.into(), label: label.into(), last_used: when });
        list.truncate(RECENT_MAX);
        write_json(&self.path, &list)?;
        Ok(list)
    }

    pub fn forget(&self, base: &str) -> Result<Vec<RecentHub>, String> {
        let mut list = self.list();
        list.retain(|h| h.base != base);
        write_json(&self.path, &list)?;
        Ok(list)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// A theme id from the catalog (themes.rs, apps/design/THEMES.md). `system` is Default.
    pub theme: String,
    /// `system`, `light` or `dark`: which look a theme with two looks shows. Themes with one
    /// look keep it. Dark by default: Learn is video first.
    pub appearance: String,
    /// Reconnect to the last hub when the app opens.
    pub reopen_last_hub: bool,
    /// The two note chime when the camera confirms a step.
    pub chime: bool,
    /// A system notification when a lesson finishes or checks go off while the window is hidden.
    pub notifications: bool,
}

impl Default for Settings {
    fn default() -> Settings {
        Settings {
            theme: "system".into(),
            appearance: "system".into(),
            reopen_last_hub: true,
            chime: true,
            notifications: true,
        }
    }
}

pub struct SettingsStore {
    path: PathBuf,
}

impl SettingsStore {
    pub fn new(dir: &Path) -> SettingsStore {
        SettingsStore { path: dir.join("settings.json") }
    }

    pub fn load(&self) -> Settings {
        read_json(&self.path)
    }

    pub fn save(&self, s: &Settings) -> Result<(), String> {
        write_json(&self.path, s)
    }
}
