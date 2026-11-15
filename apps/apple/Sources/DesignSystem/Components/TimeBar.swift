import SwiftUI

/// You against the expert for one step (DESIGN.md 3.22): two 6 point bars 2 points apart, Expert in `ink3`, You
/// in `accent` (or `good` when faster), both scaled to the longest time in the lesson. Missing time: no You bar
/// and the words "No time".
struct TimeBar: View {
    var yours: Double?
    var expert: Double?
    /// The longest time across the lesson (yours or expert), so every row shares one scale.
    var longest: Double
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.s) {
            GeometryReader { geo in
                let w = geo.size.width
                VStack(alignment: .leading, spacing: 2) {
                    bar(expert, width: w, color: theme.colors.ink3)
                    if let yours {
                        let faster = expert.map { yours < $0 } ?? false
                        bar(yours, width: w, color: faster ? theme.colors.good : theme.colors.accent)
                    } else {
                        Color.clear.frame(height: 6)
                    }
                }
            }
            .frame(height: 14)
            VStack(alignment: .trailing, spacing: 0) {
                Text(expert.map { HOTime.clock($0) } ?? "No time")
                Text(yours.map { HOTime.clock($0) } ?? "No time")
            }
            .font(theme.fonts.caption.monospacedDigit())
            .foregroundStyle(theme.colors.ink2)
            .frame(minWidth: 44, alignment: .trailing)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.spoken(yours: yours, expert: expert))
    }

    static func spoken(yours: Double?, expert: Double?) -> String {
        let you = yours.map { "You \(HOTime.spoken($0))" } ?? "You, no time"
        let exp = expert.map { "expert \(HOTime.spoken($0))" } ?? "expert, no time"
        return "\(you), \(exp)."
    }

    private func bar(_ value: Double?, width: CGFloat, color: Color) -> some View {
        let fraction = value.map { longest > 0 ? min(1, $0 / longest) : 0 } ?? 0
        return RoundedRectangle(cornerRadius: 3, style: .continuous)
            .fill(color)
            .frame(width: max(value == nil ? 0 : 3, width * fraction), height: 6)
    }
}
