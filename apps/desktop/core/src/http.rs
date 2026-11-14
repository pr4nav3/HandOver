//! The hub's REST routes the app uses (CONTRACT.md 4), and fetching lesson files for the
//! window's video player, with range requests passed through.

use crate::address::{valid_lesson_id, valid_lesson_path, HubAddress};
use crate::protocol::{Lesson, LessonSummary};
use std::io::Read;
use std::time::Duration;

/// A hub on the local network answers fast; longer than this means it is not there.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const READ_TIMEOUT: Duration = Duration::from_secs(10);
/// The biggest lesson file the app will pass to its player. Step clips are a few MB.
const FILE_MAX: u64 = 512 * 1024 * 1024;

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new().timeout_connect(CONNECT_TIMEOUT).timeout_read(READ_TIMEOUT).redirects(0).build()
}

/// The hub's `{"detail": "..."}` error message, when there is one.
fn detail(resp: ureq::Response) -> Option<String> {
    let v: serde_json::Value = resp.into_json().ok()?;
    v.get("detail").and_then(|d| d.as_str()).map(str::to_string)
}

fn get_text(url: &str) -> Result<String, String> {
    match agent().get(url).call() {
        Ok(resp) => resp.into_string().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(code, resp)) => {
            Err(detail(resp).unwrap_or_else(|| format!("The hub answered {code}.")))
        }
        Err(ureq::Error::Transport(t)) => Err(t.to_string()),
    }
}

/// Checks that a HandOver hub answers at this address. The error is a sentence to show.
pub fn probe(hub: &HubAddress) -> Result<Vec<LessonSummary>, String> {
    let url = format!("{}/api/lessons", hub.base());
    match agent().get(&url).call() {
        Ok(resp) => resp
            .into_json::<Vec<LessonSummary>>()
            .map_err(|_| format!("Something answered at {}, but it is not a HandOver hub.", hub.display())),
        Err(ureq::Error::Status(..)) => {
            Err(format!("Something answered at {}, but it is not a HandOver hub.", hub.display()))
        }
        Err(ureq::Error::Transport(_)) => {
            Err(format!("No hub answered at {}. Check the address and that the hub is running.", hub.display()))
        }
    }
}

/// `GET /api/lessons`
pub fn lessons(hub: &HubAddress) -> Result<Vec<LessonSummary>, String> {
    let text = get_text(&format!("{}/api/lessons", hub.base()))?;
    serde_json::from_str(&text).map_err(|e| format!("The lesson list was unreadable: {e}"))
}

/// `GET /api/lessons/{id}`, with the contract's defaults applied.
pub fn lesson(hub: &HubAddress, id: &str) -> Result<Lesson, String> {
    if !valid_lesson_id(id) {
        return Err("bad lesson id".into());
    }
    let text = get_text(&format!("{}/api/lessons/{id}", hub.base()))?;
    Lesson::parse(&text, id)
}

/// A lesson file for the window's player: status, headers worth passing on, and the body.
pub struct FileResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl FileResponse {
    fn plain(status: u16, text: &str) -> FileResponse {
        FileResponse {
            status,
            headers: vec![("Content-Type".into(), "text/plain; charset=utf-8".into())],
            body: text.as_bytes().to_vec(),
        }
    }
}

/// Fetches `/lessons/{id}/{path}` (with its `?v=rev` query) from the hub. Only lesson files
/// are reachable this way; anything else is a 404 without touching the network. `range` is the
/// player's Range header, passed through so seeking works.
pub fn lesson_file(hub: &HubAddress, path_and_query: &str, range: Option<&str>) -> FileResponse {
    let (path, query) = path_and_query.split_once('?').unwrap_or((path_and_query, ""));
    let Some(rest) = path.strip_prefix("/lessons/") else {
        return FileResponse::plain(404, "not found");
    };
    let Some((id, file)) = rest.split_once('/') else {
        return FileResponse::plain(404, "not found");
    };
    let query_ok = query.is_empty()
        || (query.len() <= 64 && query.chars().all(|c| c.is_ascii_alphanumeric() || "=&_-".contains(c)));
    if !valid_lesson_id(id) || !valid_lesson_path(file) || !query_ok {
        return FileResponse::plain(404, "not found");
    }
    let url = format!("{}/lessons/{id}/{file}{}{query}", hub.base(), if query.is_empty() { "" } else { "?" });
    let mut req = agent().get(&url);
    if let Some(r) = range.filter(|r| r.len() < 100 && r.starts_with("bytes=")) {
        req = req.set("Range", r);
    }
    let resp = match req.call() {
        Ok(r) => r,
        Err(ureq::Error::Status(_, r)) => r,
        Err(ureq::Error::Transport(_)) => return FileResponse::plain(502, "The hub did not answer."),
    };
    let status = resp.status();
    let mut headers = Vec::new();
    for name in ["Content-Type", "Content-Range", "Accept-Ranges", "Cache-Control"] {
        if let Some(v) = resp.header(name) {
            headers.push((name.to_string(), v.to_string()));
        }
    }
    let mut body = Vec::new();
    if let Err(e) = resp.into_reader().take(FILE_MAX).read_to_end(&mut body) {
        return FileResponse::plain(502, &format!("The hub stopped sending: {e}"));
    }
    FileResponse { status, headers, body }
}

/// A `bytes=` range header resolved against a file of `len` bytes: the first and last byte.
/// None when the header is not one satisfiable single range.
pub fn resolve_range(header: &str, len: usize) -> Option<(usize, usize)> {
    let spec = header.trim().strip_prefix("bytes=")?;
    if spec.contains(',') || len == 0 {
        return None;
    }
    let (a, b) = spec.split_once('-')?;
    let (a, b) = (a.trim(), b.trim());
    let (start, end) = if a.is_empty() {
        let n: usize = b.parse().ok()?;
        if n == 0 {
            return None;
        }
        (len.saturating_sub(n), len - 1)
    } else {
        let start: usize = a.parse().ok()?;
        let end = if b.is_empty() { len - 1 } else { b.parse::<usize>().ok()?.min(len - 1) };
        (start, end)
    };
    (start <= end && start < len).then_some((start, end))
}

/// Lesson files kept in memory after the first fetch, so a looping clip is fetched from the hub
/// once and every range the player asks for is answered locally. Keys carry `?v=rev`, so a recut
/// gets new keys. Small files only; the oldest go first when the budget is used up.
pub struct FileCache {
    entries: std::sync::Mutex<Vec<(String, std::sync::Arc<CachedFile>)>>,
}

pub struct CachedFile {
    pub content_type: String,
    pub body: Vec<u8>,
}

/// Total bytes kept, and the biggest single file kept.
const CACHE_BUDGET: usize = 96 * 1024 * 1024;
const CACHE_FILE_MAX: usize = 32 * 1024 * 1024;

impl Default for FileCache {
    fn default() -> FileCache {
        FileCache { entries: std::sync::Mutex::new(Vec::new()) }
    }
}

impl FileCache {
    pub fn clear(&self) {
        self.entries.lock().expect("cache lock").clear();
    }

    fn get(&self, key: &str) -> Option<std::sync::Arc<CachedFile>> {
        let mut e = self.entries.lock().expect("cache lock");
        let i = e.iter().position(|(k, _)| k == key)?;
        let item = e.remove(i);
        let file = item.1.clone();
        e.push(item);
        Some(file)
    }

    fn put(&self, key: &str, file: CachedFile) -> std::sync::Arc<CachedFile> {
        let file = std::sync::Arc::new(file);
        let mut e = self.entries.lock().expect("cache lock");
        e.retain(|(k, _)| k != key);
        e.push((key.to_string(), file.clone()));
        while e.iter().map(|(_, f)| f.body.len()).sum::<usize>() > CACHE_BUDGET && e.len() > 1 {
            e.remove(0);
        }
        file
    }

    /// Serves a lesson file from memory, fetching it whole from the hub the first time.
    pub fn serve(&self, hub: &HubAddress, path_and_query: &str, range: Option<&str>) -> FileResponse {
        let key = format!("{}{path_and_query}", hub.base());
        let file = match self.get(&key) {
            Some(f) => f,
            None => {
                let full = lesson_file(hub, path_and_query, None);
                let content_type = full
                    .headers
                    .iter()
                    .find(|(k, _)| k.eq_ignore_ascii_case("Content-Type"))
                    .map(|(_, v)| v.clone())
                    .unwrap_or_else(|| "application/octet-stream".into());
                if full.status != 200 || full.body.len() > CACHE_FILE_MAX {
                    // Errors pass through; big files go straight to the hub with the range.
                    return if full.status == 200 { lesson_file(hub, path_and_query, range) } else { full };
                }
                self.put(&key, CachedFile { content_type, body: full.body })
            }
        };
        slice(&file, range)
    }
}

/// The whole file, or the asked range as a 206 (416 when it cannot be met).
pub fn slice(file: &CachedFile, range: Option<&str>) -> FileResponse {
    let len = file.body.len();
    let mut headers = vec![
        ("Content-Type".to_string(), file.content_type.clone()),
        ("Accept-Ranges".to_string(), "bytes".to_string()),
    ];
    let Some(r) = range else {
        return FileResponse { status: 200, headers, body: file.body.clone() };
    };
    match resolve_range(r, len) {
        Some((a, b)) => {
            headers.push(("Content-Range".to_string(), format!("bytes {a}-{b}/{len}")));
            FileResponse { status: 206, headers, body: file.body[a..=b].to_vec() }
        }
        None => {
            headers.push(("Content-Range".to_string(), format!("bytes */{len}")));
            FileResponse { status: 416, headers, body: Vec::new() }
        }
    }
}
