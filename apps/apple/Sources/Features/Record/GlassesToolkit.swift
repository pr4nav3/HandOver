import Foundation

// Every Meta Wearables Device Access Toolkit (MWDAT 1.0.1) call for recording lives in this file. Names and
// signatures follow the 1.0.1 swiftinterface files (MWDATCore, MWDATCamera) and the compiling
// ios/Sources/GlassesCameraSource.swift. Built only when the package is linked; otherwise the stub at the
// bottom keeps the glasses source unavailable. Streams over Bluetooth Classic only (no Wi-Fi entitlements, so a
// free personal team signs it). Not yet run on glasses.

#if canImport(MWDATCore) && canImport(MWDATCamera) && os(iOS)

@preconcurrency import AVFoundation
import CoreImage
import MWDATCamera
import MWDATCore
import OSLog
import UIKit

@MainActor
enum GlassesToolkitHooks {
    private static var configured = false
    private(set) static var configurationError: String?
    private static var bridges: [WeakGlassesBridge] = []

    static func makeBridge() -> GlassesToolkitBridge? {
        configure()
        let bridge = MWDATGlasses()
        bridges.removeAll { $0.value == nil }
        bridges.append(WeakGlassesBridge(bridge))
        return bridge
    }

    /// `Wearables.configure()` must run once before any other toolkit call.
    static func configure() {
        guard !configured else { return }
        configured = true
        do {
            try Wearables.configure()
            configurationError = nil
        } catch {
            configured = false
            configurationError = "Meta toolkit setup failed: \(Self.describe(error))"
        }
    }

    nonisolated static func handle(_ url: URL) {
        Task { @MainActor in
            configure()
            guard configurationError == nil else {
                notifyCallback(configurationError)
                return
            }
            do {
                let handled = try await Wearables.shared.handleUrl(url)
                if !handled { notifyCallback("Meta AI returned a callback HandOver could not recognize.") }
                else { notifyCallback(nil) }
            } catch {
                notifyCallback("Meta AI callback failed: \(describe(error))")
            }
        }
    }

    private static func notifyCallback(_ error: String?) {
        bridges.removeAll { $0.value == nil }
        for bridge in bridges { bridge.value?.registrationCallbackFinished(error: error) }
    }

    private static func describe(_ error: any Error) -> String {
        if let dat = error as? any DatError { return dat.description }
        return error.localizedDescription
    }
}

@MainActor
private final class WeakGlassesBridge {
    weak var value: MWDATGlasses?
    init(_ value: MWDATGlasses) { self.value = value }
}

extension GlassesTransport {
    /// Stream settings to try, best first. Bluetooth Classic carries little, so `.medium`, then `.low`, at 15 fps.
    var attempts: [(StreamingResolution, UInt)] {
        let rate = UInt(GlassesTransport.frameRate)
        return [(.medium, rate), (.low, rate)]
    }
}

/// Registration, camera permission, the device session and a `.raw` stream at the best settings the transport
/// allows (see `GlassesTransport.attempts`). Frames feed the preview and, while recording, an
/// AVAssetWriter (HEVC).
@MainActor
final class MWDATGlasses: GlassesToolkitBridge {
    private static let log = Logger(subsystem: "com.soham109.handover", category: "MetaGlasses")
    private weak var controller: GlassesController?
    private var session: DeviceSession?
    private var camera: MWDATCamera.Camera?
    private var stream: MWDATCamera.Stream?
    private var tokens: [any AnyListenerToken] = []
    private var watchTask: Task<Void, Never>?
    private var connectTask: Task<Void, Never>?
    private let meter = FrameMeter()
    private let writer = GlassesWriter()
    private let ciContext = CIContext()

    func connect(_ controller: GlassesController) {
        self.controller = controller
        if let error = GlassesToolkitHooks.configurationError {
            controller.set(state: .failed(error))
            return
        }
        connectTask?.cancel()
        connectTask = Task { [weak self, weak controller] in
            guard let self, let controller else { return }
            await self.run(controller)
        }
        watch(controller)
    }

    func allowCamera(_ controller: GlassesController) {
        self.controller = controller
        controller.set(state: .waitingForMetaAI)
        Task { [weak self, weak controller] in
            guard let self, let controller else { return }
            do {
                let status = try await Wearables.shared.requestPermission(.camera)
                if status == .granted { await self.run(controller) } else { controller.set(state: .permissionNeeded) }
            } catch let error {
                controller.set(state: Self.state(for: error))
            }
        }
    }

    func stop(_ controller: GlassesController) {
        connectTask?.cancel()
        let old = tokens
        tokens = []
        Task { for token in old { await token.cancel() } }
        stream?.stop()
        stream = nil
        camera?.stop()
        camera = nil
        session?.stop()
        session = nil
        controller.set(frame: nil)
        if controller.state.isStreaming || controller.state.isBusy { controller.set(state: .notRegistered) }
        refreshRegistration(controller)
    }

    func startRecording(_ controller: GlassesController, to url: URL) throws {
        guard controller.state.isStreaming else { throw RecorderError.failed("The glasses are not streaming.") }
        try writer.start(url: url)
        controller.set(recording: true)
    }

    func stopRecording(_ controller: GlassesController) async throws -> URL {
        controller.set(recording: false)
        return try await writer.finish()
    }

    // MARK: - Flow

    private func watch(_ controller: GlassesController) {
        guard watchTask == nil else { return }
        watchTask = Task { [weak controller] in
            for await state in Wearables.shared.registrationStateStream() {
                guard let controller else { return }
                if state != .registered, !controller.state.isStreaming, controller.state != .developerModeOff {
                    controller.set(state: state == .registering ? .waitingForMetaAI : .notRegistered)
                }
            }
        }
    }

    private func refreshRegistration(_ controller: GlassesController) {
        if Wearables.shared.registrationState != .registered { controller.set(state: .notRegistered) }
    }

    private func run(_ controller: GlassesController) async {
        self.controller = controller
        let wearables = Wearables.shared
        if wearables.registrationState != .registered {
            controller.set(state: .waitingForMetaAI)
            do {
                try await wearables.startRegistration()
            } catch {
                switch error {
                case .configurationInvalid: controller.set(state: .developerModeOff)
                case .metaAINotInstalled: controller.set(state: .metaAIMissing)
                case .alreadyRegistered: break
                default: controller.set(state: .failed("Meta registration failed: \(error.description)"))
                }
                if error != .alreadyRegistered { return }
            }
            // Meta AI returns through handleUrl; wait for the state to change (at most 30 s).
            for _ in 0..<60 where wearables.registrationState != .registered {
                try? await Task.sleep(for: .milliseconds(500))
                if Task.isCancelled { return }
            }
            guard wearables.registrationState == .registered else {
                controller.set(state: .notRegistered)
                return
            }
        }
        guard let device = await waitForDevice(wearables) else {
            controller.set(state: .noDevice)
            return
        }
        controller.set(device: device.name, battery: device.batteryLevel)
        do {
            if try await checkCameraPermission(wearables) != MWDATCore.PermissionStatus.granted {
                controller.set(state: .permissionNeeded)
                return
            }
        } catch let error {
            controller.set(state: Self.state(for: error))
            return
        }
        controller.set(state: .connecting)
        do {
            let session = try wearables.createSession(deviceSelector: AutoDeviceSelector(wearables: wearables))
            self.session = session
            try session.start()
            guard await waitForStarted(session) else {
                controller.set(state: session.state == .stopped ? .lost : .failed("The glasses session timed out before it started."))
                return
            }
            try startStream(session: session, controller: controller)
        } catch let error as DeviceSessionError {
            controller.set(state: Self.state(for: error))
        } catch {
            controller.set(state: .failed("Glasses session failed: \(Self.describe(error))"))
        }
    }

    private func waitForDevice(_ wearables: any WearablesInterface) async -> Device? {
        for _ in 0..<40 {
            if let device = wearables.devices.first.flatMap({ wearables.deviceForIdentifier($0) }) { return device }
            try? await Task.sleep(for: .milliseconds(250))
            if Task.isCancelled { return nil }
        }
        return nil
    }

    /// Meta AI may return before its accessory connection is ready. Retry the transient permission errors
    /// briefly instead of turning the SDK's one-frame handoff race into a permanent "Internal error" card.
    private func checkCameraPermission(_ wearables: any WearablesInterface) async throws(PermissionError) -> MWDATCore.PermissionStatus {
        var last: PermissionError?
        for attempt in 0..<8 {
            do {
                return try await wearables.checkPermissionStatus(.camera)
            } catch let error {
                last = error
                let transient = error == .noDevice || error == .noDeviceWithConnection || error == .connectionError || error == .internalError
                guard transient, attempt < 7 else { throw error }
                try? await Task.sleep(for: .milliseconds(500))
            }
        }
        throw last ?? .internalError
    }

    private func waitForStarted(_ session: DeviceSession) async -> Bool {
        for _ in 0..<120 {
            if session.state == .started { return true }
            if session.state == .stopped { return false }
            try? await Task.sleep(for: .milliseconds(100))
            if Task.isCancelled { return false }
        }
        return false
    }

    private func startStream(session: DeviceSession, controller: GlassesController) throws {
        var madeCamera: MWDATCamera.Camera?
        for (resolution, rate) in GlassesTransport.current.attempts {
            if let made = try? session.addCamera(config: StreamConfiguration(videoCodec: .raw, resolution: resolution, frameRate: rate)) {
                madeCamera = made
                break
            }
        }
        guard let madeCamera else { throw RecorderError.failed("The glasses have no camera to share.") }
        camera = madeCamera
        let stream = madeCamera.stream
        self.stream = stream
        meter.reset()
        let writer = self.writer
        let meter = self.meter
        let frameToken = stream.videoFramePublisher.listen { [weak self, weak controller] frame in
            let buffer = frame.sampleBuffer
            writer.append(buffer)
            guard let measured = meter.tick(buffer) else { return }
            let image = frame.makeUIImage()?.cgImage
            Task { @MainActor in
                guard let controller else { return }
                if let image { controller.set(frame: image) }
                if let size = measured.size {
                    controller.set(state: .streaming(width: size.width, height: size.height, fps: measured.fps))
                }
                _ = self
            }
        }
        let stateToken = stream.statePublisher.listen { [weak controller] state in
            Task { @MainActor in
                guard let controller else { return }
                switch state {
                case .paused: controller.set(state: .paused)
                case .waitingForDevice, .starting: if !controller.state.isStreaming { controller.set(state: .connecting) }
                case .stopped: if controller.state.isStreaming { controller.set(state: .lost) }
                default: break
                }
            }
        }
        let errorToken = stream.errorPublisher.listen { [weak controller] error in
            Task { @MainActor in controller?.set(state: Self.state(for: error)) }
        }
        tokens = [frameToken, stateToken, errorToken]
        stream.start()
    }

    func registrationCallbackFinished(error: String?) {
        guard let controller else { return }
        if let error {
            Self.log.error("Registration callback failed: \(error, privacy: .public)")
            controller.set(state: .failed(error))
            return
        }
        Self.log.info("Registration callback handled; state=\(Wearables.shared.registrationState.description, privacy: .public)")
        if Wearables.shared.registrationState == .registered, !controller.state.isStreaming {
            connect(controller)
        }
    }

    private static func state(for error: PermissionError) -> GlassesState {
        switch error {
        case .noDevice, .noDeviceWithConnection: .noDevice
        case .connectionError: .lost
        case .metaAINotInstalled: .metaAIMissing
        case .requestInProgress: .waitingForMetaAI
        case .requestTimeout: .failed("Meta AI camera approval timed out. Try Allow again.")
        case .internalError: .failed("Meta AI returned an internal camera-permission error. Reopen Meta AI, confirm Developer Mode is on, then try again.")
        @unknown default: .failed("Meta AI returned an unknown camera-permission error (\(error.rawValue)).")
        }
    }

    private static func describe(_ error: any Error) -> String {
        if let dat = error as? any DatError { return dat.description }
        return error.localizedDescription
    }

    private static func state(for error: StreamError) -> GlassesState {
        switch error {
        case .batteryLow: .batteryLow
        case .thermalHot: .tooHot
        case .peakPowerLimit: .powerLimit
        case .deviceNotConnected, .deviceNotFound, .timeout: .lost
        case .permissionDenied: .permissionNeeded
        case .hingesClosed: .failed("Open the glasses' hinges to use the camera.")
        default: .failed(error.localizedDescription)
        }
    }

    private static func state(for error: DeviceSessionError) -> GlassesState {
        switch error {
        case .noEligibleDevice: .noDevice
        case .batteryCritical: .batteryLow
        case .thermalCritical, .thermalEmergency: .tooHot
        case .peakPowerShutdown: .powerLimit
        case .datAppOnTheGlassesUpdateRequired: .failed("Update the HandOver access app on your glasses in Meta AI.")
        default: .failed(error.localizedDescription)
        }
    }
}

/// Measures the real frame rate and size from arriving frames, about once a second.
private final class FrameMeter: @unchecked Sendable {
    struct Reading { var fps: Int; var size: (width: Int, height: Int)? }
    private let lock = NSLock()
    private var count = 0
    private var windowStart: CFTimeInterval = 0
    private var lastPreview: CFTimeInterval = 0

    func reset() {
        lock.lock(); defer { lock.unlock() }
        count = 0
        windowStart = CACurrentMediaTime()
    }

    /// Nil between preview frames (the preview updates at most 15 times a second).
    func tick(_ buffer: CMSampleBuffer) -> Reading? {
        lock.lock(); defer { lock.unlock() }
        let now = CACurrentMediaTime()
        count += 1
        guard now - lastPreview >= 1.0 / 15 else { return nil }
        lastPreview = now
        let elapsed = now - windowStart
        let fps = elapsed > 0.5 ? Int((Double(count) / elapsed).rounded()) : 0
        if elapsed > 2 {
            count = 0
            windowStart = now
        }
        var size: (Int, Int)?
        if let pixels = CMSampleBufferGetImageBuffer(buffer) {
            size = (CVPixelBufferGetWidth(pixels), CVPixelBufferGetHeight(pixels))
        }
        return Reading(fps: fps, size: size)
    }
}

/// Writes glasses frames to an HEVC .mov. Video only: the glasses' microphone needs separate approval from
/// Meta (research notes), so this build records no sound from the glasses.
private final class GlassesWriter: @unchecked Sendable {
    private let lock = NSLock()
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var started = false

    func start(url: URL) throws {
        lock.lock(); defer { lock.unlock() }
        try? FileManager.default.removeItem(at: url)
        writer = try AVAssetWriter(outputURL: url, fileType: .mov)
        started = false
        input = nil
    }

    func append(_ buffer: CMSampleBuffer) {
        lock.lock(); defer { lock.unlock() }
        guard let writer else { return }
        if input == nil, let pixels = CMSampleBufferGetImageBuffer(buffer) {
            let settings: [String: Any] = [AVVideoCodecKey: AVVideoCodecType.hevc,
                                           AVVideoWidthKey: CVPixelBufferGetWidth(pixels),
                                           AVVideoHeightKey: CVPixelBufferGetHeight(pixels)]
            let made = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
            made.expectsMediaDataInRealTime = true
            guard writer.canAdd(made) else { return }
            writer.add(made)
            input = made
        }
        guard let input else { return }
        if !started {
            guard writer.startWriting() else { return }
            writer.startSession(atSourceTime: CMSampleBufferGetPresentationTimeStamp(buffer))
            started = true
        }
        if input.isReadyForMoreMediaData { input.append(buffer) }
    }

    func finish() async throws -> URL {
        let (writer, input, started): (AVAssetWriter?, AVAssetWriterInput?, Bool) = {
            lock.lock(); defer { lock.unlock() }
            let out = (self.writer, self.input, self.started)
            self.writer = nil
            self.input = nil
            self.started = false
            return out
        }()
        guard let writer, started else { throw RecorderError.failed("No frames arrived from the glasses.") }
        input?.markAsFinished()
        await writer.finishWriting()
        if writer.status != .completed { throw RecorderError.failed(writer.error?.localizedDescription ?? "") }
        return writer.outputURL
    }
}

#else

@MainActor
enum GlassesToolkitHooks {
    static func configure() {}
    static func makeBridge() -> GlassesToolkitBridge? { nil }
    nonisolated static func handle(_ url: URL) {}
}

#endif
