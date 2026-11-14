import Foundation

/// Builds `next` and `back` with the `from` guard (CONTRACT.md section 5).
///
/// Every command carries the position the screen showed. The hub ignores a command whose `from` no longer
/// matches, so a tap that races a camera advance never skips a step. On top of that, this guard sends at
/// most one command per position until a newer state arrives or `hold` passes, so a double tap sends one.
struct StepGuard: Sendable {
    /// How long a sent command blocks another from the same position when no state answers it.
    var hold: TimeInterval = 1.0
    private(set) var state: HubState = .empty
    private var pending: (position: Int, at: TimeInterval)?

    init(hold: TimeInterval = 1.0) { self.hold = hold }

    /// Feed every state the hub sends. A moved position releases the hold.
    mutating func observe(_ new: HubState) {
        if new.lessonId != state.lessonId || new.position != state.position || new.rev != state.rev {
            pending = nil
        }
        state = new
    }

    /// After a reconnect nothing is in flight any more.
    mutating func reset() { pending = nil }

    var canGoNext: Bool { state.hasLesson && state.total > 0 && !state.isDone }
    var canGoBack: Bool { state.hasLesson && state.total > 0 && state.position > 0 }

    /// The `next` to send now, or nil when it would do nothing or one from this position is in flight.
    mutating func next(reason: HubCommand.NextReason = .button, now: TimeInterval) -> HubCommand? {
        guard canGoNext, claim(now: now) else { return nil }
        return .next(reason: reason, from: state.position)
    }

    mutating func back(now: TimeInterval) -> HubCommand? {
        guard canGoBack, claim(now: now) else { return nil }
        return .back(from: state.position)
    }

    private mutating func claim(now: TimeInterval) -> Bool {
        if let pending, pending.position == state.position, now - pending.at < hold { return false }
        pending = (state.position, now)
        return true
    }
}
