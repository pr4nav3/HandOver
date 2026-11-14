import Foundation

/// One hub WebSocket that keeps itself connected. `UISocket` and `CameraSocket` are thin layers on it.
///
/// - Reconnects after a drop with `Backoff`, at once after close 1011, and never after close 4000.
/// - Text commands go through a send queue: kept while disconnected, sent in order once connected.
///   Navigation commands older than `navigationTTL` are dropped instead, so a tap during a blip does
///   not fire many seconds later.
/// - The greeting (the camera hello) is always the first message on every connection.
/// - Binary frames are sent only when the previous one finished (`sendFrameIfIdle`); otherwise dropped.
///
/// Single use: after `stop()` or a stop decision, make a new one.
actor HubSocket {
    enum Event: Sendable, Equatable {
        case state(ConnectionState)
        case message(HubMessage)
    }

    typealias TransportFactory = @Sendable (URL) -> any WebSocketTransport

    nonisolated let url: URL
    nonisolated let channel: HubMessage.Channel
    nonisolated let events: AsyncStream<Event>
    nonisolated let navigationTTL: Duration
    static let queueLimit = 32

    private let continuation: AsyncStream<Event>.Continuation
    private let makeTransport: TransportFactory
    private let greeting: HubCommand?
    private let clock = ContinuousClock()
    private var backoff: Backoff
    private var runTask: Task<Void, Never>?
    private var transport: (any WebSocketTransport)?
    private var isOpen = false
    private var pumping = false
    private var frameInFlight = false
    private var queue: [(command: HubCommand, queuedAt: ContinuousClock.Instant)] = []
    private(set) var state: ConnectionState = .idle
    private var finished = false

    init(url: URL, channel: HubMessage.Channel, greeting: HubCommand? = nil, backoff: Backoff = Backoff(),
         navigationTTL: Duration = .seconds(3),
         makeTransport: @escaping TransportFactory = { URLSessionTransport(url: $0) }) {
        self.navigationTTL = navigationTTL
        self.url = url
        self.channel = channel
        self.greeting = greeting
        self.backoff = backoff
        self.makeTransport = makeTransport
        (events, continuation) = AsyncStream.makeStream(of: Event.self)
    }

    func start() {
        guard runTask == nil, !finished else { return }
        runTask = Task { await self.run() }
    }

    func stop() async {
        runTask?.cancel()
        runTask = nil
        let open = transport
        transport = nil
        isOpen = false
        await open?.close(code: 1000)
        set(.idle)
        finish()
    }

    /// Queues a command; it goes out now when connected, else after the next connect.
    func send(_ command: HubCommand) {
        if queue.count >= Self.queueLimit { queue.removeFirst() }
        queue.append((command, clock.now))
        pump()
    }

    /// Sends one binary frame if connected and the previous frame finished. Returns false when dropped.
    @discardableResult
    func sendFrameIfIdle(_ data: Data) -> Bool {
        guard isOpen, !frameInFlight, let transport else { return false }
        frameInFlight = true
        Task {
            let ok = (try? await transport.send(.binary(data))) != nil
            self.frameFinished(ok: ok)
        }
        return true
    }

    var isSendingFrame: Bool { frameInFlight }
    /// Frames that went out on any connection of this socket.
    private(set) var framesSent = 0

    // MARK: - Connection loop

    private func run() async {
        while !Task.isCancelled {
            set(.connecting)
            let transport = makeTransport(url)
            self.transport = transport
            var closeCode: Int?
            do {
                try await transport.open()
                if let greeting { try await transport.send(.text(greeting.text)) }
                guard !Task.isCancelled else { break }
                isOpen = true
                backoff.reset()
                set(.connected)
                pump()
                while !Task.isCancelled {
                    let message = try await transport.receive()
                    if let routed = HubMessage.route(message, on: channel) {
                        continuation.yield(.message(routed))
                    }
                }
            } catch let closed as SocketClosed {
                closeCode = closed.code
            } catch {
                closeCode = nil
            }
            isOpen = false
            frameInFlight = false
            if self.transport != nil {
                self.transport = nil
                await transport.close(code: 1000)
            }
            if Task.isCancelled { break }
            switch ReconnectPolicy.decide(closeCode: closeCode) {
            case .stop(let reason):
                set(.stopped(reason: reason))
                queue.removeAll()
                finish()
                return
            case .now:
                continue
            case .backoff:
                let delay = backoff.next()
                set(.retrying(attempt: backoff.attempt, delay: delay))
                try? await Task.sleep(for: delay)
            }
        }
    }

    private func finish() {
        finished = true
        continuation.finish()
    }

    private func set(_ new: ConnectionState) {
        guard new != state else { return }
        state = new
        continuation.yield(.state(new))
    }

    private func frameFinished(ok: Bool) {
        frameInFlight = false
        if ok { framesSent += 1 }
    }

    /// Sends queued commands in order while connected. Reentrant calls return at once.
    private func pump() {
        guard isOpen, !pumping, !queue.isEmpty else { return }
        pumping = true
        Task { await self.drain() }
    }

    private func drain() async {
        defer { pumping = false }
        while isOpen, let transport, !queue.isEmpty {
            let item = queue.removeFirst()
            if item.command.isNavigation, clock.now - item.queuedAt > navigationTTL { continue }
            do {
                try await transport.send(.text(item.command.text))
            } catch {
                // The connection is going down; keep the command for the next one.
                queue.insert(item, at: 0)
                return
            }
        }
    }
}
