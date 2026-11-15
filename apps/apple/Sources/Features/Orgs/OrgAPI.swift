import Foundation

/// The organization routes (`server/routes_library.py`, organizations). All need a signed-in person.
extension AccountClient {
    func myOrgs() async throws -> MyOrgs {
        try await request("GET", "orgs")
    }

    func createOrg(name: String) async throws -> OrgDetail {
        try await request("POST", "orgs", body: ["name": .string(name)])
    }

    func org(_ id: String) async throws -> OrgDetail {
        try await request("GET", "orgs/\(id)")
    }

    func renameOrg(_ id: String, name: String) async throws -> OrgDetail {
        try await request("PATCH", "orgs/\(id)", body: ["name": .string(name)])
    }

    func deleteOrg(_ id: String) async throws {
        let _: JSONValue = try await request("DELETE", "orgs/\(id)")
    }

    /// Joins with an invite code. The hub compares the code exactly, so it is sent as typed (spaces removed).
    func join(code: String) async throws -> OrgSummary {
        try await request("POST", "orgs/join", body: ["code": .string(code)])
    }

    /// Accepts an invite sent to me by name.
    func accept(invite id: String) async throws -> OrgSummary {
        try await request("POST", "orgs/join", body: ["invite_id": .string(id)])
    }

    /// Makes an invite code. `maxUses` nil means no limit. The answer carries the code, once.
    func createInviteCode(org: String, role: OrgRole, expiresDays: Double, maxUses: Int?) async throws -> OrgInvite {
        try await request("POST", "orgs/\(org)/invites",
                          body: ["role": .string(role.rawValue), "expires_days": .double(expiresDays),
                                 "max_uses": maxUses.map { .int($0) } ?? .null])
    }

    func invite(username: String, to org: String, role: OrgRole) async throws -> OrgInvite {
        try await request("POST", "orgs/\(org)/invites",
                          body: ["username": .string(username), "role": .string(role.rawValue)])
    }

    /// Revokes a code or invite (admins), or declines my own invite.
    func deleteInvite(org: String, invite: String) async throws {
        let _: JSONValue = try await request("DELETE", "orgs/\(org)/invites/\(invite)")
    }

    func leave(org: String) async throws {
        let _: JSONValue = try await request("POST", "orgs/\(org)/leave")
    }

    func setRole(_ role: OrgRole, member: String, org: String) async throws {
        let _: JSONValue = try await request("PATCH", "orgs/\(org)/members/\(member)",
                                             body: ["role": .string(role.rawValue)])
    }

    func remove(member: String, org: String) async throws {
        let _: JSONValue = try await request("DELETE", "orgs/\(org)/members/\(member)")
    }
}
