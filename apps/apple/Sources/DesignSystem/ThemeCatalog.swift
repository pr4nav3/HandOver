import Foundation

// HandOver's 14 themes as plain numbers (apps/design/THEMES.md, exact values). Pure Foundation, so the
// contrast test checks every look without drawing anything. Theme.swift turns these into SwiftUI colors.
// The math and the contrast rules are ported from Vibeflux's DeckThemeCatalog.swift.

/// An sRGB color with alpha, 0...1 per channel.
struct HORGB: Hashable, Sendable {
    var r: Double
    var g: Double
    var b: Double
    var a: Double = 1

    init(r: Double, g: Double, b: Double, a: Double = 1) {
        self.r = r
        self.g = g
        self.b = b
        self.a = a
    }

    init(hex: UInt32, alpha: Double = 1) {
        self.init(r: Double((hex >> 16) & 0xFF) / 255, g: Double((hex >> 8) & 0xFF) / 255,
                  b: Double(hex & 0xFF) / 255, a: alpha)
    }

    static let white = HORGB(hex: 0xFFFFFF)
    static let black = HORGB(hex: 0x000000)

    /// The same color at `alpha`.
    func alpha(_ alpha: Double) -> HORGB { HORGB(r: r, g: g, b: b, a: alpha) }

    /// This color drawn over an opaque `background`.
    func over(_ background: HORGB) -> HORGB {
        HORGB(r: r * a + background.r * (1 - a), g: g * a + background.g * (1 - a), b: b * a + background.b * (1 - a))
    }

    /// Every channel moved by `amount` (the grain's lift, or dip when negative), kept in range.
    func lifted(_ amount: Double) -> HORGB {
        HORGB(r: min(1, max(0, r + amount)), g: min(1, max(0, g + amount)), b: min(1, max(0, b + amount)), a: a)
    }

    /// WCAG relative luminance (opaque colors).
    var luminance: Double {
        func linear(_ c: Double) -> Double { c <= 0.040_45 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4) }
        return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
    }

    /// WCAG contrast ratio of this color drawn over `background`, 1...21.
    func contrast(on background: HORGB) -> Double {
        let a = over(background).luminance, b = background.luminance
        return (max(a, b) + 0.05) / (min(a, b) + 0.05)
    }
}

/// Every color of one theme in one look (DESIGN.md 2.1).
///
/// Contrast rules (checked for every look by ThemeContrastTests, WCAG AA):
/// - Text, 4.5:1: ink and ink2 on paper, raised, well and the accent wash; accentInk, good, caution and bad on
///   paper, raised, well and their own wash; onAccent on accent.
/// - Marks, 3:1: the accent fill and idle on paper, raised and well; ink3 on paper and raised.
/// Paper is checked on the grain's lightest and darkest pixel too.
struct ThemeTokens: Hashable, Sendable {
    var isDark: Bool
    var paper, raised, well: HORGB
    var ink, ink2, ink3: HORGB
    var line, lineStrong: HORGB
    var accent, onAccent, accentInk: HORGB
    var good, caution, bad, idle: HORGB
    /// How far the worst grain pixel moves brightness either way (0 to 1), or nil with no grain.
    var grain: Double?

    /// Wash strength for tones: 12% light, 16% dark.
    var washAlpha: Double { isDark ? 0.16 : 0.12 }
    var accentSoft: HORGB { accent.alpha(washAlpha) }
    func wash(_ tone: HORGB) -> HORGB { tone.alpha(washAlpha) }
    var hover: HORGB { isDark ? HORGB.white.alpha(0.06) : ink.alpha(0.05) }
    var pressed: HORGB { isDark ? HORGB.white.alpha(0.10) : ink.alpha(0.09) }

    /// The video roles, the same in every theme.
    static let stage = HORGB(hex: 0x000000)
    static let captionFill = HORGB(hex: 0x000000, alpha: 0.72)
    static let captionInk = HORGB(hex: 0xFFFFFF)
    static let record = HORGB(hex: 0xD70015)

    /// Builds a look from THEMES.md's notation: ink2 and ink3 are alphas of ink, lines are alphas of ink in
    /// light looks and of white in dark ones, and missing tones take the light or dark defaults.
    static func make(dark: Bool, paper: UInt32, raised: UInt32, well: UInt32, ink: UInt32, ink2: Double,
                     ink3: Double, line: Double? = nil, lineStrong: Double? = nil, accent: UInt32,
                     onAccent: UInt32, accentInk: UInt32? = nil, good: UInt32? = nil, caution: UInt32? = nil,
                     bad: UInt32? = nil, idle: UInt32? = nil, grain: Double? = nil) -> ThemeTokens {
        let inkRGB = HORGB(hex: ink)
        let lineBase = dark ? HORGB.white : inkRGB
        return ThemeTokens(
            isDark: dark, paper: HORGB(hex: paper), raised: HORGB(hex: raised), well: HORGB(hex: well),
            ink: inkRGB, ink2: inkRGB.alpha(ink2), ink3: inkRGB.alpha(ink3),
            line: lineBase.alpha(line ?? (dark ? 0.10 : 0.09)),
            lineStrong: lineBase.alpha(lineStrong ?? (dark ? 0.17 : 0.16)),
            accent: HORGB(hex: accent), onAccent: HORGB(hex: onAccent), accentInk: HORGB(hex: accentInk ?? accent),
            good: HORGB(hex: good ?? (dark ? 0x30D158 : 0x186629)),
            caution: HORGB(hex: caution ?? (dark ? 0xFF9F0A : 0x934000)),
            bad: HORGB(hex: bad ?? (dark ? 0xFF6961 : 0xB80011)),
            idle: HORGB(hex: idle ?? (dark ? 0x8E8E93 : 0x6E6E73)),
            grain: grain)
    }

    /// A surface as text sees it: with the grain's darkest and lightest pixel where there is grain.
    func samples(_ surface: HORGB) -> [HORGB] {
        guard let grain else { return [surface] }
        return [surface.lifted(-grain), surface, surface.lifted(grain)]
    }

    /// Paper at its worst grain pixel for text: dipped under dark text, lifted under light text.
    var worstPaper: HORGB {
        guard let grain else { return paper }
        return paper.lifted(isDark ? grain : -grain)
    }

    /// Every pair that falls below the rules above, as readable lines. Empty when the look passes.
    func contrastProblems(textMinimum: Double = 4.5) -> [String] {
        var problems: [String] = []
        func check(_ name: String, _ fg: HORGB, on bgName: String, _ backgrounds: [HORGB], _ need: Double) {
            for bg in backgrounds {
                let ratio = fg.contrast(on: bg)
                if ratio < need { problems.append("\(name) on \(bgName): \(String(format: "%.2f", ratio)) < \(need)") }
            }
        }
        let paperSamples = samples(paper)
        let surfaces: [(String, [HORGB])] = [("paper", paperSamples), ("raised", [raised]), ("well", [well])]
        let tinted: [(String, HORGB)] = [("accentInk", accentInk), ("good", good), ("caution", caution), ("bad", bad)]
        for (bgName, bgs) in surfaces {
            for (name, fg) in [("ink", ink), ("ink2", ink2)] + tinted { check(name, fg, on: bgName, bgs, textMinimum) }
            check("idle", idle, on: bgName, bgs, 3)
            check("accent fill", accent, on: bgName, bgs, 3)
            if bgName != "well" { check("ink3", ink3, on: bgName, bgs, 3) }
        }
        for (name, tone) in tinted {
            check(name, tone, on: "its wash", [wash(tone).over(raised)] + paperSamples.map { wash(tone).over($0) },
                  textMinimum)
        }
        for (name, fg) in [("ink", ink), ("ink2", ink2)] {
            check(name, fg, on: "accent wash", [accentSoft.over(raised)], textMinimum)
        }
        check("onAccent", onAccent, on: "accent", [accent], textMinimum)
        return problems
    }
}

/// The themes in picker order. Raw values are stored (`@AppStorage`) and may sync, so they never change.
enum ThemeID: String, CaseIterable, Identifiable, Sendable {
    case system, night, highContrast, ivory, dim
    case grain, newsprint, chalkboard
    case harbor, sage, clay, nocturne
    case mono, matte

    static let fallback = ThemeID.system
    var id: String { rawValue }

    /// Unknown or missing stored values fall back to Default.
    init(stored: String?) { self = stored.flatMap(ThemeID.init(rawValue:)) ?? .fallback }

    enum Group: String, CaseIterable, Identifiable, Sendable {
        case classic, grain, color, mono
        var id: String { rawValue }
        var title: String {
            switch self {
            case .classic: "Classic"
            case .grain: "Grain"
            case .color: "Color"
            case .mono: "Mono"
            }
        }
        var themes: [ThemeID] { ThemeID.allCases.filter { $0.group == self } }
    }

    /// Whether a theme follows the system light or dark setting, or keeps one look.
    enum Looks: Sendable {
        case followsSystem, alwaysLight, alwaysDark
    }

    var group: Group {
        switch self {
        case .system, .night, .highContrast, .ivory, .dim: .classic
        case .grain, .newsprint, .chalkboard: .grain
        case .harbor, .sage, .clay, .nocturne: .color
        case .mono, .matte: .mono
        }
    }

    var name: String {
        switch self {
        case .system: "Default"
        case .night: "Night"
        case .highContrast: "High Contrast"
        case .ivory: "Ivory"
        case .dim: "Dim"
        case .grain: "Grain"
        case .newsprint: "Newsprint"
        case .chalkboard: "Chalkboard"
        case .harbor: "Harbor"
        case .sage: "Sage"
        case .clay: "Clay"
        case .nocturne: "Nocturne"
        case .mono: "Mono"
        case .matte: "Matte"
        }
    }

    /// The one line under the name in the picker.
    var blurb: String {
        switch self {
        case .system: "Cool gray, HandOver blue"
        case .night: "True black for OLED"
        case .highContrast: "Firmer text and edges"
        case .ivory: "Cream and ink blue"
        case .dim: "Gentle dark slate"
        case .grain: "Paper with a fine grain"
        case .newsprint: "Gray stock, red ink"
        case .chalkboard: "Chalk on green"
        case .harbor: "Cool teal"
        case .sage: "Muted green"
        case .clay: "Terracotta"
        case .nocturne: "Navy, always dark"
        case .mono: "Black and white"
        case .matte: "Gray, low glare"
        }
    }

    /// Extra words the picker's search matches.
    var keywords: String {
        switch self {
        case .system: "auto automatic"
        case .night: "black oled amoled"
        case .highContrast: "accessibility contrast bold"
        case .mono: "black white grayscale"
        case .matte: "eink e-ink grayscale reader"
        default: ""
        }
    }

    var looks: Looks {
        switch self {
        case .night, .dim, .chalkboard, .nocturne: .alwaysDark
        case .newsprint, .matte: .alwaysLight
        default: .followsSystem
        }
    }

    /// No hue anywhere: status keeps its meaning through its word and symbol.
    var isMono: Bool { group == .mono }

    /// The look to draw in, given whether the system (or the Appearance setting) is dark.
    func tokens(dark: Bool) -> ThemeTokens {
        switch looks {
        case .alwaysDark: Self.table[self]!.dark
        case .alwaysLight: Self.table[self]!.light
        case .followsSystem: dark ? Self.table[self]!.dark : Self.table[self]!.light
        }
    }

    /// The light and dark looks. Themes with one look list it twice.
    private static let table: [ThemeID: (light: ThemeTokens, dark: ThemeTokens)] = {
        typealias T = ThemeTokens
        var t: [ThemeID: (light: ThemeTokens, dark: ThemeTokens)] = [:]
        func one(_ id: ThemeID, _ look: ThemeTokens) { t[id] = (look, look) }

        t[.system] = (
            T.make(dark: false, paper: 0xF0F1F2, raised: 0xFBFBFC, well: 0xE4E5E8, ink: 0x1A1B1E, ink2: 0.70,
                   ink3: 0.50, accent: 0x3E5FD9, onAccent: 0xFFFFFF, accentInk: 0x3249B8),
            T.make(dark: true, paper: 0x131416, raised: 0x1D1E21, well: 0x26272B, ink: 0xEDEEF0, ink2: 0.68,
                   ink3: 0.46, accent: 0x8AA8FF, onAccent: 0x0E1630))
        one(.night, T.make(dark: true, paper: 0x000000, raised: 0x0F0F11, well: 0x1C1C1F, ink: 0xF2F2F4, ink2: 0.66,
                           ink3: 0.44, line: 0.12, lineStrong: 0.20, accent: 0x8AA8FF, onAccent: 0x0E1630))
        t[.highContrast] = (
            T.make(dark: false, paper: 0xFFFFFF, raised: 0xF2F2F4, well: 0xE3E3E8, ink: 0x000000, ink2: 0.84,
                   ink3: 0.66, line: 0.42, lineStrong: 0.66, accent: 0x0030C0, onAccent: 0xFFFFFF,
                   good: 0x0B5E25, caution: 0x7A3300, bad: 0xA3000E, idle: 0x5E5E62),
            T.make(dark: true, paper: 0x000000, raised: 0x1A1A1C, well: 0x2A2A2E, ink: 0xFFFFFF, ink2: 0.86,
                   ink3: 0.66, line: 0.45, lineStrong: 0.70, accent: 0xADC4FF, onAccent: 0x00102E,
                   good: 0x6CF294, caution: 0xFFC46B, bad: 0xFF8A80, idle: 0xB4B4B8))
        t[.ivory] = (
            T.make(dark: false, paper: 0xF4F1EA, raised: 0xFCFBF7, well: 0xE9E5DB, ink: 0x221E18, ink2: 0.70,
                   ink3: 0.50, accent: 0x255EA8, onAccent: 0xFFFFFF, accentInk: 0x1F4F8E),
            T.make(dark: true, paper: 0x1A1815, raised: 0x24211D, well: 0x2E2A25, ink: 0xEFEAE0, ink2: 0.68,
                   ink3: 0.46, accent: 0x95B7EE, onAccent: 0x0E1A30, bad: 0xFF7A70))
        one(.dim, T.make(dark: true, paper: 0x1F2227, raised: 0x272A30, well: 0x30343A, ink: 0xE1E4E8, ink2: 0.72,
                         ink3: 0.50, accent: 0x93ACF2, onAccent: 0x101830, bad: 0xFF8A82, idle: 0x9696A0))
        t[.grain] = (
            T.make(dark: false, paper: 0xEEEDE9, raised: 0xFAFAF8, well: 0xE3E2DD, ink: 0x1C1B19, ink2: 0.72,
                   ink3: 0.52, accent: 0x34519F, onAccent: 0xFFFFFF, bad: 0xA8000F, grain: 0.030),
            T.make(dark: true, paper: 0x171716, raised: 0x21211F, well: 0x2B2B29, ink: 0xEEEDEA, ink2: 0.70,
                   ink3: 0.48, accent: 0x9DB1F2, onAccent: 0x111A33, grain: 0.025))
        one(.newsprint, T.make(dark: false, paper: 0xE8E6E1, raised: 0xF5F4F0, well: 0xDCDAD4, ink: 0x141414,
                               ink2: 0.74, ink3: 0.54, accent: 0xA3221E, onAccent: 0xFFFFFF, accentInk: 0x961E1A,
                               good: 0x155C25, caution: 0x843900, bad: 0x9E000F, idle: 0x626266, grain: 0.035))
        one(.chalkboard, T.make(dark: true, paper: 0x1D2A25, raised: 0x24332D, well: 0x2C3C36, ink: 0xEEF2EC,
                                ink2: 0.74, ink3: 0.52, line: 0.12, lineStrong: 0.20, accent: 0xF0E19A,
                                onAccent: 0x2A2600, good: 0x7CF0A0, caution: 0xFFC071, bad: 0xFF9C93,
                                idle: 0xA3B0AA, grain: 0.030))
        t[.harbor] = (
            T.make(dark: false, paper: 0xECF0F1, raised: 0xF9FBFB, well: 0xDEE5E7, ink: 0x15202A, ink2: 0.72,
                   ink3: 0.50, accent: 0x0F6680, onAccent: 0xFFFFFF, accentInk: 0x0B5A71),
            T.make(dark: true, paper: 0x0F1619, raised: 0x172024, well: 0x202B30, ink: 0xE6EEF1, ink2: 0.70,
                   ink3: 0.46, accent: 0x6CC4DB, onAccent: 0x06222B))
        t[.sage] = (
            T.make(dark: false, paper: 0xEEF1EC, raised: 0xFAFBF8, well: 0xE1E6DE, ink: 0x1A211B, ink2: 0.72,
                   ink3: 0.50, accent: 0x3E6B48, onAccent: 0xFFFFFF, accentInk: 0x345C3D),
            T.make(dark: true, paper: 0x141814, raised: 0x1C221C, well: 0x252C25, ink: 0xE7EEE6, ink2: 0.70,
                   ink3: 0.46, accent: 0x9CCB9F, onAccent: 0x10241A))
        t[.clay] = (
            T.make(dark: false, paper: 0xF3EEEA, raised: 0xFCFAF8, well: 0xE8E0D9, ink: 0x241B17, ink2: 0.72,
                   ink3: 0.50, accent: 0xA8452A, onAccent: 0xFFFFFF, accentInk: 0x963C22),
            T.make(dark: true, paper: 0x1B1513, raised: 0x251D1A, well: 0x2F2622, ink: 0xF2E9E4, ink2: 0.70,
                   ink3: 0.46, accent: 0xF0A07E, onAccent: 0x2E1208))
        one(.nocturne, T.make(dark: true, paper: 0x0E1221, raised: 0x151A2D, well: 0x1D2339, ink: 0xE6E9F5,
                              ink2: 0.70, ink3: 0.46, accent: 0x9AAEFF, onAccent: 0x101640))
        t[.mono] = (
            T.make(dark: false, paper: 0xFFFFFF, raised: 0xF6F6F6, well: 0xEBEBEB, ink: 0x000000, ink2: 0.66,
                   ink3: 0.46, line: 0.12, lineStrong: 0.20, accent: 0x000000, onAccent: 0xFFFFFF,
                   good: 0x000000, caution: 0x555555, bad: 0x000000, idle: 0x777777),
            T.make(dark: true, paper: 0x000000, raised: 0x121212, well: 0x222222, ink: 0xFFFFFF, ink2: 0.68,
                   ink3: 0.46, line: 0.14, lineStrong: 0.22, accent: 0xFFFFFF, onAccent: 0x000000,
                   good: 0xFFFFFF, caution: 0xAAAAAA, bad: 0xFFFFFF, idle: 0x888888))
        one(.matte, T.make(dark: false, paper: 0xE7E6E2, raised: 0xF1F0EC, well: 0xDBDAD5, ink: 0x1E1E1E,
                           ink2: 0.74, ink3: 0.54, line: 0.12, lineStrong: 0.20, accent: 0x2E2E2E,
                           onAccent: 0xF1F0EC, good: 0x1E1E1E, caution: 0x4F4F4F, bad: 0x1E1E1E, idle: 0x6A6A6A))
        return t
    }()
}

/// The grain tile (DESIGN.md 2.7): 128 x 128 px, SplitMix64 seeded with 0x6465636B67726169. Per pixel
/// `n = (r1 + r2 + r3) / 3 - 0.5`; white (lift) when `n > 0`, black (dip) otherwise, at alpha
/// `abs(n) * 2 * amount * 2.2`, clamped. Drawn once, tiled, never animated. Same bytes as Vibeflux's.
enum GrainTile {
    static let side = 128
    static let seed: UInt64 = 0x6465_636B_6772_6169

    /// Premultiplied RGBA bytes, row by row.
    static func rgba(amount: Double) -> [UInt8] {
        var bytes = [UInt8](repeating: 0, count: side * side * 4)
        var state = seed
        func next() -> Double {
            state &+= 0x9E37_79B9_7F4A_7C15
            var z = state
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            z ^= z >> 31
            return Double(z >> 11) / Double(UInt64(1) << 53)
        }
        for i in 0..<(side * side) {
            let n = (next() + next() + next()) / 3 - 0.5
            let alpha = UInt8((min(1, max(0, abs(n) * 2 * amount * 2.2)) * 255).rounded())
            let value = n > 0 ? alpha : 0
            bytes[i * 4] = value
            bytes[i * 4 + 1] = value
            bytes[i * 4 + 2] = value
            bytes[i * 4 + 3] = alpha
        }
        return bytes
    }
}
