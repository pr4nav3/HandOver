import Foundation
import Synchronization

/// One WebSocket connection. `HubSocket` drives it; tests swap in a scripted fake.
protocol WebSocketTransport: Sendable {
    /// Returns once the handshake finished; throws if it failed.
    func open() async throws
    func send(_ message: SocketMessage) async throws
    /// The next message. Throws `SocketClosed` when the connection ends.
    func receive() async throws -> SocketMessage
    func close(code: Int) async
}

/// The connection ended. `code` is the WebSocket close code, or 0 when the network dropped without one.
struct SocketClosed: Error, Equatable, Sendable {
    var code: Int
    var reason: String = ""
}

/// `WebSocketTransport` over `URLSessionWebSocketTask`. Each connection gets its own session, so its
/// delegate (open and close events) belongs to exactly one task and is released on close.
final class URLSessionTransport: WebSocketTransport {
    /// The hub allows 8 MB per message; frames it sends are far smaller.
    static let maximumMessageSize = 4 * 1024 * 1024

    private let session: URLSession
    private let task: URLSessionWebSocketTask
    private let events: Events

    init(url: URL, openTimeout: TimeInterval = 5) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = openTimeout
        events = Events()
        session = URLSession(configuration: configuration, delegate: events, delegateQueue: nil)
        task = session.webSocketTask(with: url)
        task.maximumMessageSize = Self.maximumMessageSize
    }

    func open() async throws {
        let task = task
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, any Error>) in
                events.waitForOpen(continuation)
                task.resume()
            }
        } onCancel: {
            task.cancel(with: .goingAway, reason: nil)
        }
    }

    func send(_ message: SocketMessage) async throws {
        switch message {
        case .text(let text): try await task.send(.string(text))
        case .binary(let data): try await task.send(.data(data))
        }
    }

    func receive() async throws -> SocketMessage {
        do {
            switch try await task.receive() {
            case .string(let text): return .text(text)
            case .data(let data): return .binary(data)
            @unknown default: return .binary(Data())
            }
        } catch {
            throw await closed()
        }
    }

    func close(code: Int) async {
        task.cancel(with: URLSessionWebSocketTask.CloseCode(rawValue: code) ?? .normalClosure, reason: nil)
        session.finishTasksAndInvalidate()
    }

    /// The close code can reach the delegate a moment after the failed receive, so wait briefly for it.
    private func closed() async -> SocketClosed {
        for _ in 0..<5 {
            if let code = events.closeCode ?? Self.code(task.closeCode) {
                return SocketClosed(code: code, reason: events.closeReason)
            }
            try? await Task.sleep(for: .milliseconds(40))
        }
        return SocketClosed(code: 0)
    }

    private static func code(_ code: URLSessionWebSocketTask.CloseCode) -> Int? {
        code == .invalid ? nil : code.rawValue
    }

    /// Open and close callbacks from URLSession, on its own queue.
    private final class Events: NSObject, URLSessionWebSocketDelegate, Sendable {
        private struct State {
            var waiting: CheckedContinuation<Void, any Error>?
            var opened = false
            var failure: (any Error)?
            var closeCode: Int?
            var closeReason = ""
        }

        private let state = Mutex(State())

        var closeCode: Int? { state.withLock { $0.closeCode } }
        var closeReason: String { state.withLock { $0.closeReason } }

        func waitForOpen(_ continuation: CheckedContinuation<Void, any Error>) {
            let early: Result<Void, any Error>? = state.withLock { s in
                if s.opened { return .success(()) }
                if let failure = s.failure { return .failure(failure) }
                s.waiting = continuation
                return nil
            }
            if let early { continuation.resume(with: early) }
        }

        private func finishOpen(_ result: Result<Void, any Error>) {
            let waiting = state.withLock { s -> CheckedContinuation<Void, any Error>? in
                switch result {
                case .success: s.opened = true
                case .failure(let error): if !s.opened { s.failure = error }
                }
                defer { s.waiting = nil }
                return s.waiting
            }
            waiting?.resume(with: result)
        }

        func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                        didOpenWithProtocol protocol: String?) {
            finishOpen(.success(()))
        }

        func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
            state.withLock { s in
                s.closeCode = closeCode.rawValue
                s.closeReason = reason.map { String(decoding: $0, as: UTF8.self) } ?? ""
            }
            finishOpen(.failure(SocketClosed(code: closeCode.rawValue)))
        }

        func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: (any Error)?) {
            finishOpen(.failure(error ?? SocketClosed(code: 0)))
        }
    }
}
