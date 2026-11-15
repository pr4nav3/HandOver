import SwiftUI

/// The button kinds from DESIGN.md 3.7. `.primary` is the accent fill, one per screen.
struct HOButtonStyle: ButtonStyle {
    enum Kind: Sendable {
        case primary, secondary, quiet, destructive
    }

    enum Size: Sendable {
        case small, regular, large
        var height: CGFloat {
            switch self {
            case .small: HOSize.controlSmall
            case .regular: HOSize.control
            case .large: HOSize.controlLarge
            }
        }
        var radius: CGFloat { self == .large ? HORadius.controlLarge : HORadius.control }
    }

    var kind: Kind
    var size: Size
    var fullWidth: Bool
    /// Quiet buttons on video (the mistake card in landscape) use white text.
    var onVideo: Bool

    init(_ kind: Kind, size: Size = .regular, fullWidth: Bool = false, onVideo: Bool = false) {
        self.kind = kind
        self.size = size
        self.fullWidth = fullWidth
        self.onVideo = onVideo
    }

    func makeBody(configuration: Configuration) -> some View {
        StyledBody(configuration: configuration, style: self)
    }

    private struct StyledBody: View {
        let configuration: Configuration
        let style: HOButtonStyle
        @Environment(\.theme) private var theme
        @Environment(\.isEnabled) private var isEnabled
        @Environment(\.accessibilityReduceMotion) private var reduceMotion
        @Environment(\.dynamicTypeSize) private var typeSize
        @Environment(\.isFocused) private var isFocused

        var body: some View {
            let pressed = configuration.isPressed
            let c = theme.colors
            let shape = RoundedRectangle(cornerRadius: style.size.radius, style: .continuous)
            // Buttons grow with Dynamic Type up to 1.6x their height.
            let grow: CGFloat = typeSize.isAccessibilitySize ? 1.6 : (typeSize >= .xxLarge ? 1.2 : 1)
            configuration.label
                .font(style.size == .small ? theme.fonts.callout.weight(.medium) : theme.fonts.headline)
                .lineLimit(2)
                .minimumScaleFactor(style.size == .small ? 0.85 : 1)
                .multilineTextAlignment(.center)
                .foregroundStyle(foreground(c))
                .padding(.horizontal, style.size == .small ? HOSpace.m : HOSpace.l)
                .frame(minHeight: style.size.height * grow)
                .frame(maxWidth: style.fullWidth ? .infinity : nil)
                .background(fill(c, pressed: pressed), in: shape)
                .overlay {
                    if hasEdge { shape.strokeBorder(c.line, lineWidth: HOLine.width) }
                }
                .contentShape(shape)
                .scaleEffect(pressed && !reduceMotion ? 0.98 : 1)
                .animation(HOMotion.press, value: pressed)
                .hoFocusRing(isFocused, radius: style.size.radius)
        }

        private var hasEdge: Bool {
            (style.kind == .secondary || style.kind == .destructive) && isEnabled
        }

        private func foreground(_ c: ColorRoles) -> Color {
            if !isEnabled { return style.kind == .quiet ? (style.onVideo ? .white.opacity(0.4) : c.ink3) : c.ink3 }
            switch style.kind {
            case .primary: return c.onAccent
            case .secondary: return c.ink
            case .quiet: return style.onVideo ? .white : c.ink
            case .destructive: return c.bad
            }
        }

        private func fill(_ c: ColorRoles, pressed: Bool) -> Color {
            if !isEnabled { return style.kind == .quiet ? .clear : c.well }
            switch style.kind {
            case .primary: return pressed ? c.accent.opacity(0.82) : c.accent
            case .secondary, .destructive: return pressed ? c.well : c.raised
            case .quiet: return pressed ? (style.onVideo ? .white.opacity(0.12) : c.pressed) : .clear
            }
        }
    }
}

/// A round 36 point icon button inside a 44 point hit area: `raised` circle with a hairline, or glass on video.
struct HOIconButtonStyle: ButtonStyle {
    var onVideo = false

    func makeBody(configuration: Configuration) -> some View {
        StyledBody(configuration: configuration, onVideo: onVideo)
    }

    private struct StyledBody: View {
        let configuration: Configuration
        let onVideo: Bool
        @Environment(\.theme) private var theme
        @Environment(\.accessibilityReduceMotion) private var reduceMotion

        var body: some View {
            let pressed = configuration.isPressed
            Group {
                if onVideo {
                    configuration.label
                        .foregroundStyle(.white)
                        .frame(width: HOSize.iconButton, height: HOSize.iconButton)
                        .hoGlassCapsule(interactive: true)
                } else {
                    configuration.label
                        .foregroundStyle(theme.colors.ink)
                        .frame(width: HOSize.iconButton, height: HOSize.iconButton)
                        .background(pressed ? theme.colors.well : theme.colors.raised, in: Circle())
                        .overlay(Circle().strokeBorder(theme.colors.line, lineWidth: HOLine.width))
                }
            }
            .font(.body.weight(.medium))
            .frame(width: HOSize.touch, height: HOSize.touch)
            .contentShape(Rectangle())
            .scaleEffect(pressed && !reduceMotion ? 0.96 : 1)
            .animation(HOMotion.press, value: pressed)
        }
    }
}

#Preview("Buttons") {
    VStack(spacing: 12) {
        Button("Next") {}.buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
        Button("Next") {}.buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true)).disabled(true)
        Button("Try Again") {}.buttonStyle(HOButtonStyle(.secondary))
        Button("I'm Fine") {}.buttonStyle(HOButtonStyle(.quiet, size: .small))
        Button("Delete Lesson", systemImage: "trash") {}.buttonStyle(HOButtonStyle(.destructive))
        Button { } label: { Image(systemName: "xmark") }.buttonStyle(HOIconButtonStyle())
    }
    .padding()
    .hoPaperBackground()
    .handOverTheme(.system, dark: false)
}
