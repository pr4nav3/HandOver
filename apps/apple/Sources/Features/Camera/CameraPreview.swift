@preconcurrency import AVFoundation
import SwiftUI

/// The live capture session, aspect fit so the picture is exactly the area sent to the hub. On iPhone and iPad the
/// picture turns with the device through its own rotation coordinator, so it is never sideways or stretched.
///
/// The preview layer belongs to the capture (`CameraCapture.previewView()`), not to this view: a layout change that
/// rebuilds this view (rotating the phone) moves the same layer into the new place, so the running session is never
/// reconfigured on the main thread and no second rotation coordinator is made.
struct CameraPreview {
    let capture: CameraCapture
    /// The camera in use; pass the streamer's `deviceID` so the preview follows a camera switch.
    var deviceID: String?

    final class PreviewView: PlatformView {
        let preview = AVCaptureVideoPreviewLayer()

        /// Connects the layer to the session once. Call it before the session's input is added, so the preview's
        /// connection forms inside that configuration on the session queue rather than on the main thread.
        func attach(_ capture: CameraCapture) {
            guard preview.session !== capture.session else { return }
            #if os(macOS)
            wantsLayer = true
            layer?.backgroundColor = NSColor.black.cgColor
            if preview.superlayer == nil { layer?.addSublayer(preview) }
            #else
            backgroundColor = .black
            if preview.superlayer == nil { layer.addSublayer(preview) }
            #endif
            preview.videoGravity = .resizeAspect
            preview.session = capture.session
        }

        #if os(macOS)
        override func layout() {
            super.layout()
            preview.frame = bounds
        }
        #else
        private var rotation: CameraRotationFollower?
        private var angle: CGFloat?

        override func layoutSubviews() {
            super.layoutSubviews()
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            preview.frame = bounds
            CATransaction.commit()
            applyAngle()
        }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            if window != nil { applyAngle() }
        }

        /// Starts following the camera's rotation, again when the camera changed.
        func followRotation(of capture: CameraCapture) {
            guard let device = capture.device, rotation?.deviceID != device.uniqueID else { return }
            rotation = CameraRotationFollower(device: device, previewLayer: preview, preview: { [weak self] angle in
                self?.angle = angle
                self?.applyAngle()
            })
        }

        /// The connection can appear after the angle arrives (a camera switch), so layout applies it again.
        private func applyAngle() {
            guard let angle else { return }
            preview.connection?.apply(rotation: angle)
        }
        #endif
    }

    /// Puts the capture's one preview in `host` and keeps its rotation following the current camera.
    @MainActor
    fileprivate func show(in host: SurfaceHost) {
        let view = capture.previewView()
        host.adopt(view)
        #if os(iOS)
        view.followRotation(of: capture)
        #endif
    }
}

#if os(macOS)
extension CameraPreview: NSViewRepresentable {
    func makeNSView(context: Context) -> SurfaceHost {
        let host = SurfaceHost()
        show(in: host)
        return host
    }

    func updateNSView(_ host: SurfaceHost, context: Context) { show(in: host) }
}
#else
extension CameraPreview: UIViewRepresentable {
    func makeUIView(context: Context) -> SurfaceHost {
        let host = SurfaceHost()
        show(in: host)
        return host
    }

    func updateUIView(_ host: SurfaceHost, context: Context) { show(in: host) }
}
#endif
