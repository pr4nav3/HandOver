import SwiftUI

/// Time words used across Learn and Done.
enum HOTime {
    /// "12 s" under a minute, else "1:05" (Learn.tsx `formatSecs`).
    static func short(_ seconds: Double) -> String {
        let s = Int(seconds.rounded())
        return s < 60 ? "\(s) s" : clock(Double(s))
    }

    /// "m:ss".
    static func clock(_ seconds: Double) -> String {
        let s = max(0, Int(seconds.rounded()))
        let r = s % 60
        return "\(s / 60):\(r < 10 ? "0" : "")\(r)"
    }

    /// For VoiceOver: "14 seconds", "1 minute 5 seconds".
    static func spoken(_ seconds: Double) -> String {
        let s = max(0, Int(seconds.rounded()))
        let m = s / 60, r = s % 60
        let sec = "\(r) second\(r == 1 ? "" : "s")"
        guard m > 0 else { return sec }
        let min = "\(m) minute\(m == 1 ? "" : "s")"
        return r == 0 ? min : "\(min) \(sec)"
    }
}

/// The note after each finished step (DESIGN.md 3.19, SCREENS.md 7.10).
struct StepResult: Equatable, Sendable {
    var symbol: String
    var text: String

    /// The copy rules. `yours` is nil when the step was entered less than 1 s ago or the timer was
    /// interrupted; `expert` is the step's `end - start`.
    static func make(yours: Double?, expert: Double?, mistakesFixed: Int, byCamera: Bool) -> StepResult {
        if mistakesFixed > 0 {
            return StepResult(symbol: "checkmark",
                              text: "Done. \(mistakesFixed) mistake\(mistakesFixed == 1 ? "" : "s") fixed.")
        }
        if let yours, yours >= 1 {
            let t = HOTime.short(yours)
            if let expert, expert > 0 {
                let ratio = yours / expert
                if ratio < 0.9 { return StepResult(symbol: "hare", text: "Nice. \(t), faster than the expert.") }
                if ratio <= 1.1 { return StepResult(symbol: "checkmark", text: "Done. \(t), about the expert's time.") }
            }
            return StepResult(symbol: "checkmark", text: "Done in \(t).")
        }
        return byCamera ? StepResult(symbol: "checkmark.circle", text: "Verified.")
            : StepResult(symbol: "checkmark", text: "Done.")
    }
}

/// A glass capsule centered at the top of the clip pane, symbol plus one line. Never blocks; the caller shows
/// it for 1.5 s and replaces it at once when a new one arrives.
struct StepResultMoment: View {
    var result: StepResult
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.s) {
            Image(systemName: result.symbol).accessibilityHidden(true)
            Text(result.text).lineLimit(2)
        }
        .font(theme.fonts.callout.weight(.semibold))
        .foregroundStyle(.white)
        .padding(.horizontal, HOSpace.m)
        .padding(.vertical, HOSpace.s)
        .hoGlassCapsule()
        .accessibilityElement(children: .combine)
    }
}
