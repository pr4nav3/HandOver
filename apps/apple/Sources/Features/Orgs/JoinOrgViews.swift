import SwiftUI

/// Type or scan an invite code and join (SCREENS.md 22.3). The hub has no preview of a code before joining,
/// so joining happens on Join and the result card shows what the hub answered.
struct JoinCodeForm: View {
    var onJoined: (OrgSummary) -> Void
    @Environment(AccountStore.self) private var accounts
    @Environment(AppModel.self) private var app
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var text = ""
    @State private var error: String?
    @State private var shake = 0.0
    @State private var working = false
    @State private var scanning = false
    @State private var otherHub: InviteCode?

    var initialCode: String?

    private var parsed: InviteCode? { InviteCode(parsing: text) }

    var body: some View {
        VStack(spacing: HOSpace.l) {
            HOField(label: "Invite code", text: $text, placeholder: "K7qM 2xPA 9bc_ d-Ef", monospaced: true,
                    error: error, shake: shake)
                .autocorrectionDisabled()
                #if os(iOS)
                .textInputAutocapitalization(.never)
                #endif
                .onSubmit(join)
            Button(action: join) {
                if working { ProgressView() } else { Text("Join") }
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .keyboardShortcut(.defaultAction)
            .disabled(parsed == nil || working)
            if CameraCapture.isAvailable {
                Button { Haptics.tap(); scanning = true } label: { Label("Scan QR Code", systemImage: "qrcode.viewfinder") }
                    .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
            }
        }
        .hoAnimation(HOMotion.snappy, value: error)
        .onAppear { if let initialCode { text = initialCode } }
        .onChange(of: text) { _, _ in error = nil }
        #if os(iOS)
        .fullScreenCover(isPresented: $scanning) { scanner }
        #else
        .sheet(isPresented: $scanning) { scanner.frame(width: 520, height: 600) }
        #endif
        .confirmationDialog("Join on \(otherHub?.hub?.host ?? "another hub")?",
                            isPresented: Binding(get: { otherHub != nil }, set: { if !$0 { otherHub = nil } }),
                            titleVisibility: .visible) {
            Button("Connect and Join") {
                if let invite = otherHub, let hub = invite.hub {
                    app.connect(to: hub)
                    accounts.follow(hub)
                    text = invite.code
                }
            }
        } message: {
            Text("This code is for a different hub. HandOver connects to it first; you may need to sign in there.")
        }
    }

    private var scanner: some View {
        QRScannerScreen(title: "Scan the invite code",
                        hint: "Ask an admin to show the code from the organization's page.",
                        handle: { scanned in
                            guard let code = InviteCode(parsing: scanned) else { return "That is not an invite code." }
                            Task {
                                try? await Task.sleep(for: .milliseconds(400))
                                scanning = false
                                if let hub = code.hub, hub != app.hub {
                                    otherHub = code
                                } else {
                                    text = code.code
                                    join()
                                }
                            }
                            return nil
                        },
                        onCancel: { scanning = false })
    }

    private func join() {
        guard let code = parsed, !working, let client = accounts.client else { return }
        if let hub = code.hub, hub != app.hub {
            otherHub = code
            return
        }
        Haptics.tap()
        working = true
        Task {
            defer { working = false }
            do {
                let org = try await client.join(code: code.code)
                Haptics.success()
                onJoined(org)
            } catch {
                Haptics.error()
                if !reduceMotion { withAnimation(.default) { shake += 1 } }
                self.error = Self.words(for: error)
            }
        }
    }

    static func words(for error: any Error) -> String {
        guard let hub = error as? HubError, case .http(let status, _) = hub else { return error.friendlyMessage }
        switch status {
        case 404: return "That code does not work. Check it with the admin."
        case 409: return "You are already in this organization."
        case 429: return "Too many tries. Wait a minute, then try again."
        case 401: return "Sign in first, then join."
        default: return hub.friendly
        }
    }
}

/// The welcome card after joining.
struct JoinedCard: View {
    let org: OrgSummary
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(spacing: HOSpace.m) {
            OrgAvatar(name: org.name, size: 72)
            Text(org.name).hoFont(.display, theme).foregroundStyle(theme.colors.ink).multilineTextAlignment(.center)
            Text(org.members == 1 ? "1 member" : "\(org.members) members")
                .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
            Text("You joined as \(org.role?.title ?? OrgRole.learner.title).")
                .font(theme.fonts.body).foregroundStyle(theme.colors.ink)
        }
        .padding(HOSpace.xl)
        .frame(maxWidth: .infinity)
        .hoCard()
        .transition(.scale(scale: 0.96).combined(with: .opacity))
    }
}

/// Join with a code, as a sheet from Organizations.
struct JoinOrgSheet: View {
    var initialCode: String?
    var onJoined: (OrgSummary) -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.theme) private var theme
    @State private var joined: OrgSummary?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: HOSpace.xl) {
                    if let joined {
                        JoinedCard(org: joined)
                        Button("Open \(joined.name)") { onJoined(joined); dismiss() }
                            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    } else {
                        Text("If an admin gave you a code, enter it or scan it.")
                            .font(theme.fonts.body).foregroundStyle(theme.colors.ink2)
                            .multilineTextAlignment(.center)
                        JoinCodeForm(onJoined: { org in withAnimation(HOMotion.panel) { joined = org } },
                                     initialCode: initialCode)
                    }
                }
                .padding(HOSpace.l)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
            }
            .hoPaperBackground()
            .navigationTitle("Join with a Code")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
        .presentationDetents([.large])
    }
}

/// Onboarding's Join your team step (SCREENS.md 25.6).
struct JoinOrgPage: View {
    var stepLabel: String?
    var onDone: () -> Void
    @State private var joined: OrgSummary?

    var body: some View {
        OnboardingPage(stepLabel: stepLabel, title: "Join your team",
                       line: "If someone gave you an invite code, enter it or scan it. You can do this later from Organizations.") {
            if let joined {
                JoinedCard(org: joined)
            } else {
                JoinCodeForm { org in withAnimation(HOMotion.layout) { joined = org } }
            }
        } actions: {
            if joined != nil {
                Button("Continue") { Haptics.tap(); onDone() }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .keyboardShortcut(.defaultAction)
            }
        }
    }
}
