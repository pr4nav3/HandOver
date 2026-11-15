import SwiftUI

extension View {
    /// The app's one hook for setup: puts the shared `AccountStore` in the environment (following the app's
    /// hub), shows onboarding on first launch (a full-screen cover on iPhone and iPad, the window's content on
    /// the Mac), and opens `handover://join` invite links. Put it on the root view, inside `.environment(model)`:
    ///
    ///     RootView().handOverSetup().environment(model)
    func handOverSetup() -> some View {
        modifier(SetupGate())
    }
}

private struct SetupGate: ViewModifier {
    @Environment(AppModel.self) private var model
    @State private var flow = OnboardingModel()
    @State private var joinCode: String?
    @State private var joinToast: ToastItem?

    private var accounts: AccountStore { AccountStore.shared }

    /// Never in demo runs (`-demo`, previews): those must not touch saved state.
    private var showsOnboarding: Bool {
        !model.isPreview && !ProcessInfo.processInfo.arguments.contains("-demo") && flow.step != .done
    }

    func body(content: Content) -> some View {
        AccountScope {
            Group {
                #if os(iOS)
                content
                    .fullScreenCover(isPresented: Binding(get: { showsOnboarding }, set: { _ in })) {
                        cover
                    }
                #else
                if showsOnboarding {
                    cover.frame(minWidth: 720, minHeight: 560)
                } else {
                    content
                }
                #endif
            }
            .onOpenURL { url in
                guard InviteCode.isJoinLink(url), let invite = InviteCode(parsing: url.absoluteString) else { return }
                if let hub = invite.hub, hub != model.hub {
                    model.connect(to: hub)
                    accounts.follow(hub)
                }
                joinCode = invite.code
            }
            .sheet(isPresented: Binding(get: { joinCode != nil && !showsOnboarding }, set: { if !$0 { joinCode = nil } })) {
                JoinOrgSheet(initialCode: joinCode) { org in
                    joinToast = ToastItem(text: "You joined \(org.name).", symbol: "checkmark.circle.fill", tone: .good)
                }
                .environment(model)
                .environment(accounts)
            }
            .hoToast($joinToast)
        }
    }

    /// Default theme until the theme step, then the stored one so the choice shows for real (SCREENS.md 25.9).
    private var cover: some View {
        OnboardingView(flow: flow)
            .environment(model)
            .environment(accounts)
            .handOverTheme(flow.step == .theme ? nil : .system)
            #if os(iOS)
            .interactiveDismissDisabled()
            #endif
    }
}
