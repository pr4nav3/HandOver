import Foundation
import Synchronization
@testable import HandOver

/// A scripted WebSocket: the test pushes what the hub "sends" and reads what the app sent.
final class FakeTransport: WebSocketTransport {
    private struct State {
        var inbox: [Result<SocketMessage, SocketClosed>] = []
        var waiter: CheckedContinuation<SocketMessage, any Error>?
        var sent: [SocketMessage] = []
        var closed = false
        var heldFrame: CheckedContinuation<Void, Never>?
    }

    private let state = Mutex(State())
    let openError: SocketClosed?
    /// When true, a binary send stays in flight until `releaseFrame()`.
    let holdFrames: Bool

    init(openError: SocketClosed? = nil, holdFrames: Bool = false) {
        self.openError = openError
        self.holdFrames = holdFrames
    }

    var sent: [SocketMessage] { state.withLock { $0.sent } }
    var sentTexts: [String] {
        sent.compactMap { if case .text(let t) = $0 { return t } else { return nil } }
    }
    var sentFrames: Int {
        sent.filter { if case .binary = $0 { return true } else { return false } }.count
    }

    func open() async throws {
        if let openError { throw openError }
    }

    func send(_ message: SocketMessage) async throws {
        if case .binary = message, holdFrames {
            await withCheckedContinuation { c in state.withLock { $0.heldFrame = c } }
        }
        let closed = state.withLock { s in
            if !s.closed { s.sent.append(message) }
            return s.closed
        }
        if closed { throw SocketClosed(code: 0) }
    }

    func receive() async throws -> SocketMessage {
        try await withCheckedThrowingContinuation { c in
            let item = state.withLock { s -> Result<SocketMessage, SocketClosed>? in
                if !s.inbox.isEmpty { return s.inbox.removeFirst() }
                s.waiter = c
                return nil
            }
            if let item { c.resume(with: item) }
        }
    }

    func close(code: Int) async {
        state.withLock { $0.closed = true }
        deliver(.failure(SocketClosed(code: code)))
    }

    /// The hub sends this.
    func push(_ message: SocketMessage) { deliver(.success(message)) }
    func push(text: String) { push(.text(text)) }
    /// The hub closes the connection.
    func drop(code: Int) { deliver(.failure(SocketClosed(code: code))) }

    var isHoldingFrame: Bool { state.withLock { $0.heldFrame != nil } }

    func releaseFrame() {
        let held = state.withLock { s in defer { s.heldFrame = nil }; return s.heldFrame }
        held?.resume()
    }

    private func deliver(_ item: Result<SocketMessage, SocketClosed>) {
        let waiter = state.withLock { s -> CheckedContinuation<SocketMessage, any Error>? in
            if let w = s.waiter {
                s.waiter = nil
                return w
            }
            s.inbox.append(item)
            return nil
        }
        waiter?.resume(with: item.mapError { $0 as any Error })
    }
}

/// Hands out one `FakeTransport` per connection attempt, from a list (then healthy ones).
final class FakeNetwork: Sendable {
    private let made = Mutex<[FakeTransport]>([])
    private let planned: Mutex<[FakeTransport]>

    init(_ planned: [FakeTransport] = []) { self.planned = Mutex(planned) }

    var transports: [FakeTransport] { made.withLock { $0 } }

    var factory: HubSocket.TransportFactory {
        { [self] _ in
            let next = planned.withLock { $0.isEmpty ? FakeTransport() : $0.removeFirst() }
            made.withLock { $0.append(next) }
            return next
        }
    }

    /// The n-th connection, once it exists.
    func transport(_ index: Int) async throws -> FakeTransport {
        try await eventually("connection \(index)") { self.transports.count > index }
        return transports[index]
    }
}

/// Collects a socket's events so tests can wait for them.
final class EventLog: Sendable {
    private let events = Mutex<[HubSocket.Event]>([])

    init(_ stream: AsyncStream<HubSocket.Event>) {
        Task { [weak self] in
            for await event in stream { self?.events.withLock { $0.append(event) } }
        }
    }

    var all: [HubSocket.Event] { events.withLock { $0 } }
    var messages: [HubMessage] {
        all.compactMap { if case .message(let m) = $0 { return m } else { return nil } }
    }
    /// The newest hub `state` message.
    var latestState: HubState? {
        messages.reversed().lazy.compactMap { if case .state(let s) = $0 { s } else { nil } }.first
    }
    var states: [ConnectionState] {
        all.compactMap { if case .state(let s) = $0 { return s } else { return nil } }
    }
}

struct TimedOut: Error, CustomStringConvertible {
    var what: String
    var description: String { "timed out waiting for \(what)" }
}

/// Polls until `condition` holds, failing after `timeout`.
func eventually(_ what: String, timeout: Duration = .seconds(3), _ condition: @Sendable () async -> Bool) async throws {
    let deadline = ContinuousClock.now + timeout
    while ContinuousClock.now < deadline {
        if await condition() { return }
        try await Task.sleep(for: .milliseconds(10))
    }
    throw TimedOut(what: what)
}

/// A tiny valid-looking JPEG header plus bytes.
let sampleJPEG = Data([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46])

/// Fast retries for tests.
let quickBackoff = Backoff(base: .milliseconds(10), cap: .milliseconds(20), jitter: 0)
