import SwiftUI

/// One organization (SCREENS.md 22.4): header with the actions this person may take, then Lessons and
/// Members. Admin actions (invite, roles, remove) appear only for admins; nothing is shown disabled.
struct OrgPageView: View {
    let orgID: String
    /// Fixed data for previews and snapshots.
    var preset: OrgDetail?
    /// The tab shown first.
    var startTab: Tab = .lessons
    /// Called with the org when a teacher taps Teach. The Teach feature can preset its target from it.
    var onTeach: ((OrgDetail) -> Void)?

    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var org: OrgDetail?
    @State private var error: String?
    @State private var tab = Tab.lessons
    @State private var inviting = false
    @State private var removing: OrgMember?
    @State private var confirmLeave = false
    @State private var confirmDelete = false
    @State private var toast: ToastItem?
    @State private var teaching = false

    enum Tab: String, CaseIterable { case lessons = "Lessons", members = "Members" }

    var body: some View {
        Group {
            if let org = preset ?? org {
                page(org)
            } else if let error {
                HOEmptyState(symbol: "exclamationmark.triangle", title: "Cannot open this organization", message: error,
                             tone: .caution) {
                    Button("Try Again") { Task { await load() } }.buttonStyle(HOButtonStyle(.primary))
                }
            } else {
                HOEmptyState(title: "Loading", loading: true)
            }
        }
        .hoPaperBackground()
        .navigationTitle((preset ?? org)?.name ?? "")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .task { await load() }
        .refreshable { await load() }
        .hoToast($toast)
        .onAppear { tab = startTab }
    }

    private func page(_ org: OrgDetail) -> some View {
        let can = OrgPermissions(org: org, me: accounts.user)
        return ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                header(org, can)
                Picker("Show", selection: $tab) {
                    ForEach(Tab.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .sensoryFeedback(.selection, trigger: tab)
                switch tab {
                case .lessons: lessons(org, can)
                case .members: members(org, can)
                }
            }
            .padding(HOSpace.l)
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity)
        }
        .toolbar {
            if can.canLeave || can.canDelete {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        if can.canLeave {
                            Button("Leave Organization", systemImage: "rectangle.portrait.and.arrow.right") { confirmLeave = true }
                        }
                        if can.canDelete {
                            Button("Delete Organization", systemImage: "trash", role: .destructive) { confirmDelete = true }
                        }
                    } label: {
                        Label("More", systemImage: "ellipsis.circle")
                    }
                }
            }
        }
        .sheet(isPresented: $inviting, onDismiss: { Task { await load() } }) {
            InviteSheet(org: org)
        }
        .sheet(isPresented: $teaching, onDismiss: { Task { await load() } }) {
            NavigationStack {
                TeachView()
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { teaching = false } } }
            }
            #if os(macOS)
            .frame(minWidth: 720, minHeight: 600)
            #endif
        }
        .confirmationDialog("Remove \(removing?.name ?? "this person") from \(org.name)?",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) { if let m = removing { remove(m, from: org) } }
        } message: {
            Text("They lose access to this organization's lessons. Lessons they made stay in the org.")
        }
        .confirmationDialog("Leave \(org.name)?", isPresented: $confirmLeave, titleVisibility: .visible) {
            Button("Leave", role: .destructive) { leave(org) }
        } message: {
            Text("You lose access to its lessons. Your progress stays on the hub.")
        }
        .confirmationDialog("Delete \(org.name)?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete Organization", role: .destructive) { delete(org) }
        } message: {
            Text("Members lose access to its lessons. Lessons go back to their owners as Only Me.")
        }
    }

    private func header(_ org: OrgDetail, _ can: OrgPermissions) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            HStack(spacing: HOSpace.l) {
                OrgAvatar(name: org.name, size: 72)
                VStack(alignment: .leading, spacing: HOSpace.xs) {
                    Text(org.name).hoFont(.display, theme).foregroundStyle(theme.colors.ink)
                    Text(meta(org)).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                    if let role = org.role, role != .learner { RolePill(text: role.title) }
                }
            }
            if can.canTeach || can.canInvite {
                HStack(spacing: HOSpace.s) {
                    if can.canTeach {
                        Button {
                            Haptics.tap()
                            if let onTeach { onTeach(org) } else { teaching = true }
                        } label: { Label("Teach", systemImage: "video.badge.plus") }
                            .buttonStyle(HOButtonStyle(.primary))
                    }
                    if can.canInvite {
                        Button { Haptics.tap(); inviting = true } label: { Label("Invite", systemImage: "person.badge.plus") }
                            .buttonStyle(HOButtonStyle(.secondary))
                    }
                }
            }
        }
    }

    private func meta(_ org: OrgDetail) -> String {
        let m = org.members.count == 1 ? "1 member" : "\(org.members.count) members"
        let l = org.courses.count == 1 ? "1 lesson" : "\(org.courses.count) lessons"
        return "\(m), \(l)"
    }

    @ViewBuilder
    private func lessons(_ org: OrgDetail, _ can: OrgPermissions) -> some View {
        if org.courses.isEmpty {
            HOEmptyState(symbol: "film.stack", title: "No lessons yet",
                         message: can.canTeach ? "Make the first lesson for \(org.name)."
                                               : "When teachers publish here, lessons show up in this list.")
                .frame(minHeight: 240)
        } else {
            VStack(spacing: 0) {
                ForEach(Array(org.courses.enumerated()), id: \.element.id) { index, course in
                    if index > 0 { Divider().padding(.leading, HOSpace.l) }
                    NavigationLink { LessonDetailView(lessonId: course.id) } label: {
                        HORow(title: course.title, meta: lessonMeta(course), leading: { EmptyView() }) {
                            Image(systemName: "chevron.right").font(.footnote.weight(.semibold))
                                .foregroundStyle(theme.colors.ink3)
                                .accessibilityHidden(true)
                        }
                    }
                    .buttonStyle(HORowButtonStyle())
                }
            }
            .hoCard()
        }
    }

    private func lessonMeta(_ course: OrgCourse) -> String {
        var parts = [course.steps == 1 ? "1 step" : "\(course.steps) steps"]
        if let owner = course.owner?.name { parts.append("by \(owner)") }
        if course.status == "draft" { parts.append("Draft") }
        return parts.joined(separator: ", ")
    }

    private func members(_ org: OrgDetail, _ can: OrgPermissions) -> some View {
        VStack(alignment: .leading, spacing: HOSpace.l) {
            ForEach([OrgRole.admin, .teacher, .learner], id: \.self) { role in
                let group = org.members.filter { $0.role == role }.sorted { $0.name < $1.name }
                if !group.isEmpty {
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        SectionHeader(role == .admin ? "Admins" : role == .teacher ? "Teachers" : "Members")
                        VStack(spacing: 0) {
                            ForEach(Array(group.enumerated()), id: \.element.id) { index, member in
                                if index > 0 { Divider().padding(.leading, 64) }
                                memberRow(member, org: org, can: can)
                            }
                        }
                        .hoCard()
                        if role == .admin, can.canManageMembers, org.adminCount == 1 {
                            Text("Every organization needs at least one admin.")
                                .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                                .padding(.horizontal, HOSpace.xs)
                        }
                    }
                }
            }
        }
    }

    private func memberRow(_ member: OrgMember, org: OrgDetail, can: OrgPermissions) -> some View {
        let isMe = member.userId == accounts.user?.id
        let editable = can.canEdit(member, in: org, me: accounts.user)
        return HStack(spacing: HOSpace.m) {
            PersonAvatar(name: member.name)
            Text(isMe ? "\(member.name) (You)" : member.name)
                .font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
            Spacer(minLength: HOSpace.s)
            if editable {
                Menu {
                    Picker("Role", selection: Binding(get: { member.role }, set: { setRole($0, for: member, in: org) })) {
                        ForEach([OrgRole.admin, .teacher, .learner]) { Text($0.title).tag($0) }
                    }
                    Divider()
                    Button("Remove", systemImage: "person.badge.minus", role: .destructive) { removing = member }
                } label: {
                    HStack(spacing: 4) {
                        Text(member.role.title)
                        Image(systemName: "chevron.up.chevron.down").font(.caption2)
                    }
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.accentInk)
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .fixedSize()
            } else {
                Text(member.role.title).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
            }
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.s)
        .frame(minHeight: 52)
        #if os(iOS)
        .swipeActions { if editable { Button("Remove", role: .destructive) { removing = member } } }
        #endif
    }

    // MARK: - Actions

    private func load() async {
        guard preset == nil, let client = accounts.client else { return }
        do {
            org = try await client.org(orgID)
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.friendlyMessage
        }
    }

    private func setRole(_ role: OrgRole, for member: OrgMember, in org: OrgDetail) {
        guard role != member.role, let client = accounts.client else { return }
        Haptics.tap()
        Task {
            do {
                try await client.setRole(role, member: member.userId, org: org.id)
                toast = ToastItem(text: "\(member.name) is now a \(role.title).", symbol: "checkmark.circle.fill", tone: .good)
                await load()
            } catch {
                await fail(error)
            }
        }
    }

    private func remove(_ member: OrgMember, from org: OrgDetail) {
        guard let client = accounts.client else { return }
        Haptics.warning()
        Task {
            do {
                try await client.remove(member: member.userId, org: org.id)
                toast = ToastItem(text: "Removed \(member.name).", symbol: "person.badge.minus")
                await load()
            } catch {
                await fail(error)
            }
        }
    }

    private func leave(_ org: OrgDetail) {
        guard let client = accounts.client else { return }
        Haptics.warning()
        Task {
            do {
                try await client.leave(org: org.id)
                dismiss()
            } catch {
                await fail(error)
            }
        }
    }

    private func delete(_ org: OrgDetail) {
        guard let client = accounts.client else { return }
        Haptics.warning()
        Task {
            do {
                try await client.deleteOrg(org.id)
                dismiss()
            } catch {
                await fail(error)
            }
        }
    }

    /// A permission error refreshes the page so stale buttons leave (SCREENS.md 24).
    private func fail(_ error: any Error) async {
        Haptics.error()
        toast = ToastItem(text: error.friendlyMessage, symbol: "exclamationmark.triangle", tone: .caution)
        await load()
    }
}
