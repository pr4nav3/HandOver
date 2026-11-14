//! Development bridge: the same commands and events as the Tauri app, over HTTP on 127.0.0.1
//! only, plus the built UI from ui/dist. For working on the UI in a browser and taking
//! screenshots against a real hub:
//!
//!   DEVSERVER_HUB=127.0.0.1:8099 cargo run -p handover-core --features devserver --bin devserver
//!
//! POST /api/<command> with a JSON body answers JSON. GET /events streams the engine's events
//! (server-sent events). GET /hub/... serves what the app's `hub` scheme serves.

use handover_core::engine::Engine;
use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex};

type Subscribers = Arc<Mutex<Vec<Sender<String>>>>;

fn main() {
    let port: u16 = std::env::var("DEVSERVER_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(5176);
    let dist = std::env::var("DEVSERVER_DIST")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../ui/dist"));
    let launch = json!({
        "hub": std::env::var("DEVSERVER_HUB").ok().filter(|v| !v.is_empty()),
        "lesson": std::env::var("DEVSERVER_LESSON").ok().filter(|v| !v.is_empty()),
    });
    let engine = Engine::start();
    let subs: Subscribers = Arc::new(Mutex::new(Vec::new()));
    {
        let subs = subs.clone();
        engine.set_emitter(Box::new(move |v| {
            let text = v.to_string();
            subs.lock().expect("subscribers").retain(|s| s.send(text.clone()).is_ok());
        }));
    }
    let listener = TcpListener::bind(("127.0.0.1", port)).expect("bind 127.0.0.1");
    eprintln!("devserver on http://127.0.0.1:{port} (data: {})", engine.data_dir().display());
    for stream in listener.incoming().flatten() {
        let (engine, dist, subs, launch) = (engine.clone(), dist.clone(), subs.clone(), launch.clone());
        std::thread::spawn(move || {
            let _ = handle(stream, &engine, &dist, &subs, &launch);
        });
    }
}

fn handle(
    stream: TcpStream,
    engine: &Arc<Engine>,
    dist: &Path,
    subs: &Subscribers,
    launch: &Value,
) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request = String::new();
    reader.read_line(&mut request)?;
    let mut length = 0usize;
    let mut range = None;
    loop {
        let mut h = String::new();
        if reader.read_line(&mut h)? == 0 || h == "\r\n" {
            break;
        }
        let lower = h.to_ascii_lowercase();
        if let Some(v) = lower.strip_prefix("content-length:") {
            length = v.trim().parse().unwrap_or(0);
        }
        if lower.starts_with("range:") {
            range = Some(h[6..].trim().to_string());
        }
    }
    let mut body = vec![0u8; length.min(1 << 20)];
    reader.read_exact(&mut body)?;
    let mut parts = request.split_whitespace();
    let (method, path) = (parts.next().unwrap_or(""), parts.next().unwrap_or("/"));
    let mut out = stream;
    if method == "POST" {
        if let Some(cmd) = path.strip_prefix("/api/") {
            let args: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
            let result = match cmd {
                "__launch" => Ok(launch.to_string()),
                "__notify" => Ok("null".into()),
                // Stands in for the native picker: the file named by DEVSERVER_PICK.
                "__pick_video" => Ok(match std::env::var("DEVSERVER_PICK").ok().filter(|p| Path::new(p).is_file()) {
                    Some(p) => {
                        let path = Path::new(&p);
                        let size = std::fs::metadata(path).map(|m| m.len()).unwrap_or(0);
                        let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
                        json!({ "path": p, "name": name, "size": size }).to_string()
                    }
                    None => "null".into(),
                }),
                _ => engine.call(cmd, &args),
            };
            let (status, text) = match result {
                Ok(t) => (200, t),
                Err(e) => (400, json!({ "error": e }).to_string()),
            };
            return respond(&mut out, status, &[("Content-Type", "application/json")], text.as_bytes());
        }
    }
    if path == "/events" {
        write!(out, "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\nConnection: keep-alive\r\n\r\n")?;
        out.flush()?;
        let (tx, rx) = channel();
        subs.lock().expect("subscribers").push(tx);
        for text in rx {
            write!(out, "data: {text}\n\n")?;
            out.flush()?;
        }
        return Ok(());
    }
    if let Some(rest) = path.strip_prefix("/hub") {
        let (status, headers, data) = if rest.starts_with("/__frame") {
            match engine.frame() {
                Some(jpeg) => {
                    (200, vec![("Content-Type".to_string(), "image/jpeg".to_string())], jpeg.as_ref().clone())
                }
                None => (404, vec![], Vec::new()),
            }
        } else {
            let f = engine.lesson_file(rest, range.as_deref());
            (f.status, f.headers, f.body)
        };
        let h: Vec<(&str, &str)> = headers.iter().map(|(k, v)| (k.as_str(), v.as_str())).collect();
        return respond(&mut out, status, &h, &data);
    }
    let rel = path.split('?').next().unwrap_or("/").trim_start_matches('/');
    let rel = if rel.is_empty() { "index.html" } else { rel };
    if rel.split('/').any(|p| p == "..") {
        return respond(&mut out, 404, &[("Content-Type", "text/plain")], b"not found");
    }
    match std::fs::read(dist.join(rel)) {
        Ok(data) => {
            let ty = match rel.rsplit('.').next() {
                Some("html") => "text/html; charset=utf-8",
                Some("js") => "text/javascript",
                Some("css") => "text/css",
                Some("svg") => "image/svg+xml",
                Some("png") => "image/png",
                _ => "application/octet-stream",
            };
            respond(&mut out, 200, &[("Content-Type", ty)], &data)
        }
        Err(_) => respond(&mut out, 404, &[("Content-Type", "text/plain")], b"not found"),
    }
}

fn respond(out: &mut TcpStream, status: u16, headers: &[(&str, &str)], body: &[u8]) -> std::io::Result<()> {
    let reason = match status {
        200 => "OK",
        206 => "Partial Content",
        400 => "Bad Request",
        404 => "Not Found",
        416 => "Range Not Satisfiable",
        _ => "Status",
    };
    write!(out, "HTTP/1.1 {status} {reason}\r\n")?;
    for (k, v) in headers {
        if !k.eq_ignore_ascii_case("Cache-Control") {
            write!(out, "{k}: {v}\r\n")?;
        }
    }
    write!(out, "Content-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n", body.len())?;
    out.write_all(body)
}
