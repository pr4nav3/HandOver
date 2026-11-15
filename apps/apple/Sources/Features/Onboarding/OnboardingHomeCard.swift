import SwiftUI

/// The card Home shows once onboarding is done (SCREENS.md 25.10 and 25.11): what to do first, from the role the
/// person picked, then any optional step they skipped. "Hide" removes it for good. It reads the saved
/// onboarding progress, so it appears the moment the last onboarding page closes.
///
/// Home puts it at the top of its content:
///
///     OnboardingHomeCard(onTeach: canTeach ? { flow.section = .teach } : nil)
///
/// Pass `onTeach` only when this person can teach, so the card never points at a tab they do not have.
struct OnboardingHomeCard: View {
    var onTeach: (() -> Void)?

    @AppStorage(OnboardingStore.key) private var saved: Data?

    var body: some View {
        if let progress, progress.finished, progress.homeCard == true {
            AccountScope { OnboardingHomeCardContent(progress: progress, onTeach: onTeach, onHide: hide) }
                .transition(.opacity)
        }
    }

    private var progress: OnboardingProgress? {
        saved.flatMap { try? JSONDecoder().decode(OnboardingProgress.self, from: $0) }
    }

    private func hide() {
        Haptics.tap()
        let store = OnboardingStore()
        var p = store.load()
        p.hideHomeCard()
        store.save(p)
    }
}

/// What the card says. Separate so snapshots can draw it from a fixed progress.
struct OnboardingHomeCardContent: View {
    var progress: OnboardingProgress
    var onTeach: (() -> Void)?
    var onHide: () -> Void

    @Environment(\.theme) private var theme
    @State private var sheet: OnboardingStep?

    /// Teach first only when they picked it and can teach (SCREENS.md 25.7).
    private var teachFirst: Bool { progress.role == .teach && onTeach != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            HStack(alignment: .top, spacing: HOSpace.m) {
                SymbolTile(symbol: teachFirst ? "video.badge.plus" : "play.rectangle", side: 44)
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text(teachFirst ? "Make your first lesson" : "Pick a lesson to start")
                        .font(theme.fonts.headline)
                        .foregroundStyle(theme.colors.ink)
                    Text(teachFirst
                         ? "Record a task while you talk through it. HandOver turns it into steps you can check."
                         : Self.learnLine)
                        .font(theme.fonts.callout)
                        .foregroundStyle(theme.colors.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            if teachFirst, let onTeach {
                Button("Open Teach") { Haptics.tap(); onTeach() }
                    .buttonStyle(HOButtonStyle(.secondary, fullWidth: true))
            }
            if !progress.unfinished.isEmpty {
                Divider().overlay(theme.colors.line)
                Text("Finish setting up").sectionHeaderStyle(theme)
                VStack(spacing: 0) {
                    ForEach(progress.unfinished, id: \.self) { step in
                        Button { Haptics.tap(); sheet = step } label: { row(step) }
                            .buttonStyle(.plain)
                    }
                }
            }
            HStack {
                Spacer()
                Button("Hide", action: onHide).buttonStyle(HOButtonStyle(.quiet, size: .small))
            }
        }
        .raisedCard()
        .sheet(item: $sheet) { step in sheetContent(step) }
    }

    private func row(_ step: OnboardingStep) -> some View {
        HStack(spacing: HOSpace.m) {
            SymbolTile(symbol: Self.symbol(step), tone: .neutral, side: 30)
            Text(Self.title(step)).font(theme.fonts.body).foregroundStyle(theme.colors.ink)
            Spacer(minLength: 0)
            Image(systemName: "chevron.right").font(.footnote.weight(.semibold)).foregroundStyle(theme.colors.ink3)
                .accessibilityHidden(true)
        }
        .frame(minHeight: HOSize.touch)
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private func sheetContent(_ step: OnboardingStep) -> some View {
        switch step {
        case .joinOrg:
            JoinOrgSheet(initialCode: nil) { _ in markDone(.joinOrg) }
        case .profile:
            NavigationStack {
                ScrollView { OnboardingAvatarSheet() }
                    .hoPaperBackground()
                    .navigationTitle("Add a Picture")
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { markDone(.profile); sheet = nil }
                        }
                    }
            }
        default:
            NavigationStack {
                ThemePickerView()
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button("Done") { markDone(.theme); sheet = nil }
                        }
                    }
            }
        }
    }

    private func markDone(_ step: OnboardingStep) {
        let store = OnboardingStore()
        var p = store.load()
        p.skipped.remove(step)
        store.save(p)
    }

    static var learnLine: String {
        #if os(macOS)
        "Open a lesson below. Point the Mac's camera at your hands, then follow the clips."
        #else
        "Open a lesson below. Prop the \(DeviceWord.noun) so it sees your hands, then follow the clips."
        #endif
    }

    static func title(_ step: OnboardingStep) -> String {
        switch step {
        case .joinOrg: "Join an organization"
        case .profile: "Add a picture"
        default: "Pick a look"
        }
    }

    static func symbol(_ step: OnboardingStep) -> String {
        switch step {
        case .joinOrg: "person.3"
        case .profile: "person.crop.circle"
        default: "paintpalette"
        }
    }
}

extension OnboardingStep: Identifiable {
    var id: String { rawValue }
}

/// The avatar editor on its own, for the Home card's Add a Picture sheet.
private struct OnboardingAvatarSheet: View {
    @Environment(AccountStore.self) private var accounts

    var body: some View {
        AvatarEditor(name: accounts.user?.name ?? "")
            .padding(HOSpace.l)
            .frame(maxWidth: .infinity)
    }
}
