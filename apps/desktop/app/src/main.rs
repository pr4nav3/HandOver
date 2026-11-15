//! The HandOver desktop app: one Tauri command, `call`, hands every UI request to the core
//! engine. This file adds only what needs a window: the `hub` URL scheme that feeds the video
//! player and the live image from the paired hub, system notifications, and launch options.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use handover_core::engine::Engine;
use serde_json::{json, Value};
use std::sync::Arc;
use tauri::http::{Request, Response};
use tauri::{Emitter, Manager};
use tauri_plugin_notification::NotificationExt;

struct AppState {
    engine: Arc<Engine>,
    launch: Value,
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

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(AppState { engine: engine.clone(), launch: options })
        .invoke_handler(tauri::generate_handler![call, camera_frame, launch, notify, pick_video])
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
        .run(move |_app, event| {
            if let tauri::RunEvent::Exit = event {
                // Close the hub connection cleanly before the process ends.
                engine.disconnect();
            }
        });
}
