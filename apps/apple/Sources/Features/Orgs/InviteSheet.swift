import SwiftUI

/// Invite people (SCREENS.md 22.5), for admins. New codes show once with their QR and Share; the hub keeps
/// only a hash, so older codes are listed by what they do, with Revoke.
struct InviteSheet: View {
    let org: OrgDetail
    /// A code made before the sheet opened (snapshots).
    var presetCreated: OrgInvite?

    @Environment(\.dismiss) private var dismiss
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @State private var mode = Mode.code
    @State private var role = OrgRole.learner
    @State private var expiry = InviteExpiry.week
    @State private var uses = InviteUses.unlimited
    @State private var created: OrgInvite?
    @State private var invites: [OrgInvite] = []
    @State private var username = ""
    @State private var error: String?
    @State private var working = false
    @State private var revoking: OrgInvite?

    enum Mode: String, CaseIterable { case code = "Invite Code", username = "By Username" }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: HOSpace.xl) {
                    Picker("Invite by", selection: $mode) {
                        ForEach(Mode.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    switch mode {
                    case .code: codeSection
                    case .username: usernameSection
                    }
                }
                .padding(HOSpace.l)
                .frame(maxWidth: 600)
                .frame(maxWidth: .infinity)
                .hoAnimation(HOMotion.panel, value: created)
            }
            .hoPaperBackground()
            .navigationTitle("Invite to \(org.name)")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .confirmationDialog("Revoke this code?", isPresented: Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } }),
                                titleVisibility: .visible) {
                Button("Revoke Code", role: .destructive) { if let inv = revoking { revoke(inv) } }
            } message: {
                Text("People who already joined stay in the org. The code stops working now.")
            }
        }
        .presentationDetents([.large])
        .onAppear {
            invites = org.invites ?? []
            if created == nil { created = presetCreated }
        }
    }

    // MARK: - Codes

    private var codeSection: some View {
        VStack(alignment: .leading, spacing: HOSpace.xl) {
            if let created, let code = created.code {
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    SectionHeader("New Code")
                    InviteCodeCard(code: code, invite: created, orgName: org.name, hub: accounts.hub) {
                        revoking = created
                    }
                    Text("Copy or share it now. For safety, the hub does not show a code again.")
                        .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                        .padding(.horizontal, HOSpace.xs)
                }
                .transition(.opacity.combined(with: .scale(scale: 0.98)))
            }
            VStack(alignment: .leading, spacing: HOSpace.s) {
                SectionHeader(created == nil ? "New Code" : "Another Code")
                VStack(spacing: 0) {
                    menuRow("Joins as") {
                        Picker("Joins as", selection: $role) {
                            ForEach([OrgRole.learner, .teacher, .admin]) { Text($0.title).tag($0) }
                        }
                    }
                    Divider().padding(.leading, HOSpace.l)
                    menuRow("Expires") {
                        Picker("Expires", selection: $expiry) {
                            ForEach(InviteExpiry.allCases) { Text($0.title).tag($0) }
                        }
                    }
                    Divider().padding(.leading, HOSpace.l)
                    menuRow("Uses") {
                        Picker("Uses", selection: $uses) {
                            ForEach(InviteUses.allCases) { Text($0.title).tag($0) }
                        }
                    }
                }
                .hoCard()
                if let error, mode == .code {
                    Text(error).font(theme.fonts.footnote).foregroundStyle(theme.colors.bad).padding(.horizontal, HOSpace.xs)
                }
                Button(action: createCode) {
                    if working { ProgressView() } else { Text("Create Code") }
                }
                .buttonStyle(HOButtonStyle(created == nil ? .primary : .secondary, size: .large, fullWidth: true))
                .disabled(working)
                .padding(.top, HOSpace.xs)
            }
            let active = invites.filter { $0.isCode && $0.id != created?.id }
            if !active.isEmpty {
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    SectionHeader("Active Codes")
                    VStack(spacing: 0) {
                        ForEach(Array(active.enumerated()), id: \.element.id) { index, invite in
                            if index > 0 { Divider().padding(.leading, HOSpace.l) }
                            HStack(alignment: .top) {
                                InviteMeta(invite: invite)
                                Spacer()
                                Button("Revoke", role: .destructive) { revoking = invite }
                                    .buttonStyle(HOButtonStyle(.quiet, size: .small))
                            }
                            .padding(HOSpace.l)
                        }
                    }
                    .hoCard()
                }
            }
        }
    }

    private func menuRow<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        HStack {
            Text(title).font(theme.fonts.body).foregroundStyle(theme.colors.ink)
            Spacer()
            content().labelsHidden().pickerStyle(.menu).fixedSize()
        }
        .padding(.horizontal, HOSpace.l)
        .frame(minHeight: HOSize.control)
    }

    // MARK: - By username

    private var usernameSection: some View {
        VStack(alignment: .leading, spacing: HOSpace.xl) {
            VStack(alignment: .leading, spacing: HOSpace.m) {
                HOField(label: "Name", text: $username, placeholder: "Sam Rivera",
                        footer: "The name they sign in with on this hub.", error: mode == .username ? error : nil)
                    .autocorrectionDisabled()
                    .onSubmit(inviteUser)
                VStack(spacing: 0) {
                    menuRow("Joins as") {
                        Picker("Joins as", selection: $role) {
                            ForEach([OrgRole.learner, .teacher, .admin]) { Text($0.title).tag($0) }
                        }
                    }
                }
                .hoCard()
                Button(action: inviteUser) {
                    if working { ProgressView() } else { Text("Send Invite") }
                }
                .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                .disabled(username.trimmingCharacters(in: .whitespaces).isEmpty || working)
            }
            let pending = invites.filter { !$0.isCode }
            if !pending.isEmpty {
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    SectionHeader("Pending")
                    VStack(spacing: 0) {
                        ForEach(Array(pending.enumerated()), id: \.element.id) { index, invite in
                            if index > 0 { Divider().padding(.leading, 64) }
                            HStack(spacing: HOSpace.m) {
                                PersonAvatar(name: invite.user?.name ?? "?")
                                Text("Invited \(invite.user?.name ?? "someone") as \(invite.role.title)")
                                    .font(theme.fonts.body).foregroundStyle(theme.colors.ink)
                                Spacer()
                                Button("Cancel Invite") { revoke(invite) }
                                    .buttonStyle(HOButtonStyle(.quiet, size: .small))
                            }
                            .padding(.horizontal, HOSpace.l)
                            .padding(.vertical, HOSpace.s)
                        }
                    }
                    .hoCard()
                }
            }
        }
    }

    // MARK: - Actions

    private func createCode() {
        guard let client = accounts.client else { return }
        Haptics.tap()
        working = true
        error = nil
        Task {
            defer { working = false }
            do {
                let invite = try await client.createInviteCode(org: org.id, role: role, expiresDays: expiry.rawValue,
                                                               maxUses: uses.maxUses)
                Haptics.success()
                created = invite
                invites.append(invite)
            } catch {
                Haptics.error()
                self.error = error.friendlyMessage
            }
        }
    }

    private func inviteUser() {
        let name = username.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty, let client = accounts.client else { return }
        Haptics.tap()
        working = true
        error = nil
        Task {
            defer { working = false }
            do {
                let invite = try await client.invite(username: name, to: org.id, role: role)
                Haptics.success()
                invites.removeAll { $0.user?.id == invite.user?.id && !$0.isCode }
                invites.append(invite)
                username = ""
            } catch let failure as HubError {
                Haptics.error()
                switch failure.status {
                case 404: error = "No one on this hub has that name."
                case 409: error = "\(name) is already in \(org.name)."
                default: error = failure.friendly
                }
            } catch {
                Haptics.error()
                self.error = error.friendlyMessage
            }
        }
    }

    private func revoke(_ invite: OrgInvite) {
        guard let client = accounts.client else { return }
        Haptics.warning()
        Task {
            do {
                try await client.deleteInvite(org: org.id, invite: invite.id)
                invites.removeAll { $0.id == invite.id }
                if created?.id == invite.id { created = nil }
            } catch {
                Haptics.error()
                self.error = error.friendlyMessage
            }
        }
    }
}
