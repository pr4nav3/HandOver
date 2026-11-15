import CoreGraphics
import Foundation
import ImageIO
import Observation
import SwiftUI

/// The newest live frame from the hub's active camera, decoded.
struct LiveFrame {
    let image: CGImage
    let receivedAt: Date
    var size: CGSize { CGSize(width: image.width, height: image.height) }
}

/// Everything the screens read: the hub, the connection, the lesson library, the current lesson, the
/// learn state, the live frame, the mistake and errors. Owns the /ws/ui socket and the REST client.
/// Views get it from the environment: `@Environment(AppModel.self) private var model`.
@MainActor
@Observable
final class AppModel {
    /// Saved hubs, newest first.
    private(set) var recents: [HubURL]
    /// The hub in use, or nil.
    private(set) var hub: HubURL?
    /// The /ws/ui connection.
    private(set) var connection: ConnectionState = .idle
    private(set) var lessons: [LessonSummary] = []
    private(set) var isLoadingLessons = false
    /// The lesson the hub has selected (`state.lesson_id`), refetched whenever `rev` changes.
    private(set) var lesson: Lesson?
    private(set) var session = LearnSession()
    /// The newest live JPEG from the active camera.
    private(set) var frame: LiveFrame?
    /// The newest problem to show: a REST failure, a bad address, or a hub `error` message.
    private(set) var errorMessage: String?
    /// The REST API for the hub in use (upload, job polling, recut, delete).
    private(set) var client: HubClient?
    /// True when fed by a `PreviewHub` instead of a real hub.
    private(set) var isPreview = false

    var state: HubState { session.state }
    var mistake: MistakeMessage? { session.mistake }
    var lastAdvance: Advance? { session.lastAdvance }
    /// The step on screen, or nil with no lesson or on the done screen.
    var currentStep: Step? {
        guard let lesson, !state.isDone, lesson.steps.indices.contains(state.step) else { return nil }
        return lesson.steps[state.step]
    }
    var canGoNext: Bool { connection.isConnected && state.hasLesson && state.total > 0 && !state.isDone }
    var canGoBack: Bool { connection.isConnected && state.hasLesson && state.total > 0 && state.position > 0 }

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var socket: UISocket?
    @ObservationIgnored private var socketTask: Task<Void, Never>?
    @ObservationIgnored private var lessonTask: Task<Void, Never>?
    @ObservationIgnored private var previewTask: Task<Void, Never>?
    @ObservationIgnored private let makeTransport: HubSocket.TransportFactory

    init(defaults: UserDefaults = .standard,
         makeTransport: @escaping HubSocket.TransportFactory = { URLSessionTransport(url: $0) }) {
        self.defaults = defaults
        self.makeTransport = makeTransport
        recents = HubRecents(defaults: defaults).load()
    }

    // MARK: - Hubs

    /// Connects to a typed address, a scanned QR or a handover:// link. False (with `errorMessage` set)
    /// when the text is not an address.
    @discardableResult
    func connect(text: String) -> Bool {
        guard let hub = HubURL(parsing: text) else {
            errorMessage = "That doesn't look like a hub address. Try something like 192.168.1.20:8000."
            return false
        }
        connect(to: hub)
        return true
    }

    func connect(to hub: HubURL) {
        disconnect()
        self.hub = hub
        client = HubClient(hub: hub)
        errorMessage = nil
        recents = HubRecents.adding(hub, to: recents)
        HubRecents(defaults: defaults).save(recents)

        let socket = UISocket(hub: hub, makeTransport: makeTransport)
        self.socket = socket
        socketTask = Task { [weak self] in
            await socket.start()
            for await event in socket.events {
                guard let self else { return }
                self.handle(event)
            }
        }
        Task { await refreshLessons() }
    }

    /// Reconnects to the newest saved hub, if any. Call at launch.
    func reconnectToLastHub() {
        guard hub == nil, !isPreview, let last = recents.first else { return }
        connect(to: last)
    }

    func disconnect() {
        socketTask?.cancel()
        socketTask = nil
        lessonTask?.cancel()
        lessonTask = nil
        if let socket { Task { await socket.stop() } }
        socket = nil
        client = nil
        hub = nil
        connection = .idle
        lessons = []
        lesson = nil
        frame = nil
        session.reset()
    }

    func forget(_ hub: HubURL) {
        recents.removeAll { $0 == hub }
        HubRecents(defaults: defaults).save(recents)
        if self.hub == hub { disconnect() }
    }

    // MARK: - Library

    func refreshLessons() async {
        guard let client else { return }
        isLoadingLessons = true
        defer { isLoadingLessons = false }
        do {
            let list = try await client.lessons()
            guard client === self.client else { return }
            lessons = list
        } catch {
            report(error)
        }
    }

    // MARK: - Learn commands

    func select(lesson id: String) {
        if isPreview { return }
        Task { await socket?.selectLesson(id) }
    }

    func next(reason: HubCommand.NextReason = .button) {
        Task { await socket?.next(reason: reason) }
    }

    func back() {
        Task { await socket?.back() }
    }

    func goto(step: Int) {
        Task { await socket?.goto(step: step) }
    }

    /// Hides the mistake now and tells the hub, which clears `state.mistake` for every viewer.
    func dismissMistake() {
        session.dismissMistake()
        Task { await socket?.dismissMistake() }
    }

    /// Tells the hub to stop the run and unload the lesson (end_lesson), for every viewer. It names the lesson
    /// (and the run, when the hub is on that lesson), so the hub ignores it if someone has moved on since.
    func endLesson(lessonId: String? = nil) {
        let ids = Self.endIds(lessonId: lessonId, state: state)
        Task { await socket?.endLesson(lessonId: ids.lessonId, runId: ids.runId) }
    }

    /// The ids end_lesson carries: the given lesson (else the hub's current one) and the run when it belongs to it.
    nonisolated static func endIds(lessonId: String?, state: HubState) -> (lessonId: String?, runId: String?) {
        let lesson = lessonId ?? state.lessonId
        return (lesson, lesson != nil && lesson == state.lessonId ? state.runId : nil)
    }

    func clearError() {
        errorMessage = nil
        session.clearError()
    }

    /// A file of the current lesson (clip, captions, reference frame), with `?v=<rev>`.
    func mediaURL(_ path: String) -> URL? {
        guard let hub, let id = state.lessonId else { return nil }
        return hub.fileURL(lesson: id, path: path, rev: state.rev)
    }

    /// A camera socket to this hub, for the Camera feature. Start and stop it yourself.
    func makeCameraSocket(source: CameraInfo.Source) -> CameraSocket? {
        guard let hub else { return nil }
        let hello = CameraHello.thisDevice(source: source, deviceId: CameraHello.deviceId(defaults: defaults))
        return CameraSocket(hub: hub, hello: hello, makeTransport: makeTransport)
    }

    // MARK: - Incoming

    private func handle(_ event: HubSocket.Event) {
        switch event {
        case .state(let new):
            connection = new
            if case .stopped(let reason) = new { errorMessage = reason }
        case .message(let message):
            ingest(message)
        }
    }

    /// Applies one hub message. The socket calls it; so do `PreviewHub` and tests.
    func ingest(_ message: HubMessage) {
        let before = session.state
        session.apply(message)
        switch message {
        case .frame(let jpeg):
            if let image = Self.decode(jpeg: jpeg) { frame = LiveFrame(image: image, receivedAt: Date()) }
        case .error(let error):
            errorMessage = error.message
        case .state(let state):
            if state.lessonId != before.lessonId || state.rev != before.rev || (lesson == nil && state.lessonId != nil) {
                loadLesson(id: state.lessonId)
            }
            if !state.cameraConnected { frame = nil }
        default:
            break
        }
    }

    private func loadLesson(id: String?) {
        lessonTask?.cancel()
        guard let id else {
            lesson = nil
            return
        }
        if isPreview, lesson?.id == id { return }
        guard let client else { return }
        lessonTask = Task { [weak self] in
            do {
                let fetched = try await client.lesson(id: id)
                guard let self, !Task.isCancelled, self.state.lessonId == id else { return }
                self.lesson = fetched
            } catch is CancellationError {
            } catch {
                self?.report(error)
            }
        }
    }

    private func report(_ error: any Error) {
        if error is CancellationError { return }
        errorMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }

    nonisolated static func decode(jpeg: Data) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(jpeg as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary)
    }

    // MARK: - Previews

    /// A model fed by a `PreviewHub`, never touching the network or saved hubs. With `playing`, the
    /// script runs in a loop; otherwise it shows `startAt` (an index into the script's states).
    static func preview(_ preview: PreviewHub = .fortuneTeller, playing: Bool = false, startAt: Int = 2) -> AppModel {
        let suite = "handover.preview"
        UserDefaults.standard.removePersistentDomain(forName: suite)
        let model = AppModel(defaults: UserDefaults(suiteName: suite) ?? .standard)
        model.isPreview = true
        model.hub = preview.hub
        model.connection = .connected
        model.lessons = preview.summaries
        model.lesson = preview.lesson
        if playing {
            model.previewTask = Task { [weak model] in
                repeat {
                    for beat in preview.script {
                        try? await Task.sleep(for: beat.after)
                        guard let model, !Task.isCancelled else { return }
                        model.ingest(beat.message)
                    }
                } while !Task.isCancelled
            }
        } else {
            for message in preview.messages(upToState: startAt) { model.ingest(message) }
        }
        return model
    }
}
