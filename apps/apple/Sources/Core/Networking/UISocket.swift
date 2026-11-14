import Foundation

/// The viewer socket, `/ws/ui` (CONTRACT.md section 7): receives state, advance, mistake, error and live
/// JPEG frames; sends select_lesson, next, back, goto and dismiss_mistake.
///
/// `next` and `back` go through `StepGuard`, so they always carry `from` and a double tap sends one.
actor UISocket {
    nonisolated let events: AsyncStream<HubSocket.Event>
    private let socket: HubSocket
    private var guardrail = StepGuard()

    init(hub: HubURL, backoff: Backoff = Backoff(),
         makeTransport: @escaping HubSocket.TransportFactory = { URLSessionTransport(url: $0) }) {
        socket = HubSocket(url: hub.uiSocket, channel: .ui, backoff: backoff, makeTransport: makeTransport)
        let (stream, continuation) = AsyncStream.makeStream(of: HubSocket.Event.self)
        events = stream
        let source = socket.events
        // Watch states on the way through so the guard always knows the position on screen.
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

    func selectLesson(_ id: String) async { await socket.send(.selectLesson(id: id)) }
    func goto(step: Int) async { await socket.send(.goto(step: step)) }
    func dismissMistake() async { await socket.send(.dismissMistake) }

    /// Sends `next` from the current position. False when it was not sent (nothing to do, or a command
    /// from this position is still in flight).
    @discardableResult
    func next(reason: HubCommand.NextReason = .button) async -> Bool {
        guard let command = guardrail.next(reason: reason, now: ProcessInfo.processInfo.systemUptime) else { return false }
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
