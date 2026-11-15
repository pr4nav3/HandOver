import Foundation

// The course library API's shapes (server/routes_library.py, server/docs/library.md). Every field the app can
// live without is optional or defaulted, so an older or newer hub still decodes.

/// draft, published or unlisted.
enum CourseStatus: String, WireEnum {
    case draft, published, unlisted
    static let fallback = CourseStatus.draft

    var title: String {
        switch self {
        case .draft: "Draft"
        case .published: "Published"
        case .unlisted: "Unlisted"
        }
    }
}

/// Who can find a course.
enum CourseVisibility: String, WireEnum {
    case onlyMe = "only_me", shared, org, everyone
    static let fallback = CourseVisibility.onlyMe

    var title: String {
        switch self {
        case .onlyMe: "Only Me"
        case .shared: "People with Access"
        case .org: "Organization"
        case .everyone: "Everyone on This Hub"
        }
    }
}

/// `GET /api/courses?filter=`.
enum CourseFilter: String, CaseIterable, Identifiable, Sendable {
    case everyone, mine, shared, orgs
    var id: String { rawValue }

    var title: String {
        switch self {
        case .everyone: "Everyone"
        case .mine: "Mine"
        case .shared: "Shared with Me"
        case .orgs: "My Orgs"
        }
    }

    /// The hub's name for it. "Everyone" in the app is the hub's `all`: everything this person may see.
    var wire: String { self == .everyone ? "all" : rawValue }
}

struct PersonRef: Codable, Hashable, Sendable {
    var id: String
    var name: String
}

struct OrgRef: Codable, Hashable, Sendable {
    var id: String
    var name: String
    var slug: String?
}

/// The caller's own progress on a course, from real runs. Only present when the hub knows some.
struct CourseProgress: Codable, Hashable, Sendable {
    var runs: Int
    var completed: Int
    var lastStepsDone: Int
    var lastFinished: Bool
    var total: Int

    enum CodingKeys: String, CodingKey {
        case runs, completed, total
        case lastStepsDone = "last_steps_done"
        case lastFinished = "last_finished"
    }

    init(runs: Int = 1, completed: Int = 0, lastStepsDone: Int, lastFinished: Bool = false, total: Int) {
        self.runs = runs
        self.completed = completed
        self.lastStepsDone = lastStepsDone
        self.lastFinished = lastFinished
        self.total = total
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        runs = (try? c.decodeIfPresent(Int.self, forKey: .runs)) ?? 0
        completed = (try? c.decodeIfPresent(Int.self, forKey: .completed)) ?? 0
        lastStepsDone = (try? c.decodeIfPresent(Int.self, forKey: .lastStepsDone)) ?? 0
        lastFinished = (try? c.decodeIfPresent(Bool.self, forKey: .lastFinished)) ?? false
        total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? 0
    }

    /// In progress: started and the last run did not finish.
    var isInProgress: Bool { !lastFinished && lastStepsDone > 0 && lastStepsDone < total }
    var isCompleted: Bool { completed > 0 }
    var fraction: Double { total > 0 ? min(1, Double(lastStepsDone) / Double(total)) : 0 }
}

/// One row of `GET /api/courses`, and the `course` object of `GET /api/courses/{id}`.
struct Course: Codable, Hashable, Identifiable, Sendable {
    struct Access: Codable, Hashable, Sendable, Identifiable {
        enum Role: String, WireEnum {
            case editor, learner
            static let fallback = Role.learner
            var title: String { self == .editor ? "Editor" : "Learner" }
        }

        var userId: String
        var name: String
        var role: Role
        var id: String { userId }

        enum CodingKeys: String, CodingKey {
            case userId = "user_id"
            case name, role
        }

        init(userId: String, name: String, role: Role) {
            self.userId = userId
            self.name = name
            self.role = role
        }

        init(from decoder: any Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            userId = try c.decode(String.self, forKey: .userId)
            name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? "Deleted user"
            role = (try? c.decodeIfPresent(Role.self, forKey: .role)) ?? .learner
        }
    }

    var id: String
    var title: String
    var description: String = ""
    /// The chosen cover (relative to the lesson folder), or nil.
    var cover: String?
    /// `/lessons/<id>/<file>` for the cover or the first reference frame, or nil.
    var coverURL: String?
    var steps: Int = 0
    /// Seconds from the first step's start to the last step's end.
    var duration: Double?
    var status: CourseStatus = .draft
    var visibility: CourseVisibility = .onlyMe
    var owner: PersonRef?
    var org: OrgRef?
    var access: [Access] = []
    var updated: String?
    var version: Int = 0
    /// Made before accounts existed: no owner.
    var legacy: Bool = false
    var progress: CourseProgress?

    enum CodingKeys: String, CodingKey {
        case id, title, description, cover, steps, duration, status, visibility, owner, org, access, updated
        case version, legacy, progress
        case coverURL = "cover_url"
    }

    init(id: String, title: String, description: String = "", cover: String? = nil, coverURL: String? = nil,
         steps: Int = 0, duration: Double? = nil, status: CourseStatus = .draft,
         visibility: CourseVisibility = .onlyMe, owner: PersonRef? = nil, org: OrgRef? = nil,
         access: [Access] = [], updated: String? = nil, version: Int = 0, legacy: Bool = false,
         progress: CourseProgress? = nil) {
        self.id = id
        self.title = title
        self.description = description
        self.cover = cover
        self.coverURL = coverURL
        self.steps = steps
        self.duration = duration
        self.status = status
        self.visibility = visibility
        self.owner = owner
        self.org = org
        self.access = access
        self.updated = updated
        self.version = version
        self.legacy = legacy
        self.progress = progress
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func opt<T: Decodable>(_ type: T.Type, _ key: CodingKeys) -> T? {
            (try? c.decodeIfPresent(type, forKey: key)) ?? nil
        }
        id = try c.decode(String.self, forKey: .id)
        title = opt(String.self, .title) ?? id
        description = opt(String.self, .description) ?? ""
        cover = opt(String.self, .cover)
        coverURL = opt(String.self, .coverURL)
        steps = opt(Int.self, .steps) ?? 0
        duration = opt(Double.self, .duration)
        status = opt(CourseStatus.self, .status) ?? .draft
        visibility = opt(CourseVisibility.self, .visibility) ?? .onlyMe
        owner = opt(PersonRef.self, .owner)
        org = opt(OrgRef.self, .org)
        access = opt([Access].self, .access) ?? []
        updated = opt(String.self, .updated)
        version = opt(Int.self, .version) ?? 0
        legacy = opt(Bool.self, .legacy) ?? false
        progress = opt(CourseProgress.self, .progress)
    }
}

/// What the caller may do with one course (`permissions` in `GET /api/courses/{id}`).
struct CoursePermissions: Codable, Hashable, Sendable {
    var canView = true
    var canEdit = false
    var canPublish = false
    var canUnpublish = false
    var canManage = false
    var canTransfer = false
    var canSeeInsights = false
    var canRate = false

    enum CodingKeys: String, CodingKey {
        case canView = "can_view", canEdit = "can_edit", canPublish = "can_publish"
        case canUnpublish = "can_unpublish", canManage = "can_manage", canTransfer = "can_transfer"
        case canSeeInsights = "can_see_insights", canRate = "can_rate"
    }

    init(canView: Bool = true, canEdit: Bool = false, canPublish: Bool = false, canUnpublish: Bool = false,
         canManage: Bool = false, canTransfer: Bool = false, canSeeInsights: Bool = false, canRate: Bool = false) {
        self.canView = canView
        self.canEdit = canEdit
        self.canPublish = canPublish
        self.canUnpublish = canUnpublish
        self.canManage = canManage
        self.canTransfer = canTransfer
        self.canSeeInsights = canSeeInsights
        self.canRate = canRate
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        func flag(_ key: CodingKeys) -> Bool { ((try? c.decodeIfPresent(Bool.self, forKey: key)) ?? nil) ?? false }
        canView = flag(.canView)
        canEdit = flag(.canEdit)
        canPublish = flag(.canPublish)
        canUnpublish = flag(.canUnpublish)
        canManage = flag(.canManage)
        canTransfer = flag(.canTransfer)
        canSeeInsights = flag(.canSeeInsights)
        canRate = flag(.canRate)
    }

    /// A hub without accounts: everyone may do everything, as the web app does.
    static let open = CoursePermissions(canEdit: true, canPublish: false, canManage: false)
}

/// How many edits can be undone and redone on the hub.
struct HistoryCounts: Codable, Hashable, Sendable {
    var undo: Int = 0
    var redo: Int = 0
}

/// `GET /api/courses/{id}`.
struct CourseDetail: Decodable, Sendable {
    var course: Course
    var lesson: Lesson
    var permissions: CoursePermissions
    var history: HistoryCounts?
}

/// `GET /api/courses/{id}/ratings`.
struct RatingSummary: Codable, Hashable, Sendable {
    var average: Double?
    var count: Int = 0

    init(average: Double?, count: Int) {
        self.average = average
        self.count = count
    }

    init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        average = (try? c.decodeIfPresent(Double.self, forKey: .average)) ?? nil
        count = ((try? c.decodeIfPresent(Int.self, forKey: .count)) ?? nil) ?? 0
    }

    enum CodingKeys: String, CodingKey { case average, count }

    /// "4.6 from 12 ratings", or nil when nobody rated yet.
    var line: String? {
        guard count > 0, let average else { return nil }
        let value = average.formatted(.number.precision(.fractionLength(1)))
        return "\(value) from \(count) \(count == 1 ? "rating" : "ratings")"
    }
}

/// Formatting shared by the course screens.
enum CourseFormat {
    /// "3:12", "1:04:09". Nil for a missing or negative length.
    static func duration(_ seconds: Double?) -> String? {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return nil }
        let total = Int(seconds.rounded())
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        let ss = s < 10 ? "0\(s)" : "\(s)"
        if h > 0 {
            let mm = m < 10 ? "0\(m)" : "\(m)"
            return "\(h):\(mm):\(ss)"
        }
        return "\(m):\(ss)"
    }

    /// "8 steps, 3:12" (the comma form SCREENS.md uses for meta lines).
    static func meta(steps: Int, duration: Double?) -> String {
        let count = "\(steps) \(steps == 1 ? "step" : "steps")"
        guard let time = Self.duration(duration) else { return count }
        return "\(count), \(time)"
    }

    /// A lesson's length from its steps, as the hub computes it.
    static func duration(of lesson: Lesson) -> Double? {
        guard let first = lesson.steps.first?.startSeconds, let last = lesson.steps.last?.endSeconds else { return nil }
        return max(0, last - first)
    }

    /// One step's expert time.
    static func expertSeconds(_ step: Step) -> Double? {
        guard let a = step.startSeconds, let b = step.endSeconds, b >= a else { return nil }
        return b - a
    }
}
