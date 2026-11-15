import CoreGraphics
import SwiftUI

// The grain on `paper` in grain themes (DESIGN.md 2.7): the GrainTile bytes made into an image once per amount
// and tiled at one tile pixel per device pixel. Never animated, never drawn over video, sheets or `raised`.

@MainActor
enum GrainImage {
    private static var cache: [Double: CGImage] = [:]

    /// The tile for `amount`, made once and kept.
    static func tile(amount: Double) -> CGImage? {
        if let hit = cache[amount] { return hit }
        let side = GrainTile.side
        let bytes = GrainTile.rgba(amount: amount)
        guard let provider = CGDataProvider(data: Data(bytes) as CFData),
              let image = CGImage(width: side, height: side, bitsPerComponent: 8, bitsPerPixel: 32,
                                  bytesPerRow: side * 4, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.premultipliedLast.rawValue),
                                  provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent)
        else { return nil }
        cache[amount] = image
        return image
    }
}

/// The still grain over whatever is behind it, for the current theme and look. Draws nothing in themes
/// without grain.
struct GrainOverlay: View {
    @Environment(\.theme) private var theme
    @Environment(\.colorScheme) private var scheme
    @Environment(\.displayScale) private var displayScale

    var body: some View {
        if let amount = theme.grainAmount(dark: scheme == .dark), let tile = GrainImage.tile(amount: amount) {
            Image(decorative: tile, scale: displayScale)
                .resizable(resizingMode: .tile)
                .interpolation(.none)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

extension View {
    /// Fills behind this view with `paper` and its grain, edge to edge.
    func hoPaperBackground() -> some View {
        modifier(PaperBackground())
    }
}

private struct PaperBackground: ViewModifier {
    @Environment(\.theme) private var theme

    func body(content: Content) -> some View {
        content.background {
            ZStack {
                theme.colors.paper
                GrainOverlay()
            }
            .ignoresSafeArea()
        }
    }
}
