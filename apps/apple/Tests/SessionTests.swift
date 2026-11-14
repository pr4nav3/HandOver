import Foundation
import Testing
@testable import HandOver

struct StepGuardTests {
    private func state(_ step: Int, total: Int = 4, status: HubState.Status = .watching, lesson: String? = "a",
                       rev: Int = 1) -> HubState {
        HubState(lessonId: lesson, rev: rev, step: step, total: total, status: status)
    }

    @Test func nothingWithoutALesson() {
        var g = StepGuard()
        #expect(g.next(now: 0) == nil && g.back(now: 0) == nil)
        g.observe(state(0, total: 0))
        #expect(g.next(now: 0) == nil, "a lesson with no steps is done at once")
    }

    @Test func carriesTheShownPosition() {
        var g = StepGuard()
        g.observe(state(2))
        #expect(g.next(reason: .voice, now: 0) == .next(reason: .voice, from: 2))
    }

    @Test func oneCommandPerPositionUntilTheStateMoves() {
        var g = StepGuard(hold: 1)
        g.observe(state(1))
        #expect(g.next(now: 10) == .next(reason: .button, from: 1))
        #expect(g.next(now: 10.2) == nil, "double tap")
        #expect(g.back(now: 10.3) == nil, "back from the same position is held too")
        g.observe(state(1))  // a check result on the same step does not release it
        #expect(g.next(now: 10.5) == nil)
        g.observe(state(2))
        #expect(g.next(now: 10.6) == .next(reason: .button, from: 2))
    }

    @Test func holdExpiresWhenTheHubIgnoredIt() {
        var g = StepGuard(hold: 1)
        g.observe(state(1))
        #expect(g.next(now: 0) != nil)
        #expect(g.next(now: 1.01) == .next(reason: .button, from: 1))
    }

    @Test func resetAfterReconnect() {
        var g = StepGuard(hold: 1)
        g.observe(state(1))
        #expect(g.next(now: 0) != nil)
        g.reset()
        #expect(g.next(now: 0.1) != nil)
    }

    @Test func edges() {
        var g = StepGuard()
        g.observe(state(0))
        #expect(g.back(now: 0) == nil, "already at the first step")
        g.observe(state(3, status: .done))
        #expect(g.next(now: 0) == nil, "nothing after done")
        #expect(g.back(now: 0) == .back(from: 4), "on the done screen the position is total")
    }

    @Test func newLessonOrRevReleasesTheHold() {
        var g = StepGuard(hold: 5)
        g.observe(state(0))
        #expect(g.next(now: 0) != nil)
        g.observe(state(0, rev: 2))
        #expect(g.next(now: 0.1) != nil)
        g.observe(state(0, lesson: "b", rev: 2))
        #expect(g.next(now: 0.2) != nil)
    }
}

struct LearnSessionTests {
    private let behind = MistakeMessage(step: 3, kind: .behind, looksLike: 2, message: "Flip it over first.",
                                        confidence: 0.86, source: "gemini")
    private let ahead = MistakeMessage(step: 1, kind: .ahead, looksLike: 2, message: "You're ahead.",
                                       confidence: 0.9, source: "gemini")

    @Test func behindLivesInState() {
        var s = LearnSession()
        s.apply(.mistake(behind))
        s.apply(.state(HubState(lessonId: "a", step: 3, total: 5, mistake: behind)))
        #expect(s.mistake == behind)
        s.apply(.state(HubState(lessonId: "a", step: 3, total: 5)))
        #expect(s.mistake == nil, "cleared when the hub clears it")
    }

    @Test func aheadSurvivesItsOwnAdvance() {
        var s = LearnSession()
        s.apply(.mistake(ahead))
        s.apply(.advance(Advance(from: 1, to: 3, reason: .camera)))
        s.apply(.state(HubState(lessonId: "a", step: 3, total: 5)))
        #expect(s.mistake == ahead)
        #expect(s.cameraAdvances == 1)
        s.apply(.advance(Advance(from: 3, to: 4, reason: .button)))
        #expect(s.mistake == nil)
    }

    @Test func errorsAndDismiss() {
        var s = LearnSession()
        s.apply(.error(ErrorMessage(message: "no lesson selected")))
        #expect(s.lastError == "no lesson selected")
        s.clearError()
        s.apply(.mistake(behind))
        s.dismissMistake()
        #expect(s.lastError == nil && s.mistake == nil)
    }

    @Test func framesAndUnknownChangeNothing() {
        var s = LearnSession()
        s.apply(.frame(sampleJPEG))
        s.apply(.unknown(type: "x"))
        s.apply(.cameraStatus(CameraStatus(active: true)))
        #expect(s == LearnSession())
    }
}

@MainActor
struct PreviewHubTests {
    @Test func scriptWalksTheWholeLesson() {
        let hub = PreviewHub.fortuneTeller
        let states = hub.states
        let statuses = Set(states.map(\.status))
        #expect(statuses == Set(HubState.Status.allCases), "every status appears")
        #expect(states.last?.isDone == true)
        #expect(states.contains { $0.mistake != nil } && states.contains { $0.checkOffline })
        #expect(states.contains { $0.nextClip != nil })
        for state in states where state.hasLesson {
            #expect(state.total == hub.lesson.steps.count && state.step < state.total)
        }
    }

    @Test func feedsAModel() async {
        let model = AppModel.preview(startAt: 0)
        #expect(model.isPreview && model.lesson?.id == "fortune-teller-v1" && model.lessons.count == 2)
        for message in PreviewHub.fortuneTeller.messages(upToState: 100) { model.ingest(message) }
        #expect(model.state.isDone)
        #expect(model.currentStep == nil)
        #expect(model.lastAdvance == Advance(from: 4, to: 5, reason: .button))
    }

    @Test func previewAtAStep() {
        let model = AppModel.preview(startAt: 2)
        #expect(model.state.step == 1)
        #expect(model.currentStep?.title == "Fold corner to corner into a triangle")
        #expect(model.mediaURL("clips/02.mp4")?.absoluteString == "http://preview.local:8000/lessons/fortune-teller-v1/clips/02.mp4?v=1")
    }

    @Test func badAddressSetsAnError() {
        let model = AppModel.preview()
        #expect(model.connect(text: "ftp://nope") == false)
        #expect(model.errorMessage != nil)
    }

    @Test func decodesAJPEGFrame() throws {
        // A 1x1 JPEG.
        let jpeg = try #require(Data(base64Encoded: "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="))
        let model = AppModel.preview()
        model.ingest(.frame(jpeg))
        #expect(model.frame?.size == CGSize(width: 1, height: 1))
    }
}
