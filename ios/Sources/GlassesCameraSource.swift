// UNTESTED: written on Windows, never compiled.
//
// Every Meta Wearables Device Access Toolkit (DAT 1.0.1) call lives in this file.
// Each name we could not check against the 1.0.1 source is marked `// VERIFY:`.
// Check them against samples/CameraAccess in github.com/facebook/meta-wearables-dat-ios.
//
// Uncertain types are never named in stored properties: the session, stream and listener
// tokens are kept as `Any` and stopped through closures, so a renamed type only breaks the
// line that creates it.
//
// If this file will not compile, set HANDOVER_NO_GLASSES (see README); a stub in
// FrameSource.swift then takes over and the app runs with the phone camera.

#if !HANDOVER_NO_GLASSES && canImport(MWDATCore) && canImport(MWDATCamera)

import Foundation
import UIKit
import MWDATCore   // VERIFY: module name
import MWDATCamera // VERIFY: module name

/// Ray-Ban Meta camera via DAT, requested at 2 fps / .low and throttled to 1 JPEG per second.
///
/// Threading: call `start()` / `stop()` on the main thread. `onFrame` fires on a toolkit queue.
/// `onFallback` and `onStatus` are always called on the main thread. `onFallback` fires at most
/// once per `start()`: when no frame arrives within 15 s, or on any toolkit / stream error.
final class GlassesCameraSource: FrameSource {
    static let isAvailable = true
    static let connectTimeout: TimeInterval = 15

    var onFrame: ((Data) -> Void)?
    var onFallback: ((String) -> Void)?
    var onStatus: ((String) -> Void)?

    private let throttle = FrameThrottle(interval: 1.0)
    private let live = LockedFlag(false)
    private let gotFirstFrame = LockedFlag(false)

    // main thread only
    private var generation = 0
    private var didFallBack = false
    private var connectTask: Task<Void, Never>?
    private var timeoutWork: DispatchWorkItem?
    private var sessionRef: Any?
    private var streamRef: Any?
    private var tokens: [Any] = []
    private var stopStream: (() -> Void)?
    private var stopSession: (() -> Void)?

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

    @MainActor
    static func configureToolkit() {
        do {
            try Wearables.configure() // VERIFY: Wearables.configure() exists, throws, must run at launch
        } catch {
            print("[glasses] Wearables.configure failed: \(error)")
        }
    }

    @MainActor
    static func handleOpenURL(_ url: URL) {
        Task { @MainActor in
            do {
                // VERIFY: Wearables.shared.handleUrl(_:) name, async/throws, return type
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

        let work = DispatchWorkItem { [weak self] in
            guard let self = self, self.generation == gen else { return }
            if !self.gotFirstFrame.value {
                self.fallback("no glasses frames within \(Int(GlassesCameraSource.connectTimeout)) s", gen: gen)
            }
        }
        timeoutWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + GlassesCameraSource.connectTimeout, execute: work)

        connectTask = Task { @MainActor [weak self] in
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
        timeoutWork?.cancel()
        timeoutWork = nil
        connectTask?.cancel()
        connectTask = nil
        tokens.removeAll() // VERIFY: dropping listener tokens unsubscribes (or call token.cancel())
        let endStream = stopStream
        let endSession = stopSession
        stopStream = nil
        stopSession = nil
        streamRef = nil
        sessionRef = nil
        endStream?()
        endSession?()
    }

    // MARK: - Toolkit flow

    @MainActor
    private func connect(gen: Int) async throws {
        let wearables = Wearables.shared // VERIFY: Wearables.shared

        // 1. Registration with the Meta AI app (persists across launches).
        if !(await isRegistered()) {
            // We may be returning from the Meta AI app; give handleUrl a moment first.
            try await Task.sleep(nanoseconds: 2_000_000_000)
            guard gen == generation else { return }
            if !(await isRegistered()) {
                status("Registering in the Meta AI app...")
                try await wearables.startRegistration() // VERIFY: startRegistration() async throws
                for _ in 0..<20 {
                    if await isRegistered() { break }
                    try await Task.sleep(nanoseconds: 500_000_000)
                    guard gen == generation else { return }
                }
                guard await isRegistered() else { throw GlassesError.notRegistered }
            }
        }
        guard gen == generation else { return }

        // 2. Camera permission (may switch to the Meta AI app).
        status("Checking glasses camera permission...")
        // VERIFY: checkPermissionStatus(_:) / requestPermission(_:) names, `.camera` case, async throws
        var permission = try await wearables.checkPermissionStatus(.camera)
        if !isGranted(permission) {
            permission = try await wearables.requestPermission(.camera)
        }
        guard isGranted(permission) else { throw GlassesError.permissionDenied }
        guard gen == generation else { return }

        // 3. Device session. Must be started before addCamera.
        status("Starting glasses session...")
        let selector = AutoDeviceSelector(wearables: wearables) // VERIFY: AutoDeviceSelector(wearables:)
        let session = try await wearables.createSession(deviceSelector: selector) // VERIFY: createSession(deviceSelector:)
        sessionRef = session
        stopSession = {
            Task { @MainActor in
                try? await session.stop() // VERIFY: DeviceSession.stop() (sync or async)
            }
        }
        try await session.start() // VERIFY: DeviceSession.start() (sync or async, throws?)
        guard gen == generation else { return }

        // 4. Camera stream: 2 fps is the lowest valid rate (2, 7, 15, 24, 30); .raw avoids HEVC.
        // VERIFY: StreamConfiguration(videoCodec:resolution:frameRate:) labels and `.raw` / `.low` cases
        let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 2)
        // VERIFY: addCamera(config:) — optional or not, throws or not (datOptional handles both)
        guard let camera = try await datOptional(session.addCamera(config: config)) else {
            throw GlassesError.noCamera
        }
        let stream = camera.stream // VERIFY: camera.stream
        streamRef = stream

        // VERIFY: videoFramePublisher.listen { frame in } and that it returns a token to retain
        let frameToken = stream.videoFramePublisher.listen { [weak self] frame in
            guard let self = self, self.live.value else { return }
            self.noteFrame(gen: gen)
            guard self.throttle.shouldEmit() else { return }
            self.emit(frame.makeUIImage()) // VERIFY: VideoFrame.makeUIImage() -> UIImage?
        }
        // VERIFY: errorPublisher exists on the stream
        let errorToken = stream.errorPublisher.listen { [weak self] error in
            guard let self = self else { return }
            let reason = "glasses stream error: \(error)"
            DispatchQueue.main.async {
                self.fallback(reason, gen: gen)
            }
        }
        // VERIFY: statePublisher exists on the stream
        let stateToken = stream.statePublisher.listen { [weak self] state in
            guard let self = self else { return }
            let text = "Glasses: \(state)"
            DispatchQueue.main.async {
                guard self.generation == gen else { return }
                self.status(text)
            }
        }
        tokens = [frameToken, errorToken, stateToken]
        stopStream = {
            Task { @MainActor in
                try? await stream.stop() // VERIFY: Stream.stop() (sync since 0.8.0?)
            }
        }
        try await stream.start() // VERIFY: Stream.start() (notes say sync since 0.8.0)
        guard gen == generation else { return }
        status("Waiting for glasses frames...")
    }

    @MainActor
    private func isRegistered() async -> Bool {
        // VERIFY: Wearables.shared.registrationState property and its `.registered` case.
        // Compared by name so this compiles whatever the state type is called.
        let state = await Wearables.shared.registrationState
        return String(describing: state).lowercased().hasPrefix("registered")
    }

    private func isGranted<P>(_ permission: P) -> Bool {
        // Avoids naming the permission-status type. VERIFY: status case is spelled `granted`.
        return String(describing: permission).lowercased().hasPrefix("granted")
    }

    // MARK: - Frames (toolkit queue)

    private func noteFrame(gen: Int) {
        guard !gotFirstFrame.value else { return }
        gotFirstFrame.set(true)
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.generation == gen else { return }
            self.timeoutWork?.cancel()
            self.timeoutWork = nil
            self.status("Glasses streaming")
        }
    }

    private func emit(_ image: UIImage?) {
        guard let image = image, let jpeg = JPEGEncoder.encode(image) else { return }
        onFrame?(jpeg)
    }

    // MARK: - Main-thread helpers

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

/// Turns either `T` or `T?` into `T?`, so the call compiles whichever one the toolkit returns.
private func datOptional<T>(_ value: T?) -> T? {
    return value
}

#endif
