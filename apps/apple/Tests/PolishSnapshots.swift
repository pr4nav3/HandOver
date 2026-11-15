import Foundation
import ImageIO
import SwiftUI
import Testing
import UniformTypeIdentifiers
@testable import HandOver

/// iPhone-sized PNGs (402 by 874 points) of Teach, Make course, the editor, account, organizations, settings
/// and the onboarding pages, drawn on the Mac with the compact size class, into apps/apple/screenshots/polish-*.
/// Mac-only controls (the Photos card is iPhone only) draw as they do on the Mac. Nothing touches the network.
@MainActor
@Suite(.serialized)
struct PolishSnapshots {
    static let phone = CGSize(width: 402, height: 874)

    static var folder: URL {
        if let s = ProcessInfo.processInfo.environment["HANDOVER_SCREENSHOTS"] { return URL(fileURLWithPath: s) }
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().appending(path: "../screenshots").standardizedFileURL
    }

    static let video = TeachPickedVideo(url: URL(fileURLWithPath: "/tmp/fortune-teller.mov"), bytes: 214_300_000)

    // MARK: - Teach

    @Test func teach() async throws {
        let app = AppModel.preview(), accounts = AccountStore.preview()
        let (lesson, _) = try FeatureSnapshotTests.fixture(model: app)
        try await shoot("teach-empty") { NavigationStack { TeachView() }.environment(app).environment(accounts) }

        let store = LibraryStore()
        store.preview(items: [FeatureSnapshotTests.card(lesson, hub: try #require(app.hub), status: .draft)])
        try await shoot("teach-lessons") {
            NavigationStack { TeachView(preview: store) }.environment(app).environment(accounts)
        }

        let titling = UploadFlow()
        titling.preview(phase: .titling, video: Self.video, title: "fortune-teller")
        try await shoot("teach-title") { NavigationStack { MakeCourseView(flow: titling, hub: app.hub) }.environment(app) }

        let working = UploadFlow()
        working.preview(phase: .processing, video: Self.video, title: "Fold a fortune teller", progress: 1,
                        job: Job(status: .extracting, id: "fortune-teller"), lastStage: .extracting)
        try await shoot("teach-processing") { NavigationStack { MakeCourseView(flow: working, hub: app.hub) }.environment(app) }

        let failed = UploadFlow()
        failed.preview(phase: .failed, video: Self.video, title: "Fold a fortune teller", progress: 1,
                       job: Job(status: .error, message: "too many jobs", id: "fortune-teller"), lastStage: .queued,
                       failure: ProcessingStages.friendly("too many jobs"))
        try await shoot("teach-failed") { NavigationStack { MakeCourseView(flow: failed, hub: app.hub) }.environment(app) }

        let done = UploadFlow()
        done.preview(phase: .finished, title: lesson.title, job: Job(status: .done, id: lesson.id), lesson: lesson)
        try await shoot("teach-ready") { NavigationStack { MakeCourseView(flow: done, hub: app.hub) }.environment(app) }
    }

    // MARK: - Editor

    @Test func editor() async throws {
        let app = AppModel.preview()
        let (lesson, _) = try FeatureSnapshotTests.fixture(model: app)
        let store = EditorStore(lessonId: lesson.id)
        store.preview(lesson: lesson,
                      course: Course(id: lesson.id, title: lesson.title, steps: lesson.steps.count, status: .draft),
                      permissions: CoursePermissions(canEdit: true, canPublish: true, canManage: true),
                      capabilities: EditorCapabilities(course: true, captions: true, selfTest: true, voiceover: true))
        try await shoot("editor") {
            NavigationStack { EditorView(lessonId: lesson.id, preview: store) }.environment(app).environment(AccountStore.preview())
        }
    }

    // MARK: - Account, organizations, settings

    @Test func accountOrgsSettings() async throws {
        let app = AppModel.preview(), accounts = AccountStore.preview()
        try await shoot("profile-empty") {
            NavigationStack { ProfileView(preset: []) }.environment(app).environment(accounts)
        }
        try await shoot("sign-in") {
            SignInSheet().environment(app).environment(AccountStore.preview(user: nil))
        }
        try await shoot("orgs-empty") {
            NavigationStack { OrgsListView(preset: MyOrgs(orgs: [], invites: [])) }.environment(app).environment(accounts)
        }
        try await shoot("orgs-signed-out") {
            NavigationStack { OrgsListView() }.environment(app).environment(AccountStore.preview(user: nil))
        }
        try await shoot("settings") { NavigationStack { SettingsView() }.environment(app).environment(accounts) }
        try await shoot("org-page") {
            NavigationStack { OrgPageView(orgID: "o1", preset: SetupSnapshots.org) }.environment(app).environment(accounts)
        }
    }

    // MARK: - Onboarding

    @Test func onboarding() async throws {
        let app = AppModel.preview(), accounts = AccountStore.preview(user: nil)
        func progress(_ build: (inout OnboardingProgress) -> Void) -> OnboardingProgress {
            var p = OnboardingProgress()
            build(&p)
            return p
        }
        let connect = OnboardingModel.preview(progress { $0.finishWelcome() })
        try await shoot("onboarding-connect", wait: 0.8) { OnboardingView(flow: connect).environment(app).environment(accounts) }
        let role = OnboardingModel.preview(progress { $0.finishWelcome(); $0.connected(kind: .open); $0.choose(role: .learn) })
        try await shoot("onboarding-role") { OnboardingView(flow: role).environment(app).environment(accounts) }
        let theme = OnboardingModel.preview(progress { $0.finishWelcome(); $0.connected(kind: .open); $0.choose(role: .teach); $0.complete(.role) })
        try await shoot("onboarding-theme", wait: 0.8) { OnboardingView(flow: theme).environment(app).environment(accounts) }

        // The card Home shows after the last page: learn first with skipped steps, and teach first.
        let learner = progress {
            $0.finishWelcome(); $0.connected(kind: .open); $0.choose(role: .learn)
            $0.complete(.role); $0.complete(.theme, skipped: true)
            $0.skipped.insert(.joinOrg)
        }
        let teacher = progress { $0.finishWelcome(); $0.connected(kind: .open); $0.choose(role: .teach); $0.complete(.role); $0.complete(.theme) }
        #expect(learner.homeCard == true && learner.finished)
        try await shoot("home-card") {
            ScrollView {
                VStack(spacing: HOSpace.l) {
                    OnboardingHomeCardContent(progress: learner, onTeach: nil, onHide: {})
                    OnboardingHomeCardContent(progress: teacher, onTeach: {}, onHide: {})
                }
                .padding(HOSpace.l)
            }
            .hoPaperBackground()
            .environment(app).environment(AccountStore.preview())
        }
    }

    // MARK: - Rendering

    private func shoot<V: View>(_ name: String, wait: TimeInterval = 0.6, @ViewBuilder _ view: () -> V) async throws {
        let content = view()
            .environment(\.horizontalSizeClass, .compact)
            .handOverTheme(.system, dark: false)
        let image = try #require(await HostedRenderer.render(content, wait: wait, macSize: Self.phone), "rendered \(name)")
        var dir = Self.folder
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try Data().write(to: dir.appending(path: ".write-check"))
            try? FileManager.default.removeItem(at: dir.appending(path: ".write-check"))
        } catch {
            dir = FileManager.default.temporaryDirectory.appending(path: "handover-polish-screenshots")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        let url = dir.appending(path: "polish-\(name).png")
        let dest = try #require(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, image, nil)
        #expect(CGImageDestinationFinalize(dest), "wrote \(url.path)")
    }
}

