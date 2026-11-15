import Foundation
import ImageIO
import SwiftUI
import Testing
import UniformTypeIdentifiers
@testable import HandOver
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// PNG screenshots of the setup screens (onboarding, pairing, account, orgs, camera, settings, themes) into
/// apps/apple/screenshots/. Each screen is hosted in a real window so system controls (fields, pickers,
/// toggles, lists) draw as they do in the app. Run on an iPhone simulator for the iPhone set, on an iPad
/// simulator for the iPad set, and on the Mac for the Mac set. Nothing touches the network or the camera.
@MainActor
@Suite(.serialized)
struct SetupSnapshots {
    static var folder: URL {
        if let s = ProcessInfo.processInfo.environment["HANDOVER_SCREENSHOTS"] { return URL(fileURLWithPath: s) }
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().appending(path: "../screenshots").standardizedFileURL
    }

    #if os(iOS)
    static var device: String { UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone" }
    #else
    static let device = "mac"
    #endif

    // MARK: - Fixtures

    static let hub = HubURL(parsing: "192.168.1.20:8000")!

    static func app() -> AppModel { AppModel.preview() }

    static func accounts(signedIn: Bool = true, setup: Bool = false) -> AccountStore {
        AccountStore.preview(user: signedIn ? HubUser(id: "u1", name: "Sam Rivera", role: .owner) : nil,
                             support: .available(setupNeeded: setup, signInRequired: false))
    }

    static func progress(_ build: (inout OnboardingProgress) -> Void) -> OnboardingProgress {
        var p = OnboardingProgress()
        build(&p)
        return p
    }

    static let org = OrgDetail(
        id: "o1", name: "Bike Shop Crew", slug: "bike-shop-crew", created: nil, role: .admin,
        owner: OrgInvite.Person(id: "u1", name: "Sam Rivera"),
        members: [
            OrgMember(userId: "u1", name: "Sam Rivera", role: .admin),
            OrgMember(userId: "u2", name: "Ana Lopez", role: .teacher),
            OrgMember(userId: "u3", name: "Jordan Lee", role: .learner),
            OrgMember(userId: "u4", name: "Priya Shah", role: .learner),
        ],
        courses: [
            OrgCourse(id: "synthetic-fortune-teller-v1", title: "Fold a fortune teller (synthetic renders)", coverUrl: nil,
                      steps: 8, status: "published", owner: OrgInvite.Person(id: "u2", name: "Ana Lopez")),
        ],
        invites: [])

    static let invite = OrgInvite(id: "i1", kind: "code", role: .learner, created: nil, expires: "2026-11-21T18:00:00Z",
                                  createdBy: "Sam Rivera", maxUses: nil, uses: 0, user: nil, code: "K7qM2xPA9bcTdHEf", org: nil)

    // MARK: - Shots

    @Test func onboarding() async throws {
        let app = Self.app(), accounts = Self.accounts(signedIn: false)
        for page in 0..<4 {
            try await shoot("onboarding-welcome-\(page + 1)", wait: 1.6, macSize: Self.onboardingSize) {
                OnboardingFrameHost {
                    WelcomePages(onFinish: {}, onSkip: {}, startPage: page, settled: false)
                }
            }
        }
        let connect = OnboardingModel.preview(Self.progress { $0.finishWelcome() })
        try await shoot("onboarding-connect", wait: 0.8, macSize: Self.onboardingSize) { OnboardingView(flow: connect).environment(app).environment(accounts) }

        let owner = OnboardingModel.preview(Self.progress { $0.finishWelcome(); $0.connected(kind: .needsOwner, signInOptional: false) })
        try await shoot("account-owner-setup", macSize: Self.onboardingSize) {
            OnboardingView(flow: owner).environment(app).environment(Self.accounts(signedIn: false, setup: true))
        }
        try await shoot("account-owner-passcode", macSize: CGSize(width: 720, height: 760)) {
            ScrollView {
                OwnerSetupForm(hubName: "192.168.1.20", onDone: {}, onTaken: {}, startOnAccount: true,
                               startPasscode: "fold2026")
                    .padding(HOSpace.l)
                    .frame(maxWidth: 520)
                    .frame(maxWidth: .infinity)
            }
            .hoPaperBackground()
            .environment(Self.accounts(signedIn: false, setup: true))
        }
        let signIn = OnboardingModel.preview(Self.progress { $0.finishWelcome(); $0.connected(kind: .accounts) })
        try await shoot("account-sign-in", macSize: Self.onboardingSize) { OnboardingView(flow: signIn).environment(app).environment(accounts) }

        let profile = OnboardingModel.preview(Self.progress {
            $0.finishWelcome(); $0.connected(kind: .needsOwner, signInOptional: false)
            $0.signedIn(madeAccount: true, orgsOffered: true)
        })
        try await shoot("onboarding-profile", macSize: Self.onboardingSize) { OnboardingView(flow: profile).environment(app).environment(Self.accounts()) }

        let join = OnboardingModel.preview(Self.progress {
            $0.finishWelcome(); $0.connected(kind: .accounts); $0.signedIn(madeAccount: false, orgsOffered: true)
        })
        try await shoot("onboarding-join-org", macSize: Self.onboardingSize) { OnboardingView(flow: join).environment(app).environment(Self.accounts()) }

        let role = OnboardingModel.preview(Self.progress { $0.finishWelcome(); $0.connected(kind: .open); $0.choose(role: .learn) })
        try await shoot("onboarding-role", macSize: Self.onboardingSize) { OnboardingView(flow: role).environment(app).environment(accounts) }

        let theme = OnboardingModel.preview(Self.progress { $0.finishWelcome(); $0.connected(kind: .open); $0.complete(.role) })
        try await shoot("onboarding-theme", wait: 0.8, macSize: Self.onboardingSize) { OnboardingView(flow: theme).environment(app).environment(accounts) }
    }

    @Test func pairing() async throws {
        try await shoot("pairing-viewfinder", dark: true) {
            QRScannerScreen(title: "Scan the hub's code",
                            hint: "Point the camera at a QR code with the hub's address, like http://192.168.1.20:8000.",
                            handle: { _ in nil }, onType: {}, onCancel: {}, staticPreview: true)
        }
        try await shoot("pairing-connected", wait: 1.2) {
            ConnectStatusView(phase: .connected(Self.hub, lessons: 3)).hoPaperBackground()
        }
        try await shoot("pairing-unreachable") {
            ConnectStatusView(phase: .failed(Self.hub, .unreachable("timed out"))).hoPaperBackground()
        }
        try await shoot("permission-camera") { PermissionCard(permission: .camera) { _ in } }
    }

    @Test func accountAndOrgs() async throws {
        let app = Self.app(), accounts = Self.accounts()
        let progress: [CourseProgressItem] = [
            CourseProgressItem(id: "a", title: "Fold a fortune teller", steps: 8,
                               progress: .init(runs: 2, completed: 1, bestStepsDone: 8, lastStepsDone: 8, lastFinished: true, total: 8)),
            CourseProgressItem(id: "b", title: "Test pattern (not a real lesson)", steps: 5,
                               progress: .init(runs: 1, completed: 0, bestStepsDone: 3, lastStepsDone: 3, lastFinished: false, total: 5)),
        ]
        try await shoot("account-profile") {
            NavigationStack { ProfileView(preset: progress, presetAnalytics: .sample) }
                .environment(app).environment(accounts)
        }
        let mine = MyOrgs(orgs: [Self.org.summary,
                                 OrgSummary(id: "o2", name: "Saturday Class", members: 12, role: .learner)],
                          invites: [OrgInvite(id: "i9", kind: "user", role: .teacher, createdBy: "Ana Lopez",
                                              org: OrgBrief(id: "o3", name: "Robotics Club", slug: nil))])
        try await shoot("orgs-list") { NavigationStack { OrgsListView(preset: mine) }.environment(app).environment(accounts) }
        try await shoot("org-page") {
            NavigationStack { OrgPageView(orgID: "o1", preset: Self.org) }.environment(app).environment(accounts)
        }
        try await shoot("org-page-members") {
            NavigationStack { OrgMembersPreview(org: Self.org) }.environment(app).environment(accounts)
        }
        try await shoot("org-invite-sheet") {
            InviteSheet(org: Self.org, presetCreated: Self.invite).environment(app).environment(accounts)
        }
    }

    @Test func cameraAndSettings() async throws {
        let app = Self.app(), accounts = Self.accounts()
        let info = CameraChromeInfo(hubName: "192.168.1.20", connecting: false, reconnecting: false, sending: true, fps: 4.8,
                                    size: CGSize(width: 960, height: 540), active: true,
                                    stepLine: "Step 4 of 8: Fold all four corners to center", status: .watching,
                                    canStep: true, canBack: true, throttled: false, sourceName: "Back Camera")
        try await shoot("camera-mode", dark: true) { CameraModeScreen(onClose: {}, preview: info).environment(app) }
        try await shoot("camera-start") {
            NavigationStack { CameraView() }
                .environment(app)
                .environment(LearnFlow())
        }
        try await shoot("settings") { NavigationStack { SettingsView() }.environment(app).environment(accounts) }
        try await shoot("theme-picker") { NavigationStack { ThemePickerView() }.environment(app) }
        try await shoot("theme-picker-dark", dark: true) { NavigationStack { ThemePickerView() }.environment(app) }
    }

    // MARK: - Rendering

    /// The Mac onboarding window (SCREENS.md 25.12).
    static let onboardingSize = CGSize(width: 720, height: 560)

    private func shoot<V: View>(_ name: String, dark: Bool = false, wait: TimeInterval = 0.5,
                                macSize: CGSize = CGSize(width: 1100, height: 720),
                                @ViewBuilder _ view: () -> V) async throws {
        let content = view()
            .handOverTheme(.system, dark: dark)
        let image = try #require(await HostedRenderer.render(content, wait: wait, macSize: macSize), "rendered \(name)")
        // The sandboxed Mac test host may not write outside its container; then the PNGs go to its temporary
        // folder (copy them to apps/apple/screenshots/ from there).
        var dir = Self.folder
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try Data().write(to: dir.appending(path: ".write-check"))
            try? FileManager.default.removeItem(at: dir.appending(path: ".write-check"))
        } catch {
            dir = FileManager.default.temporaryDirectory.appending(path: "handover-setup-screenshots")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        let url = dir.appending(path: "setup-\(Self.device)-\(name).png")
        let dest = try #require(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, image, nil)
        #expect(CGImageDestinationFinalize(dest), "wrote \(url.path)")
    }
}

/// The iPad onboarding card frame without the whole flow.
private struct OnboardingFrameHost<Content: View>: View {
    @ViewBuilder var content: Content
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.theme) private var theme

    var body: some View {
        #if os(iOS)
        if sizeClass == .regular {
            content
                .frame(width: 600, height: 720)
                .background(theme.colors.paper, in: RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.colors.well.ignoresSafeArea())
        } else {
            content.safeAreaPadding(.top, 52).hoPaperBackground()
        }
        #else
        content.hoPaperBackground()
        #endif
    }
}

/// The org page opened on Members, for the screenshot.
private struct OrgMembersPreview: View {
    let org: OrgDetail
    var body: some View { OrgPageView(orgID: org.id, preset: org, startTab: .members) }
}

@MainActor
enum HostedRenderer {
    /// Hosts `view` in a window the size of the screen (iOS) or 1100 by 720 (Mac), lets it settle, and
    /// draws the window.
    static func render<V: View>(_ view: V, wait: TimeInterval, macSize: CGSize = CGSize(width: 1100, height: 720)) async -> CGImage? {
        #if os(iOS)
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return nil }
        let window = UIWindow(windowScene: scene)
        window.frame = scene.screen.bounds
        let host = UIHostingController(rootView: view)
        window.rootViewController = host
        window.makeKeyAndVisible()
        try? await Task.sleep(for: .seconds(wait))
        let format = UIGraphicsImageRendererFormat()
        format.scale = scene.screen.scale
        let image = UIGraphicsImageRenderer(bounds: window.bounds, format: format).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
        window.isHidden = true
        return image.cgImage
        #else
        let size = macSize
        let host = NSHostingView(rootView: view)
        // Keep the window the asked size; tall content must not grow it.
        host.sizingOptions = []
        host.frame = CGRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.contentView = host
        window.orderFrontRegardless()
        try? await Task.sleep(for: .seconds(wait))
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return nil }
        host.cacheDisplay(in: host.bounds, to: rep)
        window.orderOut(nil)
        return rep.cgImage
        #endif
    }
}
