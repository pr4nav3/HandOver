import Foundation

/// The hub's run score (`GET /api/runs/{run_id}/score`, server/scoring.py). Only the fields Done shows.
struct HubRunScore: Decodable, Equatable, Sendable {
    struct StepRef: Decodable, Equatable, Sendable {
        var n: Int
        var score: Int?
    }

    var score: Int?
    var label: String?
    var reason: String?
    var bestStep: StepRef?
    var weakestStep: StepRef?
    var tip: String?

    enum CodingKeys: String, CodingKey {
        case score, label, reason, tip
        case bestStep = "best_step"
        case weakestStep = "weakest_step"
    }
}

/// The two Done calls, feature-detected: a missing route or a hub without accounts answers with an error
/// status, and Done falls back to what this device recorded.
enum DoneAPI {
    enum RatingOutcome: Equatable, Sendable {
        case sent
        case needsSignIn
        case unsupported
        case failed
    }

    /// Run ids are 1 to 64 letters, digits, `_` or `-` (the hub's RUN_ID_RE).
    static func isValidRunId(_ id: String) -> Bool {
        !id.isEmpty && id.count <= 64 && id.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == "-") }
    }

    /// The hub's score for `runId`, or nil when the hub has none (404, no route, unreachable).
    static func score(hub: HubURL, runId: String, session: URLSession = .shared) async -> HubRunScore? {
        guard isValidRunId(runId) else { return nil }
        let url = hub.api("runs").appending(path: runId).appending(path: "score")
        guard let (data, response) = try? await session.data(from: url),
              (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return try? JSONDecoder().decode(HubRunScore.self, from: data)
    }

    /// `POST /api/courses/{lesson}/rating` with 1 to 5 stars and an optional comment of up to 500 characters.
    static func rate(hub: HubURL, lessonId: String, stars: Int, comment: String,
                     session: URLSession = .shared) async -> RatingOutcome {
        var request = URLRequest(url: hub.api("courses").appending(path: lessonId).appending(path: "rating"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        var body: [String: Any] = ["stars": min(5, max(1, stars))]
        let trimmed = comment.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { body["comment"] = String(trimmed.prefix(500)) }
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        guard let (_, response) = try? await session.data(for: request),
              let status = (response as? HTTPURLResponse)?.statusCode else { return .failed }
        switch status {
        case 200..<300: return .sent
        case 401, 403: return .needsSignIn
        case 404, 405: return .unsupported
        default: return .failed
        }
    }

    /// Whether this device already offered the rating prompt for a lesson (asked once per lesson).
    static func ratingOffered(_ lessonId: String, defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: "handover.ratingOffered.\(lessonId)")
    }

    static func markRatingOffered(_ lessonId: String, defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: "handover.ratingOffered.\(lessonId)")
    }
}
