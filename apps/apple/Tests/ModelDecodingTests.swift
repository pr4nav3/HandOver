import Foundation
import Testing
@testable import HandOver

/// Decoding against the JSON samples in CONTRACT.md (Revision 5) and server/docs/contract-proposals.md.
struct ModelDecodingTests {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    @Test func stateFromTheContract() throws {
        // CONTRACT.md section 7, verbatim, plus check_mode and next_clip from the hub on soham/server.
        let json = """
        {"type":"state","lesson_id":"fortune-teller-v1","rev":1763154180123,"step":4,"total":8,"status":"watching",
         "last_check":{"done":"no","confidence":0.82,"latency_ms":910,"reason":"seams still facing up"},
         "camera_connected":true,
         "camera":{"name":"Ray-Ban Meta via iPhone","platform":"ios","source":"glasses"},
         "check_offline":false,"check_offline_reason":null,
         "mistake":null,"check_mode":"gemini","next_clip":"clips/06.mp4"}
        """
        let message = try #require(HubMessage.decode(text: json))
        guard case .state(let s) = message else { Issue.record("not a state: \(message)"); return }
        #expect(s.lessonId == "fortune-teller-v1")
        #expect(s.rev == 1_763_154_180_123)
        #expect(s.step == 4 && s.total == 8 && s.position == 4)
        #expect(s.status == .watching)
        #expect(s.lastCheck == .init(done: .no, confidence: 0.82, latencyMs: 910, reason: "seams still facing up"))
        #expect(s.lastCheck?.shownReason == "seams still facing up")
        #expect(s.cameraConnected)
        #expect(s.camera == CameraInfo(name: "Ray-Ban Meta via iPhone", platform: .ios, source: .glasses))
        #expect(!s.checkOffline && s.checkOfflineReason == nil && s.mistake == nil)
        #expect(s.checkMode == .gemini)
        #expect(s.nextClip == "clips/06.mp4")
        #expect(!s.isRecording)
    }

    @Test func oldHubStateWithoutNewFields() throws {
        let s = try decode(HubState.self, #"{"type":"state","lesson_id":null,"step":0,"total":0,"status":"watching","last_check":null,"camera_connected":false}"#)
        #expect(s == HubState(lessonId: nil, step: 0, total: 0, status: .watching))
        #expect(!s.hasLesson)
    }

    @Test func unknownFieldsAndValuesAreTolerated() throws {
        let json = """
        {"type":"state","lesson_id":"x","rev":3,"step":1,"total":2,"status":"levitating","future_field":{"a":[1,2]},
         "camera":"not an object","check_offline":true,"check_offline_reason":"budget","check_mode":"llama",
         "last_check":{"done":"maybe","confidence":0.4,"latency_ms":12,"reason":null}}
        """
        let s = try decode(HubState.self, json)
        #expect(s.status == .watching, "unknown status falls back")
        #expect(s.camera == nil, "malformed NEW field reads as missing")
        #expect(s.checkOffline && s.checkOfflineReason == .budget)
        #expect(s.checkMode?.rawValue == "llama")
        #expect(s.lastCheck?.done == .unsure)
        #expect(s.lastCheck?.shownReason == nil)
    }

    @Test func doneStatePosition() throws {
        let s = try decode(HubState.self, #"{"lesson_id":"x","step":7,"total":8,"status":"done"}"#)
        #expect(s.isDone && s.position == 8)
    }

    @Test func recordingBanner() throws {
        let s = try decode(HubState.self, #"{"camera":{"name":"Replay: take1.mp4","platform":"replay","source":"file"}}"#)
        #expect(s.isRecording)
        #expect(s.camera?.platform == .replay)
    }

    @Test func mistakeMessageAndStateMistake() throws {
        let json = #"{"type":"mistake","step":4,"kind":"behind","looks_like":3,"message":"Flip it over first.","confidence":0.86,"source":"gemini"}"#
        let expected = MistakeMessage(step: 4, kind: .behind, looksLike: 3, message: "Flip it over first.",
                                      confidence: 0.86, source: "gemini")
        #expect(HubMessage.decode(text: json) == .mistake(expected))
        let inState = try decode(HubState.self, #"{"mistake":{"step":4,"kind":"behind","looks_like":3,"message":"Flip it over first.","confidence":0.86,"source":"gemini"}}"#)
        #expect(inState.mistake == expected)
    }

    @Test func otherMessages() {
        #expect(HubMessage.decode(text: #"{"type":"advance","from":2,"to":3,"reason":"camera"}"#)
            == .advance(Advance(from: 2, to: 3, reason: .camera)))
        #expect(HubMessage.decode(text: #"{"type":"advance","from":7,"to":8,"reason":"voice"}"#)
            == .advance(Advance(from: 7, to: 8, reason: .voice)))
        #expect(HubMessage.decode(text: #"{"type":"error","message":"no lesson selected"}"#)
            == .error(ErrorMessage(message: "no lesson selected")))
        #expect(HubMessage.decode(text: #"{"type":"camera_status","active":true}"#)
            == .cameraStatus(CameraStatus(active: true)))
        #expect(HubMessage.decode(text: #"{"type":"pong"}"#) == .unknown(type: "pong"))
        #expect(HubMessage.decode(text: "not json") == nil)
        #expect(HubMessage.decode(text: #"[1,2]"#) == nil)
        #expect(HubMessage.decode(text: #"{"no":"type"}"#) == nil)
        #expect(HubMessage.decode(text: #"{"type":"advance","from":"two"}"#) == nil, "known type, wrong shape")
    }

    @Test func lessonListAndJob() throws {
        let list = try decode([LessonSummary].self, #"[{"id":"demo-v1","title":"Test pattern","steps":5},{"id":"b","title":"B","steps":0}]"#)
        #expect(list.map(\.id) == ["demo-v1", "b"] && list[0].steps == 5)
        let job = try decode(Job.self, #"{"status":"extracting","message":"finding steps","id":"bike-wheel"}"#)
        #expect(job == Job(status: .extracting, message: "finding steps", id: "bike-wheel") && !job.isFinished)
        #expect(try decode(Job.self, #"{"status":"error","message":"ffmpeg failed","id":"x"}"#).isFinished)
        #expect(try decode(UploadReceipt.self, #"{"job":"j1","id":"bike-wheel-2"}"#) == UploadReceipt(job: "j1", id: "bike-wheel-2"))
    }

    @Test func fastAPIErrorDetail() {
        #expect(HubClient.detail(Data(#"{"detail":"lesson not found"}"#.utf8)) == "lesson not found")
        #expect(HubClient.detail(Data(#"{"detail":[{"loc":["body","file"],"msg":"Field required"}]}"#.utf8)) == "Field required")
        #expect(HubClient.detail(Data("oops".utf8)) == nil)
    }
}

struct LessonDecodingTests {
    // Shaped like lessons/synthetic-fortune-teller-v1/lesson.json, plus fields from a newer hub.
    static let json = """
    {
      "id": "synthetic-fortune-teller-v1", "title": "Fold a fortune teller", "video": "norm.mp4",
      "safety": [], "tools": ["Square paper"],
      "voiceover": {"model": "kokoro-v1.0", "mode": "duck"},
      "steps": [
        {"n": 1, "title": "Lay the square sheet flat", "start": "00:00", "end": "00:03", "clip": "clips/01.mp4",
         "captions": "captions/01.vtt", "ref_frame": "frames/01.jpg", "ref_time": "00:02", "check_type": "manual",
         "check_question": "", "prerequisites": [], "common_mistake": "Start with a square sheet."},
        {"n": 2, "title": "Fold corner to corner", "start": "00:03", "end": "00:06.5", "ref_time": null,
         "check_type": "camera", "check_question": "Is the paper a triangle?", "prerequisites": [1],
         "self_test": {"own": "yes", "prev": "no", "ok": true, "mock": true}, "custom_top": 12},
        {"start": "1:02:03", "end": 3725}
      ]
    }
    """

    private func lesson() throws -> Lesson {
        try JSONDecoder().decode(Lesson.self, from: Data(Self.json.utf8))
    }

    @Test func fieldsAndDefaults() throws {
        let l = try lesson()
        #expect(l.id == "synthetic-fortune-teller-v1" && l.tools == ["Square paper"] && l.steps.count == 3)
        let s1 = l.steps[0]
        #expect(s1.isManual && s1.checkQuestion == "" && s1.refTime == "00:02" && s1.commonMistake == "Start with a square sheet.")
        let s2 = l.steps[1]
        #expect(s2.clip == "clips/02.mp4" && s2.captions == "captions/02.vtt" && s2.refFrame == "frames/02.jpg")
        #expect(s2.refTime == nil && s2.endSeconds == 6.5)
        #expect(s2.selfTest == Step.SelfTest(own: .yes, prev: .no, ok: true, mock: true))
        let s3 = l.steps[2]
        #expect(s3.n == 3 && s3.title == "" && s3.checkType == .camera && s3.checkQuestion == "Is this step finished?")
        #expect(s3.clip == "clips/03.mp4" && s3.prerequisites.isEmpty)
        #expect(s3.startSeconds == 3723 && s3.endSeconds == 3725)
    }

    @Test func minimalLesson() throws {
        let l = try JSONDecoder().decode(Lesson.self, from: Data(#"{"id":"empty"}"#.utf8))
        #expect(l.title == "empty" && l.video == "norm.mp4" && l.steps.isEmpty && l.safety.isEmpty)
    }

    @Test func roundTripKeepsUnknownFieldsAndNullRefTime() throws {
        let data = try JSONEncoder().encode(try lesson())
        let object = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect((object["voiceover"] as? [String: Any])?["mode"] as? String == "duck")
        let steps = try #require(object["steps"] as? [[String: Any]])
        #expect(steps[1]["custom_top"] as? Int == 12)
        #expect(steps[1].keys.contains("ref_time") && steps[1]["ref_time"] is NSNull, "null stays null")
        #expect(!steps[2].keys.contains("ref_time"), "missing stays missing")
        #expect(steps[0]["ref_time"] as? String == "00:02")
        #expect(try JSONDecoder().decode(Lesson.self, from: data) == (try lesson()))
    }

    @Test func timeCodes() {
        #expect(TimeCode.seconds("00:08") == 8)
        #expect(TimeCode.seconds("01:02.5") == 62.5)
        #expect(TimeCode.seconds("1:00:00") == 3600)
        #expect(TimeCode.seconds("12.25") == 12.25)
        #expect(TimeCode.seconds("00:61") == nil)
        #expect(TimeCode.seconds("1.5:00") == nil)
        #expect(TimeCode.seconds("") == nil && TimeCode.seconds("ab") == nil && TimeCode.seconds("-3") == nil)
        #expect(TimeCode.format(8) == "00:08" && TimeCode.format(62.5) == "01:02.5" && TimeCode.format(600) == "10:00")
    }
}
