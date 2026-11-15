@preconcurrency import AVFoundation
import CoreGraphics
import Foundation
import QuartzCore

/// A CGImage that crosses threads. CGImage is immutable, so this is safe.
struct CameraFrameImage: @unchecked Sendable {
    let image: CGImage
}

/// A camera this device can stream from.
struct CameraChoice: Hashable, Identifiable, Sendable {
    let id: String
    let name: String
    let symbol: String

    init(device: AVCaptureDevice) {
        id = device.uniqueID
        name = CameraChoice.name(for: device)
        symbol = CameraChoice.symbol(for: device)
    }

    private static func name(for device: AVCaptureDevice) -> String {
        #if os(iOS)
        switch device.position {
        case .back: return "Back Camera"
        case .front: return "Front Camera"
        default: return device.localizedName
        }
        #else
        if device.deviceType == .deskViewCamera { return "Desk View" }
        return device.localizedName
        #endif
    }

    private static func symbol(for device: AVCaptureDevice) -> String {
        #if os(iOS)
        return "iphone"
        #else
        switch device.deviceType {
        case .deskViewCamera: return "rectangle.on.rectangle"
        case .continuityCamera: return "iphone"
        default: return "web.camera"
        }
        #endif
    }
}

/// The capture session: one camera in, frames out downscaled to the send size. Frames are processed at up
/// to 15 per second; the sender picks the newest of them when it is free.
final class CameraCapture: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    /// Every processed frame, downscaled, on a background queue.
    var onFrame: (@Sendable (CameraFrameImage) -> Void)?

    let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "com.handover.camera.session")
    private let frameQueue = DispatchQueue(label: "com.handover.camera.frames", qos: .userInitiated)
    private let output = AVCaptureVideoDataOutput()
    private let encoder: FrameEncoder
    private var lastFrame: CFTimeInterval = 0
    private let minInterval: CFTimeInterval = 1.0 / 15
    private(set) var device: AVCaptureDevice?
    #if os(iOS)
    @MainActor private var rotation: CameraRotationFollower?
    #endif

    init(encoder: FrameEncoder = .shared) {
        self.encoder = encoder
        super.init()
    }

    static var isAvailable: Bool {
        #if targetEnvironment(simulator)
        return false
        #else
        return !devices().isEmpty
        #endif
    }

    /// The cameras to pick from: on iPhone and iPad the back and front cameras; on the Mac the built-in
    /// camera, Continuity Camera (an iPhone nearby), Desk View and external cameras.
    static func devices() -> [AVCaptureDevice] {
        #if os(iOS)
        let types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera, .external]
        #else
        let types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera, .continuityCamera, .deskViewCamera, .external]
        #endif
        return AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
    }

    static func defaultDevice() -> AVCaptureDevice? {
        #if os(iOS)
        return AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) ?? devices().first
        #else
        return AVCaptureDevice.default(for: .video) ?? devices().first
        #endif
    }

    /// Starts (or switches to) a camera. Returns false when the camera could not be opened.
    func start(deviceID: String?) async -> Bool {
        let opened = await withCheckedContinuation { c in
            sessionQueue.async { [self] in
                c.resume(returning: configure(deviceID: deviceID))
                if !session.isRunning { session.startRunning() }
            }
        }
        #if os(iOS)
        if opened { await followRotation() }
        #endif
        return opened
    }

    func stop() {
        sessionQueue.async { [self] in
            if session.isRunning { session.stopRunning() }
        }
    }

    #if os(iOS)
    /// Keeps the sent frames upright in every orientation. The capture owns its follower, so frames turn with
    /// the phone even when no preview is on screen (the Learn tile hidden, for example).
    @MainActor
    private func followRotation() {
        guard let device else { return }
        if rotation?.deviceID == device.uniqueID { return }
        let queue = sessionQueue, output = self.output
        rotation = CameraRotationFollower(device: device, previewLayer: nil, capture: { angle in
            queue.async { output.connection(with: .video)?.apply(rotation: angle) }
        })
    }
    #endif

    private func configure(deviceID: String?) -> Bool {
        let wanted = deviceID.flatMap { id in Self.devices().first { $0.uniqueID == id } } ?? Self.defaultDevice()
        guard let wanted else { return false }
        if device?.uniqueID == wanted.uniqueID, !session.inputs.isEmpty { return true }
        session.beginConfiguration()
        defer { session.commitConfiguration() }
        for input in session.inputs { session.removeInput(input) }
        guard let input = try? AVCaptureDeviceInput(device: wanted), session.canAddInput(input) else { return false }
        session.addInput(input)
        if session.canSetSessionPreset(.hd1280x720) { session.sessionPreset = .hd1280x720 }
        if !session.outputs.contains(output) {
            output.alwaysDiscardsLateVideoFrames = true
            output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
            output.setSampleBufferDelegate(self, queue: frameQueue)
            guard session.canAddOutput(output) else { return false }
            session.addOutput(output)
        }
        if let connection = output.connection(with: .video), connection.isVideoMirroringSupported {
            // Frames are never mirrored: the hub compares them with the expert's unmirrored reference.
            connection.automaticallyAdjustsVideoMirroring = false
            connection.isVideoMirrored = false
        }
        device = wanted
        return true
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let now = CACurrentMediaTime()
        guard now - lastFrame >= minInterval, let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastFrame = now
        guard let image = encoder.downscale(buffer) else { return }
        onFrame?(CameraFrameImage(image: image))
    }
}
