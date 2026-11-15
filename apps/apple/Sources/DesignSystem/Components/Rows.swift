import SwiftUI

/// How a step stands for the learner in this run (DESIGN.md 3.20).
enum StepStatus: String, CaseIterable, Hashable, Sendable {
    case current, doneByCamera, doneByHand, skipped, notStarted

    var symbol: String {
        switch self {
        case .current: "play.circle.fill"
        case .doneByCamera: "checkmark.circle.fill"
        case .doneByHand: "hand.tap.fill"
        case .skipped: "arrow.uturn.forward.circle"
        case .notStarted: "circle"
        }
    }

    var word: String {
        switch self {
        case .current: "Current"
        case .doneByCamera: "Checked by camera"
        case .doneByHand: "Marked done"
        case .skipped: "Skipped"
        case .notStarted: "Not started"
        }
    }

    func color(_ c: ColorRoles) -> Color {
        switch self {
        case .current: c.accentInk
        case .doneByCamera: c.good
        case .doneByHand: c.ink2
        case .skipped: c.caution
        case .notStarted: c.ink3
        }
    }

    var isDone: Bool { self == .doneByCamera || self == .doneByHand }
}

/// A list row (DESIGN.md 3.10): optional leading view, title in `bodyMedium` (2 lines), meta in `callout` `ink2`,
/// optional trailing view. Pressed shows the press wash; selected the accent wash. At accessibility sizes the
/// meta wraps under the title. Padding `l` by `m`, at least 64 tall.
struct HORow<Leading: View, Trailing: View>: View {
    var title: String
    var meta: String?
    var selected = false
    @ViewBuilder var leading: () -> Leading
    @ViewBuilder var trailing: () -> Trailing
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.m) {
            leading()
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text(title)
                    .font(theme.fonts.bodyMedium)
                    .foregroundStyle(selected ? theme.colors.accentInk : theme.colors.ink)
                    .lineLimit(2)
                if let meta, !meta.isEmpty {
                    Text(meta)
                        .font(theme.fonts.callout)
                        .foregroundStyle(theme.colors.ink2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            trailing()
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .frame(minHeight: 64)
        .background(selected ? theme.colors.accentSoft : Color.clear)
        .contentShape(Rectangle())
    }
}

extension HORow where Trailing == EmptyView {
    init(title: String, meta: String? = nil, selected: Bool = false, @ViewBuilder leading: @escaping () -> Leading) {
        self.init(title: title, meta: meta, selected: selected, leading: leading, trailing: { EmptyView() })
    }
}

extension HORow where Leading == EmptyView, Trailing == EmptyView {
    init(title: String, meta: String? = nil, selected: Bool = false) {
        self.init(title: title, meta: meta, selected: selected, leading: { EmptyView() }, trailing: { EmptyView() })
    }
}

/// Rows press with the press wash.
struct HORowButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        StyledBody(configuration: configuration)
    }

    private struct StyledBody: View {
        let configuration: Configuration
        @Environment(\.theme) private var theme
        var body: some View {
            configuration.label
                .background(configuration.isPressed ? theme.colors.pressed : Color.clear)
        }
    }
}

/// A rounded square holding an SF Symbol (30 to 32 points), for settings and hub rows.
struct SymbolTile: View {
    var symbol: String
    var tone: HOTone = .accent
    var side: CGFloat = HOSize.tile
    @Environment(\.theme) private var theme

    var body: some View {
        Image(systemName: symbol)
            .font(.system(size: side * 0.5, weight: .medium))
            .foregroundStyle(tone.text(theme.colors))
            .frame(width: side, height: side)
            .background(tone.wash(theme.colors), in: RoundedRectangle(cornerRadius: side * 0.28, style: .continuous))
            .accessibilityHidden(true)
    }
}
