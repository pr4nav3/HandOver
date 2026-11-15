//! The engine behind the window: one `call(cmd, args)` entry point that answers JSON, and one
//! event stream (`set_emitter`) that pushes link changes, hub messages and frame arrivals.
//! The Tauri shell only forwards; everything that can be tested lives here.

use crate::address::HubAddress;
use crate::api::{self, Tokens};
use crate::camera::{CameraSink, CameraSocket, Hello};
use crate::http;
use crate::phone;
use crate::protocol::{ClientMessage, ServerMessage, State};
use crate::socket::{Link, LinkStatus, Sink, SocketEvent, UiSocket};
use crate::store::{app_data_dir, Recent, Settings, SettingsStore};
use crate::themes::{catalog, Catalog};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};

pub type Emitter = Box<dyn Fn(Value) + Send + Sync>;

/// What the socket thread updates. Shared without the socket itself, so nothing holds a cycle.
struct Shared {
    /// Bumped on every connect and disconnect; events from an older socket are dropped.
    generation: AtomicU64,
    link: Mutex<LinkStatus>,
    state: Mutex<Option<State>>,
    /// The newest live JPEG and its number.
    frame: Mutex<(u64, Option<Arc<Vec<u8>>>)>,
    emitter: RwLock<Option<Emitter>>,
}

impl Shared {
    fn emit(&self, v: Value) {
        if let Some(e) = self.emitter.read().expect("emitter lock").as_ref() {
            e(v);
        }
    }
}

pub struct Engine {
    shared: Arc<Shared>,
    hub: Mutex<Option<HubAddress>>,
    socket: Mutex<Option<UiSocket>>,
    /// This computer's webcam, sent to the hub while Learn uses it.
    camera: Mutex<Option<CameraSocket>>,
    recent: Recent,
    settings: SettingsStore,
    catalog: Catalog,
    files: http::FileCache,
    tokens: Tokens,
    dir: PathBuf,
}

/// The state as the window wants it: the hub's fields plus the derived words it shows.
pub fn state_json(s: &State) -> Value {
    let mut v = serde_json::to_value(s).unwrap_or(Value::Null);
    if let Some(obj) = v.as_object_mut() {
        obj.insert("position".into(), json!(s.position()));
        obj.insert("offline_label".into(), json!(s.offline_label()));
        obj.insert("check_reason".into(), json!(s.last_check.as_ref().and_then(|c| c.shown_reason())));
    }
    v
}

fn event_json(ev: &ServerMessage) -> Option<Value> {
    Some(match ev {
        ServerMessage::State(s) => json!({ "kind": "state", "state": state_json(s) }),
        ServerMessage::Advance(a) => json!({ "kind": "advance", "advance": a }),
        ServerMessage::Mistake(m) => json!({ "kind": "mistake", "mistake": m }),
        ServerMessage::Error(message) => json!({ "kind": "error", "message": message }),
        ServerMessage::Unknown(_) => return None,
    })
}

impl Engine {
    pub fn start() -> Arc<Engine> {
        Engine::with_dir(app_data_dir())
    }

    pub fn with_dir(dir: PathBuf) -> Arc<Engine> {
        Arc::new(Engine {
            shared: Arc::new(Shared {
                generation: AtomicU64::new(0),
                link: Mutex::new(LinkStatus::idle()),
                state: Mutex::new(None),
                frame: Mutex::new((0, None)),
                emitter: RwLock::new(None),
            }),
            hub: Mutex::new(None),
            socket: Mutex::new(None),
            camera: Mutex::new(None),
            recent: Recent::new(&dir),
            settings: SettingsStore::new(&dir),
            catalog: catalog(),
            files: http::FileCache::default(),
            tokens: Tokens::new(&dir),
            dir,
        })
    }

    pub fn set_emitter(&self, e: Emitter) {
        *self.shared.emitter.write().expect("emitter lock") = Some(e);
    }

    pub fn data_dir(&self) -> &PathBuf {
        &self.dir
    }

    /// The newest live frame, for the window's image.
    pub fn frame(&self) -> Option<Arc<Vec<u8>>> {
        self.shared.frame.lock().expect("frame lock").1.clone()
    }

    /// The hub the window is paired with.
    pub fn hub(&self) -> Option<HubAddress> {
        self.hub.lock().expect("hub lock").clone()
    }

    /// A lesson file from the paired hub, for the window's player.
    pub fn lesson_file(&self, path_and_query: &str, range: Option<&str>) -> http::FileResponse {
        match self.hub() {
            Some(hub) => self.files.serve(&hub, path_and_query, range),
            None => http::FileResponse { status: 503, headers: vec![], body: b"no hub".to_vec() },
        }
    }

    /// Every UI request lands here. Answers JSON text, or a sentence to show on failure.
    pub fn call(&self, cmd: &str, args: &Value) -> Result<String, String> {
        let s = |k: &str| args.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        let int = |k: &str| args.get(k).and_then(Value::as_i64);
        let v: Value = match cmd {
            "snapshot" => self.snapshot(),
            "connect" => self.connect(&s("address"))?,
            "disconnect" => {
                self.disconnect();
                Value::Null
            }
            "forgetHub" => json!(self.recent.forget(&s("base"))?),
            "recentHubs" => json!(self.recent.list()),
            "lessons" => json!(http::lessons(&self.require_hub()?)?),
            "lesson" => json!(http::lesson(&self.require_hub()?, &s("id"))?),
            "selectLesson" => self.send(ClientMessage::SelectLesson { id: s("id") })?,
            "next" => {
                let reason = if s("reason") == "voice" { "voice" } else { "button" };
                self.send(ClientMessage::Next { reason, from: int("from") })?
            }
            "back" => self.send(ClientMessage::Back { from: int("from") })?,
            "goto" => self.send(ClientMessage::Goto { step: int("step").ok_or("goto needs a step")? })?,
            "hold" => self.send(ClientMessage::Hold {
                hold: args.get("held").and_then(Value::as_bool).ok_or("hold needs held")?,
            })?,
            "dismissMistake" => self.send(ClientMessage::DismissMistake)?,
            "setCheckInterval" => {
                let seconds = args.get("seconds").and_then(Value::as_f64).unwrap_or(f64::NAN);
                self.send(ClientMessage::set_check_interval(seconds).ok_or("setCheckInterval needs seconds")?)?
            }
            "endLesson" => {
                let opt = |v: String| if v.is_empty() { None } else { Some(v) };
                self.send(ClientMessage::EndLesson { lesson_id: opt(s("lessonId")), run_id: opt(s("runId")) })?
            }
            "pairing" => self.pairing(&s("camera"))?,
            "cameraStart" => self.camera_start(&s("name"), &s("platform"))?,
            "cameraStop" => {
                self.camera_stop();
                Value::Null
            }
            "setSettings" => self.set_settings(args)?,
            "api" => self.api(args)?,
            "upload" => self.upload(args)?,
            _ => return Err(format!("Unknown command {cmd}")),
        };
        serde_json::to_string(&v).map_err(|e| e.to_string())
    }

    fn require_hub(&self) -> Result<HubAddress, String> {
        self.hub().ok_or_else(|| "Not connected to a hub.".to_string())
    }

    fn snapshot(&self) -> Value {
        let state = self.shared.state.lock().expect("state lock").clone();
        json!({
            "version": env!("CARGO_PKG_VERSION"),
            "link": *self.shared.link.lock().expect("link lock"),
            "state": state.as_ref().map(state_json),
            "recent": self.recent.list(),
            "settings": self.load_settings(),
            "themes": self.catalog,
        })
    }

    /// Pairs with a hub: checks it answers as a HandOver hub, then opens `/ws/ui`.
    fn connect(&self, typed: &str) -> Result<Value, String> {
        let hub = HubAddress::parse(typed)?;
        let lessons = http::probe(&hub)?;
        self.recent.touch(&hub.base(), &hub.display())?;
        let generation = self.shared.generation.fetch_add(1, Ordering::SeqCst) + 1;
        *self.shared.state.lock().expect("state lock") = None;
        *self.shared.frame.lock().expect("frame lock") = (0, None);
        let shared = self.shared.clone();
        let sink: Sink = Arc::new(move |ev| {
            if shared.generation.load(Ordering::SeqCst) != generation {
                return;
            }
            match ev {
                SocketEvent::Link(status) => {
                    *shared.link.lock().expect("link lock") = status.clone();
                    shared.emit(json!({ "kind": "link", "link": status }));
                }
                SocketEvent::Frame(jpeg) => {
                    let n = {
                        let mut f = shared.frame.lock().expect("frame lock");
                        f.0 += 1;
                        f.1 = Some(Arc::new(jpeg));
                        f.0
                    };
                    shared.emit(json!({ "kind": "frame", "n": n }));
                }
                SocketEvent::Message(m) => {
                    if let ServerMessage::State(s) = &m {
                        *shared.state.lock().expect("state lock") = Some((**s).clone());
                    }
                    if let Some(v) = event_json(&m) {
                        shared.emit(v);
                    }
                }
            }
        });
        self.files.clear();
        self.camera_stop();
        let socket = UiSocket::start(hub.clone(), sink);
        *self.hub.lock().expect("hub lock") = Some(hub.clone());
        // Dropping the old socket closes it; its late events carry an old generation.
        *self.socket.lock().expect("socket lock") = Some(socket);
        Ok(json!({ "hub": hub.base(), "label": hub.display(), "lessons": lessons, "recent": self.recent.list() }))
    }

    pub fn disconnect(&self) {
        self.camera_stop();
        self.shared.generation.fetch_add(1, Ordering::SeqCst);
        *self.socket.lock().expect("socket lock") = None;
        *self.hub.lock().expect("hub lock") = None;
        *self.shared.state.lock().expect("state lock") = None;
        *self.shared.frame.lock().expect("frame lock") = (0, None);
        let idle = LinkStatus::idle();
        *self.shared.link.lock().expect("link lock") = idle.clone();
        self.shared.emit(json!({ "kind": "link", "link": idle }));
    }

    fn send(&self, msg: ClientMessage) -> Result<Value, String> {
        match self.socket.lock().expect("socket lock").as_ref() {
            Some(sock) => {
                sock.send(&msg);
                Ok(Value::Null)
            }
            None => Err("Not connected to a hub.".into()),
        }
    }

    /// Saved settings, with a theme the catalog no longer has replaced by the default.
    fn load_settings(&self) -> Settings {
        let mut s = self.settings.load();
        if self.catalog.get(&s.theme).is_none() {
            s.theme = "system".into();
        }
        if !matches!(s.appearance.as_str(), "system" | "light" | "dark") {
            s.appearance = "system".into();
        }
        s
    }

    /// One library, account or organization request (server/docs/library.md). Answers
    /// `{"status", "ok", "data"}`; the window shows the hub's `detail` when `ok` is false.
    fn api(&self, args: &Value) -> Result<Value, String> {
        let hub = self.require_hub()?;
        let method = args.get("method").and_then(Value::as_str).unwrap_or("GET").to_ascii_uppercase();
        if !matches!(method.as_str(), "GET" | "POST" | "PATCH" | "DELETE") {
            return Err(format!("Method {method} is not allowed."));
        }
        let path = args.get("path").and_then(Value::as_str).unwrap_or("");
        if !api::valid_api_path(path) {
            return Err("That is not a hub API path.".into());
        }
        let base = hub.base();
        let token = self.tokens.get(&base);
        let mut ans = api::request(
            &hub,
            token.as_deref(),
            &method,
            path,
            args.get("query").unwrap_or(&Value::Null),
            args.get("body"),
        );
        let ok = (200..300).contains(&ans.status);
        if ok && matches!(path, "/api/auth/login" | "/api/auth/setup" | "/api/auth/handoff/redeem") {
            if let Some(t) = ans.body.as_object_mut().and_then(|o| o.remove("token")) {
                self.tokens.set(&base, t.as_str())?;
            }
        }
        // Signed out, or the hub no longer knows this token: forget it.
        if path == "/api/auth/logout" || (ans.status == 401 && token.is_some()) {
            self.tokens.set(&base, None)?;
        }
        Ok(json!({ "status": ans.status, "ok": ok, "data": ans.body }))
    }

    /// Uploads a video to make a course (`/api/courses`), or a lesson on hubs without the
    /// library (`/api/lesson`). Progress arrives as `upload` events.
    fn upload(&self, args: &Value) -> Result<Value, String> {
        let hub = self.require_hub()?;
        let s = |k: &str| args.get(k).and_then(Value::as_str).unwrap_or("").to_string();
        let route = if s("route") == "/api/lesson" { "/api/lesson" } else { "/api/courses" };
        let path = PathBuf::from(s("path"));
        let mut fields = vec![("title", s("title"))];
        for key in ["description", "org_id"] {
            if !s(key).is_empty() {
                fields.push((key, s(key)));
            }
        }
        let token = self.tokens.get(&hub.base());
        let shared = self.shared.clone();
        let ans = api::upload(&hub, token.as_deref(), route, &path, &fields, |sent, total| {
            shared.emit(json!({ "kind": "upload", "sent": sent, "total": total }));
        });
        Ok(json!({ "status": ans.status, "ok": (200..300).contains(&ans.status), "data": ans.body }))
    }

    fn set_settings(&self, args: &Value) -> Result<Value, String> {
        let mut s: Settings = self.load_settings();
        if let Some(theme) = args.get("theme").and_then(Value::as_str) {
            if self.catalog.get(theme).is_none() {
                return Err(format!("No theme called {theme}."));
            }
            s.theme = theme.to_string();
        }
        if let Some(a) = args.get("appearance").and_then(Value::as_str) {
            if !matches!(a, "system" | "light" | "dark") {
                return Err(format!("No appearance called {a}."));
            }
            s.appearance = a.to_string();
        }
        for (key, slot) in [
            ("reopenLastHub", &mut s.reopen_last_hub),
            ("chime", &mut s.chime),
            ("notifications", &mut s.notifications),
        ] {
            if let Some(b) = args.get(key).and_then(Value::as_bool) {
                *slot = b;
            }
        }
        self.settings.save(&s)?;
        Ok(json!(s))
    }

    /// What a phone needs to pair with this hub: the address it can reach, the link and its QR.
    /// The hub's own `/api/hub-info` comes first; older hubs fall back to this computer's address.
    fn pairing(&self, camera: &str) -> Result<Value, String> {
        let hub = self.require_hub()?;
        if let Some((url, link)) =
            phone::from_hub_info(&api::request(&hub, None, "GET", "/api/hub-info", &Value::Null, None))
        {
            let link = phone::camera_link(&link, camera);
            let started = api::request(&hub, None, "POST", "/api/auth/handoff/start", &Value::Null, None);
            let handoff = if (200..300).contains(&started.status) {
                started.body.get("claim").and_then(Value::as_str).map(str::to_string)
            } else {
                None
            };
            let link = handoff.as_deref().map(|claim| phone::handoff_link(&link, claim)).unwrap_or(link);
            let label = HubAddress::parse(&url).map(|h| h.authority()).unwrap_or_else(|_| url.clone());
            return Ok(json!({ "hub": url, "label": label, "link": link, "svg": phone::qr_svg(&link)?,
                              "handoff": handoff }));
        }
        let lan = phone::lan_ip();
        Ok(match phone::phone_hub(&hub, lan) {
            Some(p) => {
                let link = phone::camera_link(&phone::connect_link(&p), camera);
                json!({ "hub": p.base(), "label": p.authority(), "link": link, "svg": phone::qr_svg(&link)?,
                        "handoff": null })
            }
            None => json!({ "hub": null, "label": null, "link": null, "svg": null, "handoff": null }),
        })
    }

    /// Starts sending this computer's webcam to the hub. Frames arrive with `camera_frame`.
    fn camera_start(&self, name: &str, platform: &str) -> Result<Value, String> {
        let hub = self.require_hub()?;
        let platform = if matches!(platform, "macos" | "windows" | "linux") { platform } else { "other" };
        let name = if name.trim().is_empty() { "Computer camera" } else { name.trim() };
        let hello =
            Hello { device_id: self.camera_id(), name: name.chars().take(64).collect(), platform: platform.into() };
        let shared = self.shared.clone();
        let sink: CameraSink = Arc::new(move |link| shared.emit(json!({ "kind": "camera", "camera": link })));
        *self.camera.lock().expect("camera lock") = Some(CameraSocket::start(hub, hello, sink));
        Ok(Value::Null)
    }

    pub fn camera_stop(&self) {
        if self.camera.lock().expect("camera lock").take().is_some() {
            self.shared.emit(json!({ "kind": "camera", "camera": "off" }));
        }
    }

    /// One JPEG from the window's webcam. Dropped when the camera is not started.
    pub fn camera_frame(&self, jpeg: Vec<u8>) {
        if let Some(cam) = self.camera.lock().expect("camera lock").as_ref() {
            cam.frame(jpeg);
        }
    }

    /// A random id kept in the data folder, so the hub knows a reconnect is the same camera.
    fn camera_id(&self) -> String {
        let path = self.dir.join("camera_id");
        if let Ok(id) = std::fs::read_to_string(&path) {
            let id = id.trim();
            if !id.is_empty() && id.len() <= 64 {
                return id.to_string();
            }
        }
        use std::hash::{BuildHasher, Hasher};
        let mut h = std::collections::hash_map::RandomState::new().build_hasher();
        h.write_u128(
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0),
        );
        h.write_u32(std::process::id());
        let id = format!("desktop-{:016x}", h.finish());
        let _ = std::fs::create_dir_all(&self.dir);
        let _ = std::fs::write(&path, &id);
        id
    }

    /// True while a hub is paired and its socket is open.
    pub fn connected(&self) -> bool {
        self.shared.link.lock().expect("link lock").link == Link::Connected
    }
}
