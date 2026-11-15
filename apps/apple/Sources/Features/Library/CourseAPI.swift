import Foundation
import SwiftUI

// The course library routes (server/routes_library.py), on Account's token-carrying client, the same way
// Orgs/OrgAPI.swift does it. Every caller feature-detects: an older hub answers 404 "Not Found" for a route it
// does not have, and the screens then hide the feature or fall back to `GET /api/lessons`.

extension HubError {
    /// The hub has no such route (FastAPI's own 404 body), as opposed to a 404 for a missing course or job.
    var isMissingRoute: Bool {
        if case .http(404, let detail) = self { return detail == "Not Found" }
        return false
    }

    /// 401 or 403: the person is not signed in or may not do this.
    var isPermission: Bool { status == 401 || status == 403 }
}

extension AccountClient {
    /// `GET /api/courses`.
    func courseList(filter: CourseFilter = .everyone, query: String = "") async throws -> [Course] {
        var items = [URLQueryItem(name: "filter", value: filter.wire)]
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if !q.isEmpty { items.append(URLQueryItem(name: "q", value: String(q.prefix(100)))) }
        return try await request("GET", "courses", query: items)
    }

    /// `GET /api/courses/{id}`: the course, its lesson.json, what the caller may do, and the edit history.
    func courseDetail(id: String) async throws -> CourseDetail {
        try await request("GET", "courses/\(id)")
    }

    /// `GET /api/courses/{id}/ratings`.
    func ratings(id: String) async throws -> RatingSummary {
        try await request("GET", "courses/\(id)/ratings")
    }

    /// `PATCH /api/courses/{id}`: title, description, cover, visibility, access, org_id.
    func patchCourse(id: String, _ fields: [String: JSONValue]) async throws -> Course {
        try await request("PATCH", "courses/\(id)", body: fields)
    }

    /// `POST /api/courses/{id}/publish` with status published or unlisted, and optionally the audience.
    func publish(id: String, status: CourseStatus, visibility: CourseVisibility?, orgId: String?) async throws -> Course {
        var body: [String: JSONValue] = ["status": .string(status.rawValue)]
        if let visibility { body["visibility"] = .string(visibility.rawValue) }
        if let orgId { body["org_id"] = .string(orgId) }
        return try await request("POST", "courses/\(id)/publish", body: body)
    }

    /// `POST /api/courses/{id}/unpublish`: back to draft.
    func unpublish(id: String) async throws -> Course {
        try await request("POST", "courses/\(id)/unpublish")
    }

    /// `GET /api/users` (hub owner only). Used to suggest names for a course's access list.
    func hubUsers() async throws -> [HubUser] {
        try await request("GET", "users")
    }

    /// Whether the hub has a route, without calling it: a GET on a POST-only route answers 405, a missing route
    /// answers 404 "Not Found". Used for actions that would change something if called to test.
    func hasRoute(_ path: String) async -> Bool {
        do {
            let _: JSONValue = try await request("GET", path)
            return true
        } catch let error as HubError {
            if error.isMissingRoute { return false }
            return error.status != nil
        } catch {
            return false
        }
    }

    /// The bearer header for requests this client does not make itself (multipart uploads).
    var authorization: String? { token.map { "Bearer \($0)" } }
}

/// Multipart uploads to the course routes: `POST /api/courses` (a new draft from a take) and
/// `POST /api/courses/{id}/cover`. Bodies are staged in a temporary file, as `HubClient.upload` does.
enum CourseUpload {
    /// Sends `file` to `url` as multipart form data with `fields`, reporting 0...1 as the body goes out.
    static func send<T: Decodable & Sendable>(to url: URL, file: URL, fileField: String = "file",
                                              fields: [(String, String)], authorization: String?,
                                              timeout: TimeInterval = 600,
                                              progress: @escaping @Sendable (Double) -> Void) async throws -> T {
        let boundary = "HandOver-\(UUID().uuidString)"
        let body = try await Task.detached(priority: .userInitiated) {
            try Multipart.stage(file: file, fileField: fileField, fields: fields, boundary: boundary)
        }.value
        defer { try? FileManager.default.removeItem(at: body) }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        if let authorization { request.setValue(authorization, forHTTPHeaderField: "Authorization") }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.waitsForConnectivity = false
        let session = URLSession(configuration: configuration)
        defer { session.finishTasksAndInvalidate() }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.upload(for: request, fromFile: body, delegate: SendProgress(progress))
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch let error as URLError {
            throw HubError.unreachable(error.localizedDescription)
        }
        progress(1)
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

private final class SendProgress: NSObject, URLSessionTaskDelegate, Sendable {
    private let report: @Sendable (Double) -> Void
    init(_ report: @escaping @Sendable (Double) -> Void) { self.report = report }

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        guard totalBytesExpectedToSend > 0 else { return }
        report(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend)))
    }
}

extension AccountStore {
    /// The client to use for course calls on `hub`: the signed-in one when it follows that hub, else an anonymous
    /// one (hubs in optional-auth mode answer anonymous callers).
    func courseClient(for hub: HubURL) -> AccountClient {
        if let client, client.hub == hub { return client }
        return AccountClient(hub: hub)
    }
}
