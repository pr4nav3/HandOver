import SwiftUI

// Spacing, sizes, radii, lines, motion and shadows (DESIGN.md 2.3 to 2.8). Names match Kotlin and the web.

/// The spacing grid, in points.
enum HOSpace {
    static let xxs: CGFloat = 2
    static let xs: CGFloat = 4
    static let s: CGFloat = 8
    static let m: CGFloat = 12
    /// Screen margin on iPhone, card padding.
    static let l: CGFloat = 16
    /// Screen margin on iPad and Mac, between sections.
    static let xl: CGFloat = 24
    static let xxl: CGFloat = 32
    static let xxxl: CGFloat = 48
}

/// Control sizes at the default text size.
enum HOSize {
    /// The smallest hit area on iOS and Mac touch surfaces.
    static let touch: CGFloat = 44
    static let controlSmall: CGFloat = 32
    static let control: CGFloat = 44
    /// Next, Record, Make Course.
    static let controlLarge: CGFloat = 52
    /// Visible size of a round icon button, inside a 44 point hit area.
    static let iconButton: CGFloat = 36
    static let badge: CGFloat = 22
    static let dot: CGFloat = 9
    static let tile: CGFloat = 32
    /// iPhone portrait PiP tile: 30% of the screen width, at least 112 wide.
    static let pipFraction: CGFloat = 0.30
    static let pipMinWidth: CGFloat = 112
}

/// Continuous corner radii.
enum HORadius {
    /// Chips, timeline segments, step list thumbnails.
    static let small: CGFloat = 8
    /// Buttons, fields, rows, segmented control, mistake card on iPhone.
    static let control: CGFloat = 12
    /// Large buttons.
    static let controlLarge: CGFloat = 16
    /// Cards, video panes on iPhone.
    static let card: CGFloat = 18
    /// Sheet panels, floating glass panels, video panes on iPad and Mac.
    static let panel: CGFloat = 24
    /// The PiP tile.
    static let pip: CGFloat = 16
}

/// Layout breakpoints shared by screens.
enum HOLayout {
    /// Below this height a screen is short (iPhone landscape): pages scroll, pinned buttons move into the scroll,
    /// and overlays take one row.
    static let shortHeight: CGFloat = 480

    static func isShort(_ height: CGFloat) -> Bool { height < shortHeight }
}

/// Hairlines: half a point in `line`.
enum HOLine {
    static let width: CGFloat = 0.5
}

/// Springs and timings (DESIGN.md 2.8). With Reduce Motion every animation becomes `reduced`.
enum HOMotion {
    /// Sheets, the mistake card in and out, toasts, onboarding.
    static let panel = Animation.spring(response: 0.38, dampingFraction: 0.82)
    /// Progress segments filling, PiP snapping to a corner, reorder.
    static let layout = Animation.spring(response: 0.34, dampingFraction: 0.86)
    /// Badge label changes, small state changes.
    static let snappy = Animation.snappy(duration: 0.25)
    /// Button press: scale 0.98, primary fill to 82%.
    static let press = Animation.easeOut(duration: 0.12)
    /// Cross-fade between step clips.
    static let clip = Animation.easeInOut(duration: 0.20)
    /// Shutter circle to rounded square and back.
    static let shutter = Animation.spring(response: 0.30, dampingFraction: 0.80)
    /// What every animation becomes with Reduce Motion.
    static let reduced = Animation.easeInOut(duration: 0.15)

    /// `animation`, or `reduced` when Reduce Motion is on.
    static func resolve(_ animation: Animation, reduceMotion: Bool) -> Animation {
        reduceMotion ? reduced : animation
    }
}

/// Shadows, only for things that float (toasts, the PiP tile).
enum HOShadow {
    static func floating(dark: Bool) -> (near: Color, far: Color) {
        dark ? (Color.black.opacity(0.30), Color.black.opacity(0.45))
            : (Color(white: 0.08).opacity(0.06), Color(white: 0.08).opacity(0.16))
    }

    /// Under the raised segment of a segmented control. Light only.
    static func segment(dark: Bool) -> Color { dark ? .clear : Color.black.opacity(0.06) }
}

/// The type tokens with their tracking (DESIGN.md 2.2). `Text("x").hoFont(.display, theme)`.
enum HOTextStyle: Sendable {
    case largeTitle, display, stepTitle, title, headline, body, bodyMedium, callout, section, footnote, caption
    case badge, numeral, timer, code, captionText

    func font(_ scale: FontScale) -> Font {
        switch self {
        case .largeTitle: scale.largeTitle
        case .display: scale.display
        case .stepTitle: scale.stepTitle
        case .title: scale.title
        case .headline: scale.headline
        case .body: scale.body
        case .bodyMedium: scale.bodyMedium
        case .callout: scale.callout
        case .section: scale.section
        case .footnote: scale.footnote
        case .caption: scale.caption
        case .badge: scale.badge
        case .numeral: scale.numeral
        case .timer: scale.timer
        case .code: scale.code
        case .captionText: scale.captionText
        }
    }

    var tracking: CGFloat {
        switch self {
        case .largeTitle: -0.4
        case .display, .title: -0.3
        case .stepTitle: -0.2
        default: 0
        }
    }
}

/// The Caption Size setting: a multiple of `.body`, with Dynamic Type on top.
enum CaptionSize: String, CaseIterable, Identifiable, Sendable {
    case small, medium, large, extraLarge
    static let storageKey = "handover.captionSize"
    var id: String { rawValue }
    var scale: CGFloat {
        switch self {
        case .small: 0.85
        case .medium: 1.0
        case .large: 1.25
        case .extraLarge: 1.5
        }
    }
    var title: String {
        switch self {
        case .small: "Small"
        case .medium: "Medium"
        case .large: "Large"
        case .extraLarge: "Extra Large"
        }
    }
}

extension View {
    /// A type token with its tracking.
    func hoFont(_ style: HOTextStyle, _ theme: any Theme) -> some View {
        font(style.font(theme.fonts)).tracking(style.tracking)
    }
}
