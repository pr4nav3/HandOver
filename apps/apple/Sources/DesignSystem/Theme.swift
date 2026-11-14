import SwiftUI

// Stub for the design builder: the shape of a theme and how views read it. Role and token names follow
// apps/design/DESIGN.md (2.1 colors, 2.2 type); values per theme are in apps/design/THEMES.md.
// Views read it with `@Environment(\.theme) private var theme`; the app sets it with `.environment(\.theme, ...)`.

/// Named color roles (DESIGN.md 2.1), so views never hard-code colors.
struct ColorRoles: Sendable {
    var paper, raised, well: Color
    var ink, ink2, ink3: Color
    var line, lineStrong: Color
    var accent, onAccent, accentInk, accentSoft: Color
    var good, caution, bad, idle: Color
    /// Video roles, the same in every theme.
    var stage: Color = .black
    var captionFill: Color = .black.opacity(0.72)
    var captionInk: Color = .white
    var record = Color(red: 0xD7 / 255, green: 0x00 / 255, blue: 0x15 / 255)
}

/// The type ramp (DESIGN.md 2.2). Every style is a Dynamic Type text style.
struct FontScale: Sendable {
    var largeTitle, display, stepTitle, title, headline, body, bodyMedium: Font
    var callout, section, footnote, caption, badge, numeral, timer, code: Font
}

protocol Theme: Sendable {
    var name: String { get }
    var colors: ColorRoles { get }
    var fonts: FontScale { get }
    /// Draw the grain texture on `paper` (DESIGN.md 2.7).
    var grain: Bool { get }
}

/// Placeholder until the design builder adds the real themes: system semantic colors and text styles.
struct SystemTheme: Theme {
    let name = "System"
    let colors = ColorRoles(
        paper: .clear, raised: Color.secondary.opacity(0.08), well: Color.secondary.opacity(0.14),
        ink: .primary, ink2: .secondary, ink3: Color.secondary.opacity(0.6),
        line: Color.primary.opacity(0.09), lineStrong: Color.primary.opacity(0.16),
        accent: .accentColor, onAccent: .white, accentInk: .accentColor, accentSoft: Color.accentColor.opacity(0.12),
        good: .green, caution: .orange, bad: .red, idle: .gray)
    let fonts = FontScale(
        largeTitle: .largeTitle.bold(), display: .title.weight(.semibold), stepTitle: .title2.weight(.semibold),
        title: .title3.weight(.semibold), headline: .headline, body: .body, bodyMedium: .body.weight(.medium),
        callout: .subheadline, section: .footnote.weight(.semibold), footnote: .footnote, caption: .caption,
        badge: .caption.weight(.medium), numeral: .system(.title, design: .rounded).weight(.semibold).monospacedDigit(),
        timer: .headline.monospacedDigit(), code: .system(.footnote, design: .monospaced))
    let grain = false
}

extension EnvironmentValues {
    @Entry var theme: any Theme = SystemTheme()
}
