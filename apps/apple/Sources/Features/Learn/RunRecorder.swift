import Foundation

/// What this device saw during one run of a lesson, from real events only (SCREENS.md 20.1): time per step
/// (summed across visits, charged on each position change, as Learn.tsx does), how each step was left
/// (camera, by hand, skipped), mistakes raised per step, whether checks were off at any moment on a step, and
/// whether the hub was gone for more than 10 s (the run is then "interrupted" and gets no score).
/// Pure, so tests drive it with made-up times.
struct RunRecorder: Equatable, Sendable {
    enum Exit: Equatable, Sendable {
        case camera, hand, skipped
    }

    struct StepRecord: Equatable, Sendable {
        var seconds: Double = 0
        var visits = 0
        var leftBy: Exit?
        var mistakes = 0
        var checksOff = false
        /// A visit to this step included a hub disconnect, so its time is not shown on the result moment.
        var interruptedVisit = false
    }

    /// A forward position change, for the step result moment.
    struct Change: Equatable, Sendable {
        var from: Int
        var to: Int
        /// The advance that caused it, or nil for a goto.
        var reason: Advance.Reason?
        /// The time of the visit just finished, nil when under 1 s or interrupted.
        var visitSeconds: Double?
        /// Mistakes raised on `from` during this run.
        var mistakes: Int
    }

    private(set) var lessonId: String?
    private(set) var total = 0
    private(set) var steps: [StepRecord] = []
    /// 0-based position (`total` when done), or nil before the first state of a lesson.
    private(set) var position: Int?
    private(set) var startedAt: Date?
    private(set) var finishedAt: Date?
    /// The hub was gone for more than 10 s during the run.
    private(set) var interrupted = false
    private var enteredAt: Date?
    private var disconnectedAt: Date?
    private var visitInterrupted = false
    private var countedMistakes: Set<String> = []

    static let interruptAfter: TimeInterval = 10

    var isDone: Bool { position != nil && position == total && total > 0 }

    /// Feed every state. `advance` is the newest advance the hub sent (it always arrives before the state it
    /// causes). Returns the change when the position moved forward.
    @discardableResult
    mutating func observe(_ state: HubState, advance: Advance?, at now: Date) -> Change? {
        guard let id = state.lessonId, state.total > 0 else {
            if state.lessonId == nil { self = RunRecorder() }
            return nil
        }
        if id != lessonId || state.total != total {
            self = RunRecorder()
            lessonId = id
            total = state.total
            steps = Array(repeating: StepRecord(), count: state.total)
            position = state.position
            startedAt = now
            enteredAt = now
            if state.position < total { steps[state.position].visits = 1 }
            if state.isDone { finishedAt = now }
            noteChecks(state)
            return nil
        }
        defer { noteChecks(state) }
        guard let old = position, state.position != old else { return nil }
        let new = state.position

        var visit: Double?
        if old < total, let enteredAt {
            let elapsed = max(0, now.timeIntervalSince(enteredAt))
            steps[old].seconds += elapsed
            if visitInterrupted { steps[old].interruptedVisit = true }
            visit = visitInterrupted || elapsed < 1 ? nil : elapsed
        }

        var reason: Advance.Reason?
        if new > old {
            if let advance, advance.from == old, advance.to == new {
                reason = advance.reason
                if old < total { steps[old].leftBy = advance.reason == .camera ? .camera : .hand }
                // An ahead advance (k to k + 2) jumps a step the camera confirmed; the hub's scoring counts it
                // as camera verified too (server/scoring.py, "camera_ahead").
                for i in (old + 1)..<min(new, total) {
                    steps[i].leftBy = advance.reason == .camera ? .camera : .skipped
                }
            } else {
                for i in old..<min(new, total) where steps[i].leftBy == nil { steps[i].leftBy = .skipped }
            }
        }

        position = new
        enteredAt = now
        visitInterrupted = disconnectedAt != nil
        countedMistakes = []
        if new < total { steps[new].visits += 1 }
        if state.isDone {
            finishedAt = now
        } else {
            finishedAt = nil
        }
        guard new > old, old < total else { return nil }
        return Change(from: old, to: new, reason: reason, visitSeconds: visit, mistakes: steps[old].mistakes)
    }

    /// A mistake is on screen. Behind and live mistakes count once each per visit; `ahead` is not a mistake.
    mutating func observe(mistake m: MistakeMessage) {
        guard m.kind != .ahead, steps.indices.contains(m.step) else { return }
        let key = "\(m.step)|\(m.kind.rawValue)|\(m.looksLike)|\(m.message)"
        guard countedMistakes.insert(key).inserted else { return }
        steps[m.step].mistakes += 1
    }

    /// The /ws/ui connection went down or came back.
    mutating func connection(_ connected: Bool, at now: Date) {
        if !connected {
            if disconnectedAt == nil { disconnectedAt = now }
            visitInterrupted = true
        } else if let since = disconnectedAt {
            let gap = now.timeIntervalSince(since)
            if gap > Self.interruptAfter && lessonId != nil && !isDone { interrupted = true }
            // Time away from the hub is not charged to the step.
            enteredAt = enteredAt.map { $0.addingTimeInterval(gap) }
            disconnectedAt = nil
        }
    }

    private mutating func noteChecks(_ state: HubState) {
        if state.checkOffline, let p = position, p < total { steps[p].checksOff = true }
    }

    /// The learner status of every step (DESIGN.md 3.20).
    func statuses() -> [StepStatus] {
        steps.indices.map { i in
            if i == position { return .current }
            switch steps[i].leftBy {
            case .camera?: return .doneByCamera
            case .hand?: return .doneByHand
            case .skipped?: return .skipped
            case nil: return .notStarted
            }
        }
    }

    /// Seconds on step `i` this run, or nil when it was never timed.
    func seconds(_ i: Int) -> Double? {
        guard steps.indices.contains(i), steps[i].leftBy != nil || steps[i].seconds > 0 else { return nil }
        let s = steps[i].seconds
        return s >= 1 ? s : nil
    }
}
