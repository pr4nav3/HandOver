//! The /ws/ui connection against a small fake hub on 127.0.0.1: messages arrive typed, queued
//! commands are sent on open, a 1011 close reconnects at once, and a 4000 close stops.

use handover_core::address::HubAddress;
use handover_core::protocol::{ClientMessage, ServerMessage};
use handover_core::socket::{Link, SocketEvent, UiSocket};
use std::net::TcpListener;
use std::sync::mpsc::{channel, Receiver};
use std::sync::Arc;
use std::time::Duration;
use tungstenite::protocol::frame::coding::CloseCode;
use tungstenite::protocol::CloseFrame;
use tungstenite::Message;

const WAIT: Duration = Duration::from_secs(5);

fn next_where(rx: &Receiver<SocketEvent>, want: impl Fn(&SocketEvent) -> bool) -> SocketEvent {
    loop {
        let ev = rx.recv_timeout(WAIT).expect("event in time");
        if want(&ev) {
            return ev;
        }
    }
}

fn link(rx: &Receiver<SocketEvent>, l: Link) {
    next_where(rx, |e| matches!(e, SocketEvent::Link(s) if s.link == l));
}

fn close(ws: &mut tungstenite::WebSocket<std::net::TcpStream>, code: u16) {
    ws.close(Some(CloseFrame { code: CloseCode::from(code), reason: "".into() })).unwrap();
    // Read until the close handshake finishes.
    while ws.read().is_ok() {}
}

#[test]
fn messages_queue_reconnect_and_replaced() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let (tx, rx) = channel();
    let sink = Arc::new(move |ev: SocketEvent| {
        let _ = tx.send(ev);
    });
    let hub = HubAddress::parse(&format!("127.0.0.1:{port}")).unwrap();
    let sock = UiSocket::start(hub, sink);
    // Sent before the hub accepts: must arrive once connected.
    sock.send(&ClientMessage::SelectLesson { id: "demo-v1".into() });

    // First connection: a state, a frame, a bad message, then 1011.
    let (stream, _) = listener.accept().unwrap();
    let mut ws = tungstenite::accept(stream).unwrap();
    let first = ws.read().unwrap();
    assert_eq!(first, Message::Text(r#"{"type":"select_lesson","id":"demo-v1"}"#.into()));
    link(&rx, Link::Connected);
    ws.send(Message::Text("not json".into())).unwrap();
    ws.send(Message::Text(r#"{"type":"state","lesson_id":"demo-v1","step":2,"total":5,"status":"watching"}"#.into()))
        .unwrap();
    ws.send(Message::Binary(vec![0xFF, 0xD8, 0xFF, 0xE0, 1, 2])).unwrap();
    ws.send(Message::Binary(vec![1, 2, 3, 4])).unwrap();
    match next_where(&rx, |e| matches!(e, SocketEvent::Message(_))) {
        SocketEvent::Message(ServerMessage::State(s)) => assert_eq!(s.step, 2),
        other => panic!("expected state, got {other:?}"),
    }
    match next_where(&rx, |e| matches!(e, SocketEvent::Frame(_))) {
        SocketEvent::Frame(f) => assert_eq!(f[..2], [0xFF, 0xD8]),
        _ => unreachable!(),
    }
    close(&mut ws, 1011);
    match next_where(
        &rx,
        |e| matches!(e, SocketEvent::Link(s) if s.link == Link::Reconnecting && s.retry_in_ms.is_some()),
    ) {
        SocketEvent::Link(s) => {
            assert_eq!(s.retry_in_ms, Some(0), "1011 reconnects at once");
            assert_eq!(s.close_code, Some(1011));
        }
        _ => unreachable!(),
    }

    // Second connection: a command sent now goes straight out; then 4000 stops for good.
    let (stream, _) = listener.accept().unwrap();
    let mut ws = tungstenite::accept(stream).unwrap();
    link(&rx, Link::Connected);
    sock.send(&ClientMessage::Next { reason: "button", from: Some(2) });
    assert_eq!(ws.read().unwrap(), Message::Text(r#"{"type":"next","reason":"button","from":2}"#.into()));
    close(&mut ws, 4000);
    link(&rx, Link::Replaced);
    listener.set_nonblocking(true).unwrap();
    std::thread::sleep(Duration::from_millis(700));
    assert!(listener.accept().is_err(), "no reconnect after 4000");
    drop(sock);
}

#[test]
fn hub_down_keeps_retrying() {
    // Bind then drop, so the port is very likely closed.
    let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let (tx, rx) = channel();
    let sink = Arc::new(move |ev: SocketEvent| {
        let _ = tx.send(ev);
    });
    let sock = UiSocket::start(HubAddress::parse(&format!("127.0.0.1:{port}")).unwrap(), sink);
    link(&rx, Link::Connecting);
    let delays: Vec<u64> = (0..2)
        .map(|_| match next_where(&rx, |e| matches!(e, SocketEvent::Link(s) if s.retry_in_ms.is_some())) {
            SocketEvent::Link(s) => s.retry_in_ms.unwrap(),
            _ => unreachable!(),
        })
        .collect();
    assert_eq!(delays, [400, 800]);
    drop(sock);
}
