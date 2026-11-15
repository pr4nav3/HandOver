import SwiftUI

/// The four welcome pages (SCREENS.md 25.2): one illustration stage on top that morphs between scenes, the
/// title and line below that swipe. While dragging, the picture moves at 0.6x of the finger and the words at
/// 1.0x, so the picture lags a little. Mac and keyboards: Back and Continue, Left and Right Arrow.
struct WelcomePages: View {
    var onFinish: () -> Void
    var onSkip: () -> Void
    /// Start page and still art, for previews and snapshots.
    var startPage = 0
    var settled = false

    static let pages: [(title: String, line: String)] = [
        ("An expert does it once", "They record the task on their phone or Ray-Ban Meta glasses and talk through each step."),
        ("We turn it into steps", "HandOver finds where each step starts and ends, cuts a clip for each one, and adds captions."),
        ("Your camera follows along", "Point a phone at your work. When a step looks done, the next clip starts."),
        ("You get a score and a tip", "See how each step went against the expert, and what to practice next."),
    ]

    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var page = 0
    @State private var drag: CGFloat = 0

    private var isLast: Bool { page == Self.pages.count - 1 }

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width
            let wide = sizeClass == .regular
            VStack(spacing: 0) {
                WelcomeStage(page: page, settled: settled || reduceMotion,
                             scale: min(wide ? 1.3 : min(1, width / 360), geo.size.height * 0.52 / 270))
                    .frame(height: geo.size.height * 0.52)
                    .offset(x: reduceMotion ? 0 : drag * 0.6)
                    .opacity(reduceMotion ? 1 : 1 - min(0.35, abs(drag) / max(width, 1)))
                    .id(reduceMotion ? page : 0)
                    .transition(.opacity)
                texts(width: width)
                    .frame(maxHeight: .infinity, alignment: .top)
                dots
                    .padding(.bottom, HOSpace.l)
                buttons
            }
            .contentShape(Rectangle())
            .gesture(swipe(width: width))
        }
        .onKeyPress(.rightArrow) { advance(); return .handled }
        .onKeyPress(.leftArrow) { retreat(); return .handled }
        .onAppear {
            page = startPage
        }
        .sensoryFeedback(.selection, trigger: page)
    }

    private func texts(width: CGFloat) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Self.pages.indices, id: \.self) { i in
                VStack(spacing: HOSpace.m) {
                    Text(Self.pages[i].title)
                        .hoFont(.display, theme)
                        .foregroundStyle(theme.colors.ink)
                        .multilineTextAlignment(.center)
                    Text(Self.pages[i].line)
                        .font(theme.fonts.body)
                        .foregroundStyle(theme.colors.ink2)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: 340)
                }
                .padding(.horizontal, HOSpace.xl)
                .padding(.top, HOSpace.xl)
                .frame(width: width)
                .opacity(i == page ? 1 : 0.0)
                .accessibilityElement(children: .combine)
                .accessibilityHidden(i != page)
            }
        }
        .frame(width: width, alignment: .leading)
        .offset(x: -CGFloat(page) * width + drag)
        .clipped()
    }

    private var dots: some View {
        HStack(spacing: HOSpace.s) {
            ForEach(Self.pages.indices, id: \.self) { i in
                Circle()
                    .fill(i == page ? theme.colors.ink : theme.colors.ink3.opacity(0.5))
                    .frame(width: 7, height: 7)
                    .frame(width: 18, height: 24)
                    .contentShape(Rectangle())
                    .onTapGesture { go(to: i) }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Page \(page + 1) of \(Self.pages.count)")
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: advance()
            case .decrement: retreat()
            @unknown default: break
            }
        }
    }

    private var buttons: some View {
        HStack(spacing: HOSpace.s) {
            #if os(macOS)
            if page > 0 {
                Button("Back") { retreat() }
                    .buttonStyle(HOButtonStyle(.secondary, size: .large))
                    .frame(width: 120)
            }
            #endif
            Button(isLast ? "Get Started" : "Continue") {
                Haptics.tap()
                advance()
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.bottom, HOSpace.l)
        .frame(maxWidth: 520)
    }

    private func swipe(width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 12)
            .onChanged { value in
                let dx = value.translation.width
                // Rubber band past the first and last page.
                let atEdge = (page == 0 && dx > 0) || (isLast && dx < 0)
                drag = atEdge ? dx / 3 : dx
            }
            .onEnded { value in
                let predicted = value.predictedEndTranslation.width
                let threshold = width * 0.25
                if predicted < -threshold, !isLast {
                    go(to: page + 1)
                } else if predicted > threshold, page > 0 {
                    go(to: page - 1)
                } else {
                    withAnimation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion)) { drag = 0 }
                }
            }
    }

    private func advance() {
        if isLast { onFinish() } else { go(to: page + 1) }
    }

    private func retreat() {
        if page > 0 { go(to: page - 1) }
    }

    private func go(to target: Int) {
        let animation = reduceMotion ? HOMotion.reduced : Animation.spring(response: 0.5, dampingFraction: 0.86)
        withAnimation(animation) {
            page = max(0, min(Self.pages.count - 1, target))
            drag = 0
        }
    }
}

#Preview("Welcome") {
    WelcomePages(onFinish: {}, onSkip: {})
        .hoPaperBackground()
        .handOverTheme(.system, dark: false)
}
