//! The hub's library, accounts and organizations routes (server/docs/library.md), passed through
//! from the window with this device's sign-in token, and video uploads with progress.
//!
//! Only `/api/...` paths are reachable. The token never reaches the window: it is taken out of
//! sign-in answers, kept in the app's data folder per hub, and added to each request here.

use crate::address::HubAddress;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Sign-in tokens per hub base address. The file is readable by this user only.
pub struct Tokens {
    path: PathBuf,
}

impl Tokens {
    pub fn new(dir: &Path) -> Tokens {
        Tokens { path: dir.join("tokens.json") }
    }

    fn all(&self) -> BTreeMap<String, String> {
        std::fs::read(&self.path).ok().and_then(|d| serde_json::from_slice(&d).ok()).unwrap_or_default()
    }

    pub fn get(&self, base: &str) -> Option<String> {
        self.all().get(base).cloned()
    }

    pub fn set(&self, base: &str, token: Option<&str>) -> Result<(), String> {
        let mut all = self.all();
        match token {
            Some(t) => all.insert(base.to_string(), t.to_string()),
            None => all.remove(base),
        };
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let tmp = self.path.with_extension("json.tmp");
        std::fs::write(&tmp, serde_json::to_vec(&all).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600));
        }
        std::fs::rename(&tmp, &self.path).map_err(|e| e.to_string())
    }
}

/// A path the window may call: `/api/` and plain URL characters only.
pub fn valid_api_path(path: &str) -> bool {
    path.starts_with("/api/")
        && path.len() <= 300
        && !path.contains("..")
        && path.chars().all(|c| c.is_ascii_alphanumeric() || "/-_.".contains(c))
}

fn encode(s: &str) -> String {
    url::form_urlencoded::byte_serialize(s.as_bytes()).collect()
}

/// `{"a": "b", "n": 1}` to `a=b&n=1`. Nulls and empty strings are left out.
pub fn query_string(q: &Value) -> String {
    let Some(obj) = q.as_object() else { return String::new() };
    obj.iter()
        .filter_map(|(k, v)| {
            let v = match v {
                Value::String(s) if !s.is_empty() => s.clone(),
                Value::Number(n) => n.to_string(),
                Value::Bool(b) => b.to_string(),
                _ => return None,
            };
            Some(format!("{}={}", encode(k), encode(&v)))
        })
        .collect::<Vec<_>>()
        .join("&")
}

/// What the window gets back: the status and the hub's JSON (or text).
pub struct Answer {
    pub status: u16,
    pub body: Value,
}

fn agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_secs(3))
        .timeout_read(Duration::from_secs(120))
        .redirects(0)
        .build()
}

fn read_answer(resp: ureq::Response) -> Answer {
    let status = resp.status();
    let mut text = String::new();
    let _ = resp.into_reader().take(16 * 1024 * 1024).read_to_string(&mut text);
    let body = serde_json::from_str(&text).unwrap_or(Value::String(text));
    Answer { status, body }
}

/// One request to the hub. Network failures come back as status 0 with a sentence.
pub fn request(
    hub: &HubAddress,
    token: Option<&str>,
    method: &str,
    path: &str,
    query: &Value,
    body: Option<&Value>,
) -> Answer {
    let q = query_string(query);
    let url = format!("{}{path}{}{q}", hub.base(), if q.is_empty() { "" } else { "?" });
    let mut req = agent().request(method, &url);
    if let Some(t) = token {
        req = req.set("Authorization", &format!("Bearer {t}"));
    }
    let result = match body {
        Some(b) => req.send_json(b.clone()),
        None if method == "GET" || method == "DELETE" => req.call(),
        None => req.set("Content-Type", "application/json").send_string("{}"),
    };
    match result {
        Ok(r) | Err(ureq::Error::Status(_, r)) => read_answer(r),
        Err(ureq::Error::Transport(_)) => Answer { status: 0, body: json!({ "detail": "The hub did not answer." }) },
    }
}

/// A reader that reports how many bytes have gone out.
struct Counting<R: Read, F: FnMut(u64)> {
    inner: R,
    sent: u64,
    last: u64,
    report: F,
}

impl<R: Read, F: FnMut(u64)> Read for Counting<R, F> {
    fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
        let n = self.inner.read(buf)?;
        self.sent += n as u64;
        // About every 256 KB, and at the end.
        if self.sent - self.last >= 256 * 1024 || n == 0 {
            self.last = self.sent;
            (self.report)(self.sent);
        }
        Ok(n)
    }
}

/// Uploads a video as multipart form data to `route` (`/api/courses` or `/api/lesson`), with
/// text fields, streaming the file and reporting bytes sent.
pub fn upload(
    hub: &HubAddress,
    token: Option<&str>,
    route: &str,
    file: &Path,
    fields: &[(&str, String)],
    progress: impl FnMut(u64, u64),
) -> Answer {
    let mut progress = progress;
    let meta = match std::fs::metadata(file) {
        Ok(m) if m.is_file() => m,
        _ => return Answer { status: 0, body: json!({ "detail": "That file is not there any more." }) },
    };
    let name = file.file_name().map(|n| n.to_string_lossy().replace('"', "")).unwrap_or_else(|| "video.mp4".into());
    let boundary = format!("handover{:x}", meta.len() ^ 0x5eed_cafe_f00d);
    let mut head = String::new();
    for (k, v) in fields {
        head.push_str(&format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"));
    }
    head.push_str(&format!(
        "--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ));
    let tail = format!("\r\n--{boundary}--\r\n");
    let total = head.len() as u64 + meta.len() + tail.len() as u64;
    let Ok(f) = std::fs::File::open(file) else {
        return Answer { status: 0, body: json!({ "detail": "That file could not be opened." }) };
    };
    let body = std::io::Cursor::new(head.into_bytes()).chain(f).chain(std::io::Cursor::new(tail.into_bytes()));
    let reader = Counting { inner: body, sent: 0, last: 0, report: |sent| progress(sent.min(total), total) };
    let mut req = agent()
        .post(&format!("{}{route}", hub.base()))
        .set("Content-Type", &format!("multipart/form-data; boundary={boundary}"))
        .set("Content-Length", &total.to_string());
    if let Some(t) = token {
        req = req.set("Authorization", &format!("Bearer {t}"));
    }
    match req.send(reader) {
        Ok(r) | Err(ureq::Error::Status(_, r)) => read_answer(r),
        Err(ureq::Error::Transport(t)) => {
            Answer { status: 0, body: json!({ "detail": format!("The upload stopped: {t}") }) }
        }
    }
}
