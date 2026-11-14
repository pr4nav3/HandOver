import Foundation

/// What the learn screens show, folded from hub messages. Pure, so tests and previews drive it directly.
///
/// Mistakes: a `behind` mistake lives in `state.mistake` and goes when the hub clears it. An `ahead`
/// mistake is only a message followed by an advance from k to k + 2, so it is kept through that advance
/// and cleared on the next one (or by `dismissMistake`).
struct LearnSession: Equatable, Sendable {
    private(set) var state: HubState = .empty
    private(set) var mistake: MistakeMessage?
    private(set) var lastAdvance: Advance?
    /// The newest hub `error` message, for example `no lesson selected`.
    private(set) var lastError: String?
    /// Counts camera advances, so a view can play the chime on change.
    private(set) var cameraAdvances = 0

    /// Applies one message. Frames and unknown types do not change the session.
    mutating func apply(_ message: HubMessage) {
        switch message {
        case .state(let new):
            state = new
            if let current = new.mistake {
                mistake = current
            } else if mistake?.kind == .behind {
                mistake = nil
            }
        case .advance(let advance):
            lastAdvance = advance
            if advance.isCamera { cameraAdvances += 1 }
            if let shown = mistake, !(shown.kind == .ahead && advance.from == shown.step) {
                mistake = nil
            }
        case .mistake(let found):
            mistake = found
        case .error(let error):
            lastError = error.message
        case .cameraStatus, .frame, .unknown:
            break
        }
    }

    mutating func dismissMistake() { mistake = nil }
    mutating func clearError() { lastError = nil }
    mutating func reset() { self = LearnSession() }
}
