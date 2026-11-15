@preconcurrency import AVFoundation
import CoreGraphics

/// Rotation angles for camera pictures, in degrees clockwise, as `AVCaptureConnection.videoRotationAngle`
/// takes them.
enum CameraRotation {
    /// Snaps any angle to 0, 90, 180 or 270 (coordinators report right angles; this guards odd values).
    static func snapped(_ angle: CGFloat) -> CGFloat {
        guard angle.isFinite else { return 0 }
        let turned = angle.truncatingRemainder(dividingBy: 360)
        let positive = turned < 0 ? turned + 360 : turned
        return CGFloat(Int((positive / 90).rounded()) % 4) * 90
    }
}

/// Follows one camera's rotation with `AVCaptureDevice.RotationCoordinator` and hands each new angle to the
/// callbacks: `capture` for the frames (horizon level, from the device's gravity) and `preview` for an on-screen
/// preview layer (from the layer's window). Keep the follower alive as long as the camera is in use.
@MainActor
final class CameraRotationFollower {
    let deviceID: String
    private let coordinator: AVCaptureDevice.RotationCoordinator
    private var observations: [NSKeyValueObservation] = []

    /// `previewLayer` is nil when only the frames need to be upright (nothing on screen).
    init(device: AVCaptureDevice, previewLayer: AVCaptureVideoPreviewLayer?,
         preview: (@MainActor (CGFloat) -> Void)? = nil,
         capture: (@Sendable (CGFloat) -> Void)? = nil) {
        deviceID = device.uniqueID
        coordinator = AVCaptureDevice.RotationCoordinator(device: device, previewLayer: previewLayer)
        if let preview {
            preview(CameraRotation.snapped(coordinator.videoRotationAngleForHorizonLevelPreview))
            observations.append(coordinator.observe(\.videoRotationAngleForHorizonLevelPreview, options: [.new]) { @Sendable _, change in
                guard let angle = change.newValue else { return }
                let snapped = CameraRotation.snapped(angle)
                Task { @MainActor in preview(snapped) }
            })
        }
        if let capture {
            capture(CameraRotation.snapped(coordinator.videoRotationAngleForHorizonLevelCapture))
            observations.append(coordinator.observe(\.videoRotationAngleForHorizonLevelCapture, options: [.new]) { @Sendable _, change in
                guard let angle = change.newValue else { return }
                capture(CameraRotation.snapped(angle))
            })
        }
    }

    /// The angle to record a movie at right now.
    var captureAngle: CGFloat { CameraRotation.snapped(coordinator.videoRotationAngleForHorizonLevelCapture) }

    /// Stops the callbacks (they also stop when the follower is released).
    func stop() {
        observations.forEach { $0.invalidate() }
        observations = []
    }
}

extension AVCaptureConnection {
    /// Sets the rotation when the connection supports it and it changed.
    func apply(rotation angle: CGFloat) {
        guard videoRotationAngle != angle, isVideoRotationAngleSupported(angle) else { return }
        videoRotationAngle = angle
    }
}
