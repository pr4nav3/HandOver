@preconcurrency import AVFoundation
import SwiftUI

/// The live capture session, aspect fit so the picture is exactly the area sent to the hub. On iPhone and iPad the
/// picture turns with the device through its own rotation coordinator, so it is never sideways or stretched.
struct CameraPreview {
    let capture: CameraCapture
    /// The camera in use; pass the streamer's `deviceID` so the preview follows a camera switch.
    var deviceID: String?

    final class PreviewView: PlatformView {
        let preview = AVCaptureVideoPreviewLayer()

        func attach(_ capture: CameraCapture) {
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
}

#if os(macOS)
extension CameraPreview: NSViewRepresentable {
    func makeNSView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.attach(capture)
        return view
    }

    func updateNSView(_ view: PreviewView, context: Context) { view.attach(capture) }
}
#else
extension CameraPreview: UIViewRepresentable {
    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.attach(capture)
        view.followRotation(of: capture)
        return view
    }

    func updateUIView(_ view: PreviewView, context: Context) {
        view.followRotation(of: capture)
    }
}
#endif
