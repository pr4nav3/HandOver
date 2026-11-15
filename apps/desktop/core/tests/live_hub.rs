//! Against a real hub, when one is named: `HANDOVER_TEST_HUB=127.0.0.1:8099 cargo test --test live_hub`.
//! Start the hub in mock mode first (README.md). Without the variable these tests pass at once.

use handover_core::engine::Engine;
use serde_json::{json, Value};
use std::sync::mpsc::channel;
use std::time::{Duration, Instant};

fn hub() -> Option<String> {
    std::env::var("HANDOVER_TEST_HUB").ok().filter(|v| !v.is_empty())
}

#[test]
fn pair_select_and_follow_state() {
    let Some(address) = hub() else { return };
    let dir = std::env::temp_dir().join(format!("handover-desktop-live-{}", std::process::id()));
    let engine = Engine::with_dir(dir.clone());
    let (tx, rx) = channel::<Value>();
    engine.set_emitter(Box::new(move |v| {
        let _ = tx.send(v);
    }));

    let wrong = engine.call("connect", &json!({ "address": "127.0.0.1:1" }));
    assert!(wrong.unwrap_err().contains("No hub answered"));

    let r: Value = serde_json::from_str(&engine.call("connect", &json!({ "address": address })).unwrap()).unwrap();
    let lessons = r["lessons"].as_array().unwrap();
    assert!(!lessons.is_empty(), "the hub has lessons");
    let id = lessons[0]["id"].as_str().unwrap().to_string();
    assert_eq!(r["recent"][0]["base"], r["hub"]);

    let wait_for = |want: &dyn Fn(&Value) -> bool| {
        let until = Instant::now() + Duration::from_secs(10);
        loop {
            let left = until.checked_duration_since(Instant::now()).expect("event in time");
            let v = rx.recv_timeout(left).expect("event in time");
            if want(&v) {
                return v;
            }
        }
    };
    wait_for(&|v| v["kind"] == "link" && v["link"]["link"] == "connected");
    engine.call("selectLesson", &json!({ "id": id })).unwrap();
    let s = wait_for(&|v| v["kind"] == "state" && v["state"]["lesson_id"] == json!(id) && v["state"]["step"] == 0);
    let total = s["state"]["total"].as_i64().unwrap();
    assert!(total > 0);
    assert!(s["state"].get("offline_label").is_some());

    // Next with a stale `from` is ignored by the hub; with the right one it advances.
    engine.call("next", &json!({ "from": 3 })).unwrap();
    engine.call("next", &json!({ "from": 0 })).unwrap();
    let a = wait_for(&|v| v["kind"] == "advance");
    assert_eq!((a["advance"]["from"].as_i64(), a["advance"]["to"].as_i64()), (Some(0), Some(1)));
    assert_eq!(a["advance"]["reason"], "button");
    wait_for(&|v| v["kind"] == "state" && v["state"]["step"] == 1);
    engine.call("back", &json!({ "from": 1 })).unwrap();
    wait_for(&|v| v["kind"] == "state" && v["state"]["step"] == 0);

    // Revision 6: the check interval is a hub setting every state carries.
    assert!(s["state"]["ui_fps"].as_i64().is_some_and(|f| (1..=30).contains(&f)));
    engine.call("setCheckInterval", &json!({ "seconds": 2 })).unwrap();
    wait_for(&|v| v["kind"] == "state" && v["state"]["check_interval_s"] == 2.0);
    engine.call("setCheckInterval", &json!({ "seconds": 1 })).unwrap();
    wait_for(&|v| v["kind"] == "state" && v["state"]["check_interval_s"] == 1.0);
    assert!(engine.call("setCheckInterval", &json!({ "seconds": "fast" })).is_err());

    // The lesson and a clip, with a range request as the video player sends it.
    let lesson: Value = serde_json::from_str(&engine.call("lesson", &json!({ "id": id })).unwrap()).unwrap();
    let clip = lesson["steps"][0]["clip"].as_str().unwrap();
    let f = engine.lesson_file(&format!("/lessons/{id}/{clip}?v=1"), Some("bytes=0-1023"));
    assert_eq!(f.status, 206);
    assert_eq!(f.body.len(), 1024);
    assert!(f.headers.iter().any(|(k, v)| k == "Content-Range" && v.starts_with("bytes 0-1023/")));
    let captions = lesson["steps"][0]["captions"].as_str().unwrap();
    let vtt = engine.lesson_file(&format!("/lessons/{id}/{captions}"), None);
    assert_eq!(vtt.status, 200);
    assert!(String::from_utf8_lossy(&vtt.body).starts_with("WEBVTT"));
    // Nothing outside lesson files is reachable through the player's scheme.
    assert_eq!(engine.lesson_file("/api/lessons", None).status, 404);
    assert_eq!(engine.lesson_file(&format!("/lessons/{id}/../../etc/passwd"), None).status, 404);

    // End unloads the lesson for every screen.
    engine.call("endLesson", &json!({ "lessonId": id })).unwrap();
    wait_for(&|v| v["kind"] == "state" && v["state"]["lesson_id"].is_null());

    engine.disconnect();
    wait_for(&|v| v["kind"] == "link" && v["link"]["link"] == "idle");
    assert!(engine.call("next", &json!({})).is_err());
    let _ = std::fs::remove_dir_all(dir);
}

/// The library routes through the core, when the hub serves them: sign-in token handling.
#[test]
fn library_passthrough_keeps_token_inside() {
    let Some(address) = hub() else { return };
    let dir = std::env::temp_dir().join(format!("handover-desktop-live-lib-{}", std::process::id()));
    let engine = Engine::with_dir(dir.clone());
    engine.call("connect", &json!({ "address": address })).unwrap();
    let me: Value =
        serde_json::from_str(&engine.call("api", &json!({ "method": "GET", "path": "/api/me" })).unwrap()).unwrap();
    if me["status"] == 404 {
        return; // A hub without the library routes.
    }
    assert_eq!(me["ok"], true);
    let bad: Value = serde_json::from_str(
        &engine.call("api", &json!({ "method": "POST", "path": "/api/auth/login", "body": { "name": "nobody", "passcode": "wrong-pass" } })).unwrap(),
    )
    .unwrap();
    assert_eq!(bad["ok"], false);
    assert!(bad["data"]["detail"].as_str().is_some());
    assert!(engine.call("api", &json!({ "method": "PUT", "path": "/api/me" })).is_err());
    assert!(engine.call("api", &json!({ "method": "GET", "path": "/lessons/x" })).is_err());
    let courses: Value = serde_json::from_str(
        &engine.call("api", &json!({ "method": "GET", "path": "/api/courses", "query": { "filter": "all" } })).unwrap(),
    )
    .unwrap();
    assert_eq!(courses["ok"], true);
    assert!(courses["data"].as_array().is_some());
    engine.disconnect();
    let _ = std::fs::remove_dir_all(dir);
}

/// This computer as the camera, on a real hub: hello makes it the active camera with its name, and a newer
/// connection with the same device id closes it with 4000, after which it stays closed.
#[test]
fn computer_camera_hello_frames_and_replaced() {
    use handover_core::address::HubAddress;
    use handover_core::camera::{CameraLink, CameraSocket, Hello};
    use std::sync::Arc;
    let Some(address) = hub() else { return };
    let dir = std::env::temp_dir().join(format!("handover-desktop-live-cam-{}", std::process::id()));
    let engine = Engine::with_dir(dir.clone());
    let (tx, rx) = channel::<Value>();
    engine.set_emitter(Box::new(move |v| {
        let _ = tx.send(v);
    }));
    let r: Value = serde_json::from_str(&engine.call("connect", &json!({ "address": address })).unwrap()).unwrap();
    let id = r["lessons"][0]["id"].as_str().unwrap().to_string();
    let jpeg = engine.lesson_file(&format!("/lessons/{id}/frames/01.jpg"), None).body;
    assert_eq!(&jpeg[..2], &[0xFF, 0xD8]);

    let hub = HubAddress::parse(&address).unwrap();
    let name = format!("Live test camera {}", std::process::id());
    let hello = || Hello {
        device_id: format!("desktop-live-{}", std::process::id()),
        name: name.clone(),
        platform: "macos".into(),
    };
    let (ltx, lrx) = channel::<CameraLink>();
    let first = CameraSocket::start(
        hub.clone(),
        hello(),
        Arc::new(move |l| {
            let _ = ltx.send(l);
        }),
    );
    let until = Instant::now() + Duration::from_secs(10);
    loop {
        first.frame(jpeg.clone());
        if let Ok(v) = rx.recv_timeout(Duration::from_millis(80)) {
            if v["kind"] == "state" && v["state"]["camera"]["name"] == json!(name) {
                assert_eq!(v["state"]["camera"]["source"], "browser");
                assert_eq!(v["state"]["camera_connected"], true);
                break;
            }
        }
        assert!(Instant::now() < until, "the hub never showed this camera");
    }

    let second = CameraSocket::start(hub, hello(), Arc::new(|_| {}));
    let until = Instant::now() + Duration::from_secs(10);
    loop {
        second.frame(jpeg.clone());
        if lrx.recv_timeout(Duration::from_millis(80)) == Ok(CameraLink::Replaced) {
            break;
        }
        assert!(Instant::now() < until, "the first camera was never replaced");
    }
    // Replaced means stopped: no reconnect follows.
    std::thread::sleep(Duration::from_secs(2));
    assert!(lrx.try_iter().all(|l| l == CameraLink::Replaced));
    drop(second);
    drop(first);
    engine.disconnect();
    let _ = std::fs::remove_dir_all(dir);
}
