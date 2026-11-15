import CoreGraphics
import Foundation
import ImageIO
import SwiftUI
import Testing
import UniformTypeIdentifiers
@testable import HandOver

/// Where the repo and the screenshot folder are. `HANDOVER_REPO` and `HANDOVER_SCREENSHOTS` override them
/// (pass `TEST_RUNNER_HANDOVER_REPO=...` to xcodebuild) when the tests build from a copy.
enum TestPaths {
    static var repo: URL {
        if let r = ProcessInfo.processInfo.environment["HANDOVER_REPO"] { return URL(fileURLWithPath: r) }
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().appending(path: "../../..").standardizedFileURL
    }

    static var screenshots: URL {
        if let s = ProcessInfo.processInfo.environment["HANDOVER_SCREENSHOTS"] { return URL(fileURLWithPath: s) }
        return repo.appending(path: "apps/apple/screenshots")
    }

    /// The synthetic fortune teller lesson's reference frames (tracked in the repo).
    static func frame(_ nn: String) -> URL {
        repo.appending(path: "lessons/synthetic-fortune-teller-v1/frames/\(nn).jpg")
    }
}

/// Renders screens to PNG with ImageRenderer (no simulator, no windows) into apps/apple/screenshots/.
/// The clip pane shows the step's reference frame as its poster (ImageRenderer cannot draw AVPlayerLayer),
/// and the learner's camera shows a frame of the lesson, both from lessons/synthetic-fortune-teller-v1.
@MainActor
@Suite(.serialized)
struct SnapshotTests {
    static let iPhone = CGSize(width: 402, height: 874)
    static let iPhoneLandscape = CGSize(width: 874, height: 402)
    static let iPad = CGSize(width: 1180, height: 820)
    static let mac = CGSize(width: 1100, height: 720)

    /// PreviewHub step index to the synthetic lesson's frame that matches its title.
    static let posterFor = ["01", "02", "04", "05", "06"]

    static func cgImage(_ url: URL) -> CGImage? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return MediaImages.decode(data, maxPixels: 1280)
    }

    /// A preview model at a state of the scripted run, with the lesson's stills cached and a live frame.
    static func model(startAt: Int, live: String? = "04") -> AppModel {
        let m = AppModel.preview(startAt: startAt)
        for (i, step) in m.lesson!.steps.enumerated() {
            if let url = m.mediaURL(step.refFrame), let image = cgImage(TestPaths.frame(posterFor[i])) {
                MediaImages.shared.store(image, for: url)
            }
        }
        if let live, let data = try? Data(contentsOf: TestPaths.frame(live)) { m.ingest(.frame(data)) }
        return m
    }

    /// A run record for the preview lesson up to `step`, with real looking times.
    static func recorder(to step: Int, done: Bool = false, mistakeOn: Int? = 3) -> RunRecorder {
        let lesson = PreviewHub.fortuneTeller.lesson
        let t0 = Date(timeIntervalSince1970: 5_000_000)
        let times: [Double] = [7, 15, 31, 44, 61]  // leaves steps at 7, 8, 16, 13, 17 s
        let reasons: [Advance.Reason] = [.button, .camera, .camera, .button, .button]
        func s(_ i: Int, _ status: HubState.Status = .watching) -> HubState {
            HubState(lessonId: lesson.id, rev: 1, step: min(i, 4), total: 5, status: status, cameraConnected: true)
        }
        var r = RunRecorder()
        r.observe(s(0), advance: nil, at: t0)
        for i in 0..<step {
            if i == mistakeOn {
                r.observe(mistake: MistakeMessage(step: i, kind: .behind, looksLike: i - 1, message: "Flip it over first.",
                                                  confidence: 0.86, source: "gemini"))
            }
            let last = done && i == 4
            r.observe(last ? s(4, .done) : s(i + 1), advance: Advance(from: i, to: i + 1, reason: reasons[i]),
                      at: t0.addingTimeInterval(times[i]))
        }
        return r
    }

    @discardableResult
    static func render<V: View>(_ name: String, _ view: V, size: CGSize, theme: ThemeID = .system, dark: Bool = false,
                                scale: CGFloat = 2) throws -> URL {
        let content = view
            .frame(width: size.width, height: size.height)
            .handOverTheme(theme, dark: dark)
            .environment(\.colorScheme, dark ? .dark : .light)
            .environment(\.hoStillRendering, true)
        let renderer = ImageRenderer(content: content)
        renderer.scale = scale
        renderer.proposedSize = ProposedViewSize(size)
        let image = try #require(renderer.cgImage, "rendered \(name)")
        // The sandboxed Mac test host may not write into the repo; then the PNGs go to its temporary folder
        // (copy them to apps/apple/screenshots/ from there).
        var dir = TestPaths.screenshots
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try Data().write(to: dir.appending(path: ".write-check"))
            try? FileManager.default.removeItem(at: dir.appending(path: ".write-check"))
        } catch {
            dir = FileManager.default.temporaryDirectory.appending(path: "handover-screenshots")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        }
        let url = dir.appending(path: "\(name).png")
        let dest = try #require(CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, image, nil)
        #expect(CGImageDestinationFinalize(dest))
        #expect(image.width == Int(size.width * scale))
        return url
    }

    static func learn(_ m: AppModel, layout: LearnLayout, caption: String? = "Fold the top corner down to meet the bottom one.",
                      recorder: RunRecorder? = nil) -> some View {
        LearnView(clips: .still(caption: caption), recorder: recorder)
            .environment(m)
            .environment(\.learnLayoutOverride, layout)
    }

    // MARK: - Learn

    @Test func learnIPhonePortrait() throws {
        // State 9: step 4, watching with a check reason. State 10: the behind mistake.
        try Self.render("learn-iphone-portrait", Self.learn(Self.model(startAt: 9), layout: .pip,
                                                            recorder: Self.recorder(to: 3)), size: Self.iPhone)
        try Self.render("learn-iphone-portrait-mistake", Self.learn(Self.model(startAt: 10), layout: .pip,
                                                                    recorder: Self.recorder(to: 3)), size: Self.iPhone)
        try Self.render("learn-iphone-portrait-dark", Self.learn(Self.model(startAt: 2, live: "01"), layout: .pip,
                                                                 caption: "Fold it corner to corner.",
                                                                 recorder: Self.recorder(to: 1)),
                        size: Self.iPhone, dark: true)
    }

    @Test func learnIPhoneLandscape() throws {
        try Self.render("learn-iphone-landscape", Self.learn(Self.model(startAt: 9), layout: .sideBySide(phone: true),
                                                             recorder: Self.recorder(to: 3)), size: Self.iPhoneLandscape)
        try Self.render("learn-iphone-landscape-mistake", Self.learn(Self.model(startAt: 10), layout: .sideBySide(phone: true),
                                                                     recorder: Self.recorder(to: 3)), size: Self.iPhoneLandscape)
    }

    @Test func learnIPadAndMac() throws {
        try Self.render("learn-ipad", Self.learn(Self.model(startAt: 10), layout: .sideBySide(phone: false),
                                                 recorder: Self.recorder(to: 3)), size: Self.iPad)
        try Self.render("learn-mac", Self.learn(Self.model(startAt: 9), layout: .sideBySide(phone: false),
                                                recorder: Self.recorder(to: 3)), size: Self.mac)
        try Self.render("learn-mac-checks-off", Self.learn(Self.model(startAt: 11), layout: .sideBySide(phone: false),
                                                           recorder: Self.recorder(to: 3)), size: Self.mac, dark: true)
    }

    @Test func learnInFourThemes() throws {
        for (theme, dark) in [(ThemeID.ivory, false), (.grain, false), (.chalkboard, true), (.mono, true), (.harbor, true)] {
            try Self.render("learn-theme-\(theme.rawValue)", Self.learn(Self.model(startAt: 10), layout: .pip,
                                                                        recorder: Self.recorder(to: 3)),
                            size: Self.iPhone, theme: theme, dark: dark)
        }
    }

    @Test func learnStates() throws {
        // No camera yet, and simulated checks with a recording as the camera.
        let empty = AppModel.preview(startAt: 0)
        try Self.render("learn-no-lesson", Self.learn(empty, layout: .pip, caption: nil), size: Self.iPhone)
        let mock = Self.model(startAt: 2, live: "01")
        var s = mock.state
        s.checkMode = .mock
        s.camera = CameraInfo(name: "take.mp4", platform: .replay, source: .file)
        mock.ingest(.state(s))
        try Self.render("learn-mock-recording", Self.learn(mock, layout: .sideBySide(phone: false), caption: nil,
                                                           recorder: Self.recorder(to: 1)), size: Self.mac)
    }

    // MARK: - Components

    @Test func badges() throws {
        let view = VStack(alignment: .leading, spacing: 14) {
            ForEach(LearnStatus.allCases, id: \.self) { status in
                HStack(spacing: 16) {
                    StatusBadge(status: status).frame(width: 190, alignment: .leading)
                    StatusBadge(status: status, overVideo: true)
                        .padding(8)
                        .background(Color.black.opacity(0.85), in: RoundedRectangle(cornerRadius: 10))
                }
            }
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .hoPaperBackground()
        try Self.render("badges", view, size: CGSize(width: 520, height: 480))
        try Self.render("badges-dark", view, size: CGSize(width: 520, height: 480), dark: true)
        try Self.render("badges-mono", view, size: CGSize(width: 520, height: 480), theme: .mono)
    }

    @Test func mistakeCards() throws {
        let poster = Self.cgImage(TestPaths.frame("04"))
        let view = VStack(spacing: 14) {
            MistakeCard(kind: .behind(looksLike: 2), message: "Flip it over first.")
            MistakeCard(kind: .ahead, message: "You're ahead.")
            MistakeCard(kind: .live, message: "Crease along the line, not past it.", compact: false)
            ZStack(alignment: .bottom) {
                Color.black
                if let poster { Image(decorative: poster, scale: 1).resizable().aspectRatio(contentMode: .fit) }
                MistakeCard(kind: .behind(looksLike: 2), message: "Flip it over first.", overVideo: true).padding(8)
            }
            .frame(height: 210)
            .clipShape(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .hoPaperBackground()
        try Self.render("mistake-cards", view, size: CGSize(width: 402, height: 640))
        try Self.render("mistake-cards-dark", view, size: CGSize(width: 402, height: 640), dark: true)
    }

    @Test func componentGallery() throws {
        for (theme, dark) in [(ThemeID.system, false), (.newsprint, false), (.nocturne, true), (.matte, false)] {
            try Self.render("components-\(theme.rawValue)", Gallery(), size: CGSize(width: 402, height: 980),
                            theme: theme, dark: dark)
        }
    }

    // MARK: - Course and Done

    @Test func courseView() throws {
        let m = Self.model(startAt: 9)
        let lesson = m.lesson!
        let r = Self.recorder(to: 3)
        var seconds: [Int: Double] = [:]
        for i in 0..<5 { if let s = r.seconds(i) { seconds[i] = s } }
        let view = CourseView(lesson: lesson, statuses: r.statuses(), yourSeconds: seconds, current: 3,
                              thumbnail: { MediaImages.shared.image(m.mediaURL($0.refFrame)) }, onGoto: { _ in })
            .hoPaperBackground()
            .environment(m)
        try Self.render("course", view, size: CGSize(width: 402, height: 520))
        try Self.render("course-dark", view, size: CGSize(width: 402, height: 520), theme: .dim, dark: true)
    }

    @Test func done() throws {
        let m = Self.model(startAt: 13, live: nil)
        let summary = RunSummary(recorder: Self.recorder(to: 5, done: true), lesson: m.lesson!)
        #expect(summary.score != nil)
        let view = DoneView(summary: summary, lessonId: m.lesson!.id, onGoto: { _ in }, onStartOver: {},
                            onLibrary: {}, isStill: true).environment(m)
        try Self.render("done-iphone", view, size: CGSize(width: 402, height: 1500))
        try Self.render("done-mac", view, size: Self.mac, dark: true)

        // Not enough data: two steps skipped with goto, no times.
        var r = RunRecorder()
        let id = m.lesson!.id
        let t0 = Date(timeIntervalSince1970: 6_000_000)
        r.observe(HubState(lessonId: id, rev: 1, step: 0, total: 5), advance: nil, at: t0)
        r.observe(HubState(lessonId: id, rev: 1, step: 4, total: 5), advance: nil, at: t0.addingTimeInterval(3))
        r.observe(HubState(lessonId: id, rev: 1, step: 4, total: 5, status: .done),
                  advance: Advance(from: 4, to: 5, reason: .button), at: t0.addingTimeInterval(9))
        let sparse = DoneView(summary: RunSummary(recorder: r, lesson: m.lesson!), lessonId: id, onGoto: { _ in },
                              onStartOver: {}, isStill: true).environment(m)
        try Self.render("done-not-enough-data", sparse, size: CGSize(width: 402, height: 1300))
    }
}

/// Every DesignSystem component in one column, for the theme snapshots.
private struct Gallery: View {
    @Environment(\.theme) private var theme
    @State private var stars = 4

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Components").hoFont(.display, theme).foregroundStyle(theme.colors.ink)
            StepProgressBar(total: 8, current: 3)
            StepProgressBar(total: 8, current: 3, mistakeOnCurrent: true)
            HStack(spacing: 8) {
                StatusBadge(status: .watching)
                StatusBadge(status: .verified)
                StatusBadge(status: .checksOff)
            }
            Button("Next") {}.buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            HStack {
                Button("Back", systemImage: "chevron.left") {}.buttonStyle(HOButtonStyle(.secondary))
                Button("I'm Fine") {}.buttonStyle(HOButtonStyle(.quiet, size: .small))
                Button("Delete", systemImage: "trash") {}.buttonStyle(HOButtonStyle(.destructive))
            }
            Button("Next") {}.buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true)).disabled(true)
            HORow(title: "Fold a paper fortune teller", meta: "5 steps, 0:58") {
                SymbolTile(symbol: "play.rectangle")
            } trailing: {
                ProgressRing(fraction: 0.6, size: 20)
            }
            .hoCard(radius: HORadius.control)
            HStack(spacing: 20) {
                ScoreRing(score: 82, animateIn: false).frame(width: 120)
                ScoreRing(score: nil, animateIn: false).frame(width: 120)
                VStack(spacing: 8) {
                    ProgressRing(fraction: 0.4, size: 44, center: "2")
                    ProgressRing(fraction: 1, size: 28, completed: true)
                }
            }
            TimeBar(yours: 14, expert: 21, longest: 40)
            TimeBar(yours: 35, expert: 17, longest: 40)
            TimeBar(yours: nil, expert: 8, longest: 40)
            StarRating(rating: $stars)
            HOBanner(symbol: "creditcard.trianglebadge.exclamationmark",
                     text: "Checks are off: the hub reached its spending limit. Use Next to move on.")
            HOToast(item: ToastItem(text: "Thanks. Rating sent.", symbol: "checkmark.circle.fill", tone: .good))
            HStack(spacing: 8) {
                StepResultMoment(result: StepResult.make(yours: 12, expert: 20, mistakesFixed: 0, byCamera: true))
                VideoPill(symbol: "testtube.2", text: "Mock checks")
            }
            .padding(10)
            .background(Color(white: 0.25), in: RoundedRectangle(cornerRadius: 12))
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .hoPaperBackground()
    }
}
