import Foundation

/// The hub's `state` message (CONTRACT.md section 7, plus check_mode and next_clip from
/// server/docs/contract-proposals.md). Every field has a default, so an older hub that leaves the NEW
/// fields out still decodes, and unknown fields are ignored.
struct HubState: Codable, Hashable, Sendable {
    enum Status: String, WireEnum {
        case watching, checking, verified, manual, done
        static let fallback = Status.watching
    }

    /// The answer of the newest camera check.
    struct LastCheck: Codable, Hashable, Sendable {
        var done: Verdict
        var confidence: Double
        var latencyMs: Int
        /// Up to 8 words on what still differs from the reference. Show it at confidence 0.7 or more.
        var reason: String?

        enum CodingKeys: String, CodingKey {
            case done, confidence, reason
            case latencyMs = "latency_ms"
        }

        init(done: Verdict, confidence: Double, latencyMs: Int, reason: String? = nil) {
            self.done = done
            self.confidence = confidence
            self.latencyMs = latencyMs
            self.reason = reason
        }

        init(from decoder: any Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            done = try c.decodeIfPresent(Verdict.self, forKey: .done) ?? .unsure
            confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
            latencyMs = try c.decodeIfPresent(Int.self, forKey: .latencyMs) ?? 0
            reason = try c.decodeIfPresent(String.self, forKey: .reason)
        }

        /// The contract's rule for when the UI may show `reason`.
        var shownReason: String? { confidence >= 0.7 ? reason : nil }
    }

    /// Who is answering checks right now. Kept as a string so a new provider still reads.
    struct CheckMode: RawRepresentable, Codable, Hashable, Sendable {
        var rawValue: String
        init(rawValue: String) { self.rawValue = rawValue }
        init(from decoder: any Decoder) throws { rawValue = try decoder.singleValueContainer().decode(String.self) }
        func encode(to encoder: any Encoder) throws {
            var c = encoder.singleValueContainer()
            try c.encode(rawValue)
        }

        static let mock = CheckMode(rawValue: "mock")
        static let gemini = CheckMode(rawValue: "gemini")
        static let claude = CheckMode(rawValue: "claude")
    }

    /// Why checks are off. Kept as a string so a new reason still reads.
    struct OfflineReason: RawRepresentable, Codable, Hashable, Sendable {
        var rawValue: String
        init(rawValue: String) { self.rawValue = rawValue }
        init(from decoder: any Decoder) throws { rawValue = try decoder.singleValueContainer().decode(String.self) }
        func encode(to encoder: any Encoder) throws {
            var c = encoder.singleValueContainer()
            try c.encode(rawValue)
        }

        static let noKey = OfflineReason(rawValue: "no_key")
        static let rateLimited = OfflineReason(rawValue: "rate_limited")
        static let errors = OfflineReason(rawValue: "errors")
        static let budget = OfflineReason(rawValue: "budget")
    }

    var lessonId: String?
    /// Opaque and increasing. When it changes, refetch the lesson and add `?v=<rev>` to file URLs.
    var rev: Int = 0
    /// 0-based. On the done screen it stays at `total - 1`; use `position`.
    var step: Int = 0
    var total: Int = 0
    var status: Status = .watching
    var lastCheck: LastCheck?
    var cameraConnected: Bool = false
    /// The active camera, or nil.
    var camera: CameraInfo?
    var checkOffline: Bool = false
    var checkOfflineReason: OfflineReason?
    /// The current `behind` mistake, or nil.
    var mistake: MistakeMessage?
    var checkMode: CheckMode?
    /// The next step's clip, sent once this step has a confident yes, so it can be preloaded.
    var nextClip: String?

    enum CodingKeys: String, CodingKey {
        case lessonId = "lesson_id"
        case rev, step, total, status
        case lastCheck = "last_check"
        case cameraConnected = "camera_connected"
        case camera
        case checkOffline = "check_offline"
        case checkOfflineReason = "check_offline_reason"
        case mistake
        case checkMode = "check_mode"
        case nextClip = "next_clip"
    }

    static let empty = HubState()

    init(lessonId: String? = nil, rev: Int = 0, step: Int = 0, total: Int = 0, status: Status = .watching,
         lastCheck: LastCheck? = nil, cameraConnected: Bool = false, camera: CameraInfo? = nil,
         checkOffline: Bool = false, checkOfflineReason: OfflineReason? = nil, mistake: MistakeMessage? = nil,
         checkMode: CheckMode? = nil, nextClip: String? = nil) {
        self.lessonId = lessonId
        self.rev = rev
        self.step = step
        self.total = total
        self.status = status
        self.lastCheck = lastCheck
        self.cameraConnected = cameraConnected
        self.camera = camera
        self.checkOffline = checkOffline
        self.checkOfflineReason = checkOfflineReason
        self.mistake = mistake
        self.checkMode = checkMode
        self.nextClip = nextClip
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // The EXISTS fields must have the right type; the NEW ones read as missing when malformed.
        lessonId = try c.decodeIfPresent(String.self, forKey: .lessonId)
        rev = try c.decodeIfPresent(Int.self, forKey: .rev) ?? 0
        step = try c.decodeIfPresent(Int.self, forKey: .step) ?? 0
        total = try c.decodeIfPresent(Int.self, forKey: .total) ?? 0
        status = try c.decodeIfPresent(Status.self, forKey: .status) ?? .watching
        lastCheck = try c.decodeIfPresent(LastCheck.self, forKey: .lastCheck)
        cameraConnected = try c.decodeIfPresent(Bool.self, forKey: .cameraConnected) ?? false
        camera = (try? c.decodeIfPresent(CameraInfo.self, forKey: .camera)) ?? nil
        checkOffline = (try? c.decodeIfPresent(Bool.self, forKey: .checkOffline)) ?? false
        checkOfflineReason = (try? c.decodeIfPresent(OfflineReason.self, forKey: .checkOfflineReason)) ?? nil
        mistake = (try? c.decodeIfPresent(MistakeMessage.self, forKey: .mistake)) ?? nil
        checkMode = (try? c.decodeIfPresent(CheckMode.self, forKey: .checkMode)) ?? nil
        nextClip = (try? c.decodeIfPresent(String.self, forKey: .nextClip)) ?? nil
    }

    var hasLesson: Bool { lessonId != nil }
    var isDone: Bool { status == .done }
    /// `total` when done, else `step`. This is the `from` value for next and back.
    var position: Int { isDone ? total : step }
    /// True when the hub reads frames from a recording rather than a live camera (show "Recording").
    var isRecording: Bool { camera?.source == .file }
}

/// The active camera's identity, as in `state.camera` and the camera hello.
struct CameraInfo: Codable, Hashable, Sendable {
    enum Platform: String, WireEnum {
        case ios, web, replay, other
        static let fallback = Platform.other
    }

    enum Source: String, WireEnum {
        case glasses, phone, browser, file
        static let fallback = Source.phone
    }

    var name: String
    var platform: Platform
    var source: Source

    init(name: String, platform: Platform, source: Source) {
        self.name = name
        self.platform = platform
        self.source = source
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? "Camera"
        platform = try c.decodeIfPresent(Platform.self, forKey: .platform) ?? .other
        source = try c.decodeIfPresent(Source.self, forKey: .source) ?? .phone
    }

    enum CodingKeys: String, CodingKey { case name, platform, source }
}
