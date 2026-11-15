import Foundation

/// The Done screen's numbers from this device's own record of the run (SCREENS.md 8 and 20). Used when the hub
/// has no score for the run. Every value comes from real advance, state and mistake events; anything that
/// cannot be computed is nil and shows as "Not enough data".
struct RunSummary: Equatable, Sendable {
    struct Line: Equatable, Sendable, Identifiable {
        var index: Int
        var n: Int
        var title: String
        var isCameraStep: Bool
        var expert: Double?
        var yours: Double?
        var how: StepStatus
        var mistakes: Int
        var checksOff: Bool
        var commonMistake: String
        var id: Int { index }

        /// your time / expert time, when both exist.
        var ratio: Double? {
            guard let yours, let expert, expert > 0 else { return nil }
            return yours / expert
        }
    }

    var lessonTitle: String
    var lines: [Line]
    /// Start to done, nil when the run was interrupted or did not finish.
    var runSeconds: Double?
    var interrupted: Bool
    /// Sum of the step lengths, nil if any step has no readable times.
    var expertSeconds: Double?
    var checkedByCamera: Int
    var cameraSteps: Int
    var markedDone: Int
    var mistakes: Int
    var skipped: Int
    /// 0 to 100, or nil with not enough data (20.2).
    var score: Int?
    var scoreParts: [String]
    var best: Int?
    var weakest: Int?
    var tip: String

    init(recorder: RunRecorder, lesson: Lesson) {
        lessonTitle = lesson.title
        let statuses = recorder.statuses()
        lines = lesson.steps.enumerated().map { i, step in
            let record = recorder.steps.indices.contains(i) ? recorder.steps[i] : RunRecorder.StepRecord()
            let expert: Double? = {
                guard let s = step.startSeconds, let e = step.endSeconds, e > s else { return nil }
                return e - s
            }()
            return Line(index: i, n: i + 1, title: step.title, isCameraStep: !step.isManual, expert: expert,
                        yours: recorder.seconds(i),
                        how: statuses.indices.contains(i) ? statuses[i] : .notStarted,
                        mistakes: record.mistakes, checksOff: record.checksOff, commonMistake: step.commonMistake)
        }
        interrupted = recorder.interrupted
        if !recorder.interrupted, let start = recorder.startedAt, let end = recorder.finishedAt, end > start {
            runSeconds = end.timeIntervalSince(start)
        } else {
            runSeconds = nil
        }
        let experts = lines.map(\.expert)
        expertSeconds = experts.contains(where: { $0 == nil }) || experts.isEmpty ? nil : experts.compactMap { $0 }.reduce(0, +)
        cameraSteps = lines.filter(\.isCameraStep).count
        checkedByCamera = lines.filter { $0.isCameraStep && $0.how == .doneByCamera }.count
        markedDone = lines.filter { $0.how == .doneByHand }.count
        mistakes = lines.map(\.mistakes).reduce(0, +)
        skipped = lines.filter { $0.how == .skipped }.count
        (score, scoreParts) = Self.score(lines: lines, interrupted: recorder.interrupted)
        (best, weakest) = Self.bestAndWeakest(lines)
        tip = Self.tip(lines: lines, weakest: weakest)
    }

    /// SCREENS.md 20.2. Only when the run was not interrupted and at least half the steps have a time.
    static func score(lines: [Line], interrupted: Bool) -> (Int?, [String]) {
        let total = lines.count
        guard total > 0, !interrupted else { return (nil, []) }
        let timed = lines.filter { $0.yours != nil }.count
        guard timed * 2 >= total else { return (nil, []) }

        let qualifying = lines.filter { $0.isCameraStep && !$0.checksOff }
        let checked: Double? = qualifying.isEmpty ? nil
            : Double(qualifying.filter { $0.how == .doneByCamera }.count) / Double(qualifying.count)

        let paceValues: [Double] = lines.compactMap { line in
            if line.how == .skipped { return 0 }
            guard let ratio = line.ratio, ratio > 0 else { return nil }
            return min(1, 1 / ratio)
        }
        guard !paceValues.isEmpty else { return (nil, []) }
        let pace = paceValues.reduce(0, +) / Double(paceValues.count)
        let mistakes = lines.map(\.mistakes).reduce(0, +)
        let clean = 1 - min(1, Double(mistakes) / Double(total))

        let raw = checked.map { 0.5 * $0 + 0.3 * pace + 0.2 * clean } ?? (0.6 * pace + 0.4 * clean)
        var parts: [String] = []
        if checked != nil {
            let verified = qualifying.filter { $0.how == .doneByCamera }.count
            parts.append("\(verified) of \(qualifying.count) camera steps checked by camera.")
        }
        parts.append("Your pace was \(Int((pace * 100).rounded()))% of the expert's.")
        parts.append("\(mistakes) mistake\(mistakes == 1 ? "" : "s") in \(total) step\(total == 1 ? "" : "s").")
        return (Int((100 * raw).rounded()), parts)
    }

    /// SCREENS.md 20.3, among steps with a time that were not skipped. Needs 2 such steps.
    static func bestAndWeakest(_ lines: [Line]) -> (best: Int?, weakest: Int?) {
        let pool = lines.filter { $0.how != .skipped && $0.ratio != nil }
        guard pool.count >= 2 else { return (nil, nil) }
        let weakest = pool.max { a, b in
            a.mistakes != b.mistakes ? a.mistakes < b.mistakes : (a.ratio ?? 0) < (b.ratio ?? 0)
        }
        let clean = pool.filter { $0.mistakes == 0 }
        let byCamera = clean.filter { $0.how == .doneByCamera }
        let best = (byCamera.isEmpty ? clean : byCamera).min { ($0.ratio ?? 0) < ($1.ratio ?? 0) }
        let bestIndex = best?.index == weakest?.index ? nil : best?.index
        return (bestIndex, weakest?.index)
    }

    /// SCREENS.md 20.4: the first rule that matches.
    static func tip(lines: [Line], weakest: Int?) -> String {
        if let w = weakest, lines.indices.contains(w) {
            let line = lines[w]
            let mistake = line.commonMistake.trimmingCharacters(in: .whitespacesAndNewlines)
            if !mistake.isEmpty { return "On step \(line.n), watch for this: \(mistake)" }
            if line.mistakes > 0 { return "Replay step \(line.n)'s clip before you try it again." }
            if let ratio = line.ratio, ratio > 2 {
                return "Step \(line.n) took the longest. Watch the expert's hands closely there."
            }
        }
        if let skipped = lines.first(where: { $0.how == .skipped }) {
            return "You skipped step \(skipped.n). Try it once so the camera can check it."
        }
        if lines.contains(where: \.checksOff) {
            return "Checks were off for part of this run, so try again for a full score."
        }
        return "Try it again without looking at the clip."
    }

    /// The Best step card's reason, e.g. "Checked by camera in 9 s."
    func bestReason(_ i: Int) -> String {
        let line = lines[i]
        let time = line.yours.map { " in \(HOTime.short($0))" } ?? ""
        return line.how == .doneByCamera ? "Checked by camera\(time)." : "Marked done\(time)."
    }

    /// The Practice This card's reason, e.g. "2 mistakes, 1:40 against 0:35."
    func weakestReason(_ i: Int) -> String {
        let line = lines[i]
        var parts: [String] = []
        if line.mistakes > 0 { parts.append("\(line.mistakes) mistake\(line.mistakes == 1 ? "" : "s")") }
        if let yours = line.yours, let expert = line.expert {
            parts.append("\(HOTime.clock(yours)) against \(HOTime.clock(expert))")
        }
        return parts.isEmpty ? "Most room to improve." : parts.joined(separator: ", ") + "."
    }
}
