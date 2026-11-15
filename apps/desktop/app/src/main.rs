//! The HandOver desktop app: one Tauri command, `call`, hands every UI request to the core
//! engine. This file adds only what needs a window: the `hub` URL scheme that feeds the video
//! player and the live image from the paired hub, system notifications, and launch options.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use handover_core::engine::Engine;
use serde_json::{json, Value};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::http::{Request, Response};
use tauri::{Emitter, Manager};
use tauri_plugin_notification::NotificationExt;

struct AppState {
    engine: Arc<Engine>,
    launch: Value,
    local_hub: Arc<Mutex<Option<Child>>>,
}

#[tauri::command]
async fn call(state: tauri::State<'_, AppState>, cmd: String, args: Value) -> Result<String, String> {
    let engine = state.engine.clone();
    // Network calls (pairing, lesson lists) never block the window's thread.
    tauri::async_runtime::spawn_blocking(move || engine.call(&cmd, &args)).await.map_err(|e| e.to_string())?
}

/// One JPEG from the window's webcam, as raw bytes (no JSON), for the hub's `/ws/camera`. The
/// core keeps only the newest unsent frame, so this returns at once.
#[tauri::command]
fn camera_frame(state: tauri::State<'_, AppState>, request: tauri::ipc::Request<'_>) -> Result<(), String> {
    match request.body() {
        tauri::ipc::InvokeBody::Raw(bytes) => {
            state.engine.camera_frame(bytes.clone());
            Ok(())
        }
        _ => Err("camera_frame takes raw bytes".into()),
    }
}

/// `--hub ADDRESS` and `--lesson ID` from the command line, so a shortcut or a script can open
/// the app straight onto a hub and a lesson.
#[tauri::command]
fn launch(state: tauri::State<'_, AppState>) -> Value {
    state.launch.clone()
}

/// A system notification, only while no HandOver window has focus (the window decides what).
#[tauri::command]
fn notify(app: tauri::AppHandle, title: String, body: String) -> Result<(), String> {
    let focused = app.webview_windows().values().any(|w| w.is_focused().unwrap_or(false));
    if focused {
        return Ok(());
    }
    app.notification().builder().title(title).body(body).show().map_err(|e| e.to_string())
}

/// The native file picker for a video to teach from. Answers the path, name and size, or null.
#[tauri::command]
async fn pick_video() -> Value {
    let picked = tauri::async_runtime::spawn_blocking(|| {
        rfd::FileDialog::new()
            .set_title("Choose a Video")
            .add_filter("Video", &["mp4", "mov", "m4v", "webm", "mkv", "avi"])
            .pick_file()
    })
    .await
    .ok()
    .flatten();
    match picked {
        Some(p) => {
            let size = std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0);
            let name = p.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
            json!({ "path": p.to_string_lossy(), "name": name, "size": size })
        }
        None => Value::Null,
    }
}

/// Makes the desktop app the normal front door: if a hub already listens locally, reuse it; otherwise start the
/// checked-out hub beside this development build and wait until it answers. Packaged builds can set
/// HANDOVER_REPO to the installed hub resources until the Python hub becomes a bundled sidecar.
#[tauri::command]
async fn ensure_local_hub(state: tauri::State<'_, AppState>) -> Result<Value, String> {
    let process = state.local_hub.clone();
    tauri::async_runtime::spawn_blocking(move || ensure_local_hub_blocking(process)).await.map_err(|e| e.to_string())?
}

fn ensure_local_hub_blocking(process: Arc<Mutex<Option<Child>>>) -> Result<Value, String> {
    if local_hub_running() {
        return Ok(json!({ "address": "localhost:8000", "started": false }));
    }
    let repo = local_repo().ok_or(
        "This build cannot find the local HandOver hub. Set HANDOVER_REPO to the HandOver checkout and try again.",
    )?;
    let python = if cfg!(windows) { repo.join(".venv/Scripts/python.exe") } else { repo.join(".venv/bin/python") };
    if !python.is_file() {
        return Err(
            "The local hub is not installed yet. Create .venv from server/requirements.lock, then try again.".into()
        );
    }
    {
        let mut held = process.lock().map_err(|_| "Local hub process lock failed.")?;
        if let Some(child) = held.as_mut() {
            if child.try_wait().map_err(|e| e.to_string())?.is_none() {
                // A previous launch is still warming up; wait for it below.
            } else {
                *held = None;
            }
        }
        if held.is_none() {
            let child = Command::new(python)
                .arg("-m")
                .arg("server.main")
                .current_dir(&repo)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .map_err(|e| format!("Could not start the local hub: {e}"))?;
            *held = Some(child);
        }
    }
    for _ in 0..120 {
        if local_hub_running() {
            return Ok(json!({ "address": "localhost:8000", "started": true }));
        }
        {
            let mut held = process.lock().map_err(|_| "Local hub process lock failed.")?;
            if let Some(child) = held.as_mut() {
                if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                    *held = None;
                    return Err(format!("The local hub stopped during launch ({status}). Run scripts/run_server.sh once to see its error."));
                }
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err("The local hub took too long to start. Run scripts/run_server.sh once to see its error.".into())
}

fn local_hub_running() -> bool {
    let address: SocketAddr = "127.0.0.1:8000".parse().expect("fixed local hub address");
    TcpStream::connect_timeout(&address, Duration::from_millis(120)).is_ok()
}

fn local_repo() -> Option<PathBuf> {
    let mut starts = Vec::new();
    if let Some(path) = std::env::var_os("HANDOVER_REPO") {
        starts.push(PathBuf::from(path));
    }
    if let Ok(path) = std::env::current_dir() {
        starts.push(path);
    }
    starts.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    starts.into_iter().find_map(|start| start.ancestors().find(|path| is_repo(path)).map(Path::to_path_buf))
}

fn is_repo(path: &Path) -> bool {
    path.join("server/main.py").is_file() && path.join("server/requirements.lock").is_file()
}

fn launch_args() -> Value {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let value = |flag: &str| {
        args.iter().position(|a| a == flag).and_then(|i| args.get(i + 1)).filter(|v| !v.starts_with("--")).cloned()
    };
    json!({ "hub": value("--hub"), "lesson": value("--lesson") })
}

/// Serves `hub://localhost/...` (`http://hub.localhost/...` on Windows): `/__frame` is the
/// newest live JPEG; `/lessons/...` is fetched from the paired hub with the player's Range
/// header. Nothing else is reachable.
fn hub_scheme(engine: &Engine, request: &Request<Vec<u8>>) -> Response<Vec<u8>> {
    let uri = request.uri();
    let path = uri.path();
    let builder = Response::builder().header("Access-Control-Allow-Origin", "*");
    if path == "/__frame" {
        return match engine.frame() {
            Some(jpeg) => builder
                .status(200)
                .header("Content-Type", "image/jpeg")
                .header("Cache-Control", "no-store")
                .body(jpeg.as_ref().clone()),
            None => builder.status(404).body(Vec::new()),
        }
        .unwrap_or_default();
    }
    let path_and_query = match uri.query() {
        Some(q) => format!("{path}?{q}"),
        None => path.to_string(),
    };
    let range = request.headers().get("Range").and_then(|v| v.to_str().ok());
    let file = engine.lesson_file(&path_and_query, range);
    let mut builder = builder.status(file.status);
    for (k, v) in &file.headers {
        builder = builder.header(k.as_str(), v.as_str());
    }
    builder.body(file.body).unwrap_or_default()
}

fn main() {
    let engine = Engine::start();
    let options = launch_args();
    let local_hub = Arc::new(Mutex::new(None));

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(AppState { engine: engine.clone(), launch: options, local_hub: local_hub.clone() })
        .invoke_handler(tauri::generate_handler![call, camera_frame, launch, notify, pick_video, ensure_local_hub])
        .register_asynchronous_uri_scheme_protocol("hub", {
            let engine = engine.clone();
            move |_ctx, request, responder| {
                let engine = engine.clone();
                // Lesson files come over the network; answer off the window's thread.
                std::thread::spawn(move || responder.respond(hub_scheme(&engine, &request)));
            }
        })
        .setup({
            let engine = engine.clone();
            move |app| {
                let handle = app.handle().clone();
                engine.set_emitter(Box::new(move |event| {
                    let _ = handle.emit("hub", event);
                }));
                Ok(())
            }
        })
        .build(tauri::generate_context!())
        .expect("the window could not start")
        .run(move |app, event| {
            match event {
                // On macOS, closing the last window normally leaves the application process (and WebKit audio)
                // alive. HandOver is a single-window app, so closing that window is an explicit full quit.
                tauri::RunEvent::WindowEvent { event: tauri::WindowEvent::CloseRequested { .. }, .. } => {
                    app.exit(0);
                }
                tauri::RunEvent::Exit => {
                    // Close the hub connection cleanly before the process ends.
                    engine.disconnect();
                    if let Ok(mut held) = local_hub.lock() {
                        if let Some(mut child) = held.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
                _ => {}
            }
        });
}
