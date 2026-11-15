import SwiftUI

/// A container for a platform view that has to outlive the SwiftUI views showing it: a camera preview layer or a
/// clip's player layer. When a layout change rebuilds the SwiftUI side (rotating the phone swaps Learn between
/// its upright and sideways layouts), the new container adopts the same surface instead of making a new one, so
/// the capture session is not reconfigured and the clip does not go black while it reattaches.
final class SurfaceHost: PlatformView {
    /// The surface this container last adopted. It may have moved on to a newer container since.
    private(set) weak var surface: PlatformView?

    /// Shows `new`, taking it from any older container. Calling it again with the same surface does nothing, so an
    /// older container that SwiftUI updates on its way out never takes the surface back.
    func adopt(_ new: PlatformView) {
        guard surface !== new || new.superview == nil else { return }
        if let old = surface, old !== new, old.superview === self { old.removeFromSuperview() }
        surface = new
        new.frame = bounds
        #if os(macOS)
        new.autoresizingMask = [.width, .height]
        #else
        new.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        #endif
        addSubview(new)
    }

    /// True while this container is the one drawing its surface.
    var isShowing: Bool { surface?.superview === self }

    #if os(macOS)
    override func layout() {
        super.layout()
        if isShowing { surface?.frame = bounds }
    }
    #else
    override func layoutSubviews() {
        super.layoutSubviews()
        if isShowing { surface?.frame = bounds }
    }
    #endif
}
