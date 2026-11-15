import Foundation
import SwiftUI
import Testing
@testable import HandOver

/// iPhone landscape (874 by 402 points) drawn to apps/apple/screenshots/landscape-*.png on the Mac test host.
/// The iPhone's landscape safe area is added with `safeAreaPadding` (the Dynamic Island side and the matching
/// side, plus the home indicator), so backgrounds run edge to edge and content stays inside, as on the phone.
@MainActor
@Suite(.serialized)
struct LandscapeSnapshotTests {
    static let size = CGSize(width: 874, height: 402)
    /// iPhone 17 and 18 Pro in landscape.
    static let insets = EdgeInsets(top: 0, leading: 62, bottom: 21, trailing: 62)

    static func shoot<V: View>(_ name: String, _ view: V, model: AppModel, dark: Bool = false) async throws {
        try await FeatureSnapshotTests.render(view.safeAreaPadding(insets), model: model, size: size,
                                              name: "landscape-\(name)", dark: dark)
    }

    @Test func learn() async throws {
        let model = SnapshotTests.model(startAt: 9)
        let flow = FlowSnapshotTests.flow(camera: .thisDevice)
        flow.showRunning(model.state.lessonId)
        let still = SnapshotTests.cgImage(TestPaths.frame("04"))
        let view = LearnTab(stillCamera: still, clips: .still(caption: "Fold the top corner down to meet the bottom one."))
            .environment(flow)
            .environment(\.learnLayoutOverride, .sideBySide(phone: true))
        try await Self.shoot("learn", view, model: model)

        let mistake = SnapshotTests.model(startAt: 10)
        let flow2 = FlowSnapshotTests.flow(camera: .thisDevice)
        flow2.showRunning(mistake.state.lessonId)
        let view2 = LearnTab(stillCamera: still, clips: .still(caption: "Fold the top corner down to meet the bottom one."))
            .environment(flow2)
            .environment(\.learnLayoutOverride, .sideBySide(phone: true))
        try await Self.shoot("learn-mistake", view2, model: mistake, dark: true)
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
        let view = NavigationStack { LibraryView(preview: store) }.environment(FlowSnapshotTests.flow())
        try await Self.shoot("home", view, model: model)
    }

    @Test func startSheet() async throws {
        let model = AppModel.preview()
        let fresh = FlowSnapshotTests.flow()
        fresh.requestStart(PreviewHub.fortuneTeller.lesson.id, model: model)
        try await Self.shoot("start-sheet", CameraChoiceSheet().environment(fresh), model: model)
    }

    @Test func record() async throws {
        let model = AppModel.preview()
        let idle = RecordModel(engine: RecordPreviewEngine())
        idle.preview(phase: .ready)
        try await Self.shoot("record", RecordView(preview: idle), model: model, dark: true)
        let recording = RecordModel(engine: RecordPreviewEngine())
        let levels: [Float] = (0..<24).map { Float(0.25 + 0.55 * abs(sin(Double($0) * 0.55))) }
        recording.preview(phase: .recording, elapsed: 42, levels: levels)
        try await Self.shoot("record-recording", RecordView(preview: recording), model: model, dark: true)
    }

    @Test func onboarding() async throws {
        let model = AppModel.preview()
        for page in [0, 3] {
            // The onboarding top bar (Skip) is 52 points tall.
            let view = WelcomePages(onFinish: {}, onSkip: {}, startPage: page, settled: true)
                .safeAreaPadding(.top, 52)
                .hoPaperBackground()
            try await Self.shoot("onboarding-welcome-\(page + 1)", view, model: model)
        }
        let theme = OnboardingModel.preview(SetupSnapshots.progress { $0.finishWelcome(); $0.connected(kind: .open); $0.complete(.role) })
        try await Self.shoot("onboarding-theme", OnboardingView(flow: theme), model: model)
        let role = OnboardingModel.preview(SetupSnapshots.progress { $0.finishWelcome(); $0.connected(kind: .open); $0.choose(role: .learn) })
        try await Self.shoot("onboarding-role", OnboardingView(flow: role), model: model)
        let connect = OnboardingModel.preview(SetupSnapshots.progress { $0.finishWelcome() })
        try await Self.shoot("onboarding-connect", OnboardingView(flow: connect), model: model)
    }

    @Test func beTheCamera() async throws {
        let model = AppModel.preview()
        let view = NavigationStack { CameraView() }.environment(FlowSnapshotTests.flow())
        try await Self.shoot("be-the-camera", view, model: model)
        let info = CameraChromeInfo(hubName: "192.168.1.20", connecting: false, reconnecting: false, sending: true, fps: 14.8,
                                    size: CGSize(width: 960, height: 540), active: true,
                                    stepLine: "Step 4 of 5: Flip it over", status: .watching, canStep: true, canBack: true,
                                    throttled: false, sourceName: "Back Camera")
        try await Self.shoot("be-the-camera-live", CameraModeScreen(onClose: {}, preview: info), model: model, dark: true)
    }

    /// The other screens, with an iPhone's compact width (an iPhone Pro on its side).
    @Test func otherScreens() async throws {
        let model = AppModel.preview()
        let (lesson, cues) = try FeatureSnapshotTests.fixture(model: model)
        let detail = LessonDetailModel(preview: lesson,
                                       course: Course(id: lesson.id, title: lesson.title, steps: lesson.steps.count,
                                                      status: .published),
                                       permissions: CoursePermissions(canEdit: true))
        let flow = FlowSnapshotTests.flow()
        try await Self.shoot("lesson-detail", NavigationStack { LessonDetailView(lessonId: lesson.id, preview: detail) }
            .environment(flow).environment(\.horizontalSizeClass, .compact), model: model)
        try await Self.shoot("teach", NavigationStack { TeachView() }
            .environment(flow).environment(\.horizontalSizeClass, .compact), model: model)
        let store = EditorStore(lessonId: lesson.id)
        store.preview(lesson: lesson,
                      course: Course(id: lesson.id, title: lesson.title, steps: lesson.steps.count, status: .draft),
                      permissions: CoursePermissions(canEdit: true, canPublish: true, canManage: true),
                      capabilities: EditorCapabilities(course: true, captions: true, selfTest: true, voiceover: true),
                      cues: cues)
        store.selection = 1
        try await Self.shoot("editor", NavigationStack { EditorView(lessonId: lesson.id, preview: store) }
            .environment(\.horizontalSizeClass, .compact), model: model)
        try await Self.shoot("settings", NavigationStack { SettingsView() }.environment(flow), model: model)
        let mine = MyOrgs(orgs: [SetupSnapshots.org.summary,
                                 OrgSummary(id: "o2", name: "Saturday Class", members: 12, role: .learner)], invites: [])
        try await Self.shoot("orgs", NavigationStack { OrgsListView(preset: mine) }, model: model)
    }
}
