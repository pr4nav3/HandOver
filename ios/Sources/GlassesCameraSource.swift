// Compiles with Xcode on macOS against MWDAT 1.0.1; not yet run on a device.
//
// Every Meta Wearables Device Access Toolkit (DAT 1.0.1) call lives in this file. The names
// and signatures below were checked against the 1.0.1 swiftinterface files (MWDATCore and
// MWDATCamera modules).
//
// If this file will not compile, set HANDOVER_NO_GLASSES (see README); a stub in
// FrameSource.swift then takes over and the app runs with the phone camera.

#if !HANDOVER_NO_GLASSES && canImport(MWDATCore) && canImport(MWDATCamera)

import Foundation
import UIKit
import MWDATCore
import MWDATCamera

/// Ray-Ban Meta camera via DAT, requested at 2 fps / .low and throttled to 2 JPEGs per second.
/// While `busy` is set (the previous frame is still being sent) frames are skipped before encoding.
///
/// Threading: the class is main-actor isolated, so `start()`, `stop()` and all session state run
/// on the main thread. Toolkit listeners fire on toolkit queues; they touch only the lock-protected
/// `live`, `throttle` and `gotFirstFrame`, and hop to the main actor for everything else.
/// `onFrame`, `onFallback` and `onStatus` are called on the main thread. `onFallback` fires at most
/// once per `start()`: when no frame arrives within 15 s, or on any toolkit or stream error.
@MainActor
final class GlassesCameraSource: @MainActor FrameSource {
    nonisolated static let isAvailable = true
    nonisolated static let connectTimeout: TimeInterval = 15

    var onFrame: ((Data) -> Void)?
    var onFallback: ((String) -> Void)?
    var onStatus: ((String) -> Void)?

    // Read on toolkit queues; each is guarded by its own lock (see FrameSource.swift).
    nonisolated private let throttle = FrameThrottle()
    nonisolated private let busy: LockedFlag?
    nonisolated private let live = LockedFlag(false)
    nonisolated private let gotFirstFrame = LockedFlag(false)

    private var generation = 0
    private var didFallBack = false
    private var connectTask: Task<Void, Never>?
    private var timeoutTask: Task<Void, Never>?
    private var session: DeviceSession?
    private var stream: MWDATCamera.Stream?
    private var tokens: [any AnyListenerToken] = []

    init(busy: LockedFlag? = nil) {
        self.busy = busy
    }

    private enum GlassesError: LocalizedError {
        case notRegistered, permissionDenied, noCamera
        var errorDescription: String? {
            switch self {
            case .notRegistered: return "app not registered in the Meta AI app"
            case .permissionDenied: return "glasses camera permission denied"
            case .noCamera: return "no glasses camera available"
            }
        }
    }

    // MARK: - App-level hooks (called from HandOverCameraApp)

    /// Must run once at launch, before any other toolkit call.
    static func configureToolkit() {
        do {
            try Wearables.configure()
        } catch {
            print("[glasses] Wearables.configure failed: \(error)")
        }
    }

    static func handleOpenURL(_ url: URL) {
        Task {
            do {
                _ = try await Wearables.shared.handleUrl(url)
            } catch {
                print("[glasses] handleUrl failed: \(error)")
            }
        }
    }

    // MARK: - FrameSource

    func start() {
        stop()
        let gen = generation
        didFallBack = false
        throttle.reset()
        gotFirstFrame.set(false)
        live.set(true)
        status("Connecting to glasses...")

        timeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(GlassesCameraSource.connectTimeout * 1_000_000_000))
            guard let self, !Task.isCancelled, self.generation == gen, !self.gotFirstFrame.value else { return }
            self.fallback("no glasses frames within \(Int(GlassesCameraSource.connectTimeout)) s", gen: gen)
        }

        connectTask = Task { [weak self] in
            do {
                try await self?.connect(gen: gen)
            } catch {
                self?.fallback("glasses error: \(error.localizedDescription)", gen: gen)
            }
        }
    }

    func stop() {
        generation += 1
        live.set(false)
        timeoutTask?.cancel()
        timeoutTask = nil
        connectTask?.cancel()
        connectTask = nil
        // Listener tokens are cancelled explicitly; the 1.0.1 API exposes `cancel() async`.
        let oldTokens = tokens
        tokens = []
        if !oldTokens.isEmpty {
            Task {
                for token in oldTokens { await token.cancel() }
            }
        }
        stream?.stop()
        stream = nil
        session?.stop()
        session = nil
    }

    // MARK: - Toolkit flow

    private func connect(gen: Int) async throws {
        let wearables = Wearables.shared

        // 1. Registration with the Meta AI app (persists across launches).
        if !isRegistered() {
            // We may be returning from the Meta AI app; give handleUrl a moment first.
            try await Task.sleep(nanoseconds: 2_000_000_000)
            guard gen == generation else { return }
            if !isRegistered() {
                status("Registering in the Meta AI app...")
                try await wearables.startRegistration()
                for _ in 0..<20 {
                    if isRegistered() { break }
                    try await Task.sleep(nanoseconds: 500_000_000)
                    guard gen == generation else { return }
                }
                guard isRegistered() else { throw GlassesError.notRegistered }
            }
        }
        guard gen == generation else { return }

        // 2. Camera permission (may switch to the Meta AI app).
        status("Checking glasses camera permission...")
        var permission = try await wearables.checkPermissionStatus(.camera)
        if permission != .granted {
            permission = try await wearables.requestPermission(.camera)
        }
        guard permission == .granted else { throw GlassesError.permissionDenied }
        guard gen == generation else { return }

        // 3. Device session. Must be started before addCamera.
        status("Starting glasses session...")
        let selector = AutoDeviceSelector(wearables: wearables)
        let session = try wearables.createSession(deviceSelector: selector)
        self.session = session
        try session.start()
        guard gen == generation else { return }

        // 4. Camera stream: 2 fps is the lowest valid rate (2, 7, 15, 24, 30); .raw avoids HEVC.
        let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2)
        // addCamera(config:) throws and returns nil when the device has no camera.
        guard let camera = try session.addCamera(config: config) else {
            throw GlassesError.noCamera
        }
        let stream = camera.stream
        self.stream = stream

        // Listener closures are @Sendable and run on toolkit queues. `self` is main-actor
        // isolated (so Sendable); only its lock-protected members are read before hopping.
        let frameToken = stream.videoFramePublisher.listen { [weak self] frame in
            guard let self, self.live.value else { return }
            if !self.gotFirstFrame.value {
                self.gotFirstFrame.set(true)
                Task { @MainActor [weak self] in self?.firstFrameArrived(gen: gen) }
            }
            guard self.busy?.value != true,
                  self.throttle.shouldEmit(),
                  let image = frame.makeUIImage(),
                  let jpeg = JPEGEncoder.encode(image) else { return }
            Task { @MainActor [weak self] in self?.deliver(jpeg, gen: gen) }
        }
        let errorToken = stream.errorPublisher.listen { [weak self] error in
            let reason = "glasses stream error: \(error)"
            Task { @MainActor [weak self] in self?.fallback(reason, gen: gen) }
        }
        let stateToken = stream.statePublisher.listen { [weak self] state in
            let text = "Glasses: \(state)"
            Task { @MainActor [weak self] in
                guard let self, self.generation == gen else { return }
                self.status(text)
            }
        }
        tokens = [frameToken, errorToken, stateToken]
        stream.start()
        guard gen == generation else { return }
        status("Waiting for glasses frames...")
    }

    private func isRegistered() -> Bool {
        Wearables.shared.registrationState == .registered
    }

    // MARK: - Main-actor helpers

    private func firstFrameArrived(gen: Int) {
        guard generation == gen else { return }
        timeoutTask?.cancel()
        timeoutTask = nil
        status("Glasses streaming")
    }

    private func deliver(_ jpeg: Data, gen: Int) {
        guard generation == gen else { return }
        onFrame?(jpeg)
    }

    private func fallback(_ reason: String, gen: Int) {
        guard gen == generation, !didFallBack else { return }
        didFallBack = true
        let handler = onFallback
        stop()
        handler?(reason)
    }

    private func status(_ text: String) {
        onStatus?(text)
    }
}

#endif
