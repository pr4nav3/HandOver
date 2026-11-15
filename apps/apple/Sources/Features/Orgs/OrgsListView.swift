import SwiftUI

/// My organizations (SCREENS.md 22.1): pending invitations, then my orgs by name. Join with a Code always;
/// New Organization for anyone signed in (the hub lets every signed-in person create one).
struct OrgsListView: View {
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @State private var mine: MyOrgs?
    @State private var error: String?
    @State private var joining = false
    @State private var creating = false
    @State private var path: [String] = []
    @State private var toast: ToastItem?
    @State private var signingIn = false
    @State private var busyInvite: String?

    /// Fixed data for previews and snapshots.
    var preset: MyOrgs?

    var body: some View {
        content
            .hoPaperBackground()
            .navigationTitle("Organizations")
            .navigationDestination(for: String.self) { OrgPageView(orgID: $0) }
            .toolbar {
                if accounts.isSignedIn {
                    ToolbarItemGroup(placement: .primaryAction) {
                        Button { Haptics.tap(); joining = true } label: { Label("Join with a Code", systemImage: "qrcode.viewfinder") }
                        Button { Haptics.tap(); creating = true } label: { Label("New Organization", systemImage: "plus") }
                    }
                }
            }
            .task(id: accounts.user?.id) { await load() }
            .refreshable { await load() }
            .sheet(isPresented: $joining) {
                JoinOrgSheet { org in
                    Task { await load() }
                    toast = ToastItem(text: "You joined \(org.name).", symbol: "checkmark.circle.fill", tone: .good)
                }
            }
            .sheet(isPresented: $creating) {
                CreateOrgSheet { org in
                    Task { await load() }
                    toast = ToastItem(text: "Created \(org.name).", symbol: "checkmark.circle.fill", tone: .good)
                }
            }
            .sheet(isPresented: $signingIn) { SignInSheet() }
            .hoToast($toast)
    }

    @ViewBuilder
    private var content: some View {
        let data = preset ?? mine
        if !accounts.support.hasAccounts && preset == nil {
            HOEmptyState(symbol: "person.3", title: "No organizations on this hub",
                         message: "This hub has no accounts, so everyone shares the same lessons on Home.")
        } else if !accounts.isSignedIn && preset == nil {
            HOEmptyState(symbol: "person.3", title: "Sign in to see your organizations",
                         message: "Organizations group people and lessons, like a team or a class.") {
                Button("Sign In") { Haptics.tap(); signingIn = true }.buttonStyle(HOButtonStyle(.primary))
            }
        } else if let data {
            if data.orgs.isEmpty && data.invites.isEmpty {
                HOEmptyState(symbol: "person.3", title: "No organizations yet",
                             message: "Organizations group people and lessons, like a team or a class. Got an invite code? Join here.") {
                    VStack(spacing: HOSpace.s) {
                        Button("Join with a Code") { Haptics.tap(); joining = true }
                            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                        Button("Create Organization") { Haptics.tap(); creating = true }
                            .buttonStyle(HOButtonStyle(.quiet, size: .large, fullWidth: true))
                    }
                    .frame(maxWidth: 280)
                }
            } else {
                list(data)
            }
        } else if let error {
            HOEmptyState(symbol: "wifi.exclamationmark", title: "Cannot load organizations", message: error, tone: .caution) {
                Button("Try Again") { Task { await load() } }.buttonStyle(HOButtonStyle(.primary))
            }
        } else {
            HOEmptyState(title: "Loading", loading: true)
        }
    }

    private func list(_ data: MyOrgs) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                if !data.invites.isEmpty {
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        SectionHeader("Invitations")
                        VStack(spacing: 0) {
                            ForEach(data.invites) { invite in invitationRow(invite) }
                        }
                        .hoCard()
                    }
                }
                if !data.orgs.isEmpty {
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        SectionHeader("Your Organizations")
                        VStack(spacing: 0) {
                            ForEach(Array(data.orgs.enumerated()), id: \.element.id) { index, org in
                                if index > 0 { Divider().padding(.leading, 72) }
                                NavigationLink(value: org.id) { OrgRow(org: org) }
                                    .buttonStyle(HORowButtonStyle())
                            }
                        }
                        .hoCard()
                    }
                }
            }
            .padding(HOSpace.l)
            .frame(maxWidth: 720)
            .frame(maxWidth: .infinity)
        }
    }

    private func invitationRow(_ invite: OrgInvite) -> some View {
        HStack(alignment: .top, spacing: HOSpace.m) {
            OrgAvatar(name: invite.org?.name ?? "?")
            VStack(alignment: .leading, spacing: HOSpace.s) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(invite.org?.name ?? "Organization").font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
                    Text("Invited by \(invite.createdBy ?? "an admin"), joins as \(invite.role.title)")
                        .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                }
                HStack(spacing: HOSpace.s) {
                    if busyInvite == invite.id {
                        ProgressView()
                    } else {
                        Button("Join") { respond(invite, accept: true) }.buttonStyle(HOButtonStyle(.primary, size: .small))
                        Button("Decline") { respond(invite, accept: false) }.buttonStyle(HOButtonStyle(.quiet, size: .small))
                    }
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
    }

    private func respond(_ invite: OrgInvite, accept: Bool) {
        guard let client = accounts.client, let org = invite.org else { return }
        Haptics.tap()
        busyInvite = invite.id
        Task {
            defer { busyInvite = nil }
            do {
                if accept {
                    _ = try await client.accept(invite: invite.id)
                    Haptics.success()
                    toast = ToastItem(text: "You joined \(org.name).", symbol: "checkmark.circle.fill", tone: .good)
                } else {
                    try await client.deleteInvite(org: org.id, invite: invite.id)
                }
                await load()
            } catch {
                Haptics.error()
                toast = ToastItem(text: error.friendlyMessage, symbol: "exclamationmark.triangle", tone: .caution)
            }
        }
    }

    private func load() async {
        guard preset == nil, let client = accounts.client, accounts.isSignedIn else { return }
        do {
            mine = try await client.myOrgs()
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.friendlyMessage
        }
    }
}

/// New organization (SCREENS.md 22.2). The hub takes a name of 1 to 60 characters.
struct CreateOrgSheet: View {
    var onCreated: (OrgDetail) -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @State private var name = ""
    @State private var error: String?
    @State private var working = false

    private var trimmed: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: HOSpace.xl) {
                    OrgAvatar(name: trimmed.isEmpty ? "?" : trimmed, size: 72)
                        .hoAnimation(HOMotion.snappy, value: trimmed)
                    HOField(label: "Name", text: $name, placeholder: "Bike Shop Crew",
                            footer: "You become the admin. You can invite people next.", error: error)
                        .onSubmit(create)
                    Button(action: create) {
                        if working { ProgressView() } else { Text("Create") }
                    }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .keyboardShortcut(.defaultAction)
                    .disabled(trimmed.isEmpty || trimmed.count > 60 || working)
                }
                .padding(HOSpace.l)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
            }
            .hoPaperBackground()
            .navigationTitle("New Organization")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
        .presentationDetents([.large])
    }

    private func create() {
        guard !trimmed.isEmpty, !working, let client = accounts.client else { return }
        Haptics.tap()
        working = true
        Task {
            defer { working = false }
            do {
                let org = try await client.createOrg(name: trimmed)
                Haptics.success()
                onCreated(org)
                dismiss()
            } catch {
                Haptics.error()
                self.error = error.friendlyMessage
            }
        }
    }
}
