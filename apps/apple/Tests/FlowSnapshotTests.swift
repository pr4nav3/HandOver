import Foundation
import SwiftUI
import Testing
@testable import HandOver

/// The first-run flow drawn to apps/apple/screenshots/flow-*.png at iPhone size (on the Mac test host, so device
/// words read "Mac"): Home, the camera sheet, Learn with its End button, the empty Learn tab and Be the Camera.
@MainActor
@Suite(.serialized)
struct FlowSnapshotTests {
    static let phone = FeatureSnapshotTests.narrow

    static func flow(camera: LearnCamera? = nil) -> LearnFlow {
        let defaults = UserDefaults(suiteName: "handover.tests.flowshots.\(UUID().uuidString)") ?? .standard
        let flow = LearnFlow(defaults: defaults)
        if let camera { flow.choose(camera) }
        return flow
    }

    @Test func home() async throws {
        let model = AppModel.preview()
        let (lesson, _) = try FeatureSnapshotTests.fixture(model: model)
        let hub = try #require(model.hub)
        let store = LibraryStore()
        store.preview(items: [
            FeatureSnapshotTests.card(lesson, hub: hub, progress: CourseProgress(lastStepsDone: 3, total: lesson.steps.count)),
            CourseCardItem(id: "bike-wheel-v1", title: "Take off a quick-release front wheel",
                           covers: CourseMedia.coverCandidates(hub: hub, lessonId: lesson.id, coverURL: nil),
                           steps: 6, status: .published),
        ])
        UserDefaults.standard.removeObject(forKey: HowItWorks.hiddenKey)
        let view = NavigationStack { LibraryView(preview: store) }.environment(Self.flow())
        try await FeatureSnapshotTests.render(view, model: model, size: Self.phone, name: "flow-home")
    }

    @Test func startSheet() async throws {
        let model = AppModel.preview()
        let fresh = Self.flow()
        fresh.requestStart(PreviewHub.fortuneTeller.lesson.id, model: model)
        try await FeatureSnapshotTests.render(CameraChoiceSheet().environment(fresh), model: model, size: Self.phone,
                                              name: "flow-start-sheet")
        let other = Self.flow(camera: .otherDevice)
        try await FeatureSnapshotTests.render(CameraChoiceSheet().environment(other), model: model, size: Self.phone,
                                              name: "flow-start-sheet-other-device")
    }

    @Test func learnWithEnd() async throws {
        let model = SnapshotTests.model(startAt: 2, live: nil)
        let flow = Self.flow(camera: .thisDevice)
        flow.showRunning(model.state.lessonId)
        let still = SnapshotTests.cgImage(TestPaths.frame("04"))
        let view = LearnTab(stillCamera: still, clips: .still(caption: "Fold the top corner down to meet the bottom one."))
            .environment(flow)
            .environment(\.learnLayoutOverride, .pip)
        try await FeatureSnapshotTests.render(view, model: model, size: Self.phone, name: "flow-learn")
    }

    @Test func emptyLearnTab() async throws {
        let model = AppModel.preview()
        let view = NavigationStack { LearnTab() }.environment(Self.flow(camera: .thisDevice))
        try await FeatureSnapshotTests.render(view, model: model, size: Self.phone, name: "flow-learn-empty")
    }

    @Test func beTheCamera() async throws {
        let model = AppModel.preview()
        let view = NavigationStack { CameraView() }.environment(Self.flow())
        try await FeatureSnapshotTests.render(view, model: model, size: Self.phone, name: "flow-be-the-camera")
    }
}
