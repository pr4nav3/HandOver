import Testing
@testable import HandOver

@MainActor
struct LearnFeedbackTests {
    let cameraStep = Step(n: 1, title: "Fold", start: "0", end: "1")

    func state(_ phase: String) -> HubState {
        HubState(lessonId: "lesson", step: 0, total: 3, cameraConnected: true,
                 observation: .init(phase: phase, frameAgeMs: 73, cameraFPS: 14.8))
    }

    @Test func livePhasesGiveOneClearAction() {
        #expect(LearnFeedback.resolve(state: state("moving"), step: cameraStep, status: .watching).title == "Keep folding")
        #expect(LearnFeedback.resolve(state: state("settling"), step: cameraStep, status: .watching).title == "Hold it there")
        #expect(LearnFeedback.resolve(state: state("checking"), step: cameraStep, status: .checking).title == "Checking this fold")
    }

    @Test func heldTakesPrecedenceOverVerifiedObservation() {
        var s = state("verified")
        s.held = true
        #expect(LearnFeedback.resolve(state: s, step: cameraStep, status: .verified).phase == "held")
    }

    @Test func liveMetricIsShortAndReadable() {
        #expect(LearnFeedback.liveMetric(state("watching").observation) == "15 fps · Live")
        #expect(LearnFeedback.liveMetric(.init(phase: "watching", frameAgeMs: 1_600, cameraFPS: 7)) == "7.0 fps · 2 s behind")
    }
}
