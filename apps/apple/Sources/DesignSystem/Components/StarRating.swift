import SwiftUI

/// Five stars, 32 points in 44 point hit areas (DESIGN.md 3.23). Tap sets, drag across scrubs with a `tap`
/// haptic per star. `accent` filled, `ink3` empty (Mono: `ink`). VoiceOver: one adjustable element.
struct StarRating: View {
    @Binding var rating: Int
    var starSize: CGFloat = 32
    var readOnly = false
    @Environment(\.theme) private var theme

    var body: some View {
        let hit = readOnly ? starSize : max(HOSize.touch, starSize + 12)
        HStack(spacing: 0) {
            ForEach(1...5, id: \.self) { i in
                Image(systemName: i <= rating ? "star.fill" : "star")
                    .font(.system(size: starSize * 0.82))
                    .foregroundStyle(i <= rating ? (theme.isMono ? theme.colors.ink : theme.colors.accent)
                                     : (theme.isMono ? theme.colors.ink : theme.colors.ink3))
                    .frame(width: hit, height: hit)
                    .contentShape(Rectangle())
            }
        }
        .gesture(readOnly ? nil : DragGesture(minimumDistance: 0).onChanged { value in
            let n = min(5, max(1, Int(value.location.x / hit) + 1))
            if n != rating {
                rating = n
                Haptics.tap()
            }
        })
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Rating")
        .accessibilityValue("\(rating) of 5 stars")
        .accessibilityAdjustableAction { direction in
            guard !readOnly else { return }
            switch direction {
            case .increment: rating = min(5, rating + 1)
            case .decrement: rating = max(1, rating - 1)
            @unknown default: break
            }
        }
    }
}
