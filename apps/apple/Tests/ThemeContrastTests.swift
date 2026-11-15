import Foundation
import Testing
@testable import HandOver

/// Every theme, light and dark, against the contrast rules in ThemeCatalog.swift (ported from Vibeflux's
/// DeckThemeContrastTests), plus the measured ratios THEMES.md publishes for each text pair.
struct ThemeContrastTests {
    /// Every look that exists: two for themes that follow the system, one for the others.
    static var looks: [(ThemeID, Bool)] {
        ThemeID.allCases.flatMap { id -> [(ThemeID, Bool)] in
            switch id.looks {
            case .followsSystem: [(id, false), (id, true)]
            case .alwaysLight: [(id, false)]
            case .alwaysDark: [(id, true)]
            }
        }
    }

    @Test func fourteenThemesInFourGroups() {
        #expect(ThemeID.allCases.count == 14)
        #expect(ThemeID.Group.allCases.map { $0.themes.count } == [5, 3, 4, 2])
        #expect(Set(ThemeID.allCases.map(\.name)).count == 14)
    }

    @Test func everyLookPassesWCAG() {
        for (id, dark) in Self.looks {
            let problems = id.tokens(dark: dark).contrastProblems()
            #expect(problems.isEmpty, "\(id.rawValue) \(dark ? "dark" : "light"): \(problems)")
        }
    }

    @Test func highContrastReachesSevenToOne() {
        for dark in [false, true] {
            let t = ThemeID.highContrast.tokens(dark: dark)
            for (name, fg, bg) in [("ink", t.ink, t.paper), ("ink2 paper", t.ink2, t.paper), ("ink2 raised", t.ink2, t.raised),
                                   ("accentInk", t.accentInk, t.raised), ("onAccent", t.onAccent, t.accent),
                                   ("good", t.good, t.paper), ("caution", t.caution, t.paper), ("bad", t.bad, t.paper)] {
                #expect(fg.contrast(on: bg) >= 7, "High Contrast \(dark ? "dark" : "light") \(name)")
            }
        }
    }

    /// THEMES.md tables: ink on paper, ink2 on paper, ink2 on raised, accentInk on raised, onAccent on accent.
    /// Paper pairs of grain themes are measured on the worst grain pixel. The doc rounds down to one decimal.
    static let published: [String: [Double]] = [
        "system L": [15.2, 5.9, 6.2, 7.3, 5.4], "system D": [15.8, 7.7, 7.3, 7.2, 7.7],
        "night D": [18.7, 8.0, 7.7, 8.3, 7.7],
        "highContrast L": [21.0, 14.5, 13.4, 8.5, 9.6], "highContrast D": [21.0, 15.1, 13.0, 10.0, 10.8],
        "ivory L": [14.6, 5.7, 6.0, 7.9, 6.4], "ivory D": [14.7, 7.3, 6.9, 7.8, 8.5],
        "dim D": [12.5, 7.1, 6.5, 6.4, 7.8],
        "grain L": [13.6, 6.0, 6.7, 7.1, 7.4], "grain D": [14.4, 7.6, 7.4, 7.6, 8.2],
        "newsprint L": [13.5, 6.6, 7.5, 7.6, 7.4],
        "chalkboard D": [11.7, 7.2, 7.1, 10.0, 11.5],
        "harbor L": [14.3, 6.1, 6.4, 7.4, 6.4], "harbor D": [15.5, 8.0, 7.5, 8.3, 8.3],
        "sage L": [14.4, 6.1, 6.3, 7.3, 6.1], "sage D": [15.1, 7.8, 7.3, 8.8, 8.8],
        "clay L": [14.6, 6.2, 6.5, 6.8, 5.9], "clay D": [15.0, 7.8, 7.3, 7.9, 8.3],
        "nocturne D": [15.3, 7.9, 7.5, 8.1, 8.1],
        "mono L": [21.0, 7.2, 7.1, 19.4, 21.0], "mono D": [21.0, 9.3, 8.9, 18.7, 21.0],
        "matte L": [13.3, 6.2, 6.6, 11.9, 11.9],
    ]

    @Test func matchesPublishedRatios() {
        #expect(Self.published.count == Self.looks.count, "one row per look")
        for (id, dark) in Self.looks {
            let key = "\(id.rawValue) \(dark ? "D" : "L")"
            guard let want = Self.published[key] else {
                Issue.record("no published row for \(key)")
                continue
            }
            let t = id.tokens(dark: dark)
            let paper = t.worstPaper
            let got = [t.ink.contrast(on: paper), t.ink2.contrast(on: paper), t.ink2.contrast(on: t.raised),
                       t.accentInk.contrast(on: t.raised), t.onAccent.contrast(on: t.accent)]
            let names = ["ink on paper", "ink2 on paper", "ink2 on raised", "accentInk on raised", "onAccent on accent"]
            for i in 0..<5 {
                // Rounded down to one decimal in the doc, so the true value is in [want, want + 0.1); allow a
                // little slack for the doc's own rounding of grain samples.
                #expect(got[i] >= want[i] - 0.06 && got[i] < want[i] + 0.16,
                        "\(key) \(names[i]): measured \(String(format: "%.3f", got[i])), THEMES.md says \(want[i])")
            }
        }
    }

    @Test func aKnownFailingPairIsCaught() {
        var t = ThemeID.system.tokens(dark: false)
        t.ink2 = t.ink.alpha(0.3)
        #expect(t.contrastProblems().contains { $0.hasPrefix("ink2 on paper") })
    }

    @Test func blackOnWhiteIs21() {
        #expect(abs(HORGB.black.contrast(on: .white) - 21) < 0.01)
    }

    @Test func storedValuesRoundTripAndUnknownFallsBack() {
        for id in ThemeID.allCases { #expect(ThemeID(stored: id.rawValue) == id) }
        #expect(ThemeID(stored: "plum") == .system)
        #expect(ThemeID(stored: nil) == .system)
    }

    @Test func themesWithOneLookIgnoreTheSystem() {
        #expect(ThemeID.night.tokens(dark: false) == ThemeID.night.tokens(dark: true))
        #expect(ThemeID.newsprint.tokens(dark: true).isDark == false)
        #expect(ThemeID.chalkboard.tokens(dark: false).isDark == true)
        #expect(ThemeStore.isDark(.matte, appearance: .dark, systemDark: true) == false)
        #expect(ThemeStore.isDark(.harbor, appearance: .dark, systemDark: false) == true)
        #expect(ThemeStore.isDark(.harbor, appearance: .system, systemDark: true) == true)
        #expect(ThemeStore.forcedScheme(.dim, appearance: .light) == .dark)
        #expect(ThemeStore.forcedScheme(.system, appearance: .system) == nil)
    }

    @Test func increaseContrastUsesHighContrastValuesAndKeepsTheChoice() {
        let t = ThemeStore.resolve(.clay, dark: false, increaseContrast: true)
        #expect(t.id == .clay)
        #expect(t.light == ThemeID.highContrast.tokens(dark: false))
    }

    @Test func grainSettingsMatchTheSpec() {
        #expect(ThemeID.grain.tokens(dark: false).grain == 0.030)
        #expect(ThemeID.grain.tokens(dark: true).grain == 0.025)
        #expect(ThemeID.newsprint.tokens(dark: false).grain == 0.035)
        #expect(ThemeID.chalkboard.tokens(dark: true).grain == 0.030)
        #expect(ThemeID.allCases.filter { $0.tokens(dark: false).grain != nil || $0.tokens(dark: true).grain != nil }
            == [.grain, .newsprint, .chalkboard])
    }

    @Test func grainTileIsStableAndBounded() {
        let a = GrainTile.rgba(amount: 0.03), b = GrainTile.rgba(amount: 0.03)
        #expect(a == b)
        #expect(a.count == 128 * 128 * 4)
        // alpha = |n| * 2 * amount * 2.2 with |n| <= 0.5, so at most amount * 2.2.
        let maxAlpha = stride(from: 3, to: a.count, by: 4).map { a[$0] }.max() ?? 0
        #expect(Double(maxAlpha) / 255 <= 0.03 * 2.2 + 0.005)
        // Premultiplied: every lift pixel has rgb == alpha, every dip has rgb 0.
        for i in stride(from: 0, to: a.count, by: 4) { #expect(a[i] == 0 || a[i] == a[i + 3]) }
    }
}
