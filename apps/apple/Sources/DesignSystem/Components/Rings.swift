import SwiftUI

/// Track `well`, fill `accent`, round caps (DESIGN.md 3.21). 4 point stroke at 28, 8 at 96, in between in
/// proportion. Completed draws `good` with a check in the center.
struct ProgressRing: View {
    /// 0...1.
    var fraction: Double
    var size: CGFloat = 28
    /// Center text in `numeral` (shown from 44 points up).
    var center: String?
    var completed = false
    @Environment(\.theme) private var theme

    private var stroke: CGFloat { max(3, min(8, 4 + (size - 28) * (4 / 68))) }

    var body: some View {
        let clamped = min(1, max(0, completed ? 1 : fraction))
        ZStack {
            Circle().stroke(theme.colors.well, lineWidth: stroke)
            Circle()
                .trim(from: 0, to: clamped)
                .stroke(completed ? theme.colors.good : theme.colors.accent,
                        style: StrokeStyle(lineWidth: stroke, lineCap: .round))
                .rotationEffect(.degrees(-90))
            if completed {
                Image(systemName: "checkmark")
                    .font(.system(size: size * 0.36, weight: .bold))
                    .foregroundStyle(theme.colors.good)
            } else if let center, size >= 44 {
                Text(center)
                    .font(.system(size: size * 0.28, weight: .semibold, design: .rounded).monospacedDigit())
                    .foregroundStyle(theme.colors.ink)
                    .minimumScaleFactor(0.6)
            }
        }
        .padding(stroke / 2)
        .frame(width: size, height: size)
        .hoAnimation(HOMotion.layout, value: clamped)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Progress")
        .accessibilityValue(completed ? "Complete" : "\(Int((clamped * 100).rounded())) percent")
    }
}

/// The Done screen's score (DESIGN.md 3.21): 120 points, 10 point stroke, filled in the label's tone, the
/// number in rounded numerals with the label under it. With no score: the track only and "Not enough data".
struct ScoreRing: View {
    var score: Int?
    /// The hub's label when it sent one; otherwise from SCREENS.md 8's bands.
    var label: String?
    var size: CGFloat = 120
    /// Fill from 0 on appear over 0.6 s. Off for snapshots, where `onAppear` does not run.
    var animateIn = true
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown: Double = 0

    /// SCREENS.md 8: 85 to 100 Excellent, 60 to 84 Good, below Keep practicing.
    static func label(for score: Int) -> String {
        score >= 85 ? "Excellent" : score >= 60 ? "Good" : "Keep practicing"
    }

    static func tone(for label: String) -> HOTone {
        switch label {
        case "Excellent": .good
        case "Good": .accent
        default: .caution
        }
    }

    var body: some View {
        let shownLabel = score.map { label ?? Self.label(for: $0) }
        let tone = shownLabel.map(Self.tone(for:)) ?? .neutral
        ZStack {
            Circle().stroke(theme.colors.well, lineWidth: 10)
            if let score {
                Circle()
                    .trim(from: 0, to: (animateIn ? shown : 1) * Double(min(100, max(0, score))) / 100)
                    .stroke(tone.color(theme.colors), style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                VStack(spacing: 0) {
                    Text("\(score)")
                        .font(.system(.largeTitle, design: .rounded).weight(.semibold).monospacedDigit())
                        .foregroundStyle(theme.colors.ink)
                    Text(shownLabel ?? "")
                        .font(theme.fonts.callout)
                        .foregroundStyle(tone.text(theme.colors))
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
                .padding(HOSpace.m)
            } else {
                Text("Not enough data")
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
                    .padding(HOSpace.l)
            }
        }
        .padding(5)
        .frame(width: size, height: size)
        .onAppear {
            if reduceMotion {
                shown = 1
            } else {
                withAnimation(.easeOut(duration: 0.6)) { shown = 1 }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(score.map { "Score \($0) of 100, \((shownLabel ?? "").lowercased())" } ?? "Score: not enough data")
    }
}
