import Foundation

// The editor routes (server/docs/library.md, "Editor") on Account's token-carrying client, and the two ways the
// editor saves: through those routes (the hub keeps undo history), or, on hubs without them, by sending the whole
// lesson through `POST /api/lessons/{id}/recut` with undo kept on this device.

private struct EditResponse: Decodable {
    var lesson: Lesson
    var history: HistoryCounts?
    var recut: Bool?
}

struct SelfTestResponse: Decodable {
    struct Result: Decodable {
        var n: Int
        var selfTest: Step.SelfTest?
        enum CodingKeys: String, CodingKey { case n, selfTest = "self_test" }
    }
    var results: [Result]
    var lesson: Lesson
    var history: HistoryCounts?
}

struct CourseJob: Decodable, Equatable, Sendable {
    var status: String
    var message: String?
    var isFinished: Bool { status == "done" || status == "error" }
}

private struct JobReceipt: Decodable { var job: String }

/// `GET /api/courses/{id}/produce` (proposed; see the report): whether produced videos exist and are current.
struct ProduceStatus: Decodable, Equatable, Sendable {
    var present: Bool
    var stale: Bool?
}

extension AccountClient {
    private func edit(_ id: String, _ op: String, _ body: [String: JSONValue]?) async throws -> EditOutcome {
        let answer: EditResponse = try await request("POST", "courses/\(id)/edit/\(op)", body: body)
        return EditOutcome(lesson: answer.lesson, history: answer.history ?? HistoryCounts(), recut: answer.recut ?? false)
    }

    func apply(_ op: EditOp, course id: String) async throws -> EditOutcome {
        switch op {
        case let .boundary(n, start, end, next):
            var first: [String: JSONValue] = ["n": .int(n)]
            if let start { first["start"] = .double(start) }
            if let end { first["end"] = .double(end) }
            var steps: [JSONValue] = [.object(first)]
            if let next { steps.append(.object(["n": .int(next.n), "start": .double(next.start)])) }
            return try await edit(id, "boundaries", ["steps": .array(steps)])
        case let .split(n, at):
            return try await edit(id, "split", ["n": .int(n), "at": .double(at)])
        case let .merge(n):
            return try await edit(id, "merge", ["n": .int(n)])
        case let .delete(n):
            return try await edit(id, "delete", ["n": .int(n)])
        case let .step(n, fields):
            var body = fields.json
            body["n"] = .int(n)
            return try await edit(id, "step", body)
        case let .captions(n, cues):
            return try await edit(id, "captions", ["n": .int(n), "cues": .array(cues.map(\.json))])
        }
    }

    func undoEdit(course id: String) async throws -> EditOutcome { try await edit(id, "undo", nil) }
    func redoEdit(course id: String) async throws -> EditOutcome { try await edit(id, "redo", nil) }

    /// Runs the check on this step's frame and the previous one (`POST .../edit/selftest {"n"}`).
    func selfTest(course id: String, n: Int) async throws -> SelfTestResponse {
        try await request("POST", "courses/\(id)/edit/selftest", body: ["n": .int(n)])
    }

    /// Writes and speaks a voiceover for some steps; returns the job to poll.
    func voiceover(course id: String, steps: [Int]?, voice: String?) async throws -> String {
        var body: [String: JSONValue] = ["mode": .string("duck")]
        if let voice { body["voice"] = .string(voice) }
        if let steps { body["steps"] = .array(steps.map { .int($0) }) }
        let receipt: JobReceipt = try await request("POST", "courses/\(id)/edit/voiceover", body: body)
        return receipt.job
    }

    /// Back to the original sound.
    func removeVoiceover(course id: String) async throws -> Lesson {
        struct Answer: Decodable { var lesson: Lesson }
        let answer: Answer = try await request("POST", "courses/\(id)/edit/voiceover/undo")
        return answer.lesson
    }

    func courseJob(course id: String, job: String) async throws -> CourseJob {
        try await request("GET", "courses/\(id)/jobs/\(job)")
    }

    /// Polls a course job until it ends.
    func waitForCourseJob(course id: String, job: String) async throws -> CourseJob {
        while true {
            let current = try await courseJob(course: id, job: job)
            if current.isFinished { return current }
            try await Task.sleep(for: .seconds(1))
        }
    }

    func produceStatus(course id: String) async throws -> ProduceStatus {
        try await request("GET", "courses/\(id)/produce")
    }

    /// Re-renders the produced videos with a style; returns the job to poll.
    func produce(course id: String, style: ProductionStyle) async throws -> String {
        let receipt: JobReceipt = try await request("POST", "courses/\(id)/produce", body: ["style": style.json])
        return receipt.job
    }
}

/// What the editor can do on this hub.
struct EditorCapabilities: Equatable, Sendable {
    /// Course routes: details, cover, publish, access.
    var course = false
    var captions = false
    var selfTest = false
    var voiceover = false
    var production = false

    static let recutOnly = EditorCapabilities()
    static let full = EditorCapabilities(course: true, captions: true, selfTest: true, voiceover: true, production: true)
}

/// How the editor loads and saves. Tests use fakes.
@MainActor
protocol EditorService: AnyObject {
    func load() async throws -> EditorSnapshot
    func apply(_ op: EditOp, to lesson: Lesson) async throws -> EditOutcome
    func undo(from lesson: Lesson) async throws -> EditOutcome
    func redo(from lesson: Lesson) async throws -> EditOutcome
}

struct EditorSnapshot: Sendable {
    var lesson: Lesson
    var course: Course?
    var permissions: CoursePermissions
    var history: HistoryCounts
    var capabilities: EditorCapabilities
}

/// Saves through the hub's editor routes; the hub keeps the history.
@MainActor
final class CourseEditorService: EditorService {
    let id: String
    let client: AccountClient

    init(id: String, client: AccountClient) {
        self.id = id
        self.client = client
    }

    func load() async throws -> EditorSnapshot {
        let detail = try await client.courseDetail(id: id)
        async let voice = client.hasRoute("courses/\(id)/edit/voiceover")
        async let produce = try? client.produceStatus(course: id)
        let produced = await produce
        let caps = EditorCapabilities(course: true, captions: true, selfTest: true, voiceover: await voice,
                                      production: produced?.present == true)
        return EditorSnapshot(lesson: detail.lesson, course: detail.course, permissions: detail.permissions,
                              history: detail.history ?? HistoryCounts(), capabilities: caps)
    }

    func apply(_ op: EditOp, to lesson: Lesson) async throws -> EditOutcome { try await client.apply(op, course: id) }
    func undo(from lesson: Lesson) async throws -> EditOutcome { try await client.undoEdit(course: id) }
    func redo(from lesson: Lesson) async throws -> EditOutcome { try await client.redoEdit(course: id) }
}

/// Saves by sending the whole lesson through recut, keeping undo on this device (hubs without editor routes).
@MainActor
final class RecutEditorService: EditorService {
    let id: String
    private let fetch: @Sendable (String) async throws -> Lesson
    private let recut: @Sendable (String, Lesson) async throws -> Lesson
    private(set) var stack = EditorUndoStack<Lesson>()

    init(id: String, fetch: @escaping @Sendable (String) async throws -> Lesson,
         recut: @escaping @Sendable (String, Lesson) async throws -> Lesson) {
        self.id = id
        self.fetch = fetch
        self.recut = recut
    }

    convenience init(id: String, hub: HubClient) {
        self.init(id: id, fetch: { try await hub.lesson(id: $0) }, recut: { try await hub.recut(id: $0, lesson: $1) })
    }

    func load() async throws -> EditorSnapshot {
        let lesson = try await fetch(id)
        return EditorSnapshot(lesson: lesson, course: nil, permissions: .open, history: stack.counts,
                              capabilities: .recutOnly)
    }

    func apply(_ op: EditOp, to lesson: Lesson) async throws -> EditOutcome {
        let changed = try LessonEdits.apply(op, to: lesson)
        stack.record(lesson)
        do {
            let saved = try await recut(id, changed)
            return EditOutcome(lesson: saved, history: stack.counts, recut: op.recuts)
        } catch {
            stack.dropLast()
            throw error
        }
    }

    func undo(from lesson: Lesson) async throws -> EditOutcome {
        guard let previous = stack.undo(from: lesson) else { throw HubError.http(status: 409, detail: "nothing to undo") }
        do {
            return EditOutcome(lesson: try await recut(id, previous), history: stack.counts, recut: true)
        } catch {
            _ = stack.redo(from: previous)
            throw error
        }
    }

    func redo(from lesson: Lesson) async throws -> EditOutcome {
        guard let next = stack.redo(from: lesson) else { throw HubError.http(status: 409, detail: "nothing to redo") }
        do {
            return EditOutcome(lesson: try await recut(id, next), history: stack.counts, recut: true)
        } catch {
            _ = stack.undo(from: next)
            throw error
        }
    }
}
