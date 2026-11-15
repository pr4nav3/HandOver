import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

// The shape of a theme and how views read it. Role and token names follow apps/design/DESIGN.md (2.1 colors,
// 2.2 type); values per theme are in ThemeCatalog.swift (apps/design/THEMES.md).
//
// Views read it with `@Environment(\.theme) private var theme`. The app applies the stored choice once at the
// root with `.handOverTheme()`, which resolves the look (light or dark, Increase Contrast), forces the color
// scheme for themes with one look, and puts the resolved theme in the environment. Without the root modifier
// the environment holds Default with colors that follow light and dark by themselves.

/// Named color roles (DESIGN.md 2.1), so views never hard-code colors.
struct ColorRoles: Sendable {
    var paper, raised, well: Color
    var ink, ink2, ink3: Color
    var line, lineStrong: Color
    var accent, onAccent, accentInk, accentSoft: Color
    var good, caution, bad, idle: Color
    /// Hover and press washes over raised things.
    var hover: Color = .primary.opacity(0.05)
    var pressed: Color = .primary.opacity(0.09)
    /// Tone washes (12% light, 16% dark).
    var goodWash: Color = .green.opacity(0.12)
    var cautionWash: Color = .orange.opacity(0.12)
    var badWash: Color = .red.opacity(0.12)
    /// Video roles, the same in every theme.
    var stage: Color = .black
    var captionFill: Color = .black.opacity(0.72)
    var captionInk: Color = .white
    var record = Color(red: 0xD7 / 255, green: 0x00 / 255, blue: 0x15 / 255)
    /// What glass over video becomes with Reduce Transparency: the dark look's raised at 96%.
    var overVideoRaised: Color = Color(white: 0.12).opacity(0.96)
}

/// The type ramp (DESIGN.md 2.2). Every style is a Dynamic Type text style.
struct FontScale: Sendable {
    var largeTitle, display, stepTitle, title, headline, body, bodyMedium: Font
    var callout, section, footnote, caption, badge, numeral, timer, code: Font
    /// Captions over video: `.body` semibold at the Medium Caption Size.
    var captionText: Font = .body.weight(.semibold)

    /// The ramp from DESIGN.md 2.2: SF Pro everywhere, SF Rounded only for glanceable numerals.
    static let standard = FontScale(
        largeTitle: .largeTitle.bold(), display: .title.weight(.semibold), stepTitle: .title2.weight(.semibold),
        title: .title3.weight(.semibold), headline: .headline, body: .body, bodyMedium: .body.weight(.medium),
        callout: .subheadline, section: .footnote.weight(.semibold), footnote: .footnote, caption: .caption,
        badge: .caption.weight(.medium),
        numeral: .system(.title, design: .rounded).weight(.semibold).monospacedDigit(),
        timer: .headline.weight(.semibold).monospacedDigit(), code: .system(.footnote, design: .monospaced))
}

protocol Theme: Sendable {
    var name: String { get }
    var colors: ColorRoles { get }
    var fonts: FontScale { get }
    /// Draw the grain texture on `paper` (DESIGN.md 2.7).
    var grain: Bool { get }
    /// The catalog entry this theme draws.
    var id: ThemeID { get }
    /// No hue anywhere (Mono, Matte): status keeps its meaning through words and symbols.
    var isMono: Bool { get }
    /// The grain amount for a look, or nil with no grain.
    func grainAmount(dark: Bool) -> Double?
}

extension Theme {
    var id: ThemeID { .system }
    var isMono: Bool { false }
    func grainAmount(dark: Bool) -> Double? { nil }
}

extension Color {
    /// A fixed color from catalog numbers.
    init(ho c: HORGB) {
        self.init(.sRGB, red: c.r, green: c.g, blue: c.b, opacity: c.a)
    }

    /// A color that follows the light or dark trait it is drawn in.
    static func dynamic(light: HORGB, dark: HORGB) -> Color {
        if light == dark { return Color(ho: light) }
        #if canImport(UIKit)
        return Color(uiColor: UIColor { traits in
            let c = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: c.r, green: c.g, blue: c.b, alpha: c.a)
        })
        #elseif canImport(AppKit)
        return Color(nsColor: NSColor(name: nil) { appearance in
            let isDark = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
            let c = isDark ? dark : light
            return NSColor(srgbRed: c.r, green: c.g, blue: c.b, alpha: c.a)
        })
        #endif
    }
}

/// A theme from the catalog, either resolved to one look (what `.handOverTheme()` puts in the environment)
/// or following light and dark by itself (the environment default).
struct HOTheme: Theme {
    let id: ThemeID
    let light: ThemeTokens
    let dark: ThemeTokens
    let colors: ColorRoles
    let fonts = FontScale.standard

    var name: String { id.name }
    var grain: Bool { light.grain != nil || dark.grain != nil }
    var isMono: Bool { id.isMono }
    func grainAmount(dark isDark: Bool) -> Double? { (isDark ? dark : light).grain }

    /// One look of `id`, fixed.
    init(_ id: ThemeID, dark: Bool) {
        self.init(id: id, tokens: id.tokens(dark: dark))
    }

    /// `id` drawn with `tokens` (High Contrast values under Increase Contrast keep the chosen id).
    init(id: ThemeID, tokens: ThemeTokens) {
        self.init(id: id, light: tokens, dark: tokens)
    }

    /// `id` following light and dark.
    init(dynamic id: ThemeID) {
        self.init(id: id, light: id.tokens(dark: false), dark: id.tokens(dark: true))
    }

    private init(id: ThemeID, light: ThemeTokens, dark: ThemeTokens) {
        self.id = id
        self.light = light
        self.dark = dark
        func c(_ pick: (ThemeTokens) -> HORGB) -> Color { .dynamic(light: pick(light), dark: pick(dark)) }
        colors = ColorRoles(
            paper: c(\.paper), raised: c(\.raised), well: c(\.well),
            ink: c(\.ink), ink2: c(\.ink2), ink3: c(\.ink3), line: c(\.line), lineStrong: c(\.lineStrong),
            accent: c(\.accent), onAccent: c(\.onAccent), accentInk: c(\.accentInk), accentSoft: c(\.accentSoft),
            good: c(\.good), caution: c(\.caution), bad: c(\.bad), idle: c(\.idle),
            hover: c(\.hover), pressed: c(\.pressed),
            goodWash: c { $0.wash($0.good) }, cautionWash: c { $0.wash($0.caution) }, badWash: c { $0.wash($0.bad) },
            overVideoRaised: Color(ho: ThemeID.system.tokens(dark: true).raised.alpha(0.96)))
    }
}

/// Kept for code written against the first stub: Default, following light and dark.
struct SystemTheme: Theme {
    private let base = HOTheme(dynamic: .system)
    var name: String { base.name }
    var colors: ColorRoles { base.colors }
    var fonts: FontScale { base.fonts }
    var grain: Bool { false }
}

extension EnvironmentValues {
    @Entry var theme: any Theme = HOTheme(dynamic: .system)
}

// MARK: - The stored choice

/// The Appearance setting (System, Light, Dark). It applies only to themes with two looks.
enum ThemeAppearance: String, CaseIterable, Identifiable, Sendable {
    case system, light, dark
    var id: String { rawValue }
    var title: String {
        switch self {
        case .system: "System"
        case .light: "Light"
        case .dark: "Dark"
        }
    }
}

/// Where the theme choice lives. Read and write it with `@AppStorage(ThemeStore.themeKey)` and
/// `@AppStorage(ThemeStore.appearanceKey)`; `.handOverTheme()` redraws the app when either changes.
enum ThemeStore {
    static let themeKey = "handover.theme"
    static let appearanceKey = "handover.appearance"

    /// Whether `id` is drawn dark, given the Appearance setting and the system.
    static func isDark(_ id: ThemeID, appearance: ThemeAppearance, systemDark: Bool) -> Bool {
        switch id.looks {
        case .alwaysDark: true
        case .alwaysLight: false
        case .followsSystem:
            switch appearance {
            case .system: systemDark
            case .light: false
            case .dark: true
            }
        }
    }

    /// The color scheme to force, or nil to follow the system.
    static func forcedScheme(_ id: ThemeID, appearance: ThemeAppearance) -> ColorScheme? {
        switch id.looks {
        case .alwaysDark: .dark
        case .alwaysLight: .light
        case .followsSystem:
            switch appearance {
            case .system: nil
            case .light: .light
            case .dark: .dark
            }
        }
    }

    /// The resolved theme to draw: with Increase Contrast, High Contrast's values in the same look.
    static func resolve(_ id: ThemeID, dark: Bool, increaseContrast: Bool) -> HOTheme {
        increaseContrast && id != .highContrast
            ? HOTheme(id: id, tokens: ThemeID.highContrast.tokens(dark: dark))
            : HOTheme(id, dark: dark)
    }
}

extension View {
    /// Draws everything inside in the stored theme. Put it once at the root. `override` pins a theme (and
    /// `dark` a look) for previews and snapshot tests.
    func handOverTheme(_ override: ThemeID? = nil, dark: Bool? = nil) -> some View {
        modifier(HandOverThemeModifier(override: override, overrideDark: dark))
    }
}

private struct HandOverThemeModifier: ViewModifier {
    var override: ThemeID?
    var overrideDark: Bool?
    @AppStorage(ThemeStore.themeKey) private var stored = ThemeID.fallback.rawValue
    @AppStorage(ThemeStore.appearanceKey) private var storedAppearance = ThemeAppearance.system.rawValue
    @Environment(\.colorScheme) private var scheme
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        let id = override ?? ThemeID(stored: stored)
        let appearance = overrideDark.map { $0 ? ThemeAppearance.dark : .light }
            ?? ThemeAppearance(rawValue: storedAppearance) ?? .system
        let dark = ThemeStore.isDark(id, appearance: appearance, systemDark: scheme == .dark)
        let theme = ThemeStore.resolve(id, dark: dark, increaseContrast: contrast == .increased)
        content
            .environment(\.theme, theme)
            .environment(\.colorScheme, dark ? .dark : .light)
            .tint(theme.colors.accent)
            .preferredColorScheme(ThemeStore.forcedScheme(id, appearance: appearance))
    }
}
