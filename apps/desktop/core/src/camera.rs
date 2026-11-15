//! This computer as the camera: one `/ws/camera` connection on its own thread. The window
//! captures its webcam and hands JPEGs to `CameraSocket::frame`; only the newest unsent frame is
//! kept, so a slow link drops frames instead of falling behind.

use crate::address::HubAddress;
use crate::backoff::Backoff;
use crate::protocol::{close_policy, is_jpeg, ClosePolicy};
use serde::Serialize;
use serde_json::json;
use std::io::ErrorKind;
use std::net::{TcpStream, ToSocketAddrs};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};
use tungstenite::{Message, WebSocket};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(3);
const IO_TIMEOUT: Duration = Duration::from_secs(5);
/// How long the thread waits for a new frame before it reads what the hub sent.
const WAIT: Duration = Duration::from_millis(40);
/// The hub ignores frames over 2 MB (CONTRACT.md 6).
pub const FRAME_MAX: usize = 2 * 1024 * 1024;

/// Holds at most one value: a new one replaces one that was not taken yet.
pub struct LatestSlot<T> {
    value: Mutex<Option<T>>,
    ready: Condvar,
}

impl<T> Default for LatestSlot<T> {
    fn default() -> Self {
        LatestSlot { value: Mutex::new(None), ready: Condvar::new() }
    }
}

impl<T> LatestSlot<T> {
    /// Stores `v`. Answers true when it replaced a value nobody took (that one is dropped).
    pub fn put(&self, v: T) -> bool {
        let dropped = self.value.lock().expect("slot lock").replace(v).is_some();
        self.ready.notify_one();
        dropped
    }

    /// The newest value, waiting up to `wait` for one.
    pub fn take(&self, wait: Duration) -> Option<T> {
        let guard = self.value.lock().expect("slot lock");
        let (mut guard, _) = self.ready.wait_timeout_while(guard, wait, |v| v.is_none()).expect("slot lock");
        guard.take()
    }

    pub fn clear(&self) {
        self.value.lock().expect("slot lock").take();
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CameraLink {
    Connecting,
    /// Connected and this camera's frames are the ones the hub judges.
    Sending,
    /// Connected, but another camera is active.
    Standby,
    Reconnecting,
    /// The hub closed with 4000: another connection with this device id took over.
    Replaced,
}

pub type CameraSink = Arc<dyn Fn(CameraLink) + Send + Sync>;

struct Shared {
    slot: LatestSlot<Vec<u8>>,
    stop: AtomicBool,
}

/// Owns the camera thread. Dropping it closes the connection.
pub struct CameraSocket {
    shared: Arc<Shared>,
}

/// Who this camera is, sent as `hello` on every open.
#[derive(Debug, Clone)]
pub struct Hello {
    pub device_id: String,
    pub name: String,
    /// `macos`, `windows` or `linux`.
    pub platform: String,
}

impl Hello {
    pub fn to_json(&self) -> String {
        json!({ "type": "hello", "device_id": self.device_id, "name": self.name, "platform": self.platform, "source": "browser" })
            .to_string()
    }
}

impl CameraSocket {
    pub fn start(hub: HubAddress, hello: Hello, sink: CameraSink) -> CameraSocket {
        let shared = Arc::new(Shared { slot: LatestSlot::default(), stop: AtomicBool::new(false) });
        let s = shared.clone();
        std::thread::Builder::new()
            .name("hub-camera".into())
            .spawn(move || run(hub, hello, s, sink))
            .expect("the camera thread could not start");
        CameraSocket { shared }
    }

    /// Queues one JPEG. Anything else, or anything too big, is ignored.
    pub fn frame(&self, jpeg: Vec<u8>) {
        if is_jpeg(&jpeg) && jpeg.len() <= FRAME_MAX {
            self.shared.slot.put(jpeg);
        }
    }
}

impl Drop for CameraSocket {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::SeqCst);
        self.shared.slot.ready.notify_one();
    }
}

fn run(hub: HubAddress, hello: Hello, shared: Arc<Shared>, sink: CameraSink) {
    let mut backoff = Backoff::new();
    let mut first = true;
    while !shared.stop.load(Ordering::SeqCst) {
        sink(if first { CameraLink::Connecting } else { CameraLink::Reconnecting });
        first = false;
        let policy = match open(&hub) {
            Ok(mut ws) => {
                backoff.reset();
                // Frames captured while the link was down are stale.
                shared.slot.clear();
                match serve(&mut ws, &hello, &shared, &sink) {
                    None => return,
                    Some(code) => close_policy(code),
                }
            }
            Err(_) => ClosePolicy::Backoff,
        };
        let Some(delay) = backoff.next_delay(policy) else {
            sink(CameraLink::Replaced);
            return;
        };
        let until = Instant::now() + delay;
        while Instant::now() < until {
            if shared.stop.load(Ordering::SeqCst) {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}

fn open(hub: &HubAddress) -> Result<WebSocket<TcpStream>, String> {
    let url = format!("ws://{}/ws/camera", hub.authority());
    let mut last = String::from("no address");
    for addr in hub.authority().to_socket_addrs().map_err(|e| e.to_string())? {
        match TcpStream::connect_timeout(&addr, CONNECT_TIMEOUT) {
            Ok(stream) => {
                stream.set_nodelay(true).ok();
                stream.set_read_timeout(Some(IO_TIMEOUT)).map_err(|e| e.to_string())?;
                stream.set_write_timeout(Some(IO_TIMEOUT)).map_err(|e| e.to_string())?;
                let (ws, _) = tungstenite::client(url.as_str(), stream).map_err(|e| e.to_string())?;
                ws.get_ref().set_read_timeout(Some(Duration::from_millis(2))).map_err(|e| e.to_string())?;
                return Ok(ws);
            }
            Err(e) => last = e.to_string(),
        }
    }
    Err(last)
}

/// Sends hello, then frames as they come. None when stopped; Some(close code) when the link ended.
fn serve(ws: &mut WebSocket<TcpStream>, hello: &Hello, shared: &Shared, sink: &CameraSink) -> Option<Option<u16>> {
    if ws.send(Message::Text(hello.to_json())).is_err() {
        return Some(None);
    }
    sink(CameraLink::Sending);
    let mut close_code = None;
    let mut got_close = false;
    loop {
        if shared.stop.load(Ordering::SeqCst) {
            let _ = ws.close(None);
            let _ = ws.flush();
            return None;
        }
        if let Some(jpeg) = shared.slot.take(WAIT) {
            if ws.send(Message::Binary(jpeg)).is_err() {
                return Some(close_code);
            }
        }
        // Read everything waiting: camera_status, state, pings (answered by tungstenite), close.
        loop {
            match ws.read() {
                Ok(Message::Text(text)) => {
                    if let Ok(v) = serde_json::from_str::<serde_json::Value>(&text) {
                        if v.get("type").and_then(|t| t.as_str()) == Some("camera_status") {
                            let active = v.get("active").and_then(|a| a.as_bool()).unwrap_or(true);
                            sink(if active { CameraLink::Sending } else { CameraLink::Standby });
                        }
                    }
                }
                Ok(Message::Close(frame)) => {
                    got_close = true;
                    close_code = frame.map(|f| u16::from(f.code));
                }
                Ok(_) => {}
                Err(tungstenite::Error::Io(e)) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {
                    // The close reply already went out; do not wait for the hub to drop TCP.
                    if got_close {
                        return Some(close_code);
                    }
                    break;
                }
                Err(_) => return Some(close_code),
            }
        }
    }
}
