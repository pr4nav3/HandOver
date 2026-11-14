//! How long to wait before reconnecting. Same curve as the web app (web/src/useUiSocket.ts):
//! 0.4 s doubling to a 5 s cap, reset by a connection that opened.

use crate::protocol::ClosePolicy;
use std::time::Duration;

const BASE_MS: u64 = 400;
const CAP_MS: u64 = 5_000;
/// A full hub (close 1013) is asked again less often.
const FULL_BASE_MS: u64 = 2_000;
const FULL_CAP_MS: u64 = 15_000;

#[derive(Debug, Default, Clone)]
pub struct Backoff {
    attempt: u32,
}

impl Backoff {
    pub fn new() -> Backoff {
        Backoff { attempt: 0 }
    }

    /// The connection opened: the next drop starts the curve again.
    pub fn reset(&mut self) {
        self.attempt = 0;
    }

    /// Failed attempts since the last open.
    pub fn attempt(&self) -> u32 {
        self.attempt
    }

    /// The wait before the next try, or None to stay closed.
    pub fn next_delay(&mut self, policy: ClosePolicy) -> Option<Duration> {
        let n = self.attempt.min(16);
        self.attempt = self.attempt.saturating_add(1);
        let ms = match policy {
            ClosePolicy::Stop => return None,
            // Only the first retry is instant, so a hub that keeps closing 1011 is not hammered.
            ClosePolicy::Immediately if n == 0 => 0,
            ClosePolicy::Immediately | ClosePolicy::Backoff => (BASE_MS << n).min(CAP_MS),
            ClosePolicy::SlowBackoff => (FULL_BASE_MS << n).min(FULL_CAP_MS),
        };
        Some(Duration::from_millis(ms))
    }
}
