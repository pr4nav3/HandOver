import SwiftUI

/// The last onboarding step (SCREENS.md 25.9): a live miniature Learn screen in the highlighted theme, the 14
/// theme cards in a snapping row (a 7 by 2 grid on the Mac), and the appearance control. Picking applies to
/// the onboarding screen at once, so the person sees it for real.
struct ThemePage: View {
    let flow: OnboardingModel
    @AppStorage(ThemeStore.themeKey) private var stored = ThemeID.fallback.rawValue
    @AppStorage(ThemeStore.appearanceKey) private var appearance = ThemeAppearance.system.rawValue
    @Environment(\.theme) private var theme
    @State private var centered: ThemeID?

    private var selected: ThemeID { ThemeID(stored: stored) }

    /// About 40% of the height for the preview (SCREENS.md 25.9); the Mac window is only 560 tall.
    #if os(macOS)
    private static let previewWidth: CGFloat = 230
    #else
    private static let previewWidth: CGFloat = 320
    #endif

    var body: some View {
        GeometryReader { geo in
            let short = HOLayout.isShort(geo.size.height)
            VStack(spacing: 0) {
                ScrollView {
                    VStack(spacing: HOSpace.l) {
                        VStack(spacing: HOSpace.xs) {
                            if let label = flow.progress.stepLabel {
                                Text(label).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                            }
                            Text("Pick a look").hoFont(.display, theme).foregroundStyle(theme.colors.ink)
                            Text("You can change it anytime in Settings.")
                                .font(theme.fonts.body).foregroundStyle(theme.colors.ink2)
                        }
                        .padding(.top, short ? HOSpace.s : HOSpace.l)
                        LearnMiniature()
                            .frame(maxWidth: Self.previewWidth)
                            .padding(.horizontal, HOSpace.l)
                            .animation(HOMotion.clip, value: stored)
                        AppearancePicker(selection: $appearance)
                            .frame(maxWidth: 320)
                        themes
                        if short { footer }
                    }
                    .padding(.bottom, HOSpace.l)
                }
                .scrollBounceBehavior(.basedOnSize)
                if !short { footer }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .onAppear { centered = selected }
    }

    /// What happens next and the button. Pinned at the bottom; scrolls with the page on a short screen.
    private var footer: some View {
        VStack(spacing: HOSpace.s) {
            Text(nextLine)
                .font(theme.fonts.footnote)
                .foregroundStyle(theme.colors.ink2)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
            Button("Start Using HandOver") {
                Haptics.success()
                flow.complete(.theme)
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.top, HOSpace.s)
        .padding(.bottom, HOSpace.l)
        .frame(maxWidth: 520)
    }

    @ViewBuilder
    private var themes: some View {
        #if os(macOS)
        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: HOSpace.s), count: 7), spacing: HOSpace.s) {
            ForEach(ThemeID.allCases) { id in
                Button { pick(id) } label: { ThemeCard(id: id, selected: id == selected, compact: true) }
                    .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, HOSpace.l)
        #else
        ScrollView(.horizontal, showsIndicators: false) {
            LazyHStack(spacing: HOSpace.m) {
                ForEach(ThemeID.allCases) { id in
                    Button { pick(id) } label: { ThemeCard(id: id, selected: id == selected, compact: true) }
                        .buttonStyle(.plain)
                        .frame(width: 132)
                        .id(id)
                }
            }
            .scrollTargetLayout()
        }
        .contentMargins(.horizontal, HOSpace.l, for: .scrollContent)
        .scrollTargetBehavior(.viewAligned)
        .scrollPosition(id: $centered, anchor: .center)
        .frame(height: 124)
        .onChange(of: centered) { _, id in
            if let id, id != selected { pick(id, scroll: false) }
        }
        #endif
    }

    /// Where the button goes, so the last tap is not a leap into the unknown (SCREENS.md 25.10).
    private var nextLine: String {
        flow.progress.role == .teach
            ? "Next is Home. Make your first lesson in Teach."
            : "Next is Home, with the lessons on your hub. Open one to start."
    }

    private func pick(_ id: ThemeID, scroll: Bool = true) {
        Haptics.tap()
        stored = id.rawValue
        if scroll { withAnimation(HOMotion.layout) { centered = id } }
    }
}

/// A miniature Learn screen drawn with the real components: progress bar, the black clip pane with a caption,
/// the step title, the Watching badge and a Next button.
struct LearnMiniature: View {
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            StepProgressBar(total: SampleLesson.steps, current: 3)
            SampleFrame(step: 4, radius: HORadius.control)
                .aspectRatio(16 / 9, contentMode: .fit)
                .overlay(alignment: .bottom) {
                    Text(SampleLesson.stepFourLine)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(theme.colors.captionInk)
                        .padding(.horizontal, HOSpace.s)
                        .padding(.vertical, HOSpace.xs)
                        .background(theme.colors.captionFill, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                        .padding(HOSpace.s)
                }
            HStack(alignment: .center) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Step 4 of \(SampleLesson.steps)").font(theme.fonts.caption).foregroundStyle(theme.colors.ink2)
                    Text(SampleLesson.stepTitles[3]).font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                        .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: HOSpace.s)
                StatusBadge(status: .watching)
            }
            Text("Next")
                .font(theme.fonts.headline)
                .foregroundStyle(theme.colors.onAccent)
                .frame(maxWidth: .infinity, minHeight: 40)
                .background(theme.colors.accent, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
        }
        .padding(HOSpace.m)
        .background {
            ZStack {
                theme.colors.paper
                GrainOverlay()
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HORadius.panel, style: .continuous).strokeBorder(theme.colors.lineStrong, lineWidth: HOLine.width))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Preview of a lesson in the \(theme.name) theme")
    }
}
