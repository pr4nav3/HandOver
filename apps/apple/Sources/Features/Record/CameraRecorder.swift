@preconcurrency import AVFoundation
import Foundation

/// The phone or Mac camera through AVCaptureMovieFileOutput (server/docs/glasses-recording-research.md, "Phone
/// recording"): 1080p at 30 fps, HEVC when the device has it, SDR (sRGB), stabilization on iPhone, and
/// horizon-level rotation from `AVCaptureDevice.RotationCoordinator`. Narration level comes from the movie
/// output's audio channel. All session work runs on one serial queue.
@MainActor
final class CameraRecorder: RecordCaptureEngine {
    /// The preview layer the recorder view shows. Its rotation follows the device.
    let previewLayer: AVCaptureVideoPreviewLayer
    private let core = CaptureCore()
    private var rotation: AVCaptureDevice.RotationCoordinator?
    private var rotationObservation: NSKeyValueObservation?

    init() {
        previewLayer = AVCaptureVideoPreviewLayer(session: core.session)
        previewLayer.videoGravity = .resizeAspectFill
    }

    func requestAccess() async -> RecordCaptureAccess {
        let camera = await Self.access(.video)
        let declared = Bundle.main.object(forInfoDictionaryKey: "NSMicrophoneUsageDescription") != nil
        let microphone = declared ? await Self.access(.audio) : false
        return RecordCaptureAccess(camera: camera, microphone: microphone, microphoneDeclared: declared)
    }

    private static func access(_ type: AVMediaType) async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: type) {
        case .authorized: return true
        case .notDetermined: return await AVCaptureDevice.requestAccess(for: type)
        default: return false
        }
    }

    func cameras() -> [RecordCamera] {
        Self.discover().map { device in
            RecordCamera(id: device.uniqueID, name: device.localizedName, kind: Self.kind(of: device))
        }
    }

    func start(camera: RecordCamera?, withAudio: Bool) async throws {
        let devices = Self.discover()
        guard let device = devices.first(where: { $0.uniqueID == camera?.id }) ?? devices.first else {
            throw RecorderError.noCamera
        }
        try await core.configure(device: device, audio: withAudio)
        followRotation(of: device)
    }

    func stopSession() {
        rotationObservation = nil
        rotation = nil
        core.stop()
    }

    func startRecording(to url: URL) throws {
        let angle = rotation?.videoRotationAngleForHorizonLevelCapture
        try core.startRecording(to: url, rotation: angle)
    }

    func stopRecording() async throws -> URL { try await core.stopRecording() }

    var canPause: Bool { true }
    func pauseRecording() { core.pause() }
    func resumeRecording() { core.resume() }

    func audioLevel() -> Float? {
        core.audioPower().map { RecordModel.normalize(decibels: $0) }
    }

    // MARK: - Devices

    private static func discover() -> [AVCaptureDevice] {
        #if os(iOS)
        let types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera]
        let found = AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
        // Back camera first: a teacher films their hands, not their face.
        return found.sorted { a, _ in a.position == .back }
        #else
        let types: [AVCaptureDevice.DeviceType] = [.continuityCamera, .deskViewCamera, .builtInWideAngleCamera, .external]
        return AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
        #endif
    }

    private static func kind(of device: AVCaptureDevice) -> RecordCamera.Kind {
        #if os(iOS)
        return device.position == .front ? .front : .back
        #else
        switch device.deviceType {
        case .deskViewCamera: return .deskView
        case .continuityCamera: return .continuity
        case .external: return .external
        default: return device.isContinuityCamera ? .continuity : .builtIn
        }
        #endif
    }

    private func followRotation(of device: AVCaptureDevice) {
        let coordinator = AVCaptureDevice.RotationCoordinator(device: device, previewLayer: previewLayer)
        rotation = coordinator
        applyPreviewRotation(coordinator.videoRotationAngleForHorizonLevelPreview)
        rotationObservation = coordinator.observe(\.videoRotationAngleForHorizonLevelPreview, options: [.new]) { [weak self] _, change in
            guard let angle = change.newValue else { return }
            Task { @MainActor in self?.applyPreviewRotation(angle) }
        }
    }

    private func applyPreviewRotation(_ angle: CGFloat) {
        guard let connection = previewLayer.connection, connection.isVideoRotationAngleSupported(angle) else { return }
        connection.videoRotationAngle = angle
    }
}

enum RecorderError: LocalizedError {
    case noCamera, cannotAddCamera, notRecording, failed(String)

    var errorDescription: String? {
        switch self {
        case .noCamera: "No camera found. Connect a camera, or use Continuity Camera with your iPhone."
        case .cannotAddCamera: "The camera is busy in another app. Close it, then try again."
        case .notRecording: "Nothing is recording."
        case .failed(let why): "The recording stopped. \(why)"
        }
    }
}

/// The AVFoundation objects, used only on `queue`.
private final class CaptureCore: NSObject, AVCaptureFileOutputRecordingDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "com.handover.record.session")
    private let movie = AVCaptureMovieFileOutput()
    private var videoInput: AVCaptureDeviceInput?
    private var audioInput: AVCaptureDeviceInput?
    private let lock = NSLock()
    private var finishing: CheckedContinuation<URL, any Error>?

    func configure(device: AVCaptureDevice, audio: Bool) async throws {
        try await withCheckedThrowingContinuation { (done: CheckedContinuation<Void, any Error>) in
            queue.async { [self] in
                do {
                    try build(device: device, audio: audio)
                    if !session.isRunning { session.startRunning() }
                    done.resume()
                } catch {
                    done.resume(throwing: error)
                }
            }
        }
    }

    private func build(device: AVCaptureDevice, audio: Bool) throws {
        session.beginConfiguration()
        #if os(iOS)
        // SDR: no automatic P3 or HDR, so the hub's normalize step gets plain Rec. 709 video.
        session.automaticallyConfiguresCaptureDeviceForWideColor = false
        #endif
        if session.canSetSessionPreset(.hd1920x1080) {
            session.sessionPreset = .hd1920x1080
        } else {
            session.sessionPreset = .high
        }
        if let videoInput { session.removeInput(videoInput) }
        if let audioInput { session.removeInput(audioInput) }
        videoInput = nil
        audioInput = nil
        guard let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) else {
            session.commitConfiguration()
            throw RecorderError.cannotAddCamera
        }
        session.addInput(input)
        videoInput = input
        if audio, let mic = AVCaptureDevice.default(for: .audio), let input = try? AVCaptureDeviceInput(device: mic),
           session.canAddInput(input) {
            session.addInput(input)
            audioInput = input
        }
        if !session.outputs.contains(movie), session.canAddOutput(movie) {
            session.addOutput(movie)
        }
        if let connection = movie.connection(with: .video) {
            #if os(iOS)
            if connection.isVideoStabilizationSupported {
                connection.preferredVideoStabilizationMode = device.activeFormat.isVideoStabilizationModeSupported(.cinematicExtended)
                    ? .cinematicExtended : .auto
            }
            if movie.availableVideoCodecTypes.contains(.hevc) {
                movie.setOutputSettings([AVVideoCodecKey: AVVideoCodecType.hevc], for: connection)
            }
            #endif
            // The Mac keeps the output's default codec: the hub normalizes every upload anyway.
        }
        session.commitConfiguration()

        // 30 fps and sRGB after the preset picked the format.
        if (try? device.lockForConfiguration()) != nil {
            if device.activeFormat.supportedColorSpaces.contains(.sRGB) { device.activeColorSpace = .sRGB }
            let thirty = CMTime(value: 1, timescale: 30)
            if device.activeFormat.videoSupportedFrameRateRanges.contains(where: { $0.minFrameRate <= 30 && $0.maxFrameRate >= 30 }) {
                device.activeVideoMinFrameDuration = thirty
                device.activeVideoMaxFrameDuration = thirty
            }
            device.unlockForConfiguration()
        }
    }

    func stop() {
        queue.async { [self] in if session.isRunning { session.stopRunning() } }
    }

    func startRecording(to url: URL, rotation: CGFloat?) throws {
        guard !movie.isRecording else { return }
        try? FileManager.default.removeItem(at: url)
        if let rotation, let connection = movie.connection(with: .video), connection.isVideoRotationAngleSupported(rotation) {
            connection.videoRotationAngle = rotation
        }
        guard movie.connection(with: .video) != nil else { throw RecorderError.cannotAddCamera }
        movie.startRecording(to: url, recordingDelegate: self)
    }

    func stopRecording() async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            lock.lock()
            guard movie.isRecording else {
                lock.unlock()
                continuation.resume(throwing: RecorderError.notRecording)
                return
            }
            finishing = continuation
            lock.unlock()
            movie.stopRecording()
        }
    }

    func pause() { if movie.isRecording { movie.pauseRecording() } }
    func resume() { if movie.isRecordingPaused { movie.resumeRecording() } }

    func audioPower() -> Float? {
        movie.connection(with: .audio)?.audioChannels.first?.averagePowerLevel
    }

    func fileOutput(_ output: AVCaptureFileOutput, didFinishRecordingTo outputFileURL: URL,
                    from connections: [AVCaptureConnection], error: (any Error)?) {
        lock.lock()
        let continuation = finishing
        finishing = nil
        lock.unlock()
        // An error can still mean the file finished (for example the disk filled after the last frame).
        let finished = (error as NSError?)?.userInfo[AVErrorRecordingSuccessfullyFinishedKey] as? Bool ?? (error == nil)
        if finished {
            continuation?.resume(returning: outputFileURL)
        } else {
            continuation?.resume(throwing: RecorderError.failed(error?.localizedDescription ?? ""))
        }
    }
}
