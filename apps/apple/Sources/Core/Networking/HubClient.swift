import Foundation
import UniformTypeIdentifiers

/// A REST failure, in words a person can act on.
enum HubError: Error, Equatable, Sendable, LocalizedError {
    /// The hub answered with an error status. `detail` is its message (CONTRACT.md section 4 lists them).
    case http(status: Int, detail: String)
    /// No answer: the hub is off, on another network, or the address is wrong.
    case unreachable(String)
    /// The answer was not what the contract says.
    case badResponse(String)
    case fileUnreadable(String)

    var errorDescription: String? {
        switch self {
        case .http(_, let detail): detail
        case .unreachable(let why): "Can't reach the hub. \(why)"
        case .badResponse(let why): "The hub sent something unexpected. \(why)"
        case .fileUnreadable(let why): "Can't read the video. \(why)"
        }
    }

    var status: Int? {
        if case .http(let status, _) = self { return status }
        return nil
    }
}

/// The hub's REST API (CONTRACT.md section 4): lessons, upload with progress, job polling, recut, delete.
actor HubClient {
    nonisolated let hub: HubURL
    private let session: URLSession

    init(hub: HubURL, session: URLSession? = nil) {
        self.hub = hub
        if let session {
            self.session = session
        } else {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.timeoutIntervalForRequest = 10
            configuration.waitsForConnectivity = false
            self.session = URLSession(configuration: configuration)
        }
    }

    /// `GET /api/lessons`, sorted by id.
    func lessons() async throws -> [LessonSummary] {
        try await get(hub.api("lessons"))
    }

    /// `GET /api/lessons/{id}`.
    func lesson(id: String) async throws -> Lesson {
        try await get(hub.api("lessons").appending(path: id))
    }

    /// `GET /api/jobs/{job}`.
    func job(_ job: String) async throws -> Job {
        try await get(hub.api("jobs").appending(path: job))
    }

    /// Polls a job until it is done or failed, reporting every change. Cancel the task to stop early.
    func waitForJob(_ job: String, every interval: Duration = .seconds(1),
                    onUpdate: @Sendable (Job) async -> Void = { _ in }) async throws -> Job {
        var last: Job?
        while true {
            let current = try await self.job(job)
            if current != last {
                last = current
                await onUpdate(current)
            }
            if current.isFinished { return current }
            try await Task.sleep(for: interval)
        }
    }

    /// `POST /api/lesson`: uploads a video file as multipart form data and returns the job to poll.
    /// `progress` gets 0...1 as the body goes out. The body is staged in a temporary file, so a 2 GB video
    /// never sits in memory and the hub gets the Content-Length it requires.
    func upload(video: URL, title: String, id: String? = nil,
                progress: @escaping @Sendable (Double) -> Void = { _ in }) async throws -> UploadReceipt {
        let boundary = "HandOver-\(UUID().uuidString)"
        var fields = [("title", title)]
        if let id, !id.isEmpty { fields.append(("id", id)) }
        let body = try await Task.detached(priority: .userInitiated) {
            try Multipart.stage(file: video, fileField: "file", fields: fields, boundary: boundary)
        }.value
        defer { try? FileManager.default.removeItem(at: body) }

        var request = URLRequest(url: hub.api("lesson"))
        request.httpMethod = "POST"
        request.timeoutInterval = 600
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let delegate = UploadProgress(progress)
        let (data, response) = try await transport {
            try await session.upload(for: request, fromFile: body, delegate: delegate)
        }
        progress(1)
        return try decode(data, response)
    }

    /// `POST /api/lessons/{id}/recut`. With a lesson, it is saved first (the whole lesson.json is replaced,
    /// which is why `Lesson` keeps unknown fields); without, the stored one is recut. Returns the new lesson.
    func recut(id: String, lesson: Lesson? = nil) async throws -> Lesson {
        var request = URLRequest(url: hub.api("lessons").appending(path: id).appending(path: "recut"))
        request.httpMethod = "POST"
        request.timeoutInterval = 300
        if let lesson {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(lesson)
        }
        let (data, response) = try await transport { try await session.data(for: request) }
        return try decode(data, response)
    }

    /// `DELETE /api/lessons/{id}`.
    func delete(id: String) async throws {
        var request = URLRequest(url: hub.api("lessons").appending(path: id))
        request.httpMethod = "DELETE"
        let (data, response) = try await transport { try await session.data(for: request) }
        _ = try decode(data, response) as Deleted
    }

    // MARK: - Plumbing

    private struct Deleted: Decodable { var deleted: String }

    private func get<T: Decodable>(_ url: URL) async throws -> T {
        let (data, response) = try await transport { try await session.data(from: url) }
        return try decode(data, response)
    }

    private func transport(_ work: () async throws -> (Data, URLResponse)) async throws -> (Data, URLResponse) {
        do {
            return try await work()
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch let error as URLError {
            throw HubError.unreachable(error.localizedDescription)
        }
    }

    private nonisolated func decode<T: Decodable>(_ data: Data, _ response: URLResponse) throws -> T {
        guard let http = response as? HTTPURLResponse else { throw HubError.badResponse("Not an HTTP answer.") }
        guard (200..<300).contains(http.statusCode) else {
            throw HubError.http(status: http.statusCode, detail: Self.detail(data) ?? "HTTP \(http.statusCode)")
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw HubError.badResponse(String(describing: error))
        }
    }

    /// FastAPI errors are `{"detail": "<message>"}`; a 422 has a list of `{"msg": ...}` instead.
    static func detail(_ data: Data) -> String? {
        guard let body = try? JSONDecoder().decode([String: JSONValue].self, from: data) else { return nil }
        switch body["detail"] {
        case .string(let s): return s
        case .array(let items):
            let messages = items.compactMap { item -> String? in
                if case .object(let o) = item, case .string(let msg) = o["msg"] { return msg }
                return nil
            }
            return messages.isEmpty ? nil : messages.joined(separator: "; ")
        default: return nil
        }
    }
}

/// Upload progress from URLSession, forwarded as a fraction.
private final class UploadProgress: NSObject, URLSessionTaskDelegate, Sendable {
    private let report: @Sendable (Double) -> Void

    init(_ report: @escaping @Sendable (Double) -> Void) { self.report = report }

    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        guard totalBytesExpectedToSend > 0 else { return }
        report(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend)))
    }
}

/// Writes a multipart/form-data body to a temporary file.
enum Multipart {
    static func stage(file: URL, fileField: String, fields: [(String, String)], boundary: String) throws -> URL {
        let scoped = file.startAccessingSecurityScopedResource()
        defer { if scoped { file.stopAccessingSecurityScopedResource() } }
        guard let input = try? FileHandle(forReadingFrom: file) else {
            throw HubError.fileUnreadable(file.lastPathComponent)
        }
        defer { try? input.close() }

        let out = FileManager.default.temporaryDirectory.appending(path: "handover-upload-\(UUID().uuidString)")
        guard FileManager.default.createFile(atPath: out.path(percentEncoded: false), contents: nil),
              let output = try? FileHandle(forWritingTo: out) else {
            throw HubError.fileUnreadable("No room for a temporary copy.")
        }
        do {
            defer { try? output.close() }
            var head = ""
            for (name, value) in fields {
                head += "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(escape(name))\"\r\n\r\n\(value)\r\n"
            }
            let filename = file.lastPathComponent.isEmpty ? "video.mp4" : file.lastPathComponent
            head += "--\(boundary)\r\nContent-Disposition: form-data; name=\"\(escape(fileField))\"; filename=\"\(escape(filename))\"\r\n"
            head += "Content-Type: \(mimeType(for: file))\r\n\r\n"
            try output.write(contentsOf: Data(head.utf8))
            while let chunk = try input.read(upToCount: 1 << 20), !chunk.isEmpty {
                try output.write(contentsOf: chunk)
            }
            try output.write(contentsOf: Data("\r\n--\(boundary)--\r\n".utf8))
        } catch {
            try? FileManager.default.removeItem(at: out)
            throw HubError.fileUnreadable(error.localizedDescription)
        }
        return out
    }

    static func mimeType(for file: URL) -> String {
        UTType(filenameExtension: file.pathExtension)?.preferredMIMEType ?? "video/mp4"
    }

    private static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "\"", with: "%22").replacingOccurrences(of: "\r", with: "").replacingOccurrences(of: "\n", with: "")
    }
}
