import Foundation

/// A role inside an organization (`library.ORG_ROLES`). Shown as Admin, Teacher, Member.
enum OrgRole: String, WireEnum, Identifiable {
    case admin = "org_admin"
    case teacher
    case learner
    static let fallback = OrgRole.learner

    var id: String { rawValue }

    var title: String {
        switch self {
        case .admin: "Admin"
        case .teacher: "Teacher"
        case .learner: "Member"
        }
    }

    /// Admins and Teachers can teach in the org.
    var canTeach: Bool { self != .learner }
}

/// `{id, name, slug}` as the hub nests it.
struct OrgBrief: Codable, Hashable, Sendable, Identifiable {
    var id: String
    var name: String
    var slug: String?
}

/// One of my organizations in `GET /api/orgs`.
struct OrgSummary: Codable, Hashable, Sendable, Identifiable {
    var id: String
    var name: String
    var slug: String?
    var created: String?
    /// Member count.
    var members: Int
    /// My role, or nil when I see it only as the hub owner.
    var role: OrgRole?
}

/// An invite: a code (`kind == "code"`) or one addressed to a person by name (`kind == "user"`).
struct OrgInvite: Codable, Hashable, Sendable, Identifiable {
    var id: String
    var kind: String
    var role: OrgRole
    var created: String?
    var expires: String?
    var createdBy: String?
    var maxUses: Int?
    var uses: Int?
    var user: Person?
    /// Only in the answer that created the code; the hub keeps just its hash.
    var code: String?
    /// The org, in my pending invites.
    var org: OrgBrief?

    struct Person: Codable, Hashable, Sendable {
        var id: String?
        var name: String
    }

    enum CodingKeys: String, CodingKey {
        case id, kind, role, created, expires, uses, user, code, org
        case createdBy = "created_by"
        case maxUses = "max_uses"
    }

    var isCode: Bool { kind == "code" }

    var expiryDate: Date? { expires.flatMap(OrgDates.parse) }

    func isExpired(now: Date = Date()) -> Bool {
        guard let expiryDate else { return false }
        return expiryDate <= now
    }

    var usesLeft: Int? {
        guard let maxUses else { return nil }
        return max(0, maxUses - (uses ?? 0))
    }
}

/// A member row in an org page.
struct OrgMember: Codable, Hashable, Sendable, Identifiable {
    var userId: String
    var name: String
    var role: OrgRole
    var joined: String?

    var id: String { userId }

    enum CodingKeys: String, CodingKey {
        case name, role, joined
        case userId = "user_id"
    }
}

/// A course published to an org.
struct OrgCourse: Codable, Hashable, Sendable, Identifiable {
    var id: String
    var title: String
    var coverUrl: String?
    var steps: Int
    var status: String?
    var owner: OrgInvite.Person?

    enum CodingKeys: String, CodingKey {
        case id, title, steps, status, owner
        case coverUrl = "cover_url"
    }
}

/// `GET /api/orgs/{id}`.
struct OrgDetail: Codable, Hashable, Sendable, Identifiable {
    var id: String
    var name: String
    var slug: String?
    var created: String?
    var role: OrgRole?
    var owner: OrgInvite.Person?
    var members: [OrgMember]
    var courses: [OrgCourse]
    /// Live invites, only for admins (and the hub owner); nil for everyone else.
    var invites: [OrgInvite]?

    var summary: OrgSummary {
        OrgSummary(id: id, name: name, slug: slug, created: created, members: members.count, role: role)
    }

    var adminCount: Int { members.filter { $0.role == .admin }.count }
}

/// `GET /api/orgs`: my orgs, and invites addressed to me that I have not answered.
struct MyOrgs: Codable, Hashable, Sendable {
    var orgs: [OrgSummary]
    var invites: [OrgInvite]
}

/// What a person may do on an org page (SCREENS.md 24). Computed from the hub's answers, never guessed
/// from names: the org role from `GET /api/orgs/{id}`, the hub role from `GET /api/me`.
struct OrgPermissions: Equatable, Sendable {
    var canTeach = false
    var canInvite = false
    var canManageMembers = false
    var canDelete = false
    var canLeave = false

    init(org: OrgDetail, me: HubUser?) {
        let hubOwner = me?.role == .owner
        let role = org.role
        let admin = role == .admin || hubOwner
        canTeach = role?.canTeach == true || hubOwner
        canInvite = admin
        canManageMembers = admin
        canDelete = hubOwner || (me != nil && org.owner?.id == me?.id)
        canLeave = role != nil && !(role == .admin && org.adminCount <= 1)
    }

    /// May this person change or remove `member`? Never the last admin, never yourself here.
    func canEdit(_ member: OrgMember, in org: OrgDetail, me: HubUser?) -> Bool {
        guard canManageMembers, member.userId != me?.id else { return false }
        return !(member.role == .admin && org.adminCount <= 1)
    }
}

enum OrgDates {
    static func parse(_ text: String) -> Date? {
        let full = ISO8601DateFormatter()
        full.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = full.date(from: text) { return date }
        let plain = ISO8601DateFormatter()
        return plain.date(from: text)
    }
}
