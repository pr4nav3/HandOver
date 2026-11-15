import Foundation
import Observation

/// The Library's data: courses from `GET /api/courses` with filters and search, or, on a hub without the
/// course routes, the lesson list from `GET /api/lessons` (search runs on this device then).
@MainActor
@Observable
final class LibraryStore {
    /// Which hub API the list came from.
    enum Source: Equatable { case unknown, courses, legacy }

    enum Phase: Equatable {
        case idle, loading, loaded
        case failed(String)
    }

    /// How the store reaches the hub. Tests pass fakes.
    struct Backend: Sendable {
        var hub: HubURL
        /// Nil when the hub has no account routes at all (skip straight to the lesson list).
        var courses: (@Sendable (CourseFilter, String) async throws -> [Course])?
        var lessons: @Sendable () async throws -> [LessonSummary]
        var lesson: @Sendable (String) async throws -> Lesson
    }

    private(set) var source: Source = .unknown
    private(set) var phase: Phase = .idle
    private(set) var items: [CourseCardItem] = []
    /// Shown only when the search or filter came back empty but the hub has lessons.
    private(set) var lastQuery = ""
    var filter: CourseFilter = .everyone
    var query = ""

    @ObservationIgnored private var backend: Backend?
    @ObservationIgnored private var durations: [String: Double] = [:]
    @ObservationIgnored private var legacyAll: [LessonSummary] = []
    @ObservationIgnored private var loadTask: Task<Void, Never>?
    @ObservationIgnored private var durationTask: Task<Void, Never>?

    init(backend: Backend? = nil) { self.backend = backend }

    /// Lessons the person started and did not finish, newest first.
    var continueItems: [CourseCardItem] { items.filter { $0.progress?.isInProgress == true } }
    var isEmpty: Bool { phase == .loaded && items.isEmpty }
    var isSearching: Bool { !lastQuery.isEmpty }
    /// Filters other than Everyone need the course routes.
    var showsFilters: Bool { source == .courses }

    /// Points the store at a hub; reloads when it changed.
    func use(_ backend: Backend?) {
        let changed = backend?.hub != self.backend?.hub
        self.backend = backend
        if changed {
            source = .unknown
            items = []
            durations = [:]
            phase = .idle
        }
    }

    /// Reloads the list now, and waits for it.
    func reload() async {
        loadTask?.cancel()
        let task = Task { await load() }
        loadTask = task
        await task.value
    }

    /// Reloads after a short pause, for typing in the search field.
    func queryChanged() {
        loadTask?.cancel()
        loadTask = Task {
            try? await Task.sleep(for: .milliseconds(300))
            if Task.isCancelled { return }
            await load()
        }
    }

    private func load() async {
        guard let backend else {
            phase = .idle
            items = []
            return
        }
        if items.isEmpty { phase = .loading }
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if source != .legacy, let courses = backend.courses {
            do {
                let list = try await courses(filter, q)
                if Task.isCancelled { return }
                source = .courses
                items = list.map { card($0, hub: backend.hub) }
                lastQuery = q
                phase = .loaded
                return
            } catch let error as HubError where error.isMissingRoute {
                source = .legacy
            } catch is CancellationError {
                return
            } catch {
                if Task.isCancelled { return }
                fail(error)
                return
            }
        }
        source = .legacy
        do {
            legacyAll = try await backend.lessons()
            if Task.isCancelled { return }
            applyLegacy(query: q, hub: backend.hub)
            lastQuery = q
            phase = .loaded
            fillDurations(backend)
        } catch is CancellationError {
        } catch {
            if !Task.isCancelled { fail(error) }
        }
    }

    private func fail(_ error: any Error) {
        let message = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        phase = .failed(message)
    }

    private func applyLegacy(query: String, hub: HubURL) {
        let needle = query.lowercased()
        items = legacyAll
            .filter { needle.isEmpty || $0.title.lowercased().contains(needle) || $0.id.lowercased().contains(needle) }
            .map { summary in
                CourseCardItem(id: summary.id, title: summary.title,
                               covers: CourseMedia.coverCandidates(hub: hub, lessonId: summary.id, coverURL: nil),
                               steps: summary.steps, duration: durations[summary.id])
            }
    }

    /// Legacy lists carry no length; read each lesson once (a few at a time) to show it.
    private func fillDurations(_ backend: Backend) {
        let missing = legacyAll.map(\.id).filter { durations[$0] == nil }
        guard !missing.isEmpty else { return }
        durationTask?.cancel()
        durationTask = Task {
            for chunk in stride(from: 0, to: missing.count, by: 4).map({ Array(missing[$0..<min($0 + 4, missing.count)]) }) {
                let found = await withTaskGroup(of: (String, Double?).self) { group in
                    for id in chunk {
                        group.addTask { (id, (try? await backend.lesson(id)).flatMap(CourseFormat.duration(of:))) }
                    }
                    var out: [(String, Double?)] = []
                    for await pair in group { out.append(pair) }
                    return out
                }
                if Task.isCancelled { return }
                for (id, seconds) in found { if let seconds { durations[id] = seconds } }
                for i in items.indices { items[i].duration = durations[items[i].id] ?? items[i].duration }
            }
        }
    }

    func card(_ course: Course, hub: HubURL) -> CourseCardItem {
        CourseCardItem(id: course.id, title: course.title,
                       covers: CourseMedia.coverCandidates(hub: hub, lessonId: course.id, coverURL: course.coverURL),
                       steps: course.steps, duration: course.duration, status: course.status,
                       progress: course.progress, ownerId: course.owner?.id, ownerName: course.owner?.name)
    }

    /// Drops a deleted lesson from the list at once.
    func remove(_ id: String) {
        items.removeAll { $0.id == id }
        legacyAll.removeAll { $0.id == id }
    }

    /// Fills the store for previews and snapshots.
    func preview(items: [CourseCardItem], source: Source = .courses) {
        self.items = items
        self.source = source
        phase = .loaded
    }
}

extension LibraryStore.Backend {
    /// The live backend for the app's hub.
    @MainActor
    static func live(model: AppModel, accounts: AccountStore) -> LibraryStore.Backend? {
        guard let hub = model.hub, let client = model.client else { return nil }
        let account = accounts.courseClient(for: hub)
        let noAccounts = accounts.hub == hub && accounts.support == .unavailable
        var courses: (@Sendable (CourseFilter, String) async throws -> [Course])?
        if !noAccounts {
            courses = { filter, q in try await account.courseList(filter: filter, query: q) }
        }
        return LibraryStore.Backend(hub: hub, courses: courses,
                                    lessons: { try await client.lessons() },
                                    lesson: { id in try await client.lesson(id: id) })
    }
}
