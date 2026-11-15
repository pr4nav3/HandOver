import Foundation

/// The camera socket, `/ws/camera` (CONTRACT.md section 6). Sends hello first on every connection, then
/// JPEG frames with send-when-idle backpressure; receives camera_status, state, advance, mistake and error.
/// Close 4000 (a newer connection from this device) stops it for good.
actor CameraSocket {
    /// The hub ignores frames over 2 MB.
    static let maxFrameBytes = 2 * 1024 * 1024
    /// The hub drops frames from one camera closer together than 0.2 s, so do not spend the upload.
    static let minFrameGap: Duration = .milliseconds(50)

    nonisolated let events: AsyncStream<HubSocket.Event>
    nonisolated let hello: CameraHello
    private let socket: HubSocket
    private let clock = ContinuousClock()
    private var lastFrameAt: ContinuousClock.Instant?
    private var guardrail = StepGuard()

    init(hub: HubURL, hello: CameraHello, backoff: Backoff = Backoff(),
         makeTransport: @escaping HubSocket.TransportFactory = { URLSessionTransport(url: $0) }) {
        self.hello = hello
        socket = HubSocket(url: hub.cameraSocket, channel: .camera, greeting: .hello(hello), backoff: backoff,
                           makeTransport: makeTransport)
        let (stream, continuation) = AsyncStream.makeStream(of: HubSocket.Event.self)
        events = stream
        let source = socket.events
        Task { [weak self] in
            for await event in source {
                await self?.observe(event)
                continuation.yield(event)
            }
            continuation.finish()
        }
    }

    func start() async { await socket.start() }
    func stop() async { await socket.stop() }

    /// Sends one JPEG if the socket is idle. Returns false when the frame was dropped (not connected,
    /// the previous frame still sending, too soon after the last one, too large, or not a JPEG).
    @discardableResult
    func send(frame jpeg: Data) async -> Bool {
        guard jpeg.count <= Self.maxFrameBytes, HubMessage.isJPEG(jpeg) else { return false }
        let now = clock.now
        if let lastFrameAt, now - lastFrameAt < Self.minFrameGap { return false }
        guard await socket.sendFrameIfIdle(jpeg) else { return false }
        lastFrameAt = now
        return true
    }

    var framesSent: Int { get async { await socket.framesSent } }

    /// True when `send(frame:)` would send now (connected, idle, and the gap since the last frame passed).
    var canSendFrame: Bool {
        get async {
            if let lastFrameAt, clock.now - lastFrameAt < Self.minFrameGap { return false }
            return await socket.canSendFrame
        }
    }

    /// `next` from the phone, with the same `from` guard as the web app.
    @discardableResult
    func next() async -> Bool {
        guard let command = guardrail.next(now: ProcessInfo.processInfo.systemUptime) else { return false }
        await socket.send(command)
        return true
    }

    @discardableResult
    func back() async -> Bool {
        guard let command = guardrail.back(now: ProcessInfo.processInfo.systemUptime) else { return false }
        await socket.send(command)
        return true
    }

    private func observe(_ event: HubSocket.Event) {
        switch event {
        case .message(.state(let state)): guardrail.observe(state)
        case .state(.connected): guardrail.reset()
        default: break
        }
    }
}
