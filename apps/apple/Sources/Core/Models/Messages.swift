import Foundation

/// `advance`: sent right before the state it causes. `to` may equal `total` (finished).
struct Advance: Codable, Hashable, Sendable {
    enum Reason: String, WireEnum {
        case camera, button, voice
        static let fallback = Reason.button
    }

    var from: Int
    var to: Int
    var reason: Reason

    /// Play the chime only when the camera moved the step.
    var isCamera: Bool { reason == .camera }
}

/// `mistake`, and the same fields (minus `type`) in `state.mistake`.
struct MistakeMessage: Codable, Hashable, Sendable {
    enum Kind: String, WireEnum {
        case behind, ahead
        static let fallback = Kind.behind
    }

    /// 0-based step the learner is on.
    var step: Int
    var kind: Kind
    /// 0-based step the live frame looks like.
    var looksLike: Int
    var message: String
    var confidence: Double
    /// "gemini", "claude" or "mock".
    var source: String

    enum CodingKeys: String, CodingKey {
        case step, kind, message, confidence, source
        case looksLike = "looks_like"
    }

    init(step: Int, kind: Kind, looksLike: Int, message: String, confidence: Double, source: String) {
        self.step = step
        self.kind = kind
        self.looksLike = looksLike
        self.message = message
        self.confidence = confidence
        self.source = source
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        step = try c.decode(Int.self, forKey: .step)
        kind = try c.decodeIfPresent(Kind.self, forKey: .kind) ?? .behind
        looksLike = try c.decodeIfPresent(Int.self, forKey: .looksLike) ?? step
        message = try c.decodeIfPresent(String.self, forKey: .message) ?? ""
        confidence = try c.decodeIfPresent(Double.self, forKey: .confidence) ?? 0
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
    }
}

/// `error` on either socket, for example `no lesson selected`.
struct ErrorMessage: Codable, Hashable, Sendable {
    var message: String
}

/// `camera_status` on /ws/camera: whether this camera is the one the hub judges.
struct CameraStatus: Codable, Hashable, Sendable {
    var active: Bool
}

/// `{"job","id"}` from `POST /api/lesson`.
struct UploadReceipt: Codable, Hashable, Sendable {
    var job: String
    var id: String
}

/// `GET /api/jobs/{job}`.
struct Job: Codable, Hashable, Sendable {
    enum Status: String, WireEnum {
        case queued, normalizing, extracting, cutting, done, error
        static let fallback = Status.queued
    }

    var status: Status
    var message: String
    /// The lesson id the job builds.
    var id: String

    init(status: Status, message: String = "", id: String) {
        self.status = status
        self.message = message
        self.id = id
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(Status.self, forKey: .status)
        message = try c.decodeIfPresent(String.self, forKey: .message) ?? ""
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? ""
    }

    enum CodingKeys: String, CodingKey { case status, message, id }

    var isFinished: Bool { status == .done || status == .error }
}
