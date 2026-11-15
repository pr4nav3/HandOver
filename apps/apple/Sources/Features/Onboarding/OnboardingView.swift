import SwiftUI

/// The first-launch flow (SCREENS.md 25): welcome pages, connect, accounts when the hub has them, the role
/// choice and the theme. Progress is saved after every step; quitting resumes where it stopped.
struct OnboardingView: View {
    let flow: OnboardingModel
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.horizontalSizeClass) private var sizeClass

    var body: some View {
        let step = flow.step
        ZStack {
            page(step)
                .id(step)
                .transition(transition)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .safeAreaInset(edge: .top, spacing: 0) { topBar(step) }
        .modifier(OnboardingFrame())
        .animation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion), value: step)
        .task { await SampleLesson.prewarm() }
    }

    private var transition: AnyTransition {
        reduceMotion ? .opacity : .asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity),
                                              removal: .move(edge: .leading).combined(with: .opacity))
    }

    @ViewBuilder
    private func page(_ step: OnboardingStep) -> some View {
        switch step {
        case .welcome:
            WelcomePages(onFinish: { flow.finishWelcome() }, onSkip: { flow.finishWelcome() })
        case .connect:
            ConnectPage(flow: flow)
        case .ownerSetup:
            OnboardingPage(stepLabel: flow.progress.stepLabel, title: "Set up this hub",
                           line: "You are the first person here, so you become the hub owner. Owners manage accounts and organizations.") {
                OwnerSetupForm(hubName: hubName, onDone: {
                    Task { await flow.signedIn(madeAccount: true, accounts: accounts) }
                }, onTaken: { flow.ownerTaken() })
            } actions: {
                EmptyView()
            }
        case .account:
            OnboardingPage(stepLabel: flow.progress.stepLabel, title: "Sign in",
                           line: "Your account lives on this hub. There is no HandOver cloud account.") {
                SignInForm(showsFooter: false) {
                    Task { await flow.signedIn(madeAccount: false, accounts: accounts) }
                }
                Text("No account yet? Ask the person who runs this hub to add you.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
            } actions: {
                EmptyView()
            }
        case .profile:
            OnboardingPage(stepLabel: flow.progress.stepLabel, title: "Add a picture",
                           line: "People see it next to your name. Initials work fine.") {
                AvatarEditor(name: accounts.user?.name ?? "")
                    .padding(.top, HOSpace.l)
            } actions: {
                Button("Continue") { Haptics.tap(); flow.complete(.profile) }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .keyboardShortcut(.defaultAction)
            }
        case .joinOrg:
            JoinOrgPage(stepLabel: flow.progress.stepLabel) { flow.complete(.joinOrg) }
        case .role:
            RolePage(flow: flow)
        case .theme:
            ThemePage(flow: flow)
        case .done:
            Color.clear
        }
    }

    private var hubName: String { "this hub" }

    private func topBar(_ step: OnboardingStep) -> some View {
        HStack {
            if flow.progress.backTarget != nil, step != .welcome {
                Button { Haptics.tap(); flow.back() } label: {
                    Image(systemName: "chevron.left").font(.body.weight(.semibold))
                }
                .buttonStyle(HOIconButtonStyle())
                .accessibilityLabel("Back")
            }
            Spacer()
            if let skip = skipTitle(step) {
                Button(skip) {
                    Haptics.tap()
                    switch step {
                    case .welcome: flow.finishWelcome()
                    case .theme: flow.complete(.theme, skipped: true)
                    default: flow.complete(step, skipped: true)
                    }
                }
                .buttonStyle(HOButtonStyle(.quiet, size: .small))
            }
        }
        .padding(.horizontal, HOSpace.s)
        .frame(height: 52)
    }

    private func skipTitle(_ step: OnboardingStep) -> String? {
        switch step {
        case .welcome: "Skip"
        case .theme: "Keep Default"
        case .account: flow.progress.signInOptional ? "Not Now" : nil
        case .profile, .joinOrg, .role: "Not Now"
        case .connect, .ownerSetup, .done: nil
        }
    }
}

/// iPhone: full screen. iPad: a centered 600 by 720 card on paper. Mac: the window content. A large iPhone on its
/// side reports a regular width but a compact height; it stays full screen, since the card would not fit.
private struct OnboardingFrame: ViewModifier {
    @Environment(\.horizontalSizeClass) private var sizeClass
    #if os(iOS)
    @Environment(\.verticalSizeClass) private var verticalSizeClass
    #endif
    @Environment(\.theme) private var theme

    func body(content: Content) -> some View {
        #if os(iOS)
        if sizeClass == .regular && verticalSizeClass == .regular {
            content
                .frame(width: 600, height: 720)
                .background(theme.colors.paper, in: RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous)
                    .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(theme.colors.well.ignoresSafeArea())
        } else {
            content.hoPaperBackground()
        }
        #else
        content.hoPaperBackground()
        #endif
    }
}
