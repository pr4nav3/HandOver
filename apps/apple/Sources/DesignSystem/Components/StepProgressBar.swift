import SwiftUI

/// One segment per step at the top of Learn (DESIGN.md 3.3): done `good`, current `accent` (or `caution` while a
/// behind mistake is shown), upcoming `well`. Over 20 steps it becomes one bar with a tick for the current step.
/// No lesson shows one `well` segment.
struct StepProgressBar: View {
    /// Number of steps; 0 with no lesson.
    var total: Int
    /// 0-based current step; `total` when the lesson is done.
    var current: Int
    var mistakeOnCurrent = false
    /// When set (iPad and Mac), tapping a segment offers "Go to Step N".
    var onGoto: ((Int) -> Void)?
    @Environment(\.theme) private var theme

    static let segmentLimit = 20

    enum Segment: Equatable {
        case done, current, currentMistake, upcoming
    }

    /// The fill of every segment, pure so it can be tested.
    static func segments(total: Int, current: Int, mistake: Bool) -> [Segment] {
        guard total > 0 else { return [.upcoming] }
        return (0..<total).map { i in
            if i < current { return .done }
            if i == current { return mistake ? .currentMistake : .current }
            return .upcoming
        }
    }

    var body: some View {
        Group {
            if total > Self.segmentLimit {
                continuous
            } else {
                segmented
            }
        }
        .frame(height: 4)
        .hoAnimation(HOMotion.layout, value: current)
        .hoAnimation(HOMotion.layout, value: mistakeOnCurrent)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Progress")
        .accessibilityValue(total == 0 ? "No lesson" : current >= total
                            ? "All \(total) steps done" : "Step \(current + 1) of \(total)")
        .accessibilityAdjustableAction { direction in
            guard let onGoto, total > 0 else { return }
            switch direction {
            case .increment: if current + 1 < total { onGoto(current + 1) }
            case .decrement: if current > 0 { onGoto(current - 1) }
            @unknown default: break
            }
        }
    }

    private func fill(_ s: Segment) -> Color {
        switch s {
        case .done: theme.colors.good
        case .current: theme.colors.accent
        case .currentMistake: theme.colors.caution
        case .upcoming: theme.colors.well
        }
    }

    private var bars: some View {
        HStack(spacing: 3) {
            ForEach(Array(Self.segments(total: total, current: current, mistake: mistakeOnCurrent).enumerated()),
                    id: \.offset) { _, s in
                RoundedRectangle(cornerRadius: 2, style: .continuous).fill(fill(s))
            }
        }
    }

    @ViewBuilder
    private var segmented: some View {
        if let onGoto, total > 0 {
            Menu {
                ForEach(0..<total, id: \.self) { i in
                    Button("Go to Step \(i + 1)") { onGoto(i) }.disabled(i == current)
                }
            } label: {
                // 44 point hit area around the 4 point bar.
                bars.frame(height: 4).padding(.vertical, 20).contentShape(Rectangle())
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .frame(height: 4)
        } else {
            bars
        }
    }

    private var continuous: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let doneFraction = CGFloat(min(current, total)) / CGFloat(max(total, 1))
            ZStack(alignment: .leading) {
                Capsule().fill(theme.colors.well)
                Capsule().fill(theme.colors.good).frame(width: w * doneFraction)
                if current < total {
                    Rectangle()
                        .fill(mistakeOnCurrent ? theme.colors.caution : theme.colors.accent)
                        .frame(width: 3)
                        .offset(x: min(w - 3, w * doneFraction))
                }
            }
        }
    }
}

#Preview("Progress") {
    VStack(spacing: 24) {
        StepProgressBar(total: 0, current: 0)
        StepProgressBar(total: 8, current: 3)
        StepProgressBar(total: 8, current: 3, mistakeOnCurrent: true)
        StepProgressBar(total: 30, current: 12)
    }
    .padding()
    .hoPaperBackground()
    .handOverTheme(.system, dark: false)
}
