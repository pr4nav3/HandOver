//! The hub's wire format (CONTRACT.md sections 3, 4 and 7), as typed Rust values.
//!
//! Readers follow the contract's compatibility rule: every field added after Revision 1 is
//! optional, unknown fields are ignored, and unknown message types or enum values never fail a
//! parse. A message that is not JSON, or not an object, is the only error.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// `state.status`. Values a newer hub may add read as `Unknown`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    #[default]
    Watching,
    Checking,
    Verified,
    Manual,
    Done,
    #[serde(other)]
    Unknown,
}

/// `last_check.done`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Verdict {
    Yes,
    No,
    #[serde(other)]
    Unsure,
}

/// Why camera checks are off (`check_offline_reason`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OfflineReason {
    NoKey,
    RateLimited,
    Errors,
    #[serde(other)]
    Other,
}

impl OfflineReason {
    /// The short words shown beside the "Checks off, use Next" badge. Same words as the web app.
    pub fn label(self) -> &'static str {
        match self {
            OfflineReason::NoKey => "No Gemini key",
            OfflineReason::RateLimited => "Rate limited",
            OfflineReason::Errors => "Check errors",
            OfflineReason::Other => "Checks unavailable",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LastCheck {
    pub done: Verdict,
    #[serde(default)]
    pub confidence: f64,
    #[serde(default)]
    pub latency_ms: u64,
    /// Up to 8 words on what differs from the reference. Shown at confidence 0.7 or more.
    #[serde(default)]
    pub reason: Option<String>,
}

/// A check reason is shown only when the model was at least this sure (CONTRACT.md 7).
pub const REASON_MIN_CONFIDENCE: f64 = 0.7;

impl LastCheck {
    /// The reason worth showing to the learner, if any: a confident "no" with words.
    pub fn shown_reason(&self) -> Option<&str> {
        let r = self.reason.as_deref()?.trim();
        (self.done == Verdict::No && self.confidence >= REASON_MIN_CONFIDENCE && !r.is_empty()).then_some(r)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Camera {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub platform: String,
    #[serde(default)]
    pub source: String,
}

impl Camera {
    /// Frames come from a recorded file, so the UI must say "Recording", never pass it as live.
    pub fn is_recording(&self) -> bool {
        self.source == "file"
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MistakeKind {
    Behind,
    Ahead,
    #[serde(other)]
    Unknown,
}

/// A mistake (CONTRACT.md 7.2), as sent alone or carried in `state.mistake`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Mistake {
    pub step: i64,
    pub kind: MistakeKind,
    #[serde(default)]
    pub looks_like: i64,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub confidence: f64,
    #[serde(default)]
    pub source: String,
}

/// The hub's `state` message. Fields from later revisions are optional; `None` means the hub
/// did not send the field (an older hub), which is different from an explicit null for
/// `mistake` and `camera`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct State {
    #[serde(default)]
    pub lesson_id: Option<String>,
    #[serde(default)]
    pub rev: i64,
    #[serde(default)]
    pub step: i64,
    #[serde(default)]
    pub total: i64,
    #[serde(default)]
    pub status: Status,
    #[serde(default)]
    pub last_check: Option<LastCheck>,
    #[serde(default)]
    pub camera_connected: bool,
    #[serde(default, deserialize_with = "explicit", skip_serializing_if = "Option::is_none")]
    pub camera: Option<Option<Camera>>,
    #[serde(default)]
    pub check_offline: bool,
    #[serde(default)]
    pub check_offline_reason: Option<OfflineReason>,
    #[serde(default, deserialize_with = "explicit", skip_serializing_if = "Option::is_none")]
    pub mistake: Option<Option<Mistake>>,
}

/// Keeps "absent" (outer None, from `default`) apart from "null" (Some(None)).
fn explicit<'de, D, T>(d: D) -> Result<Option<Option<T>>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(d).map(Some)
}

impl State {
    /// `position = total` when done, else `step` (CONTRACT.md 5).
    pub fn position(&self) -> i64 {
        if self.status == Status::Done {
            self.total
        } else {
            self.step
        }
    }

    /// The words for the checks-off reason, when checks are off.
    pub fn offline_label(&self) -> Option<&'static str> {
        if !self.check_offline {
            return None;
        }
        Some(self.check_offline_reason.unwrap_or(OfflineReason::Other).label())
    }

    /// The `from` value for next and back: the step the learner sees (stale guard, CONTRACT.md 5).
    pub fn shown_step(&self) -> i64 {
        self.step
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AdvanceReason {
    Camera,
    Button,
    Voice,
    #[serde(other)]
    Other,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Advance {
    pub from: i64,
    pub to: i64,
    pub reason: AdvanceReason,
}

/// One text message from `/ws/ui`.
#[derive(Debug, Clone, PartialEq)]
pub enum ServerMessage {
    State(Box<State>),
    Advance(Advance),
    Mistake(Mistake),
    Error(String),
    /// A type this client does not know, or a known type with fields it cannot read. Ignored.
    Unknown(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParseError {
    NotJson,
    NotObject,
}

impl std::fmt::Display for ParseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            ParseError::NotJson => "not JSON",
            ParseError::NotObject => "not a JSON object",
        })
    }
}

/// Reads one text message from `/ws/ui`. Unknown types and malformed known types come back as
/// `Unknown`, so one odd message never breaks the connection.
pub fn parse_server_message(text: &str) -> Result<ServerMessage, ParseError> {
    let value: Value = serde_json::from_str(text).map_err(|_| ParseError::NotJson)?;
    let obj = value.as_object().ok_or(ParseError::NotObject)?;
    let kind = obj.get("type").and_then(Value::as_str).unwrap_or("").to_string();
    let unknown = || ServerMessage::Unknown(kind.clone());
    Ok(match kind.as_str() {
        "state" => serde_json::from_value::<State>(value.clone())
            .map(|s| ServerMessage::State(Box::new(s)))
            .unwrap_or_else(|_| unknown()),
        "advance" => serde_json::from_value(value.clone()).map(ServerMessage::Advance).unwrap_or_else(|_| unknown()),
        "mistake" => serde_json::from_value(value.clone()).map(ServerMessage::Mistake).unwrap_or_else(|_| unknown()),
        "error" => ServerMessage::Error(
            obj.get("message")
                .and_then(Value::as_str)
                .filter(|m| !m.trim().is_empty())
                .unwrap_or("Something went wrong")
                .to_string(),
        ),
        _ => unknown(),
    })
}

/// A message to the hub on `/ws/ui` (CONTRACT.md 7).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    SelectLesson {
        id: String,
    },
    Next {
        reason: &'static str,
        #[serde(skip_serializing_if = "Option::is_none")]
        from: Option<i64>,
    },
    Back {
        #[serde(skip_serializing_if = "Option::is_none")]
        from: Option<i64>,
    },
    Goto {
        step: i64,
    },
    DismissMistake,
    /// Stops the run and unloads the lesson; every client gets a state with no lesson.
    EndLesson,
}

impl ClientMessage {
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("client messages always serialize")
    }
}

/// `GET /api/lessons` rows.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LessonSummary {
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub steps: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum CheckType {
    #[default]
    Camera,
    Manual,
    #[serde(other)]
    Other,
}

/// One step of lesson.json, with the contract's defaults filled in by `Lesson::parse`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Step {
    #[serde(default)]
    pub n: i64,
    #[serde(default)]
    pub title: String,
    pub start: String,
    pub end: String,
    #[serde(default)]
    pub clip: String,
    #[serde(default)]
    pub captions: String,
    #[serde(default)]
    pub ref_frame: String,
    #[serde(default)]
    pub check_type: CheckType,
    #[serde(default)]
    pub check_question: Option<String>,
    #[serde(default)]
    pub prerequisites: Vec<i64>,
    #[serde(default)]
    pub ref_time: Option<String>,
    #[serde(default)]
    pub common_mistake: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Lesson {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub video: String,
    #[serde(default)]
    pub steps: Vec<Step>,
    #[serde(default)]
    pub safety: Vec<String>,
    #[serde(default)]
    pub tools: Vec<String>,
}

impl Lesson {
    /// Reads lesson.json and applies the defaults in CONTRACT.md 3. `folder` is the lesson id
    /// the hub served it under, used when `id` or `title` is missing.
    pub fn parse(text: &str, folder: &str) -> Result<Lesson, String> {
        let mut lesson: Lesson = serde_json::from_str(text).map_err(|e| format!("lesson.json unreadable: {e}"))?;
        if lesson.id.is_empty() {
            lesson.id = folder.to_string();
        }
        if lesson.title.is_empty() {
            lesson.title = folder.to_string();
        }
        if lesson.video.is_empty() {
            lesson.video = "norm.mp4".into();
        }
        for (i, step) in lesson.steps.iter_mut().enumerate() {
            let nn = format!("{:02}", i + 1);
            if step.n <= 0 {
                step.n = i as i64 + 1;
            }
            if step.clip.is_empty() {
                step.clip = format!("clips/{nn}.mp4");
            }
            if step.captions.is_empty() {
                step.captions = format!("captions/{nn}.vtt");
            }
            if step.ref_frame.is_empty() {
                step.ref_frame = format!("frames/{nn}.jpg");
            }
            if step.check_question.is_none() && step.check_type == CheckType::Camera {
                step.check_question = Some("Is this step finished?".into());
            }
        }
        Ok(lesson)
    }
}

/// `"MM:SS"`, `"MM:SS.s"`, `"HH:MM:SS"` or plain seconds, to seconds (CONTRACT.md 3).
pub fn timestamp_seconds(ts: &str) -> Option<f64> {
    let ts = ts.trim();
    if ts.is_empty() {
        return None;
    }
    let parts: Vec<&str> = ts.split(':').collect();
    if parts.len() > 3 {
        return None;
    }
    let mut total = 0.0;
    for (i, part) in parts.iter().enumerate() {
        let v: f64 = part.parse().ok()?;
        if !v.is_finite() || v < 0.0 || (i > 0 && v >= 60.0) {
            return None;
        }
        total = total * 60.0 + v;
    }
    Some(total)
}

/// What a close code from the hub means for reconnecting (CONTRACT.md 6, proposals P15).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClosePolicy {
    /// 4000 `replaced`: another connection took over this one. Stay closed.
    Stop,
    /// 1011: the hub gave up on a stalled send. Reconnect at once.
    Immediately,
    /// 1013: the hub is full. Reconnect, slowly.
    SlowBackoff,
    /// Anything else, or no close frame: reconnect with the normal back-off.
    Backoff,
}

pub fn close_policy(code: Option<u16>) -> ClosePolicy {
    match code {
        Some(4000) => ClosePolicy::Stop,
        Some(1011) => ClosePolicy::Immediately,
        Some(1013) => ClosePolicy::SlowBackoff,
        _ => ClosePolicy::Backoff,
    }
}

/// True when binary data looks like one JPEG (CONTRACT.md 7: binary messages are live frames).
pub fn is_jpeg(data: &[u8]) -> bool {
    data.len() > 3 && data[0] == 0xFF && data[1] == 0xD8
}
