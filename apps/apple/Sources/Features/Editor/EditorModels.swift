import Foundation

// The editor's data and its pure rules: caption cues and WebVTT, boundary snapping, the local undo stack,
// edit operations, production style and publish rules. Everything here is testable without a hub.

/// One caption line, in seconds from the start of its step's clip.
struct EditorCaptionCue: Hashable, Identifiable, Sendable {
    var id = UUID()
    var start: Double
    var end: Double
    var text: String

    static func == (a: EditorCaptionCue, b: EditorCaptionCue) -> Bool { a.start == b.start && a.end == b.end && a.text == b.text }
    func hash(into hasher: inout Hasher) {
        hasher.combine(start)
        hasher.combine(end)
        hasher.combine(text)
    }

    var json: JSONValue {
        .object(["start": .double((start * 1000).rounded() / 1000), "end": .double((end * 1000).rounded() / 1000),
                 "text": .string(text)])
    }
}

/// Reads and writes WebVTT as the hub writes it (`HH:MM:SS.mmm --> HH:MM:SS.mmm`, then the text).
enum WebVTT {
    static func parse(_ text: String) -> [EditorCaptionCue] {
        var cues: [EditorCaptionCue] = []
        let blocks = text.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n\n")
        for block in blocks {
            let lines = block.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
            guard let timing = lines.firstIndex(where: { $0.contains("-->") }) else { continue }
            let parts = lines[timing].components(separatedBy: "-->")
            guard parts.count == 2,
                  let a = seconds(parts[0]),
                  let b = seconds(parts[1].trimmingCharacters(in: .whitespaces).split(separator: " ").first.map(String.init) ?? "")
            else { continue }
            let body = lines[(timing + 1)...].joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !body.isEmpty else { continue }
            cues.append(EditorCaptionCue(start: a, end: b, text: body))
        }
        return cues.sorted { $0.start < $1.start }
    }

    static func seconds(_ raw: String) -> Double? {
        let t = raw.trimmingCharacters(in: .whitespaces)
        let parts = t.split(separator: ":").map(String.init)
        guard (2...3).contains(parts.count) else { return nil }
        var total = 0.0
        for part in parts {
            guard let v = Double(part) else { return nil }
            total = total * 60 + v
        }
        return total
    }

    static func format(_ seconds: Double) -> String {
        let ms = Int((max(0, seconds) * 1000).rounded())
        let h = ms / 3_600_000, m = (ms / 60_000) % 60, s = (ms / 1000) % 60, f = ms % 1000
        func pad(_ v: Int, _ n: Int) -> String { String(repeating: "0", count: max(0, n - String(v).count)) + String(v) }
        return "\(pad(h, 2)):\(pad(m, 2)):\(pad(s, 2)).\(pad(f, 3))"
    }

    static func write(_ cues: [EditorCaptionCue]) -> String {
        var lines = ["WEBVTT", ""]
        for cue in cues.sorted(by: { $0.start < $1.start }) {
            lines += ["\(format(cue.start)) --> \(format(cue.end))", cue.text, ""]
        }
        return lines.joined(separator: "\n") + "\n"
    }
}

/// Where a dragged boundary lands (DESIGN.md 3.18, SCREENS.md 14.4): on the nearest caption cue edge within
/// 0.4 s unless placed freely, then at 0.1 s steps, and never closer than the minimum step length to its
/// neighbors' far edges.
enum EditorBoundarySnap {
    static let snapWindow = 0.4
    /// The editor keeps steps at least 0.5 s (teach cleans out shorter ones; the hub's own floor is 0.3 s).
    static let minimumStep = 0.5

    struct Result: Equatable {
        var time: Double
        /// True when it landed on a cue edge (the selection haptic plays).
        var snapped: Bool
    }

    /// - Parameters:
    ///   - proposed: where the finger or pointer is, in absolute seconds.
    ///   - lower: the previous step's start (the boundary may not come closer than `minimumStep` to it).
    ///   - upper: the next step's end.
    ///   - edges: caption cue edges in absolute seconds.
    ///   - free: Option held (Mac) or a two-finger drag: no snapping.
    static func place(_ proposed: Double, lower: Double, upper: Double, edges: [Double], free: Bool = false) -> Result {
        let low = lower + minimumStep
        let high = upper - minimumStep
        guard low <= high else { return Result(time: (lower + upper) / 2, snapped: false) }
        let clamped = min(max(proposed, low), high)
        if !free {
            let candidates = edges.filter { $0 >= low && $0 <= high && abs($0 - proposed) <= snapWindow }
            if let nearest = candidates.min(by: { abs($0 - proposed) < abs($1 - proposed) }) {
                return Result(time: nearest, snapped: true)
            }
        }
        let tenths = (clamped * 10).rounded() / 10
        return Result(time: min(max(tenths, low), high), snapped: false)
    }

    /// Every cue start and end, made absolute from each step's clip start.
    static func edges(steps: [Step], cues: [Int: [EditorCaptionCue]]) -> [Double] {
        var out: [Double] = []
        for (index, step) in steps.enumerated() {
            guard let start = step.startSeconds, let list = cues[index] else { continue }
            for cue in list {
                out.append(start + cue.start)
                out.append(start + cue.end)
            }
        }
        return Array(Set(out.map { ($0 * 1000).rounded() / 1000 })).sorted()
    }

    /// The split point under the playhead is allowed when both parts keep the minimum length.
    static func canSplit(_ step: Step, at time: Double) -> Bool {
        guard let a = step.startSeconds, let b = step.endSeconds else { return false }
        return time - a >= minimumStep && b - time >= minimumStep
    }
}

/// A bounded undo and redo history of whole states, for hubs where the editor saves through recut and keeps
/// its own history (on hubs with the editor routes the hub keeps it).
struct EditorUndoStack<State: Equatable>: Equatable {
    private(set) var undoStates: [State] = []
    private(set) var redoStates: [State] = []
    let limit: Int

    init(limit: Int = 20) { self.limit = max(1, limit) }

    var canUndo: Bool { !undoStates.isEmpty }
    var canRedo: Bool { !redoStates.isEmpty }
    var counts: HistoryCounts { HistoryCounts(undo: undoStates.count, redo: redoStates.count) }

    /// Records the state before a change. A new change clears redo.
    mutating func record(_ before: State) {
        if undoStates.last == before { return }
        undoStates.append(before)
        if undoStates.count > limit { undoStates.removeFirst(undoStates.count - limit) }
        redoStates.removeAll()
    }

    /// The state to go back to, given the current one (which becomes redoable).
    mutating func undo(from current: State) -> State? {
        guard let previous = undoStates.popLast() else { return nil }
        redoStates.append(current)
        return previous
    }

    mutating func redo(from current: State) -> State? {
        guard let next = redoStates.popLast() else { return nil }
        undoStates.append(current)
        return next
    }

    /// Takes back the last `record` (the change it was for failed).
    mutating func dropLast() { _ = undoStates.popLast() }
}

/// The step fields the inspector edits without a recut.
struct EditorStepFields: Equatable, Sendable {
    var title: String?
    var checkType: Step.CheckType?
    var checkQuestion: String?
    var commonMistake: String?

    var isEmpty: Bool { title == nil && checkType == nil && checkQuestion == nil && commonMistake == nil }

    /// Later edits win.
    func merged(with newer: EditorStepFields) -> EditorStepFields {
        EditorStepFields(title: newer.title ?? title, checkType: newer.checkType ?? checkType,
                   checkQuestion: newer.checkQuestion ?? checkQuestion, commonMistake: newer.commonMistake ?? commonMistake)
    }

    var json: [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        if let title { out["title"] = .string(title) }
        if let checkType { out["check_type"] = .string(checkType.rawValue) }
        if let checkQuestion { out["check_question"] = .string(checkQuestion) }
        if let commonMistake { out["common_mistake"] = .string(commonMistake) }
        return out
    }
}

/// One editor change. `n` is 1-based, as on the wire.
enum EditOp: Equatable, Sendable {
    case boundary(n: Int, start: Double?, end: Double?, next: (n: Int, start: Double)?)
    case split(n: Int, at: Double)
    case merge(n: Int)
    case delete(n: Int)
    case step(n: Int, EditorStepFields)
    case captions(n: Int, [EditorCaptionCue])

    static func == (a: EditOp, b: EditOp) -> Bool {
        switch (a, b) {
        case let (.boundary(n1, s1, e1, x1), .boundary(n2, s2, e2, x2)):
            n1 == n2 && s1 == s2 && e1 == e2 && x1?.n == x2?.n && x1?.start == x2?.start
        case let (.split(n1, a1), .split(n2, a2)): n1 == n2 && a1 == a2
        case let (.merge(n1), .merge(n2)), let (.delete(n1), .delete(n2)): n1 == n2
        case let (.step(n1, f1), .step(n2, f2)): n1 == n2 && f1 == f2
        case let (.captions(n1, c1), .captions(n2, c2)): n1 == n2 && c1 == c2
        default: false
        }
    }

    /// Changes step timing, so the hub cuts the clips again.
    var recuts: Bool {
        switch self {
        case .boundary, .split, .merge, .delete: true
        case .step, .captions: false
        }
    }
}

/// What an edit, undo or redo returns.
struct EditOutcome: Sendable {
    var lesson: Lesson
    var history: HistoryCounts
    var recut: Bool
}

/// Applies an edit to a lesson on this device, the same way the hub's editor routes do. Used on hubs without
/// those routes, where the whole lesson goes back through recut.
enum LessonEdits {
    enum Failure: LocalizedError, Equatable {
        case noStep(Int), tooShort, lastStep, onlyStep, notSupported

        var errorDescription: String? {
            switch self {
            case .noStep(let n): "no step \(n)"
            case .tooShort: "Too short to split here."
            case .lastStep: "This is the last step; there is nothing after it to merge."
            case .onlyStep: "A lesson needs at least one step."
            case .notSupported: "This hub cannot save that change. Update the hub to edit it."
            }
        }
    }

    static func apply(_ op: EditOp, to lesson: Lesson) throws -> Lesson {
        var out = lesson
        func index(_ n: Int) throws -> Int {
            guard out.steps.indices.contains(n - 1) else { throw Failure.noStep(n) }
            return n - 1
        }
        switch op {
        case let .boundary(n, start, end, next):
            let i = try index(n)
            if let start { out.steps[i].start = TimeCode.format(start) }
            if let end { out.steps[i].end = TimeCode.format(end) }
            out.steps[i].refTime = nil
            out.steps[i].selfTest = nil
            if let next {
                let j = try index(next.n)
                out.steps[j].start = TimeCode.format(next.start)
                out.steps[j].refTime = nil
                out.steps[j].selfTest = nil
            }
        case let .split(n, at):
            let i = try index(n)
            guard EditorBoundarySnap.canSplit(out.steps[i], at: at) else { throw Failure.tooShort }
            var first = out.steps[i]
            var second = out.steps[i]
            first.end = TimeCode.format(at)
            second.start = TimeCode.format(at)
            second.title = "\(first.title.isEmpty ? "Step \(n)" : first.title) (part 2)"
            first.refTime = nil
            first.selfTest = nil
            second.selfTest = nil
            out.steps.replaceSubrange(i...i, with: [first, second])
            renumber(&out)
        case let .merge(n):
            let i = try index(n)
            guard i + 1 < out.steps.count else { throw Failure.lastStep }
            var merged = out.steps[i + 1]
            merged.start = out.steps[i].start
            merged.title = out.steps[i].title.isEmpty ? merged.title : out.steps[i].title
            merged.selfTest = nil
            out.steps.replaceSubrange(i...(i + 1), with: [merged])
            renumber(&out)
        case let .delete(n):
            let i = try index(n)
            guard out.steps.count > 1 else { throw Failure.onlyStep }
            out.steps.remove(at: i)
            renumber(&out)
        case let .step(n, fields):
            let i = try index(n)
            if let title = fields.title { out.steps[i].title = title }
            if let type = fields.checkType { out.steps[i].checkType = type }
            if let question = fields.checkQuestion { out.steps[i].checkQuestion = question }
            if let mistake = fields.commonMistake { out.steps[i].commonMistake = mistake }
            if out.steps[i].isManual {
                out.steps[i].checkQuestion = ""
            } else if out.steps[i].checkQuestion.trimmingCharacters(in: .whitespaces).isEmpty {
                out.steps[i].checkQuestion = "Is this step finished?"
            }
            if fields.checkType != nil || fields.checkQuestion != nil { out.steps[i].selfTest = nil }
        case .captions:
            throw Failure.notSupported
        }
        return out
    }

    /// Steps are numbered 1...n with their files following the number, as teach writes them.
    private static func renumber(_ lesson: inout Lesson) {
        for i in lesson.steps.indices {
            let n = i + 1
            let nn = n < 10 ? "0\(n)" : "\(n)"
            lesson.steps[i].n = n
            lesson.steps[i].clip = "clips/\(nn).mp4"
            lesson.steps[i].captions = "captions/\(nn).vtt"
            lesson.steps[i].refFrame = "frames/\(nn).jpg"
        }
    }
}

/// The produced video's look (server/docs/production.md, "Style"), from lesson.json `production`.
struct ProductionStyle: Equatable, Sendable {
    enum TitleCards: String, CaseIterable, Sendable {
        case card, overlay, off
        var title: String {
            switch self {
            case .card: "Full Card"
            case .overlay: "Over the Video"
            case .off: "Off"
            }
        }
    }

    var theme = "system"
    var titleCards: TitleCards = .card
    var zoom = true
    var highlight = true
    var burnCaptions = false

    init() {}

    init(lesson: Lesson) {
        guard case .object(let o) = lesson.extra["production"] else { return }
        if case .string(let t) = o["theme"] { theme = t }
        switch o["title_cards"] {
        case .string(let s): titleCards = TitleCards(rawValue: s) ?? .card
        case .bool(let b): titleCards = b ? .card : .off
        default: break
        }
        if case .bool(let b) = o["zoom"] { zoom = b }
        if case .bool(let b) = o["highlight"] { highlight = b }
        if case .bool(let b) = o["burn_captions"] { burnCaptions = b }
    }

    var json: JSONValue {
        .object(["theme": .string(theme), "title_cards": .string(titleCards.rawValue), "zoom": .bool(zoom),
                 "highlight": .bool(highlight), "burn_captions": .bool(burnCaptions)])
    }
}

/// Kokoro v1.0 voices offered in the picker (the hub checks the name; `af_heart` is its default).
enum EditorVoiceCatalog {
    struct Voice: Hashable, Identifiable, Sendable {
        var id: String
        var name: String
    }

    static let all: [Voice] = [
        Voice(id: "af_heart", name: "Heart (US English)"),
        Voice(id: "af_bella", name: "Bella (US English)"),
        Voice(id: "af_nicole", name: "Nicole (US English)"),
        Voice(id: "am_michael", name: "Michael (US English)"),
        Voice(id: "am_fenrir", name: "Fenrir (US English)"),
        Voice(id: "bf_emma", name: "Emma (UK English)"),
        Voice(id: "bm_george", name: "George (UK English)"),
    ]

    static func name(_ id: String?) -> String {
        guard let id else { return "Hub Default" }
        return all.first { $0.id == id }?.name ?? id
    }
}

/// The voiceover on a lesson, as lesson.json `voiceover` says (null or missing means the original sound).
struct VoiceoverInfo: Equatable, Sendable {
    var voice: String?
    var steps: Set<Int> = []

    init?(lesson: Lesson) {
        guard let value = lesson.extra["voiceover"], value != .null else { return nil }
        if case .object(let o) = value {
            if case .string(let v) = o["voice"] { voice = v }
            if case .array(let list) = o["steps"] {
                steps = Set(list.compactMap { if case .int(let n) = $0 { n } else { nil } })
            }
        }
    }

    func covers(step n: Int) -> Bool { steps.isEmpty || steps.contains(n) }
}

/// The publish sheet's rules (SCREENS.md 15.2): who it can go to, the checklist, and the button.
struct EditorPublishPlan: Equatable {
    struct Audience: Hashable, Identifiable {
        enum Kind: Hashable { case onlyMe, shared, org(String), everyone }
        var kind: Kind
        var title: String
        var detail: String?
        var id: String {
            switch kind {
            case .onlyMe: "only_me"
            case .shared: "shared"
            case .org(let id): "org:\(id)"
            case .everyone: "everyone"
            }
        }

        var visibility: CourseVisibility {
            switch kind {
            case .onlyMe: .onlyMe
            case .shared: .shared
            case .org: .org
            case .everyone: .everyone
            }
        }

        var orgId: String? { if case .org(let id) = kind { id } else { nil } }
    }

    struct OrgOption: Hashable {
        var id: String
        var name: String
        var members: Int
    }

    var audiences: [Audience]
    var warnings: [String]
    var steps: Int
    var camera: Int
    var manual: Int
    var isPublished: Bool

    /// - Parameters:
    ///   - teachOrgs: orgs where the person is Admin or Teacher.
    ///   - canPublishToEveryone: the hub owner (the hub decides; it refuses otherwise).
    init(course: Course, lesson: Lesson, teachOrgs: [OrgOption], canPublishToEveryone: Bool) {
        var list = [Audience(kind: .onlyMe, title: "Only Me"), Audience(kind: .shared, title: "People with Access")]
        for org in teachOrgs {
            list.append(Audience(kind: .org(org.id), title: "Publish to \(org.name)",
                                 detail: "\(org.members) \(org.members == 1 ? "member" : "members")"))
        }
        if canPublishToEveryone { list.append(Audience(kind: .everyone, title: "Everyone on This Hub")) }
        audiences = list
        steps = lesson.steps.count
        camera = lesson.steps.filter { !$0.isManual }.count
        manual = steps - camera
        var warnings: [String] = []
        for step in lesson.steps {
            if !step.isManual && step.checkQuestion.trimmingCharacters(in: .whitespaces).isEmpty {
                warnings.append("Step \(step.n) has no check question.")
            }
            if step.selfTest?.ok == false { warnings.append("Step \(step.n) failed its test.") }
        }
        if lesson.steps.isEmpty { warnings.append("A course needs at least one step to publish.") }
        self.warnings = warnings
        isPublished = course.status != .draft
    }

    var primaryTitle: String { isPublished ? "Update" : "Publish" }
    var canPublish: Bool { steps > 0 }

    /// The row that matches the course as it is now.
    func current(_ course: Course) -> Audience? {
        audiences.first { $0.visibility == course.visibility && ($0.orgId == nil || $0.orgId == course.org?.id) }
            ?? audiences.first
    }

    /// The status to send: unlisted when the toggle is on.
    static func status(unlisted: Bool) -> CourseStatus { unlisted ? .unlisted : .published }
}

/// The autosave indicator (SCREENS.md 14.5).
enum EditorSaveState: Equatable, Sendable {
    case idle, saving, saved, updatingClips
    case offline
    case failed(String)

    var text: String? {
        switch self {
        case .idle: nil
        case .saving: "Saving"
        case .saved: "Saved"
        case .updatingClips: "Updating clips"
        case .offline: "Saved on this device only"
        case .failed: "Could not save"
        }
    }
}
