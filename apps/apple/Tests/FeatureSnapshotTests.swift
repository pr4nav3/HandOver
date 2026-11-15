import Foundation
import SwiftUI
import Testing
@testable import HandOver
#if os(macOS)
import AppKit
#endif

/// Library, lesson detail, Make course, the timeline, Record, the glasses import entry and the editor, drawn to
/// PNG in apps/apple/screenshots/ (no simulator). Pictures and captions are the real files of
/// lessons/synthetic-fortune-teller-v1; video panes stay black because nothing can play offscreen.
///
/// On the Mac the views are drawn through an offscreen NSHostingView, because ImageRenderer cannot draw
/// AppKit-backed controls (lists, forms, fields, pickers). iPhone-only pieces (the Photos import capsule) are
/// drawn as their components.
@MainActor
@Suite(.serialized)
struct FeatureSnapshotTests {
    static let narrow = CGSize(width: 402, height: 874)
    static let iPad = CGSize(width: 1180, height: 820)
    static let mac = CGSize(width: 1100, height: 720)

    static var repo: URL {
        if let r = ProcessInfo.processInfo.environment["HANDOVER_REPO"] { return URL(fileURLWithPath: r) }
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().appending(path: "../../..").standardizedFileURL
    }

    static var out: URL {
        if let s = ProcessInfo.processInfo.environment["HANDOVER_SCREENSHOTS"] { return URL(fileURLWithPath: s) }
        return repo.appending(path: "apps/apple/screenshots")
    }

    static var lessonFolder: URL { repo.appending(path: "lessons/synthetic-fortune-teller-v1") }

    /// The synthetic lesson, its frames in the image cache under the preview hub's URLs, and its caption cues.
    static func fixture(model: AppModel) throws -> (Lesson, [Int: [EditorCaptionCue]]) {
        let data = try Data(contentsOf: lessonFolder.appending(path: "lesson.json"))
        let lesson = try JSONDecoder().decode(Lesson.self, from: data)
        let hub = try #require(model.hub)
        var cues: [Int: [EditorCaptionCue]] = [:]
        for (i, step) in lesson.steps.enumerated() {
            if let image = HubImageCache.decode(file: lessonFolder.appending(path: step.refFrame)) {
                HubImageCache.shared.store(image, for: hub.fileURL(lesson: lesson.id, path: step.refFrame))
                HubImageCache.shared.store(image, for: hub.fileURL(lesson: lesson.id, path: step.refFrame, rev: 0))
            }
            if let text = try? String(contentsOf: lessonFolder.appending(path: step.captions), encoding: .utf8) {
                cues[i] = WebVTT.parse(text)
            }
        }
        return (lesson, cues)
    }

    static func card(_ lesson: Lesson, hub: HubURL, status: CourseStatus = .published, progress: CourseProgress? = nil) -> CourseCardItem {
        CourseCardItem(id: lesson.id, title: lesson.title,
                       covers: CourseMedia.coverCandidates(hub: hub, lessonId: lesson.id, coverURL: nil),
                       steps: lesson.steps.count, duration: CourseFormat.duration(of: lesson), status: status,
                       progress: progress)
    }

    // MARK: - Screens

    @Test func library() async throws {
        let model = AppModel.preview()
        let (lesson, _) = try Self.fixture(model: model)
        let hub = try #require(model.hub)
        let store = LibraryStore()
        store.preview(items: [Self.card(lesson, hub: hub, progress: CourseProgress(lastStepsDone: 3, total: lesson.steps.count))])
        let view = NavigationStack { LibraryView(preview: store) }
        try await Self.render(view, model: model, size: Self.mac, name: "library-mac")
        try await Self.render(view, model: model, size: Self.narrow, name: "library-narrow")
    }

    @Test func lessonDetail() async throws {
        let model = AppModel.preview()
        let (lesson, _) = try Self.fixture(model: model)
        let detail = LessonDetailModel(preview: lesson,
                                       course: Course(id: lesson.id, title: lesson.title, steps: lesson.steps.count,
                                                      status: .published),
                                       permissions: CoursePermissions(canEdit: true))
        let view = NavigationStack { LessonDetailView(lessonId: lesson.id, preview: detail) }
        try await Self.render(view, model: model, size: Self.mac, name: "lesson-detail-mac")
        try await Self.render(view, model: model, size: Self.narrow, name: "lesson-detail-narrow")
    }

    @Test func teachProcessing() async throws {
        let model = AppModel.preview()
        let flow = UploadFlow()
        flow.preview(phase: .processing, video: TeachPickedVideo(url: URL(fileURLWithPath: "/tmp/fortune-teller.mov"), bytes: 214_300_000),
                     title: "Fold a fortune teller", progress: 1, job: Job(status: .extracting, id: "fortune-teller"),
                     lastStage: .extracting)
        let view = NavigationStack { MakeCourseView(flow: flow, hub: model.hub) }
        try await Self.render(view, model: model, size: Self.narrow, name: "teach-processing")

        let uploading = UploadFlow()
        uploading.preview(phase: .uploading, video: TeachPickedVideo(url: URL(fileURLWithPath: "/tmp/fortune-teller.mov"), bytes: 214_300_000),
                          title: "Fold a fortune teller", progress: 0.42)
        try await Self.render(NavigationStack { MakeCourseView(flow: uploading, hub: model.hub) }, model: model,
                              size: Self.narrow, name: "teach-uploading")
    }

    @Test func timeline() async throws {
        let model = AppModel.preview()
        let (lesson, _) = try Self.fixture(model: model)
        let flow = UploadFlow()
        flow.preview(phase: .finished, title: lesson.title, job: Job(status: .done, id: lesson.id), lesson: lesson)
        let view = NavigationStack { MakeCourseView(flow: flow, hub: model.hub) }
        try await Self.render(view, model: model, size: Self.narrow, name: "teach-timeline")
    }

    @Test func record() async throws {
        let model = AppModel.preview()
        let idle = RecordModel(engine: RecordPreviewEngine())
        idle.preview(phase: .ready)
        try await Self.render(RecordView(preview: idle), model: model, size: Self.narrow, name: "record-idle", dark: true)

        let recording = RecordModel(engine: RecordPreviewEngine())
        let levels: [Float] = (0..<24).map { Float(0.25 + 0.55 * abs(sin(Double($0) * 0.55))) }
        recording.preview(phase: .recording, elapsed: 42, levels: levels)
        try await Self.render(RecordView(preview: recording), model: model, size: Self.narrow, name: "record-recording", dark: true)
    }

    @Test func glassesImportEntry() async throws {
        let model = AppModel.preview()
        let view = ZStack {
            Color.black
            VStack(spacing: HOSpace.l) {
                Spacer()
                RecordGlassesCard(controller: GlassesController(state: .notRegistered)) {}
                GlassesImportLabel()
                Spacer().frame(height: 120)
            }
            .padding(HOSpace.l)
        }
        try await Self.render(view, model: model, size: Self.narrow, name: "record-glasses-entry", dark: true)
    }

    @Test func editor() async throws {
        let model = AppModel.preview()
        let (lesson, cues) = try Self.fixture(model: model)
        let store = EditorStore(lessonId: lesson.id)
        store.preview(lesson: lesson,
                      course: Course(id: lesson.id, title: lesson.title, steps: lesson.steps.count, status: .draft),
                      permissions: CoursePermissions(canEdit: true, canPublish: true, canManage: true),
                      capabilities: EditorCapabilities(course: true, captions: true, selfTest: true, voiceover: true),
                      cues: cues)
        store.selection = 1
        let view = NavigationStack { EditorView(lessonId: lesson.id, preview: store) }
        try await Self.render(view, model: model, size: Self.iPad, name: "editor-ipad")
        try await Self.render(view, model: model, size: Self.mac, name: "editor-mac")
    }

    // MARK: - Drawing

    static func render<V: View>(_ view: V, model: AppModel, size: CGSize, name: String, dark: Bool = false) async throws {
        let root = view
            .environment(model)
            .environment(AccountStore.preview())
            .environment(\.colorScheme, dark ? .dark : .light)
            .frame(width: size.width, height: size.height)
        // The sandboxed Mac test host cannot write into the repo; it writes to its own temporary folder
        // (handover-screenshots) and the files are copied to apps/apple/screenshots/ afterwards.
        var folder = out
        if (try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)) == nil
            || !FileManager.default.isWritableFile(atPath: folder.path(percentEncoded: false)) {
            folder = FileManager.default.temporaryDirectory.appending(path: "handover-screenshots")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        }
        let file = folder.appending(path: "\(name).png")
        #if os(macOS)
        let host = NSHostingView(rootView: root)
        host.frame = CGRect(origin: .zero, size: size)
        let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        window.contentView = host
        host.layoutSubtreeIfNeeded()
        // Let tasks and layout settle (images come from the cache, nothing loads from a network).
        for _ in 0..<6 {
            try await Task.sleep(for: .milliseconds(60))
            host.layoutSubtreeIfNeeded()
        }
        let rep = try #require(host.bitmapImageRepForCachingDisplay(in: host.bounds))
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try #require(rep.representation(using: .png, properties: [:]))
        try png.write(to: file)
        window.contentView = nil
        #else
        let renderer = ImageRenderer(content: root)
        renderer.scale = 2
        let image = try #require(renderer.uiImage)
        try #require(image.pngData()).write(to: file)
        #endif
        #expect(FileManager.default.fileExists(atPath: file.path(percentEncoded: false)))
    }
}
