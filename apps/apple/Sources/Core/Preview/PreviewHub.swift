import Foundation

/// A pretend hub for SwiftUI previews, demo launches (`-demo`) and tests: a lesson, a library, and a
/// scripted run of hub messages that walks through every learn status, a camera check with a reason,
/// a `behind` mistake, a camera advance with `next_clip`, a button advance, checks going offline, and done.
///
/// Use `AppModel.preview()` in a `#Preview`, or `messages(upToState:)` to feed a model by hand.
struct PreviewHub: Sendable {
    struct Beat: Sendable {
        var after: Duration
        var message: HubMessage
    }

    var hub: HubURL
    var lesson: Lesson
    var summaries: [LessonSummary]
    var script: [Beat]

    /// Just the states, in order.
    var states: [HubState] {
        script.compactMap { beat in
            if case .state(let state) = beat.message { return state }
            return nil
        }
    }

    /// Every message up to and including the state at `index` in `states`.
    func messages(upToState index: Int) -> [HubMessage] {
        var seen = -1
        var out: [HubMessage] = []
        for beat in script {
            out.append(beat.message)
            if case .state = beat.message {
                seen += 1
                if seen >= index { break }
            }
        }
        return out
    }

    /// Sends the script into a model once, beat by beat.
    @MainActor
    func play(into model: AppModel) async {
        for beat in script {
            try? await Task.sleep(for: beat.after)
            if Task.isCancelled { return }
            model.ingest(beat.message)
        }
    }

    static let fortuneTeller: PreviewHub = {
        let lesson = Lesson(
            id: "fortune-teller-v1",
            title: "Fold a paper fortune teller",
            steps: [
                Step(n: 1, title: "Lay the square sheet flat", start: "00:00", end: "00:06", checkType: .manual,
                     commonMistake: "Start with a square sheet, not a rectangle."),
                Step(n: 2, title: "Fold corner to corner into a triangle", start: "00:06", end: "00:14",
                     checkQuestion: "Is the paper folded into a single triangle?", prerequisites: [1],
                     commonMistake: "Line the corners up exactly before creasing."),
                Step(n: 3, title: "Fold all four corners to the center", start: "00:14", end: "00:31",
                     checkQuestion: "Are all four corners folded to the center?", prerequisites: [2]),
                Step(n: 4, title: "Flip it over", start: "00:31", end: "00:36",
                     checkQuestion: "Is the folded side facing down?", prerequisites: [3],
                     commonMistake: "Flip it over first."),
                Step(n: 5, title: "Fold the corners in again and shape it", start: "00:36", end: "00:58",
                     checkType: .manual, prerequisites: [4]),
            ],
            safety: [],
            tools: ["Square paper"]
        )
        let id = lesson.id
        let total = lesson.steps.count
        let phone = CameraInfo(name: "iPhone camera", platform: .ios, source: .phone)
        func state(_ step: Int, _ status: HubState.Status, check: HubState.LastCheck? = nil,
                   mistake: MistakeMessage? = nil, offline: HubState.OfflineReason? = nil,
                   nextClip: String? = nil) -> HubMessage {
            .state(HubState(lessonId: id, rev: 1, step: step, total: total, status: status, lastCheck: check,
                            cameraConnected: true, camera: phone, checkOffline: offline != nil,
                            checkOfflineReason: offline, mistake: mistake, checkMode: .gemini, nextClip: nextClip))
        }
        let behind = MistakeMessage(step: 3, kind: .behind, looksLike: 2, message: "Flip it over first.",
                                    confidence: 0.86, source: "gemini")
        let beat = { (seconds: Double, message: HubMessage) in Beat(after: .seconds(seconds), message: message) }
        let script: [Beat] = [
            beat(0, .state(HubState(checkMode: .gemini))),
            beat(0.5, state(0, .manual)),
            beat(2, .advance(Advance(from: 0, to: 1, reason: .button))),
            beat(0, state(1, .watching)),
            beat(1.5, state(1, .checking)),
            beat(1, state(1, .watching, check: .init(done: .no, confidence: 0.82, latencyMs: 910,
                                                       reason: "corners not lined up"))),
            beat(2, state(1, .verified, check: .init(done: .yes, confidence: 0.93, latencyMs: 840),
                          nextClip: "clips/03.mp4")),
            beat(0.8, .advance(Advance(from: 1, to: 2, reason: .camera))),
            beat(0, state(2, .watching)),
            beat(2, state(2, .verified, check: .init(done: .yes, confidence: 0.9, latencyMs: 790),
                          nextClip: "clips/04.mp4")),
            beat(0.8, .advance(Advance(from: 2, to: 3, reason: .camera))),
            beat(0, state(3, .watching)),
            beat(2, state(3, .watching, check: .init(done: .no, confidence: 0.88, latencyMs: 870,
                                                       reason: "folded side still up"))),
            beat(1, .mistake(behind)),
            beat(0, state(3, .watching, check: .init(done: .no, confidence: 0.88, latencyMs: 870,
                                                       reason: "folded side still up"), mistake: behind)),
            beat(2.5, state(3, .watching, offline: .rateLimited)),
            beat(2, .advance(Advance(from: 3, to: 4, reason: .button))),
            beat(0, state(4, .manual)),
            beat(2, .advance(Advance(from: 4, to: 5, reason: .button))),
            beat(0, state(4, .done)),
        ]
        return PreviewHub(
            hub: HubURL(parsing: "preview.local:8000")!,
            lesson: lesson,
            summaries: [
                LessonSummary(id: "bike-wheel-v1", title: "Take off a quick-release front wheel", steps: 6),
                LessonSummary(id: id, title: lesson.title, steps: total),
            ],
            script: script
        )
    }()
}
