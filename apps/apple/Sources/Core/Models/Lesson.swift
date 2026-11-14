import Foundation

/// One row of `GET /api/lessons` (CONTRACT.md section 4). `steps` is the step count.
struct LessonSummary: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var title: String
    var steps: Int
}

/// lesson.json (CONTRACT.md section 3). Missing fields take the contract's defaults. Fields this app does
/// not know are kept in `extra` and written back, so a recut never loses them.
struct Lesson: Codable, Hashable, Identifiable, Sendable {
    var id: String
    var title: String
    var video: String = "norm.mp4"
    var steps: [Step] = []
    /// Short warnings from the narration (NEW, S-S).
    var safety: [String] = []
    /// Tools named in the narration (NEW, S-S).
    var tools: [String] = []
    var extra: [String: JSONValue] = [:]

    init(id: String, title: String, video: String = "norm.mp4", steps: [Step] = [], safety: [String] = [],
         tools: [String] = [], extra: [String: JSONValue] = [:]) {
        self.id = id
        self.title = title
        self.video = video
        self.steps = steps
        self.safety = safety
        self.tools = tools
        self.extra = extra
    }

    private static let known: Set<String> = ["id", "title", "video", "steps", "safety", "tools"]

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: AnyKey.self)
        id = try c.decodeIfPresent(String.self, forKey: AnyKey("id")) ?? ""
        title = try c.decodeIfPresent(String.self, forKey: AnyKey("title")) ?? id
        video = try c.decodeIfPresent(String.self, forKey: AnyKey("video")) ?? "norm.mp4"
        let wire = try c.decodeIfPresent([Step.Wire].self, forKey: AnyKey("steps")) ?? []
        steps = wire.enumerated().map { Step(wire: $0.element, index: $0.offset) }
        safety = try c.decodeIfPresent([String].self, forKey: AnyKey("safety")) ?? []
        tools = try c.decodeIfPresent([String].self, forKey: AnyKey("tools")) ?? []
        extra = try c.extras(excluding: Self.known)
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: AnyKey.self)
        try c.encode(id, forKey: AnyKey("id"))
        try c.encode(title, forKey: AnyKey("title"))
        try c.encode(video, forKey: AnyKey("video"))
        try c.encode(steps, forKey: AnyKey("steps"))
        try c.encode(safety, forKey: AnyKey("safety"))
        try c.encode(tools, forKey: AnyKey("tools"))
        try c.encode(extras: extra)
    }
}

/// One step of a lesson (CONTRACT.md section 3).
struct Step: Codable, Hashable, Identifiable, Sendable {
    enum CheckType: String, WireEnum {
        case camera, manual
        static let fallback = CheckType.camera
    }

    /// The teach-time self-test (NEW, S-T). `mock` is true when it ran against the mock checker.
    struct SelfTest: Codable, Hashable, Sendable {
        var own: Verdict
        var prev: Verdict
        var ok: Bool
        var mock: Bool?
    }

    /// 1-based step number.
    var n: Int
    var title: String = ""
    /// "MM:SS" or "MM:SS.s" (also "HH:MM:SS" or plain seconds). See `TimeCode`.
    var start: String
    var end: String
    /// Paths relative to the lesson folder. Build URLs with `HubURL.fileURL(lesson:path:rev:)`.
    var clip: String
    var captions: String
    var refFrame: String
    var checkType: CheckType = .camera
    var checkQuestion: String = "Is this step finished?"
    /// 1-based step numbers, each smaller than `n`.
    var prerequisites: [Int] = []
    /// Absolute time in norm.mp4 of the reference frame; nil means the clip's last frame (NEW, M8).
    var refTime: String? {
        didSet { refTimeWasNull = false }
    }
    /// Shown and spoken when the learner is behind (NEW, M9).
    var commonMistake: String = ""
    var selfTest: SelfTest?
    var extra: [String: JSONValue] = [:]
    /// The hub treats a stored `"ref_time": null` and a missing ref_time differently on recut, so a null we
    /// read is written back as null and a missing one stays missing.
    private var refTimeWasNull = false

    var id: Int { n }
    var isManual: Bool { checkType == .manual }
    var startSeconds: Double? { TimeCode.seconds(start) }
    var endSeconds: Double? { TimeCode.seconds(end) }

    init(n: Int, title: String = "", start: String, end: String, clip: String? = nil, captions: String? = nil,
         refFrame: String? = nil, checkType: CheckType = .camera, checkQuestion: String? = nil,
         prerequisites: [Int] = [], refTime: String? = nil, commonMistake: String = "", selfTest: SelfTest? = nil) {
        let nn = Step.twoDigits(n)
        self.n = n
        self.title = title
        self.start = start
        self.end = end
        self.clip = clip ?? "clips/\(nn).mp4"
        self.captions = captions ?? "captions/\(nn).vtt"
        self.refFrame = refFrame ?? "frames/\(nn).jpg"
        self.checkType = checkType
        self.checkQuestion = checkQuestion ?? (checkType == .manual ? "" : "Is this step finished?")
        self.prerequisites = prerequisites
        self.refTime = refTime
        self.commonMistake = commonMistake
        self.selfTest = selfTest
    }

    private static func twoDigits(_ n: Int) -> String { n < 10 ? "0\(n)" : "\(n)" }

    /// The step as it is on the wire, every field optional, before the index-based defaults are applied.
    struct Wire: Decodable {
        var n: Int?
        var title: String?
        var start: String?
        var end: String?
        var clip: String?
        var captions: String?
        var refFrame: String?
        var checkType: CheckType?
        var checkQuestion: String?
        var prerequisites: [Int]?
        var refTime: String?
        var refTimeIsNull = false
        var commonMistake: String?
        var selfTest: SelfTest?
        var extra: [String: JSONValue] = [:]

        init(from decoder: any Decoder) throws {
            let c = try decoder.container(keyedBy: AnyKey.self)
            func opt<T: Decodable>(_ type: T.Type, _ key: String) -> T? {
                // A field of the wrong type reads as missing instead of failing the whole lesson.
                (try? c.decodeIfPresent(type, forKey: AnyKey(key))) ?? nil
            }
            n = opt(Int.self, "n")
            title = opt(String.self, "title")
            start = Step.Wire.time(c, "start")
            end = Step.Wire.time(c, "end")
            clip = opt(String.self, "clip")
            captions = opt(String.self, "captions")
            refFrame = opt(String.self, "ref_frame")
            checkType = opt(CheckType.self, "check_type")
            checkQuestion = opt(String.self, "check_question")
            prerequisites = opt([Int].self, "prerequisites")
            refTime = Step.Wire.time(c, "ref_time")
            refTimeIsNull = c.contains(AnyKey("ref_time")) && ((try? c.decodeNil(forKey: AnyKey("ref_time"))) ?? false)
            commonMistake = opt(String.self, "common_mistake")
            selfTest = opt(SelfTest.self, "self_test")
            extra = try c.extras(excluding: Step.known)
        }

        /// Times are strings, but the hub also accepts plain seconds on read; keep a number as its text.
        private static func time(_ c: KeyedDecodingContainer<AnyKey>, _ key: String) -> String? {
            if let s = try? c.decodeIfPresent(String.self, forKey: AnyKey(key)) { return s }
            if let i = try? c.decodeIfPresent(Int.self, forKey: AnyKey(key)) { return String(i) }
            if let d = try? c.decodeIfPresent(Double.self, forKey: AnyKey(key)) { return String(d) }
            return nil
        }
    }

    fileprivate static let known: Set<String> = [
        "n", "title", "start", "end", "clip", "captions", "ref_frame", "check_type", "check_question",
        "prerequisites", "ref_time", "common_mistake", "self_test",
    ]

    init(wire w: Wire, index: Int) {
        let type = w.checkType ?? .camera
        self.init(n: w.n ?? index + 1, title: w.title ?? "", start: w.start ?? "", end: w.end ?? "",
                  clip: w.clip, captions: w.captions, refFrame: w.refFrame, checkType: type,
                  checkQuestion: w.checkQuestion, prerequisites: w.prerequisites ?? [], refTime: w.refTime,
                  commonMistake: w.commonMistake ?? "", selfTest: w.selfTest)
        // Defaults follow the step's index, as the hub does, even when `n` was written differently.
        let nn = Step.twoDigits(index + 1)
        if w.clip == nil { clip = "clips/\(nn).mp4" }
        if w.captions == nil { captions = "captions/\(nn).vtt" }
        if w.refFrame == nil { refFrame = "frames/\(nn).jpg" }
        if w.checkQuestion == nil, type == .camera { checkQuestion = "Is this step finished?" }
        extra = w.extra
        refTimeWasNull = w.refTimeIsNull && w.refTime == nil
    }

    init(from decoder: any Decoder) throws {
        self.init(wire: try Wire(from: decoder), index: 0)
    }

    func encode(to encoder: any Encoder) throws {
        var c = encoder.container(keyedBy: AnyKey.self)
        try c.encode(n, forKey: AnyKey("n"))
        try c.encode(title, forKey: AnyKey("title"))
        try c.encode(start, forKey: AnyKey("start"))
        try c.encode(end, forKey: AnyKey("end"))
        try c.encode(clip, forKey: AnyKey("clip"))
        try c.encode(captions, forKey: AnyKey("captions"))
        try c.encode(refFrame, forKey: AnyKey("ref_frame"))
        try c.encode(checkType, forKey: AnyKey("check_type"))
        try c.encode(checkQuestion, forKey: AnyKey("check_question"))
        try c.encode(prerequisites, forKey: AnyKey("prerequisites"))
        if let refTime {
            try c.encode(refTime, forKey: AnyKey("ref_time"))
        } else if refTimeWasNull {
            try c.encodeNil(forKey: AnyKey("ref_time"))
        }
        try c.encode(commonMistake, forKey: AnyKey("common_mistake"))
        try c.encodeIfPresent(selfTest, forKey: AnyKey("self_test"))
        try c.encode(extras: extra)
    }
}

/// Step times as the contract writes them: "MM:SS", "MM:SS.s", "HH:MM:SS" or plain seconds.
enum TimeCode {
    static func seconds(_ text: String) -> Double? {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return nil }
        let parts = t.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
        guard (1...3).contains(parts.count) else { return nil }
        var total = 0.0
        for (i, part) in parts.enumerated() {
            let isLast = i == parts.count - 1
            guard let v = Double(part), v >= 0, v.isFinite else { return nil }
            // Only the seconds may have a fraction; minutes and hours are whole and seconds stay under 60
            // when minutes are given.
            if !isLast, v != v.rounded() { return nil }
            if isLast, parts.count > 1, v >= 60 { return nil }
            total = total * 60 + v
        }
        return total
    }

    /// "MM:SS" or "MM:SS.s" (one decimal when there is a fraction), the form the teach pipeline writes.
    static func format(_ seconds: Double) -> String {
        let tenths = Int((max(0, seconds) * 10).rounded())
        let m = tenths / 600
        let s = (tenths % 600) / 10
        let f = tenths % 10
        let mm = m < 10 ? "0\(m)" : "\(m)"
        let ss = s < 10 ? "0\(s)" : "\(s)"
        return f == 0 ? "\(mm):\(ss)" : "\(mm):\(ss).\(f)"
    }
}
