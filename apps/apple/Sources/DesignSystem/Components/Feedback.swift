import SwiftUI

// Empty and error states, banners, toasts and the small pills over video (DESIGN.md 3.11 to 3.13, SCREENS.md 18).

/// Centered: symbol, title, message (max 320 wide) and optional actions. The loading variant shows a spinner
/// instead of the symbol, only after 0.5 s, so a fast load never flashes one.
struct HOEmptyState<Actions: View>: View {
    var symbol: String?
    var title: String
    var message: String?
    var tone: HOTone = .neutral
    var loading = false
    @ViewBuilder var actions: () -> Actions
    @Environment(\.theme) private var theme
    @State private var showSpinner = false

    var body: some View {
        VStack(spacing: HOSpace.s) {
            if loading {
                ProgressView()
                    .controlSize(.large)
                    .opacity(showSpinner ? 1 : 0)
                    .task {
                        try? await Task.sleep(for: .milliseconds(500))
                        showSpinner = true
                    }
            } else if let symbol {
                Image(systemName: symbol)
                    .font(theme.fonts.largeTitle.weight(.light))
                    .foregroundStyle(tone == .neutral ? theme.colors.ink2 : tone.text(theme.colors))
                    .padding(.bottom, HOSpace.xs)
                    .accessibilityHidden(true)
            }
            Text(title)
                .hoFont(.title, theme)
                .foregroundStyle(theme.colors.ink)
                .multilineTextAlignment(.center)
            if let message, !loading {
                Text(message)
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 320)
            }
            actions().padding(.top, HOSpace.s)
        }
        .padding(HOSpace.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .contain)
    }
}

extension HOEmptyState where Actions == EmptyView {
    init(symbol: String? = nil, title: String, message: String? = nil, tone: HOTone = .neutral, loading: Bool = false) {
        self.init(symbol: symbol, title: title, message: message, tone: tone, loading: loading, actions: { EmptyView() })
    }
}

/// A slim card for an ongoing condition (DESIGN.md 3.12): tone symbol, one `footnote` line in `ink2`, an
/// optional small secondary button.
struct HOBanner: View {
    var symbol: String
    var tone: HOTone = .caution
    var text: String
    var actionTitle: String?
    var action: () -> Void = {}
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .center, spacing: HOSpace.s) {
            Image(systemName: symbol)
                .foregroundStyle(tone.text(theme.colors))
                .accessibilityHidden(true)
            Text(text)
                .font(theme.fonts.footnote)
                .foregroundStyle(theme.colors.ink2)
                .lineLimit(3)
                .frame(maxWidth: .infinity, alignment: .leading)
            if let actionTitle {
                Button(actionTitle) { Haptics.tap(); action() }
                    .buttonStyle(HOButtonStyle(.secondary, size: .small))
            }
        }
        .padding(.horizontal, HOSpace.m)
        .padding(.vertical, HOSpace.s)
        .hoCard(radius: HORadius.control)
        .accessibilityElement(children: .combine)
    }
}

/// A one line toast (DESIGN.md 3.13).
struct ToastItem: Equatable, Identifiable, Sendable {
    var id = UUID()
    var text: String
    var symbol: String?
    var tone: HOTone = .neutral
    var actionTitle: String?
}

/// Capsule, `raised`, floating shadow, 52 tall, optional tone symbol and one quiet action.
struct HOToast: View {
    var item: ToastItem
    var action: () -> Void = {}
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.s) {
            if let symbol = item.symbol {
                Image(systemName: symbol)
                    .foregroundStyle(item.tone == .neutral ? theme.colors.ink2 : item.tone.text(theme.colors))
                    .accessibilityHidden(true)
            }
            Text(item.text)
                .font(theme.fonts.bodyMedium)
                .foregroundStyle(theme.colors.ink)
                .lineLimit(2)
            if let title = item.actionTitle {
                Button(title) { Haptics.tap(); action() }
                    .buttonStyle(HOButtonStyle(.quiet, size: .small))
            }
        }
        .padding(.horizontal, HOSpace.l)
        .frame(minHeight: 52)
        .background(theme.colors.raised, in: Capsule())
        .overlay(Capsule().strokeBorder(theme.colors.line, lineWidth: HOLine.width))
        .hoFloatingShadow()
        .accessibilityElement(children: .combine)
    }
}

extension View {
    /// Shows `item` as a toast at the bottom; it leaves on its own after 4 s and is announced to VoiceOver.
    func hoToast(_ item: Binding<ToastItem?>, action: @escaping () -> Void = {}) -> some View {
        modifier(ToastHost(item: item, action: action))
    }
}

private struct ToastHost: ViewModifier {
    @Binding var item: ToastItem?
    var action: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.overlay(alignment: .bottom) {
            ZStack {
                if let item {
                    HOToast(item: item) { action(); self.item = nil }
                        .padding(.horizontal, HOSpace.l)
                        .padding(.bottom, HOSpace.l)
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                        .task(id: item.id) {
                            AccessibilityNotification.Announcement(item.text).post()
                            try? await Task.sleep(for: .seconds(4))
                            if self.item?.id == item.id { self.item = nil }
                        }
                }
            }
            .animation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion), value: item)
        }
    }
}

/// A small glass pill over video: "Mock checks", "Checks off: No API key", "Recording".
struct VideoPill: View {
    var symbol: String
    var text: String
    var tone: HOTone = .caution
    /// The solid `record` dot before the text (Recording).
    var recordDot = false
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: 6) {
            if recordDot {
                Circle().fill(theme.colors.record).frame(width: 8, height: 8).accessibilityHidden(true)
            }
            Image(systemName: symbol)
                .foregroundStyle(tone.onVideo)
                .accessibilityHidden(true)
            Text(text)
                .foregroundStyle(.white)
                .lineLimit(1)
        }
        .font(theme.fonts.badge)
        .padding(.horizontal, 10)
        .frame(minHeight: 26)
        .hoGlassCapsule()
        .accessibilityElement(children: .combine)
    }
}
