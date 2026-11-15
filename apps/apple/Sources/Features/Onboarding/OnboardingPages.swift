import SwiftUI

/// The shared layout of a step page: "Step 2 of 5", title, line, content, and the primary button at the
/// bottom (SCREENS.md 25.1). On a short screen (iPhone landscape) the button scrolls with the page instead of
/// staying pinned, so the content keeps the room.
struct OnboardingPage<Content: View, Actions: View>: View {
    var stepLabel: String?
    var title: String
    var line: String?
    @ViewBuilder var content: Content
    @ViewBuilder var actions: Actions
    @Environment(\.theme) private var theme

    var body: some View {
        GeometryReader { geo in
            let inline = HOLayout.isShort(geo.size.height)
            VStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: HOSpace.xl) {
                        VStack(spacing: HOSpace.s) {
                            if let stepLabel {
                                Text(stepLabel)
                                    .font(theme.fonts.footnote)
                                    .foregroundStyle(theme.colors.ink2)
                            }
                            Text(title)
                                .hoFont(.display, theme)
                                .foregroundStyle(theme.colors.ink)
                                .multilineTextAlignment(.center)
                                .accessibilityAddTraits(.isHeader)
                            if let line {
                                Text(line)
                                    .font(theme.fonts.body)
                                    .foregroundStyle(theme.colors.ink2)
                                    .multilineTextAlignment(.center)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .frame(maxWidth: 360)
                            }
                        }
                        .padding(.top, inline ? HOSpace.s : HOSpace.xxl)
                        content
                        if inline {
                            VStack(spacing: HOSpace.s) { actions }
                        }
                    }
                    .padding(.horizontal, HOSpace.l)
                    .padding(.bottom, HOSpace.l)
                    .frame(maxWidth: 520)
                    .frame(maxWidth: .infinity)
                }
                .scrollBounceBehavior(.basedOnSize)
                if !inline {
                    VStack(spacing: HOSpace.s) { actions }
                        .padding(.horizontal, HOSpace.l)
                        .padding(.bottom, HOSpace.l)
                        .frame(maxWidth: 520)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

// MARK: - Connect (25.3)

struct ConnectPage: View {
    let flow: OnboardingModel
    @Environment(AppModel.self) private var app
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pairing = false
    @State private var startWithAddress = false
    @State private var askNetwork = false
    @State private var pendingAddress = false
    @State private var appeared = false

    var body: some View {
        // Fills the screen when it fits; scrolls on a short screen (iPhone landscape) instead of clipping.
        GeometryReader { geo in
            ScrollView {
                page(short: HOLayout.isShort(geo.size.height))
                    .frame(minHeight: geo.size.height)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
        .onAppear {
            withAnimation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion).delay(0.05)) { appeared = true }
        }
        .sheet(isPresented: $askNetwork) {
            PermissionCard(permission: .localNetwork) { allowed in
                askNetwork = false
                if allowed { present(address: pendingAddress) }
            }
            .presentationDetents([.medium])
        }
        #if os(iOS)
        .fullScreenCover(isPresented: $pairing, onDismiss: { flow.connector.reset() }) { cover }
        #else
        .sheet(isPresented: $pairing, onDismiss: { flow.connector.reset() }) { cover.frame(width: 520, height: 600) }
        #endif
        .onChange(of: flow.progress.connected) { _, connected in
            if connected { pairing = false }
        }
    }

    private func page(short: Bool) -> some View {
        VStack(spacing: 0) {
            Spacer(minLength: short ? HOSpace.s : HOSpace.xxl)
            VStack(spacing: short ? HOSpace.m : HOSpace.l) {
                HubMark(size: short ? 56 : 88)
                    .scaleEffect(appeared || reduceMotion ? 1 : 0.9)
                    .opacity(appeared ? 1 : 0)
                VStack(spacing: HOSpace.s) {
                    if let label = flow.progress.stepLabel {
                        Text(label).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                    }
                    Text("Connect to your hub")
                        .hoFont(.largeTitle, theme)
                        .foregroundStyle(theme.colors.ink)
                        .multilineTextAlignment(.center)
                    Text("The hub is the HandOver app running on a laptop near you. It keeps your lessons.")
                        .font(theme.fonts.body)
                        .foregroundStyle(theme.colors.ink2)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 360)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .opacity(appeared ? 1 : 0)
            }
            .padding(.horizontal, HOSpace.l)
            Spacer(minLength: short ? HOSpace.l : HOSpace.xxl)
            VStack(spacing: HOSpace.s) {
                // The hub shows no QR code of its own (run_server.sh prints the address), so typing comes first.
                Button { open(address: true) } label: { Text("Enter Address") }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .keyboardShortcut(.defaultAction)
                if CameraCapture.isAvailable {
                    Button { open(address: false) } label: { Label("Scan a Code", systemImage: "qrcode.viewfinder") }
                        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                }
                Text("No hub yet? Start HandOver on a laptop on the same Wi-Fi, then tap Enter Address.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, HOSpace.xs)
            }
            .padding(.horizontal, HOSpace.l)
            .padding(.bottom, HOSpace.l)
            .frame(maxWidth: 520)
            .opacity(appeared ? 1 : 0)
            .offset(y: appeared || reduceMotion ? 0 : 12)
        }
        .frame(maxWidth: .infinity)
    }

    private var cover: some View {
        HubPairingCover(connector: flow.connector,
                        test: { hub in flow.test(hub, app: app, accounts: accounts) },
                        onClose: { pairing = false },
                        startWithAddress: startWithAddress)
            .environment(app)
            .environment(accounts)
    }

    /// Local Network card first, once, before the first connect attempt (iOS).
    private func open(address: Bool) {
        Haptics.tap()
        if AppPermission.localNetwork.needsCard, AppPermission.localNetwork.status == .notAsked {
            pendingAddress = address
            askNetwork = true
        } else {
            present(address: address)
        }
    }

    private func present(address: Bool) {
        startWithAddress = address
        pairing = true
    }
}

/// The app mark until there is an icon asset: hands passing a play triangle, from SF Symbols, on the accent.
struct HubMark: View {
    var size: CGFloat = 64
    @Environment(\.theme) private var theme

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.2237, style: .continuous)
                .fill(theme.colors.accent)
            Image(systemName: "hand.raised.fingers.spread.fill")
                .font(.system(size: size * 0.46, weight: .regular))
                .foregroundStyle(theme.colors.onAccent)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

// MARK: - Role (25.7)

struct RolePage: View {
    let flow: OnboardingModel
    @Environment(\.theme) private var theme
    @State private var choice: LearnerRole?

    var body: some View {
        OnboardingPage(stepLabel: flow.progress.stepLabel, title: "What brings you here?",
                       line: "This only changes what Home shows first. You can do both anytime.") {
            VStack(spacing: HOSpace.m) {
                RoleCard(symbol: "graduationcap", title: "I Want to Learn",
                         line: "Lessons to take and where you left off.", selected: choice == .learn) { pick(.learn) }
                RoleCard(symbol: "video.badge.plus", title: "I Want to Teach",
                         line: "Record a task and turn it into a lesson.", selected: choice == .teach) { pick(.teach) }
                Button { pick(.both) } label: {
                    HStack {
                        Text("Both").font(theme.fonts.bodyMedium)
                        Spacer()
                        Image(systemName: choice == .both ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .foregroundStyle(choice == .both ? theme.colors.accentInk : theme.colors.ink3)
                    }
                    .foregroundStyle(choice == .both ? theme.colors.accentInk : theme.colors.ink)
                    .padding(.horizontal, HOSpace.l)
                    .frame(minHeight: HOSize.control)
                    .background(choice == .both ? theme.colors.accentSoft : .clear,
                                in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(choice == .both ? .isSelected : [])
            }
            .hoAnimation(HOMotion.snappy, value: choice)
        } actions: {
            Button("Continue") {
                Haptics.tap()
                if let choice { flow.choose(role: choice) }
                flow.complete(.role)
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .keyboardShortcut(.defaultAction)
            .disabled(choice == nil)
        }
        .onAppear { choice = flow.progress.role }
    }

    private func pick(_ role: LearnerRole) {
        Haptics.tap()
        choice = role
        flow.choose(role: role)
    }
}

private struct RoleCard: View {
    let symbol: String
    let title: String
    let line: String
    let selected: Bool
    let action: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: HOSpace.m) {
                SymbolTile(symbol: symbol, side: 44)
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text(title).font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                    Text(line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(selected ? theme.colors.accentInk : theme.colors.ink3)
            }
            .padding(HOSpace.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(selected ? theme.colors.accentSoft : theme.colors.raised,
                        in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                .strokeBorder(selected ? theme.colors.accent : theme.colors.line, lineWidth: selected ? 1.5 : HOLine.width))
            .contentShape(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isSelected, .isButton] : .isButton)
    }
}
