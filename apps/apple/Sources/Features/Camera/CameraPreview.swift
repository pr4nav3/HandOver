@preconcurrency import AVFoundation
import SwiftUI

/// The live capture session, aspect fit so the picture is exactly the area sent to the hub.
struct CameraPreview {
    let capture: CameraCapture

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
        override func layoutSubviews() {
            super.layoutSubviews()
            preview.frame = bounds
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
        capture.followRotation(preview: view.preview)
        return view
    }

    func updateUIView(_ view: PreviewView, context: Context) {}
}
#endif
