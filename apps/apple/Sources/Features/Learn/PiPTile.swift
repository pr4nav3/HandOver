import SwiftUI

/// Settings keys Learn reads. The Settings screen (another feature) writes them; the defaults live here.
enum LearnSettings {
    /// Captions over the clip. On by default.
    static let captionsKey = "handover.learn.captions"
    /// The step result moment after each step. On by default.
    static let stepResultsKey = "handover.learn.stepResults"
    /// Speak the mistake card aloud. On by default on Mac, off on iPhone and iPad (SCREENS.md 7.9).
    static let speakMistakesKey = "handover.learn.speakMistakes"
    /// iPhone portrait: which corner the PiP tile sits in.
    static let pipCornerKey = "handover.learn.pipCorner"
    /// iPhone portrait: true when the learner's camera is the large pane.
    static let liveLargeKey = "handover.learn.liveLarge"
    /// iPhone portrait: the tile is hidden behind the Show Preview button.
    static let pipHiddenKey = "handover.learn.pipHidden"
    /// Side by side: the clip on the left (Swap Videos). Default is live left, clip right, as the web app.
    static let clipFirstKey = "handover.learn.clipFirst"

    static var speakMistakesDefault: Bool {
        #if os(macOS)
        true
        #else
        false
        #endif
    }
}

/// The four corners the PiP tile snaps to.
enum PiPCorner: String, CaseIterable, Sendable {
    case topLeading, topTrailing, bottomLeading, bottomTrailing

    var isTop: Bool { self == .topLeading || self == .topTrailing }
    var isLeading: Bool { self == .topLeading || self == .bottomLeading }

    var title: String {
        switch self {
        case .topLeading: "Move to Top Left"
        case .topTrailing: "Move to Top Right"
        case .bottomLeading: "Move to Bottom Left"
        case .bottomTrailing: "Move to Bottom Right"
        }
    }

    /// The corner a released tile goes to: the quadrant of its predicted end point, so a throw carries it
    /// toward the corner it was thrown at.
    static func nearest(to predictedCenter: CGPoint, in size: CGSize) -> PiPCorner {
        let left = predictedCenter.x < size.width / 2
        let top = predictedCenter.y < size.height / 2
        switch (top, left) {
        case (true, true): return .topLeading
        case (true, false): return .topTrailing
        case (false, true): return .bottomLeading
        case (false, false): return .bottomTrailing
        }
    }

    /// The tile's center when it rests in this corner, `inset` from the container's edges.
    func center(tile: CGSize, in container: CGSize, inset: CGFloat) -> CGPoint {
        CGPoint(x: isLeading ? inset + tile.width / 2 : container.width - inset - tile.width / 2,
                y: isTop ? inset + tile.height / 2 : container.height - inset - tile.height / 2)
    }
}

/// The small floating video over the large pane (DESIGN.md 3.6): drag to any corner (it snaps with `layout`),
/// tap to swap, long press for Swap and Hide Preview. Floating shadow and a white 20% hairline.
struct PiPTile<Content: View>: View {
    var container: CGSize
    var tileSize: CGSize
    @Binding var corner: PiPCorner
    var label: String
    var onSwap: () -> Void
    var onHide: () -> Void
    @ViewBuilder var content: () -> Content
    @GestureState private var drag: CGSize = .zero
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let rest = corner.center(tile: tileSize, in: container, inset: HOSpace.m)
        content()
            .frame(width: tileSize.width, height: tileSize.height)
            .clipShape(RoundedRectangle(cornerRadius: HORadius.pip, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.pip, style: .continuous)
                .strokeBorder(Color.white.opacity(0.2), lineWidth: HOLine.width))
            .hoFloatingShadow()
            .contentShape(RoundedRectangle(cornerRadius: HORadius.pip, style: .continuous))
            .position(x: rest.x + drag.width, y: rest.y + drag.height)
            .gesture(
                DragGesture(minimumDistance: 8)
                    .updating($drag) { value, state, _ in state = value.translation }
                    .onEnded { value in
                        let predicted = CGPoint(x: rest.x + value.predictedEndTranslation.width,
                                                y: rest.y + value.predictedEndTranslation.height)
                        let next = PiPCorner.nearest(to: predicted, in: container)
                        withAnimation(reduceMotion ? nil : HOMotion.layout) { corner = next }
                        Haptics.soft()
                    }
            )
            .onTapGesture {
                Haptics.tap()
                onSwap()
            }
            .contextMenu {
                Button("Swap", systemImage: "arrow.up.left.and.arrow.down.right") { onSwap() }
                Button("Hide Preview", systemImage: "pip.remove") { onHide() }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel("\(label), small. Double tap to swap.")
            .accessibilityAction { onSwap() }
            .accessibilityAction(named: "Swap") { onSwap() }
            .accessibilityAction(named: PiPCorner.topLeading.title) { corner = .topLeading }
            .accessibilityAction(named: PiPCorner.topTrailing.title) { corner = .topTrailing }
            .accessibilityAction(named: PiPCorner.bottomLeading.title) { corner = .bottomLeading }
            .accessibilityAction(named: PiPCorner.bottomTrailing.title) { corner = .bottomTrailing }
            .accessibilityAction(named: "Hide") { onHide() }
    }
}
