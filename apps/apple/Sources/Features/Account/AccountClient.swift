import Foundation

/// A person on the hub (`server/accounts.py` `public()`): id, name and hub role.
struct HubUser: Codable, Hashable, Sendable, Identifiable {
    enum Role: String, WireEnum {
        case owner, teacher, learner
        static let fallback = Role.learner
    }

    var id: String
    var name: String
    var role: Role
    var created: String?

    var roleTitle: String {
        switch role {
        case .owner: "Owner"
        case .teacher: "Teacher"
        case .learner: "Learner"
        }
    }
}

/// `GET /api/me`: who the token belongs to, whether sign-in is required, and whether the hub has no
/// users yet (first-run owner setup).
struct MeResponse: Codable, Hashable, Sendable {
    var user: HubUser?
    var auth: String
    var setupNeeded: Bool

    enum CodingKeys: String, CodingKey {
        case user, auth
        case setupNeeded = "setup_needed"
    }

    init(user: HubUser?, auth: String = "optional", setupNeeded: Bool = false) {
        self.user = user
        self.auth = auth
        self.setupNeeded = setupNeeded
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        user = try c.decodeIfPresent(HubUser.self, forKey: .user)
        auth = try c.decodeIfPresent(String.self, forKey: .auth) ?? "optional"
        setupNeeded = try c.decodeIfPresent(Bool.self, forKey: .setupNeeded) ?? false
    }

    var signInRequired: Bool { auth == "required" }
}

/// `POST /api/auth/setup` and `/api/auth/login`.
struct SignInResponse: Codable, Sendable {
    var user: HubUser
    var token: String
    var expires: String?
}

/// One course in `GET /api/courses`, with the caller's own progress from real runs (nil when none).
struct CourseProgressItem: Codable, Hashable, Sendable, Identifiable {
    struct Progress: Codable, Hashable, Sendable {
        var runs: Int
        var completed: Int
        var bestStepsDone: Int
        var lastStepsDone: Int
        var lastFinished: Bool
        var lastAt: String?
        var total: Int

        enum CodingKeys: String, CodingKey {
            case runs, completed, total
            case bestStepsDone = "best_steps_done"
            case lastStepsDone = "last_steps_done"
            case lastFinished = "last_finished"
            case lastAt = "last_at"
        }

        init(runs: Int, completed: Int, bestStepsDone: Int, lastStepsDone: Int, lastFinished: Bool,
             lastAt: String? = nil, total: Int) {
            self.runs = runs
            self.completed = completed
            self.bestStepsDone = bestStepsDone
            self.lastStepsDone = lastStepsDone
            self.lastFinished = lastFinished
            self.lastAt = lastAt
            self.total = total
        }

        init(from decoder: any Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            runs = try c.decodeIfPresent(Int.self, forKey: .runs) ?? 0
            completed = try c.decodeIfPresent(Int.self, forKey: .completed) ?? 0
            bestStepsDone = try c.decodeIfPresent(Int.self, forKey: .bestStepsDone) ?? 0
            lastStepsDone = try c.decodeIfPresent(Int.self, forKey: .lastStepsDone) ?? 0
            lastFinished = try c.decodeIfPresent(Bool.self, forKey: .lastFinished) ?? false
            lastAt = try c.decodeIfPresent(String.self, forKey: .lastAt)
            total = try c.decodeIfPresent(Int.self, forKey: .total) ?? 0
        }

        /// 0...1 of the last run, for a progress ring.
        var fraction: Double { total > 0 ? min(1, Double(lastStepsDone) / Double(total)) : 0 }
    }

    var id: String
    var title: String
    var steps: Int
    var progress: Progress?

    init(id: String, title: String, steps: Int, progress: Progress?) {
        self.id = id
        self.title = title
        self.steps = steps
        self.progress = progress
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? id
        steps = try c.decodeIfPresent(Int.self, forKey: .steps) ?? 0
        progress = try c.decodeIfPresent(Progress.self, forKey: .progress)
    }

    enum CodingKeys: String, CodingKey { case id, title, steps, progress }
}

/// The hub's account and organization API (`server/routes_library.py`), sending the bearer token when there
/// is one. Separate from Core's `HubClient` so the token never leaks into calls that do not need it.
actor AccountClient {
    nonisolated let hub: HubURL
    private(set) var token: String?
    private let session: URLSession

    init(hub: HubURL, token: String? = nil, session: URLSession? = nil) {
        self.hub = hub
        self.token = token
        if let session {
            self.session = session
        } else {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.timeoutIntervalForRequest = 10
            configuration.waitsForConnectivity = false
            self.session = URLSession(configuration: configuration)
        }
    }

    func setToken(_ token: String?) { self.token = token }

    /// `GET /api/me`. Nil when the hub has no account routes (an older hub: answers 404).
    func me() async throws -> MeResponse? {
        do {
            return try await request("GET", "me")
        } catch HubError.http(let status, _) where status == 404 || status == 405 {
            return nil
        }
    }

    func setup(name: String, passcode: String) async throws -> SignInResponse {
        try await request("POST", "auth/setup", body: ["name": .string(name), "passcode": .string(passcode)])
    }

    func login(name: String, passcode: String) async throws -> SignInResponse {
        try await request("POST", "auth/login", body: ["name": .string(name), "passcode": .string(passcode)])
    }

    func logout() async throws {
        let _: JSONValue = try await request("POST", "auth/logout")
    }

    /// `GET /api/courses`: everything this person may see, each with their own progress.
    func courses() async throws -> [CourseProgressItem] {
        try await request("GET", "courses")
    }

    // MARK: - Plumbing

    func request<T: Decodable>(_ method: String, _ path: String, body: [String: JSONValue]? = nil,
                               query: [URLQueryItem] = []) async throws -> T {
        var url = hub.api(path)
        if !query.isEmpty { url = url.appending(queryItems: query) }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch let error as URLError {
            throw HubError.unreachable(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw HubError.badResponse("Not an HTTP answer.") }
        guard (200..<300).contains(http.statusCode) else {
            throw HubError.http(status: http.statusCode, detail: HubClient.detail(data) ?? "HTTP \(http.statusCode)")
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw HubError.badResponse(String(describing: error))
        }
    }
}

extension HubError {
    /// The hub's words for a failure, cleaned up for people: a capital letter and a full stop.
    var friendly: String {
        switch self {
        case .http(let status, let detail):
            if status == 401, detail.contains("wrong name") { return "That name and passcode do not match." }
            if status == 429 { return "Too many tries. Wait a minute, then try again." }
            if status == 403 { return "You do not have permission to do that." }
            return Self.sentence(detail)
        default:
            return errorDescription ?? "Something went wrong."
        }
    }

    static func sentence(_ text: String) -> String {
        guard let first = text.first else { return text }
        var out = first.uppercased() + text.dropFirst()
        if !(out.hasSuffix(".") || out.hasSuffix("?") || out.hasSuffix("!")) { out += "." }
        return out
    }
}

extension Error {
    /// Words for any error from the account and org APIs.
    var friendlyMessage: String {
        if let hub = self as? HubError { return hub.friendly }
        return (self as? LocalizedError)?.errorDescription ?? localizedDescription
    }
}
