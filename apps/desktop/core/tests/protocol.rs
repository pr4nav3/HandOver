//! Protocol parsing, against the JSON samples in CONTRACT.md (fixtures/*_contract.json) and the
//! compatibility rules around them: older hubs, newer hubs, and junk.

use handover_core::engine::state_json;
use handover_core::protocol::*;

fn fixture(name: &str) -> String {
    std::fs::read_to_string(format!("{}/tests/fixtures/{name}", env!("CARGO_MANIFEST_DIR"))).expect("fixture exists")
}

fn state(name: &str) -> State {
    match parse_server_message(&fixture(name)).expect("parses") {
        ServerMessage::State(s) => *s,
        other => panic!("expected state, got {other:?}"),
    }
}

#[test]
fn contract_state_sample() {
    let s = state("state_contract.json");
    assert_eq!(s.lesson_id.as_deref(), Some("fortune-teller-v1"));
    assert_eq!(s.rev, 1_763_154_180_123);
    assert_eq!((s.step, s.total, s.position()), (4, 8, 4));
    assert_eq!(s.status, Status::Watching);
    let lc = s.last_check.as_ref().expect("last_check");
    assert_eq!(lc.done, Verdict::No);
    assert!((lc.confidence - 0.82).abs() < 1e-9);
    assert_eq!(lc.latency_ms, 910);
    assert_eq!(lc.shown_reason(), Some("seams still facing up"));
    assert!(s.camera_connected);
    let cam = s.camera.clone().expect("present").expect("not null");
    assert_eq!(cam.name, "Ray-Ban Meta via iPhone");
    assert_eq!((cam.platform.as_str(), cam.source.as_str()), ("ios", "glasses"));
    assert!(!cam.is_recording());
    assert!(!s.check_offline);
    assert_eq!(s.check_offline_reason, None);
    assert_eq!(s.offline_label(), None);
    // Present and null, which is not the same as absent.
    assert_eq!(s.mistake, Some(None));
}

#[test]
fn contract_mistake_sample() {
    let m = match parse_server_message(&fixture("mistake_contract.json")).unwrap() {
        ServerMessage::Mistake(m) => m,
        other => panic!("expected mistake, got {other:?}"),
    };
    assert_eq!(m.step, 4);
    assert_eq!(m.kind, MistakeKind::Behind);
    assert_eq!(m.looks_like, 3);
    assert_eq!(m.message, "Flip it over first.");
    assert!((m.confidence - 0.86).abs() < 1e-9);
    assert_eq!(m.source, "gemini");
}

#[test]
fn contract_advance_sample() {
    let a = parse_server_message(&fixture("advance_contract.json")).unwrap();
    assert_eq!(a, ServerMessage::Advance(Advance { from: 4, to: 5, reason: AdvanceReason::Camera }));
}

#[test]
fn advance_with_new_reason_still_reads() {
    let a = parse_server_message(r#"{"type":"advance","from":0,"to":1,"reason":"timer"}"#).unwrap();
    assert_eq!(a, ServerMessage::Advance(Advance { from: 0, to: 1, reason: AdvanceReason::Other }));
}

#[test]
fn revision_one_state_has_no_new_fields() {
    let s = state("state_revision1.json");
    assert_eq!(s.status, Status::Manual);
    assert_eq!(s.rev, 0);
    assert_eq!(s.camera, None, "absent, not null");
    assert_eq!(s.mistake, None, "absent, not null");
    assert!(!s.check_offline);
    // The window gets no `mistake` key, so it keeps the one it has (web/src/Learn.tsx rule).
    let v = state_json(&s);
    assert!(v.get("mistake").is_none());
    assert!(v.get("camera").is_none());
}

#[test]
fn checks_off_reason_and_recording() {
    let s = state("state_offline.json");
    assert!(s.check_offline);
    assert_eq!(s.check_offline_reason, Some(OfflineReason::RateLimited));
    assert_eq!(s.offline_label(), Some("Rate limited"));
    assert!(s.camera.clone().unwrap().unwrap().is_recording());
    let m = s.mistake.clone().unwrap().unwrap();
    assert_eq!((m.kind, m.looks_like, m.source.as_str()), (MistakeKind::Behind, 0, "mock"));
    // An unsure check never shows a reason.
    assert_eq!(s.last_check.as_ref().unwrap().shown_reason(), None);
    let v = state_json(&s);
    assert_eq!(v["offline_label"], "Rate limited");
    assert_eq!(v["check_reason"], serde_json::Value::Null);
    assert_eq!(v["mistake"]["message"], "This still looks like step 1.");
}

#[test]
fn every_offline_reason_has_words() {
    for (raw, words) in [
        ("no_key", "No Gemini key"),
        ("rate_limited", "Rate limited"),
        ("errors", "Check errors"),
        ("melted", "Checks unavailable"),
    ] {
        let text = format!(
            r#"{{"type":"state","step":0,"total":1,"status":"watching","check_offline":true,"check_offline_reason":"{raw}"}}"#
        );
        let ServerMessage::State(s) = parse_server_message(&text).unwrap() else { panic!("state") };
        assert_eq!(s.offline_label(), Some(words), "{raw}");
    }
    // Off with no reason still says something.
    let ServerMessage::State(s) =
        parse_server_message(r#"{"type":"state","check_offline":true,"check_offline_reason":null}"#).unwrap()
    else {
        panic!("state")
    };
    assert_eq!(s.offline_label(), Some("Checks unavailable"));
}

#[test]
fn no_lesson_state() {
    let s = state("state_no_lesson.json");
    assert_eq!(s.lesson_id, None);
    assert_eq!((s.step, s.total, s.status), (0, 0, Status::Watching));
    assert_eq!(s.camera, Some(None));
}

#[test]
fn done_position_is_total() {
    let ServerMessage::State(s) =
        parse_server_message(r#"{"type":"state","lesson_id":"a","step":7,"total":8,"status":"done"}"#).unwrap()
    else {
        panic!("state")
    };
    assert_eq!(s.position(), 8);
    assert_eq!(s.shown_step(), 7);
}

#[test]
fn unknown_status_does_not_fail() {
    let ServerMessage::State(s) = parse_server_message(r#"{"type":"state","status":"pondering"}"#).unwrap() else {
        panic!("state")
    };
    assert_eq!(s.status, Status::Unknown);
}

#[test]
fn reason_needs_a_confident_no() {
    let lc = |done: Verdict, confidence: f64, reason: Option<&str>| LastCheck {
        done,
        confidence,
        latency_ms: 0,
        reason: reason.map(str::to_string),
    };
    assert_eq!(lc(Verdict::No, 0.7, Some("corner up")).shown_reason(), Some("corner up"));
    assert_eq!(lc(Verdict::No, 0.69, Some("corner up")).shown_reason(), None);
    assert_eq!(lc(Verdict::Yes, 0.95, Some("corner up")).shown_reason(), None);
    assert_eq!(lc(Verdict::No, 0.9, Some("   ")).shown_reason(), None);
    assert_eq!(lc(Verdict::No, 0.9, None).shown_reason(), None);
}

#[test]
fn error_and_unknown_and_junk() {
    assert_eq!(
        parse_server_message(r#"{"type":"error","message":"no lesson selected"}"#).unwrap(),
        ServerMessage::Error("no lesson selected".into())
    );
    assert_eq!(
        parse_server_message(r#"{"type":"error"}"#).unwrap(),
        ServerMessage::Error("Something went wrong".into())
    );
    assert_eq!(
        parse_server_message(r#"{"type":"camera_status","active":true}"#).unwrap(),
        ServerMessage::Unknown("camera_status".into())
    );
    // A known type with unreadable fields is ignored, not an error.
    assert_eq!(
        parse_server_message(r#"{"type":"advance","from":"x"}"#).unwrap(),
        ServerMessage::Unknown("advance".into())
    );
    assert_eq!(parse_server_message("not json"), Err(ParseError::NotJson));
    assert_eq!(parse_server_message("[1,2]"), Err(ParseError::NotObject));
    assert_eq!(parse_server_message(r#"{"no":"type"}"#).unwrap(), ServerMessage::Unknown(String::new()));
}

#[test]
fn client_messages_match_contract() {
    assert_eq!(
        ClientMessage::SelectLesson { id: "demo-v1".into() }.to_json(),
        r#"{"type":"select_lesson","id":"demo-v1"}"#
    );
    assert_eq!(
        ClientMessage::Next { reason: "button", from: Some(3) }.to_json(),
        r#"{"type":"next","reason":"button","from":3}"#
    );
    assert_eq!(ClientMessage::Next { reason: "voice", from: None }.to_json(), r#"{"type":"next","reason":"voice"}"#);
    assert_eq!(ClientMessage::Back { from: Some(2) }.to_json(), r#"{"type":"back","from":2}"#);
    assert_eq!(ClientMessage::Goto { step: 0 }.to_json(), r#"{"type":"goto","step":0}"#);
    assert_eq!(ClientMessage::DismissMistake.to_json(), r#"{"type":"dismiss_mistake"}"#);
    assert_eq!(ClientMessage::EndLesson.to_json(), r#"{"type":"end_lesson"}"#);
}

#[test]
fn lesson_defaults() {
    let l = Lesson::parse(&fixture("lesson_minimal.json"), "fold-v1").unwrap();
    assert_eq!((l.id.as_str(), l.title.as_str(), l.video.as_str()), ("fold-v1", "fold-v1", "norm.mp4"));
    assert_eq!(l.safety, vec!["Mind the blade"]);
    assert_eq!(l.tools, vec!["Scissors"]);
    let a = &l.steps[0];
    assert_eq!(a.n, 1);
    assert_eq!(
        (a.clip.as_str(), a.captions.as_str(), a.ref_frame.as_str()),
        ("clips/01.mp4", "captions/01.vtt", "frames/01.jpg")
    );
    assert_eq!(a.check_type, CheckType::Camera);
    assert_eq!(a.check_question.as_deref(), Some("Is this step finished?"));
    let b = &l.steps[1];
    assert_eq!(b.check_type, CheckType::Manual);
    assert_eq!(b.check_question.as_deref(), Some(""));
    assert_eq!(b.prerequisites, vec![1]);
    assert_eq!(b.common_mistake, "Flip it over first.");
    assert_eq!(b.ref_time.as_deref(), Some("00:15.0"));
    assert_eq!(b.clip, "clips/02.mp4");
}

#[test]
fn real_lessons_in_the_repo_parse() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../lessons");
    let mut seen = 0;
    for entry in std::fs::read_dir(&dir).into_iter().flatten().flatten() {
        let path = entry.path().join("lesson.json");
        let Ok(text) = std::fs::read_to_string(&path) else { continue };
        let id = entry.file_name().to_string_lossy().into_owned();
        let l = Lesson::parse(&text, &id).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        assert!(!l.steps.is_empty(), "{id} has steps");
        for s in &l.steps {
            assert!(timestamp_seconds(&s.start).is_some() && timestamp_seconds(&s.end).is_some(), "{id} step {}", s.n);
        }
        seen += 1;
    }
    assert!(seen > 0, "no lessons found in {}", dir.display());
}

#[test]
fn timestamps() {
    assert_eq!(timestamp_seconds("01:05"), Some(65.0));
    assert_eq!(timestamp_seconds("00:16.5"), Some(16.5));
    assert_eq!(timestamp_seconds("1:02:03"), Some(3723.0));
    assert_eq!(timestamp_seconds("42"), Some(42.0));
    assert_eq!(timestamp_seconds("7.25"), Some(7.25));
    assert_eq!(timestamp_seconds(""), None);
    assert_eq!(timestamp_seconds("00:61"), None);
    assert_eq!(timestamp_seconds("a:b"), None);
    assert_eq!(timestamp_seconds("1:2:3:4"), None);
    assert_eq!(timestamp_seconds("-1"), None);
}

#[test]
fn close_codes() {
    assert_eq!(close_policy(Some(4000)), ClosePolicy::Stop);
    assert_eq!(close_policy(Some(1011)), ClosePolicy::Immediately);
    assert_eq!(close_policy(Some(1013)), ClosePolicy::SlowBackoff);
    assert_eq!(close_policy(Some(1000)), ClosePolicy::Backoff);
    assert_eq!(close_policy(None), ClosePolicy::Backoff);
}

#[test]
fn jpeg_sniff() {
    assert!(is_jpeg(&[0xFF, 0xD8, 0xFF, 0xE0, 0]));
    assert!(!is_jpeg(&[0x89, b'P', b'N', b'G', 0]));
    assert!(!is_jpeg(&[0xFF, 0xD8]));
}
