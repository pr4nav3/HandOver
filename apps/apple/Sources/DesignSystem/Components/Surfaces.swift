import SwiftUI

// Cards, glass, floating shadows, focus rings and Reduce Motion aware animation (DESIGN.md 2.6, 2.8, 5).

/// What a status dot, badge or message means. One mapping from meaning to color.
enum HOTone: Hashable, Sendable {
    case neutral, accent, good, caution, bad, idle

    /// For dots, fills and symbols.
    func color(_ c: ColorRoles) -> Color {
        switch self {
        case .neutral: c.ink2
        case .accent: c.accent
        case .good: c.good
        case .caution: c.caution
        case .bad: c.bad
        case .idle: c.idle
        }
    }

    /// For text and symbols on paper, raised, wells and this tone's wash (all 4.5:1).
    func text(_ c: ColorRoles) -> Color {
        switch self {
        case .neutral, .idle: c.ink2
        case .accent: c.accentInk
        case .good: c.good
        case .caution: c.caution
        case .bad: c.bad
        }
    }

    /// The tone's wash. Neutral and idle use the well.
    func wash(_ c: ColorRoles) -> Color {
        switch self {
        case .neutral, .idle: c.well
        case .accent: c.accentSoft
        case .good: c.goodWash
        case .caution: c.cautionWash
        case .bad: c.badWash
        }
    }

    /// The tone's color on video (glass, dark scheme): dots keep their hue, text stays white.
    var onVideo: Color {
        switch self {
        case .neutral, .idle: Color(white: 0.72)
        case .accent: Color(ho: ThemeID.system.tokens(dark: true).accent)
        case .good: Color(ho: HORGB(hex: 0x30D158))
        case .caution: Color(ho: HORGB(hex: 0xFF9F0A))
        case .bad: Color(ho: HORGB(hex: 0xFF6961))
        }
    }
}

extension View {
    /// A card: `raised` fill plus a hairline, continuous corners.
    func hoCard(radius: CGFloat = HORadius.card, fill: Color? = nil) -> some View {
        modifier(CardSurface(radius: radius, fill: fill))
    }

    /// Liquid Glass in a capsule for controls over video (iOS 26, macOS 26); a material before, and `raised` at
    /// 96% with Reduce Transparency. Content is drawn in the dark scheme so it reads on any frame.
    func hoGlassCapsule(interactive: Bool = false) -> some View {
        modifier(GlassSurface(shape: .capsule, interactive: interactive))
    }

    /// Liquid Glass in a rounded rectangle, for panels that float over video.
    func hoGlassPanel(radius: CGFloat = HORadius.panel, interactive: Bool = false) -> some View {
        modifier(GlassSurface(shape: .rounded(radius), interactive: interactive))
    }

    /// The two-layer floating shadow (toasts, the PiP tile).
    func hoFloatingShadow() -> some View {
        modifier(FloatingShadow())
    }

    /// A 2 point accent ring at 55%, 2 points outside the shape, while this control has keyboard focus.
    func hoFocusRing(_ focused: Bool, radius: CGFloat = HORadius.control) -> some View {
        modifier(FocusRing(focused: focused, radius: radius))
    }

    /// `animation` on `value`, or a 0.15 s cross-fade with Reduce Motion.
    func hoAnimation<V: Equatable>(_ animation: Animation = HOMotion.layout, value: V) -> some View {
        modifier(MotionAware(animation: animation, value: value))
    }
}

private struct CardSurface: ViewModifier {
    let radius: CGFloat
    let fill: Color?
    @Environment(\.theme) private var theme
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .background(fill ?? theme.colors.raised, in: shape)
            .overlay(shape.strokeBorder(contrast == .increased ? theme.colors.lineStrong : theme.colors.line,
                                        lineWidth: HOLine.width))
    }
}

private enum GlassShape {
    case capsule
    case rounded(CGFloat)
}

private struct GlassSurface: ViewModifier {
    let shape: GlassShape
    let interactive: Bool
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        Group {
            switch shape {
            case .capsule: styled(content, Capsule())
            case .rounded(let r): styled(content, RoundedRectangle(cornerRadius: r, style: .continuous))
            }
        }
        .environment(\.colorScheme, .dark)
    }

    @ViewBuilder
    private func styled<S: InsettableShape>(_ content: Content, _ shape: S) -> some View {
        if reduceTransparency {
            content
                .background(theme.colors.overVideoRaised, in: shape)
                .overlay(shape.strokeBorder(Color.white.opacity(0.17), lineWidth: HOLine.width))
        } else if #available(iOS 26.0, macOS 26.0, *) {
            content.glassEffect(interactive ? .regular.interactive() : .regular, in: shape)
        } else {
            content
                .background(.regularMaterial, in: shape)
                .overlay(shape.strokeBorder(Color.white.opacity(0.12), lineWidth: HOLine.width))
        }
    }
}

private struct FloatingShadow: ViewModifier {
    @Environment(\.colorScheme) private var scheme

    func body(content: Content) -> some View {
        let s = HOShadow.floating(dark: scheme == .dark)
        content
            .shadow(color: s.near, radius: 1, y: 1)
            .shadow(color: s.far, radius: 16, y: 10)
    }
}

private struct FocusRing: ViewModifier {
    let focused: Bool
    let radius: CGFloat
    @Environment(\.theme) private var theme

    func body(content: Content) -> some View {
        content.overlay {
            if focused {
                RoundedRectangle(cornerRadius: radius + 2, style: .continuous)
                    .strokeBorder(theme.colors.accent.opacity(0.55), lineWidth: 2)
                    .padding(-4)
                    .allowsHitTesting(false)
            }
        }
    }
}

private struct MotionAware<V: Equatable>: ViewModifier {
    let animation: Animation
    let value: V
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.animation(HOMotion.resolve(animation, reduceMotion: reduceMotion), value: value)
    }
}

/// A small tone dot. Hidden from VoiceOver: the status lives in the label next to it.
struct StatusDot: View {
    var color: Color
    @ScaledMetric(relativeTo: .caption) private var size = HOSize.dot

    var body: some View {
        Circle().fill(color).frame(width: size, height: size).accessibilityHidden(true)
    }
}

extension EnvironmentValues {
    /// True while rendering a still (ImageRenderer snapshots), which does not draw scroll view content.
    @Entry var hoStillRendering = false
}

/// A vertical scroll view that becomes a plain stack when rendering a still.
struct HOScroll<Content: View>: View {
    @ViewBuilder var content: () -> Content
    @Environment(\.hoStillRendering) private var still

    var body: some View {
        if still {
            VStack(spacing: 0) { content() }.frame(maxHeight: .infinity, alignment: .top)
        } else {
            ScrollView { content() }
        }
    }
}
