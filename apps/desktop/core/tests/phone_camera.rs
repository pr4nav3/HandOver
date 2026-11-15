//! Pairing a phone (the address, the handover:// link, the QR) and this computer as the camera
//! (newest frame only, hello first, standby and replaced) against a small fake hub.

use handover_core::address::HubAddress;
use handover_core::api::Answer;
use handover_core::camera::{CameraLink, CameraSocket, Hello, LatestSlot};
use handover_core::phone::{connect_link, from_hub_info, is_loopback_host, phone_hub, qr_svg};
use std::net::{IpAddr, TcpListener};
use std::sync::mpsc::channel;
use std::sync::Arc;
use std::time::Duration;
use tungstenite::protocol::frame::coding::CloseCode;
use tungstenite::protocol::CloseFrame;
use tungstenite::Message;

#[test]
fn latest_slot_keeps_only_the_newest_frame() {
    let slot = LatestSlot::default();
    assert!(!slot.put(vec![1]));
    assert!(slot.put(vec![2]), "an untaken frame is dropped");
    assert!(slot.put(vec![3]));
    assert_eq!(slot.take(Duration::from_millis(10)), Some(vec![3]));
    assert_eq!(slot.take(Duration::from_millis(10)), None, "nothing is sent twice");
    assert!(!slot.put(vec![4]));
    slot.clear();
    assert_eq!(slot.take(Duration::from_millis(10)), None);
}

#[test]
fn latest_slot_wakes_a_waiting_taker() {
    let slot = Arc::new(LatestSlot::default());
    let s = slot.clone();
    let t = std::thread::spawn(move || s.take(Duration::from_secs(5)));
    std::thread::sleep(Duration::from_millis(50));
    slot.put(7u8);
    assert_eq!(t.join().unwrap(), Some(7));
}

#[test]
fn phone_address_and_link() {
    let lan: IpAddr = "192.168.1.20".parse().unwrap();
    let local = HubAddress::parse("127.0.0.1:8000").unwrap();
    assert_eq!(phone_hub(&local, Some(lan)).unwrap().base(), "http://192.168.1.20:8000");
    let named = HubAddress::parse("localhost:8099").unwrap();
    assert_eq!(phone_hub(&named, Some(lan)).unwrap().base(), "http://192.168.1.20:8099");
    assert!(phone_hub(&local, None).is_none(), "a loopback hub with no LAN address cannot pair a phone");
    let remote = HubAddress::parse("10.0.0.5:8000").unwrap();
    assert_eq!(phone_hub(&remote, Some(lan)).unwrap(), remote, "a LAN hub is used as is");
    assert!(is_loopback_host("[::1]"));
    assert!(is_loopback_host("LOCALHOST"));
    assert!(!is_loopback_host("hub.local"));

    let link = connect_link(&HubAddress::parse("192.168.1.20").unwrap());
    assert_eq!(link, "handover://connect?hub=http%3A%2F%2F192.168.1.20%3A8000");
    // The hub's own answer wins; a missing route or no LAN address falls back.
    let info = |status: u16, body: serde_json::Value| from_hub_info(&Answer { status, body });
    let good = serde_json::json!({ "hub_url": "http://10.0.0.7:8000", "pair_link": "handover://connect?hub=http%3A%2F%2F10.0.0.7%3A8000" });
    assert_eq!(info(200, good.clone()).unwrap().0, "http://10.0.0.7:8000");
    assert!(info(404, good).is_none());
    assert!(info(200, serde_json::json!({ "hub_url": null, "pair_link": null })).is_none());
    let svg = qr_svg(&link).unwrap();
    assert!(svg.starts_with("<?xml") && svg.contains("<svg") && svg.contains("#000000"));
}

#[test]
fn camera_sends_hello_then_frames_and_honors_the_hub() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let (tx, rx) = channel();
    let sink = Arc::new(move |l: CameraLink| {
        let _ = tx.send(l);
    });
    let hub = HubAddress::parse(&format!("127.0.0.1:{port}")).unwrap();
    let hello = Hello { device_id: "desktop-test".into(), name: "Mac camera".into(), platform: "macos".into() };
    let cam = CameraSocket::start(hub, hello, sink);
    let wait = |want: CameraLink| loop {
        if rx.recv_timeout(Duration::from_secs(5)).expect("camera event in time") == want {
            break;
        }
    };

    let (stream, _) = listener.accept().unwrap();
    let mut ws = tungstenite::accept(stream).unwrap();
    let first = ws.read().unwrap();
    let v: serde_json::Value = serde_json::from_str(first.to_text().unwrap()).unwrap();
    assert_eq!(v["type"], "hello");
    assert_eq!(v["device_id"], "desktop-test");
    assert_eq!(v["platform"], "macos");
    assert_eq!(v["source"], "browser");
    wait(CameraLink::Sending);

    cam.frame(vec![1, 2, 3, 4]); // not a JPEG: ignored
    let jpeg = vec![0xFF, 0xD8, 0xFF, 0xE0, 9, 9];
    cam.frame(jpeg.clone());
    assert_eq!(ws.read().unwrap(), Message::Binary(jpeg));

    ws.send(Message::Text(r#"{"type":"camera_status","active":false}"#.into())).unwrap();
    wait(CameraLink::Standby);
    ws.send(Message::Text(r#"{"type":"camera_status","active":true}"#.into())).unwrap();
    wait(CameraLink::Sending);

    ws.close(Some(CloseFrame { code: CloseCode::from(4000), reason: "replaced".into() })).unwrap();
    while ws.read().is_ok() {}
    wait(CameraLink::Replaced);
    drop(cam);
}
