// Compiles with Xcode on macOS against MWDAT 1.0.1; not yet run on a device.
//
// Client for the hub's /ws/camera socket (CONTRACT.md section 6).
//   -> hello (first), binary JPEG frames, next {from}, back {from}
//   <- camera_status, state, advance, mistake, error (text JSON, after hello)
//   close 4000 "replaced": never reconnect.

import Foundation
import Combine
import UIKit

@MainActor
final class HubClient: ObservableObject {
    @Published private(set) var connected = false
    @Published private(set) var connecting = false
    @Published private(set) var replaced = false
    /// camera_status.active: this camera is the one the hub judges.
    @Published private(set) var active = false
    @Published private(set) var hasState = false
    @Published private(set) var step = 0
    @Published private(set) var total = 0
    @Published private(set) var status = ""
    @Published private(set) var lessonId: String?
    @Published private(set) var stepTitle: String?
    @Published private(set) var lastAdvanceReason: String?
    @Published private(set) var mistakeMessage: String?
    @Published private(set) var errorMessage: String?
    /// True while frames are being sent successfully (cleared 3 s after the last one).
    @Published private(set) var isSending = false
    @Published private(set) var framesSent = 0
    @Published private(set) var urlString = ""

    /// Called once when the hub closes this socket with code 4000.
    var onReplaced: (@MainActor () -> Void)?

    let deviceId: String

    private var url: URL?
    private var source = "phone"
    private var shouldRun = false
    private var task: URLSessionWebSocketTask?
    private weak var lastEndedTask: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var reconnectTask: Task<Void, Never>?
    private var sendingResetTask: Task<Void, Never>?
    private var titlesTask: Task<Void, Never>?
    private var attempt = 0
    private var sendInFlight = false {
        didSet { sendBusy.set(sendInFlight) }
    }
    /// True while a frame is being sent. Camera sources read it on their own
    /// queues and skip encoding, so frames never queue behind a slow network.
    nonisolated let sendBusy = LockedFlag(false)
    private var lessonRev: Int?
    private var stepTitles: [String] = []

    private let socketDelegate = SocketDelegate()
    private lazy var session: URLSession = {
        let configuration = URLSessionConfiguration.default
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 10
        return URLSession(configuration: configuration, delegate: socketDelegate, delegateQueue: OperationQueue.main)
    }()

    init() {
        deviceId = HubClient.loadDeviceId()
        socketDelegate.owner = self
    }

    var canNavigate: Bool { connected && hasState && total > 0 }

    // MARK: - Public API

    /// `host` may be "192.168.1.20:8000", "192.168.1.20" (port 8000 assumed),
    /// "ws://host:port[/path]", "wss://host:port[/path]", or an http(s):// URL.
    func connect(to host: String) {
        guard let url = HubClient.makeURL(from: host) else {
            errorMessage = "Bad hub address: \(host)"
            return
        }
        disconnect()
        self.url = url
        urlString = url.absoluteString
        shouldRun = true
        replaced = false
        attempt = 0
        errorMessage = nil
        openSocket()
    }

    func disconnect() {
        shouldRun = false
        reconnectTask?.cancel()
        reconnectTask = nil
        receiveTask?.cancel()
        receiveTask = nil
        titlesTask?.cancel()
        titlesTask = nil
        if let task = task {
            task.cancel(with: .normalClosure, reason: nil)
        }
        task = nil
        resetConnectionState()
        hasState = false
    }

    /// "phone" or "glasses". Re-sends hello when connected (hello may repeat).
    func setSource(_ newSource: String) {
        guard newSource != source else { return }
        source = newSource
        if let task = task, connected {
            sendHello(on: task)
        }
    }

    /// Sends one JPEG as a binary message. Drops the frame if the previous send is still in flight.
    /// `source` is the camera that made it; the hub hears a new hello before the first frame from a
    /// different camera, so it never shows "glasses" before a glasses frame exists.
    func send(frame: Data, source frameSource: String) {
        guard connected, let task = task, !sendInFlight else { return }
        setSource(frameSource)
        sendInFlight = true
        task.send(.data(frame)) { [weak self] error in
            let ok = (error == nil)
            guard let self = self else { return }
            Task { @MainActor in
                self.frameSendFinished(task: task, ok: ok)
            }
        }
    }

    func next() {
        guard let task = task, canNavigate else { return }
        errorMessage = nil
        sendJSON(["type": "next", "reason": "button", "from": step], on: task)
    }

    func back() {
        guard let task = task, canNavigate else { return }
        errorMessage = nil
        sendJSON(["type": "back", "from": step], on: task)
    }

    // MARK: - Socket lifecycle

    private func openSocket() {
        guard shouldRun, let url = url else { return }
        let task = session.webSocketTask(with: url)
        task.maximumMessageSize = 4 * 1024 * 1024
        self.task = task
        connecting = true
        connected = false
        task.resume()
        sendHello(on: task) // queued by URLSession until the handshake completes
        startReceiving(on: task)
    }

    private func startReceiving(on task: URLSessionWebSocketTask) {
        receiveTask?.cancel()
        receiveTask = Task { [weak self] in
            while !Task.isCancelled {
                let message: URLSessionWebSocketTask.Message
                do {
                    message = try await task.receive()
                } catch {
                    let code = task.closeCode.rawValue
                    if let strong = self {
                        strong.socketEnded(task, closeCode: code)
                    }
                    return
                }
                guard let strong = self else { return }
                strong.handle(message, from: task)
            }
        }
    }

    fileprivate func socketOpened(_ openedTask: URLSessionWebSocketTask) {
        guard openedTask === task else { return }
        markConnected()
    }

    fileprivate func socketEnded(_ endedTask: URLSessionWebSocketTask, closeCode: Int) {
        if closeCode == 4000 {
            // The close callback can arrive after a receive failure already retired the task.
            if endedTask === task || (task == nil && endedTask === lastEndedTask) {
                markReplaced()
            }
            return
        }
        guard endedTask === task else { return }
        lastEndedTask = endedTask
        task = nil
        receiveTask = nil
        resetConnectionState()
        scheduleReconnect()
    }

    private func markConnected() {
        if !connected {
            connected = true
            connecting = false
            attempt = 0
        }
    }

    private func markReplaced() {
        replaced = true
        shouldRun = false
        reconnectTask?.cancel()
        reconnectTask = nil
        receiveTask?.cancel()
        receiveTask = nil
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        resetConnectionState()
        // The session note says what happened and what to do; no second, technical message.
        errorMessage = nil
        onReplaced?()
    }

    private func resetConnectionState() {
        connected = false
        connecting = false
        active = false
        isSending = false
        sendInFlight = false
        sendingResetTask?.cancel()
        sendingResetTask = nil
    }

    private func scheduleReconnect() {
        guard shouldRun, !replaced else { return }
        let delay = min(5.0, 0.5 * pow(2.0, Double(attempt)))
        attempt += 1
        connecting = true
        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard let strong = self, !Task.isCancelled, strong.shouldRun, strong.task == nil else { return }
            strong.openSocket()
        }
    }

    // MARK: - Sending

    private func sendHello(on task: URLSessionWebSocketTask) {
        let name = source == "glasses" ? "Ray-Ban Meta via iPhone" : "iPhone camera"
        let hello: [String: Any] = [
            "type": "hello",
            "device_id": deviceId,
            "name": name,
            "platform": "ios",
            "source": source,
        ]
        sendJSON(hello, on: task)
    }

    private func sendJSON(_ object: [String: Any], on task: URLSessionWebSocketTask) {
        guard JSONSerialization.isValidJSONObject(object),
              let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { error in
            if let error = error {
                print("[hub] send failed: \(error.localizedDescription)")
            }
        }
    }

    private func frameSendFinished(task sentOn: URLSessionWebSocketTask, ok: Bool) {
        sendInFlight = false
        guard ok, sentOn === task else { return }
        framesSent += 1
        isSending = true
        sendingResetTask?.cancel()
        sendingResetTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            guard let strong = self, !Task.isCancelled else { return }
            strong.isSending = false
        }
    }

    // MARK: - Receiving

    private func handle(_ message: URLSessionWebSocketTask.Message, from source: URLSessionWebSocketTask) {
        guard source === task else { return }
        markConnected()
        switch message {
        case .string(let text):
            handleText(text)
        case .data:
            break // the hub never sends binary on /ws/camera
        @unknown default:
            break
        }
    }

    private func handleText(_ text: String) {
        guard let data = text.data(using: .utf8),
              let parsed = try? JSONSerialization.jsonObject(with: data),
              let json = parsed as? [String: Any],
              let type = json["type"] as? String else { return }

        switch type {
        case "state":
            if let value = json["step"] as? Int { step = value }
            if let value = json["total"] as? Int { total = value }
            status = (json["status"] as? String) ?? ""
            if let mistake = json["mistake"] as? [String: Any] {
                mistakeMessage = mistake["message"] as? String
            } else {
                mistakeMessage = nil
            }
            hasState = true
            updateLesson(id: json["lesson_id"] as? String, rev: json["rev"] as? Int)
            refreshStepTitle()
        case "advance":
            lastAdvanceReason = json["reason"] as? String
        case "mistake":
            mistakeMessage = json["message"] as? String
        case "camera_status":
            if let value = json["active"] as? Bool { active = value }
        case "error":
            errorMessage = json["message"] as? String
        default:
            break // ignore unknown types (CONTRACT compatibility rule)
        }
    }

    // MARK: - Step titles (GET /api/lessons/{id})

    private func updateLesson(id: String?, rev: Int?) {
        guard let id = id else {
            lessonId = nil
            lessonRev = nil
            stepTitles = []
            titlesTask?.cancel()
            titlesTask = nil
            return
        }
        guard id != lessonId || rev != lessonRev else { return }
        lessonId = id
        lessonRev = rev
        stepTitles = []
        titlesTask?.cancel()
        guard let lessonURL = lessonURL(for: id) else { return }
        titlesTask = Task { [weak self] in
            do {
                let (data, _) = try await URLSession.shared.data(from: lessonURL)
                let titles = HubClient.parseStepTitles(data)
                guard let strong = self, !Task.isCancelled, strong.lessonId == id else { return }
                strong.stepTitles = titles
                strong.refreshStepTitle()
            } catch {
                // Titles are cosmetic; "Step 3 of 8" still shows.
            }
        }
    }

    private func refreshStepTitle() {
        if step >= 0, step < stepTitles.count, !stepTitles[step].isEmpty {
            stepTitle = stepTitles[step]
        } else {
            stepTitle = nil
        }
    }

    private func lessonURL(for id: String) -> URL? {
        guard let url = url, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        components.scheme = (components.scheme == "wss") ? "https" : "http"
        components.path = "/api/lessons/\(id)"
        components.query = nil
        return components.url
    }

    private static func parseStepTitles(_ data: Data) -> [String] {
        guard let parsed = try? JSONSerialization.jsonObject(with: data),
              let lesson = parsed as? [String: Any],
              let steps = lesson["steps"] as? [[String: Any]] else { return [] }
        return steps.map { ($0["title"] as? String) ?? "" }
    }

    // MARK: - Helpers

    static func makeURL(from raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        let lower = text.lowercased()
        var bare = false
        if lower.hasPrefix("https://") {
            text = "wss://" + String(text.dropFirst("https://".count))
        } else if lower.hasPrefix("http://") {
            text = "ws://" + String(text.dropFirst("http://".count))
        } else if !(lower.hasPrefix("ws://") || lower.hasPrefix("wss://")) {
            text = "ws://" + text
            bare = true
        }
        guard var components = URLComponents(string: text),
              let host = components.host, !host.isEmpty else { return nil }
        components.scheme = components.scheme?.lowercased()
        if bare && components.port == nil {
            components.port = 8000 // HANDOVER_PORT default
        }
        if components.path.isEmpty || components.path == "/" {
            components.path = "/ws/camera"
        }
        return components.url
    }

    private static func loadDeviceId() -> String {
        let key = "handover.deviceId"
        if let existing = UserDefaults.standard.string(forKey: key), !existing.isEmpty {
            return existing
        }
        let fresh = "ios-" + UUID().uuidString.lowercased()
        UserDefaults.standard.set(fresh, forKey: key)
        return fresh
    }
}

// MARK: - URLSession delegate

/// Delivers open/close events (including the close code) to the HubClient on the main actor.
private final class SocketDelegate: NSObject, URLSessionWebSocketDelegate {
    weak var owner: HubClient?

    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocolName: String?) {
        guard let owner = owner else { return }
        Task { @MainActor in
            owner.socketOpened(webSocketTask)
        }
    }

    func urlSession(_ session: URLSession,
                    webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
                    reason: Data?) {
        let code = closeCode.rawValue
        guard let owner = owner else { return }
        Task { @MainActor in
            owner.socketEnded(webSocketTask, closeCode: code)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let webSocketTask = task as? URLSessionWebSocketTask else { return }
        let code = webSocketTask.closeCode.rawValue
        guard let owner = owner else { return }
        Task { @MainActor in
            owner.socketEnded(webSocketTask, closeCode: code)
        }
    }
}
