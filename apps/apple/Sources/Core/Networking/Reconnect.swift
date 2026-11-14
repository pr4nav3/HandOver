import Foundation

/// Where a socket is.
enum ConnectionState: Equatable, Sendable {
    /// Not started, or stopped by the app.
    case idle
    case connecting
    case connected
    /// Lost; trying again after `delay`.
    case retrying(attempt: Int, delay: Duration)
    /// Will not reconnect on its own (for example close 4000, a newer connection from this device).
    case stopped(reason: String)

    var isConnected: Bool { self == .connected }

    /// Short words for a status line.
    var label: String {
        switch self {
        case .idle: "Not connected"
        case .connecting: "Connecting"
        case .connected: "Connected"
        case .retrying: "Reconnecting"
        case .stopped(let reason): reason
        }
    }
}

/// What to do after a connection ends, from its close code (CONTRACT.md section 6 and proposal P15).
enum ReconnectPolicy {
    enum Decision: Equatable, Sendable {
        case stop(reason: String)
        case now
        case backoff
    }

    static let replaced = 4000
    static let stalled = 1011
    static let tryLater = 1013

    static func decide(closeCode: Int?) -> Decision {
        switch closeCode {
        case replaced: .stop(reason: "Replaced by a newer connection from this device")
        case stalled: .now  // the hub gave up on one slow send; the next connect starts with a full state
        default: .backoff  // includes 1013 (connection cap) and network drops
        }
    }
}

/// Retry delays: 0.5 s, 1, 2, 4, 8, then 10 s each time, with up to 20% jitter so many clients do not
/// reconnect in step.
struct Backoff: Sendable {
    var base: Duration = .milliseconds(500)
    var cap: Duration = .seconds(10)
    var jitter: Double = 0.2
    private(set) var attempt = 0

    init(base: Duration = .milliseconds(500), cap: Duration = .seconds(10), jitter: Double = 0.2) {
        self.base = base
        self.cap = cap
        self.jitter = jitter
    }

    /// The next delay. `random` is in 0...1 (tests pass a fixed value).
    mutating func next(random: Double = Double.random(in: 0...1)) -> Duration {
        let exponent = min(attempt, 16)
        attempt += 1
        let raw = min(base * (1 << exponent), cap)
        let factor = 1 - jitter * min(max(random, 0), 1)
        return raw * factor
    }

    mutating func reset() { attempt = 0 }
}
