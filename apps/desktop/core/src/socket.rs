//! One `/ws/ui` connection to the hub, kept open on its own thread: reconnects with back-off,
//! honors the hub's close codes, queues commands sent while it is down, and notices a hub that
//! went silent (the hub pings every 10 s, so 30 s of nothing means the link is dead).

use crate::address::HubAddress;
use crate::backoff::Backoff;
use crate::protocol::{close_policy, is_jpeg, parse_server_message, ClientMessage, ClosePolicy, ServerMessage};
use serde::Serialize;
use std::collections::VecDeque;
use std::io::ErrorKind;
use std::net::{TcpStream, ToSocketAddrs};
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError, Sender, TryRecvError};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};
use tungstenite::{Message, WebSocket};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);
/// How often the thread looks for commands to send while waiting for the hub.
const POLL: Duration = Duration::from_millis(50);
/// Silence longer than this (three missed pings) means the connection is gone.
const SILENCE_LIMIT: Duration = Duration::from_secs(30);
/// Commands sent while disconnected wait here, oldest dropped first (as in the web app).
pub const QUEUE_MAX: usize = 20;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Link {
    /// The first try for this hub.
    Connecting,
    Connected,
    /// The connection dropped or a try failed; another try is scheduled.
    Reconnecting,
    /// The hub closed with 4000: another connection replaced this one. No more tries.
    Replaced,
    /// Not connected to any hub.
    Idle,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct LinkStatus {
    pub link: Link,
    /// `http://host:port`, empty when idle.
    pub hub: String,
    /// Host, plus the port when it is not 8000.
    pub label: String,
    /// Failed tries since the last open.
    pub attempt: u32,
    /// When reconnecting: milliseconds until the next try.
    pub retry_in_ms: Option<u64>,
    /// The last close code from the hub, if it sent one.
    pub close_code: Option<u16>,
}

impl LinkStatus {
    pub fn idle() -> LinkStatus {
        LinkStatus {
            link: Link::Idle,
            hub: String::new(),
            label: String::new(),
            attempt: 0,
            retry_in_ms: None,
            close_code: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum SocketEvent {
    Link(LinkStatus),
    Message(ServerMessage),
    /// One live JPEG from the active camera.
    Frame(Vec<u8>),
}

pub type Sink = Arc<dyn Fn(SocketEvent) + Send + Sync>;

enum Control {
    Send(String),
    Stop,
}

/// Owns the connection thread. Dropping it closes the connection and ends the thread.
pub struct UiSocket {
    tx: Sender<Control>,
    thread: Option<JoinHandle<()>>,
}

impl UiSocket {
    pub fn start(hub: HubAddress, sink: Sink) -> UiSocket {
        let (tx, rx) = channel();
        let thread = std::thread::Builder::new()
            .name("hub-socket".into())
            .spawn(move || run(hub, rx, sink))
            .expect("the socket thread could not start");
        UiSocket { tx, thread: Some(thread) }
    }

    /// Sends now when connected, else queues for the next connection.
    pub fn send(&self, msg: &ClientMessage) {
        let _ = self.tx.send(Control::Send(msg.to_json()));
    }
}

impl Drop for UiSocket {
    fn drop(&mut self) {
        let _ = self.tx.send(Control::Stop);
        // The thread notices within one poll or connect timeout; do not block the caller on it.
        drop(self.thread.take());
    }
}

fn push(queue: &mut VecDeque<String>, text: String) {
    queue.push_back(text);
    while queue.len() > QUEUE_MAX {
        queue.pop_front();
    }
}

enum Exit {
    Stopped,
    Closed(Option<u16>),
}

fn run(hub: HubAddress, rx: Receiver<Control>, sink: Sink) {
    let mut backoff = Backoff::new();
    let mut queue: VecDeque<String> = VecDeque::new();
    let mut ever_connected = false;
    let mut close_code = None;
    let status = |link, attempt, retry_in_ms, close_code| {
        sink(SocketEvent::Link(LinkStatus {
            link,
            hub: hub.base(),
            label: hub.display(),
            attempt,
            retry_in_ms,
            close_code,
        }))
    };
    loop {
        // Commands that arrived while waiting are kept; a stop ends the thread.
        loop {
            match rx.try_recv() {
                Ok(Control::Send(t)) => push(&mut queue, t),
                Ok(Control::Stop) | Err(TryRecvError::Disconnected) => return,
                Err(TryRecvError::Empty) => break,
            }
        }
        status(if ever_connected { Link::Reconnecting } else { Link::Connecting }, backoff.attempt(), None, close_code);
        let policy = match open(&hub) {
            Ok(mut ws) => {
                ever_connected = true;
                backoff.reset();
                status(Link::Connected, 0, None, None);
                match serve(&mut ws, &rx, &mut queue, &sink) {
                    Exit::Stopped => return,
                    Exit::Closed(code) => {
                        close_code = code;
                        close_policy(code)
                    }
                }
            }
            Err(_) => ClosePolicy::Backoff,
        };
        let Some(delay) = backoff.next_delay(policy) else {
            status(Link::Replaced, backoff.attempt(), None, close_code);
            // Stay quiet until the app stops this socket or starts a new one.
            loop {
                match rx.recv() {
                    Ok(Control::Send(_)) => {}
                    Ok(Control::Stop) | Err(_) => return,
                }
            }
        };
        status(Link::Reconnecting, backoff.attempt(), Some(delay.as_millis() as u64), close_code);
        let until = Instant::now() + delay;
        while let Some(left) = until.checked_duration_since(Instant::now()) {
            match rx.recv_timeout(left) {
                Ok(Control::Send(t)) => push(&mut queue, t),
                Ok(Control::Stop) | Err(RecvTimeoutError::Disconnected) => return,
                Err(RecvTimeoutError::Timeout) => break,
            }
        }
    }
}

fn open(hub: &HubAddress) -> Result<WebSocket<TcpStream>, String> {
    let addrs = hub.authority().to_socket_addrs().map_err(|e| e.to_string())?;
    let mut last = String::from("no address");
    for addr in addrs {
        match TcpStream::connect_timeout(&addr, CONNECT_TIMEOUT) {
            Ok(stream) => {
                stream.set_nodelay(true).ok();
                stream.set_read_timeout(Some(HANDSHAKE_TIMEOUT)).map_err(|e| e.to_string())?;
                stream.set_write_timeout(Some(HANDSHAKE_TIMEOUT)).map_err(|e| e.to_string())?;
                let (ws, _) = tungstenite::client(hub.ui_socket(), stream).map_err(|e| e.to_string())?;
                ws.get_ref().set_read_timeout(Some(POLL)).map_err(|e| e.to_string())?;
                return Ok(ws);
            }
            Err(e) => last = e.to_string(),
        }
    }
    Err(last)
}

fn serve(ws: &mut WebSocket<TcpStream>, rx: &Receiver<Control>, queue: &mut VecDeque<String>, sink: &Sink) -> Exit {
    while let Some(text) = queue.pop_front() {
        if ws.send(Message::Text(text.clone())).is_err() {
            queue.push_front(text);
            return Exit::Closed(None);
        }
    }
    let mut heard = Instant::now();
    let mut close_code = None;
    let mut got_close = false;
    loop {
        loop {
            match rx.try_recv() {
                Ok(Control::Send(text)) => {
                    if ws.send(Message::Text(text.clone())).is_err() {
                        push(queue, text);
                        return Exit::Closed(None);
                    }
                }
                Ok(Control::Stop) | Err(TryRecvError::Disconnected) => {
                    let _ = ws.close(None);
                    let _ = ws.flush();
                    return Exit::Stopped;
                }
                Err(TryRecvError::Empty) => break,
            }
        }
        match ws.read() {
            Ok(msg) => {
                heard = Instant::now();
                match msg {
                    Message::Text(text) => {
                        // Text that is not a JSON object is ignored (CONTRACT.md 7).
                        if let Ok(m) = parse_server_message(&text) {
                            sink(SocketEvent::Message(m));
                        }
                    }
                    Message::Binary(data) if is_jpeg(&data) => sink(SocketEvent::Frame(data)),
                    Message::Close(frame) => {
                        got_close = true;
                        close_code = frame.map(|f| u16::from(f.code));
                    }
                    _ => {}
                }
            }
            Err(tungstenite::Error::Io(e)) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {
                // After a close frame, this read already sent the reply; do not wait for the hub
                // to drop the TCP connection.
                if got_close {
                    return Exit::Closed(close_code);
                }
                if heard.elapsed() > SILENCE_LIMIT {
                    return Exit::Closed(None);
                }
            }
            Err(tungstenite::Error::ConnectionClosed | tungstenite::Error::AlreadyClosed) => {
                return Exit::Closed(close_code)
            }
            Err(_) => return Exit::Closed(close_code),
        }
    }
}
