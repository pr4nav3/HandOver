import CoreGraphics
import Foundation
import Observation
#if os(iOS)
import UIKit
#endif

/// This device's own camera while Camera mode runs. Other screens read it to show the phone's camera
/// without opening a second capture session, for example Learn's floating preview:
/// `PhoneCameraFeed.shared.image` (nil when Camera mode is not running).
@MainActor
@Observable
final class PhoneCameraFeed {
    static let shared = PhoneCameraFeed()

    /// The newest frame, downscaled to the send size (960 px on the long side), upright, not mirrored.
    private(set) var image: CGImage?
    private(set) var isRunning = false

    func publish(_ image: CGImage) { self.image = image }

    func setRunning(_ running: Bool) {
        isRunning = running
        if !running { image = nil }
    }
}

/// Camera mode's engine: capture, the camera socket, the one-slot newest-frame sender and its stats.
@MainActor
@Observable
final class CameraStreamer {
    enum Phase: Equatable {
        case idle
        case noCamera
        case denied
        case starting
        case streaming
        /// Another device took over (close 4000) or the hub stopped us for good.
        case replaced(String)
    }

    private(set) var phase: Phase = .idle
    private(set) var connection: ConnectionState = .idle
    /// From `camera_status`: true when the hub judges this camera, false on standby.
    private(set) var isActiveCamera: Bool?
    /// The state the hub sends on the camera socket (step, total, status).
    private(set) var state: HubState?
    /// Frames per second actually sent, over the last 5 s.
    private(set) var sentFPS: Double = 0
    /// The size of the frames sent.
    private(set) var frameSize: CGSize = .zero
    private(set) var framesSent = 0
    /// Frames dropped because the socket was still busy or the hub's gap had not passed.
    private(set) var framesDropped = 0
    private(set) var choices: [CameraChoice] = []
    private(set) var deviceID: String?
    /// iPhone is warm: one frame every 2 s at most.
    private(set) var isThrottled = false

    var isSending: Bool { phase == .streaming && connection.isConnected }

    @ObservationIgnored private let feed: PhoneCameraFeed
    @ObservationIgnored private var capture: CameraCapture?
    @ObservationIgnored private var socket: CameraSocket?
    @ObservationIgnored private var slot: LatestFrameSlot<CameraFrameImage>?
    @ObservationIgnored private var tasks: [Task<Void, Never>] = []
    @ObservationIgnored private var rate = SendRate()
    @ObservationIgnored private var startedAt: TimeInterval = 0
    @ObservationIgnored private var isPushing = false

    init(feed: PhoneCameraFeed = .shared) {
        self.feed = feed
    }

    /// Starts capture and the socket. `makeSocket` is `AppModel.makeCameraSocket(source: .phone)`.
    func start(makeSocket: () -> CameraSocket?) async {
        guard phase == .idle || phase == .denied || phase == .noCamera || isReplaced else { return }
        stop()
        guard CameraCapture.isAvailable else {
            phase = .noCamera
            return
        }
        guard await CameraPermission.request() else {
            phase = .denied
            return
        }
        guard let socket = makeSocket() else { return }
        phase = .starting
        choices = CameraCapture.devices().map(CameraChoice.init)
        let capture = CameraCapture()
        let slot = LatestFrameSlot<CameraFrameImage>()
        let feed = self.feed
        capture.onFrame = { frame in
            slot.put(frame)
            Task { @MainActor in feed.publish(frame.image) }
        }
        self.capture = capture
        self.socket = socket
        self.slot = slot
        guard await capture.start(deviceID: deviceID) else {
            phase = .noCamera
            return
        }
        deviceID = capture.device?.uniqueID
        feed.setRunning(true)
        startedAt = ProcessInfo.processInfo.systemUptime
        rate = SendRate()
        phase = .streaming
        beginSending(socket: socket, slot: slot)
    }

    /// Streams frames handed to `push(_:)` instead of this device's camera, for example the Meta glasses during
    /// Learn. `makeSocket` is `AppModel.makeCameraSocket(source: .glasses)`.
    func startPushing(makeSocket: () -> CameraSocket?) async {
        guard phase == .idle || isReplaced else { return }
        stop()
        guard let socket = makeSocket() else { return }
        let slot = LatestFrameSlot<CameraFrameImage>()
        self.socket = socket
        self.slot = slot
        isPushing = true
        startedAt = ProcessInfo.processInfo.systemUptime
        rate = SendRate()
        phase = .streaming
        beginSending(socket: socket, slot: slot)
    }

    /// One frame for `startPushing`. Only the newest waits; older ones are replaced. Any size; frames larger than
    /// the send size are scaled down off the main thread.
    func push(_ image: CGImage) {
        guard isPushing else { return }
        slot?.put(CameraFrameImage(image: image))
    }

    private func beginSending(socket: CameraSocket, slot: LatestFrameSlot<CameraFrameImage>) {
        setIdleTimer(disabled: true)
        tasks.append(Task { [weak self] in
            await socket.start()
            for await event in socket.events {
                self?.handle(event)
            }
        })
        let owner = WeakBox(self)
        tasks.append(Task.detached(priority: .userInitiated) {
            await CameraStreamer.sendLoop(sink: socket, slot: slot) { size in
                await owner.value?.didSend(size: size)
            } didDrop: {
                await owner.value?.didDrop()
            } minGap: {
                await owner.value?.minGap ?? FrameSizing.sendGap
            }
        })
        tasks.append(Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                self?.tick()
            }
        })
        #if os(iOS)
        updateThermal()
        tasks.append(Task { [weak self] in
            for await _ in NotificationCenter.default.notifications(named: ProcessInfo.thermalStateDidChangeNotification) {
                self?.updateThermal()
            }
        })
        #endif
    }

    func stop() {
        tasks.forEach { $0.cancel() }
        tasks = []
        slot?.close()
        slot = nil
        capture?.stop()
        capture = nil
        if let socket { Task { await socket.stop() } }
        socket = nil
        if !isPushing { feed.setRunning(false) }
        isPushing = false
        setIdleTimer(disabled: false)
        if phase == .streaming || phase == .starting { phase = .idle }
        connection = .idle
        isActiveCamera = nil
        sentFPS = 0
    }

    /// Switches camera without dropping the socket.
    func switchCamera(to id: String) async {
        guard let capture else {
            deviceID = id
            return
        }
        _ = await capture.start(deviceID: id)
        // Set after the switch, so the preview (which watches this) turns with the new camera.
        deviceID = capture.device?.uniqueID ?? id
    }

    @discardableResult
    func next() async -> Bool { await socket?.next() ?? false }

    @discardableResult
    func back() async -> Bool { await socket?.back() ?? false }

    var captureSession: CameraCapture? { capture }

    // MARK: - Private

    private var isReplaced: Bool {
        if case .replaced = phase { return true }
        return false
    }

    private var minGap: Duration { isThrottled ? .seconds(2) : FrameSizing.sendGap }

    private func handle(_ event: HubSocket.Event) {
        switch event {
        case .state(let new):
            connection = new
            if case .stopped(let reason) = new {
                phase = .replaced(reason)
                capture?.stop()
                feed.setRunning(false)
                setIdleTimer(disabled: false)
            }
            if !new.isConnected { isActiveCamera = nil }
        case .message(.cameraStatus(let status)):
            isActiveCamera = status.active
        case .message(.state(let state)):
            self.state = state
        default:
            break
        }
    }

    private func didSend(size: CGSize) {
        let now = ProcessInfo.processInfo.systemUptime
        rate.record(now)
        framesSent += 1
        frameSize = size
        sentFPS = rate.fps(now: now, since: startedAt)
    }

    private func didDrop() { framesDropped += 1 }

    private func tick() {
        let now = ProcessInfo.processInfo.systemUptime
        rate.trim(now: now)
        sentFPS = rate.fps(now: now, since: startedAt)
    }

    #if os(iOS)
    private func updateThermal() {
        let state = ProcessInfo.processInfo.thermalState
        isThrottled = state == .serious || state == .critical
    }
    #endif

    private func setIdleTimer(disabled: Bool) {
        #if os(iOS)
        UIApplication.shared.isIdleTimerDisabled = disabled
        #endif
    }

    /// Takes the newest frame, encodes it and hands it to the socket, at most once per `minGap`. If the socket is
    /// still busy with the previous frame, this frame is dropped and the loop waits for the next one: nothing
    /// queues, so the hub always sees the latest moment. Runs off the main thread.
    nonisolated static func sendLoop(socket: CameraSocket, slot: LatestFrameSlot<CameraFrameImage>,
                                     encoder: FrameEncoder = .shared,
                                     didSend: @Sendable (CGSize) async -> Void,
                                     minGap: @Sendable () async -> Duration) async {
        await sendLoop(sink: socket, slot: slot, encoder: encoder, didSend: didSend, minGap: minGap)
    }

    /// The loop behind `sendLoop(socket:...)`, for any sink. `didDrop` counts frames the sink refused.
    nonisolated static func sendLoop<Sink: FrameSink>(sink: Sink, slot: LatestFrameSlot<CameraFrameImage>,
                                                      encoder: FrameEncoder = .shared,
                                                      didSend: @Sendable (CGSize) async -> Void,
                                                      didDrop: @Sendable () async -> Void = {},
                                                      retryDelay: Duration = .milliseconds(66),
                                                      minGap: @Sendable () async -> Duration) async {
        let clock = ContinuousClock()
        var lastSent: ContinuousClock.Instant?
        while !Task.isCancelled, var frame = await slot.take() {
            if let lastSent {
                let gap = await minGap()
                if clock.now - lastSent < gap {
                    try? await Task.sleep(until: lastSent + gap, clock: clock)
                    if let newer = slot.poll() { frame = newer }
                }
            }
            guard !Task.isCancelled else { return }
            // Not connected or still busy: drop this frame before spending time encoding it, and wait a frame
            // interval so a reconnect does not spin through every camera frame.
            guard await sink.isReady() else {
                await didDrop()
                try? await Task.sleep(for: retryDelay)
                continue
            }
            guard let image = encoder.fitted(frame.image), let jpeg = encoder.jpeg(image) else { continue }
            if await sink.trySend(jpeg) {
                lastSent = clock.now
                await didSend(CGSize(width: image.width, height: image.height))
            } else {
                await didDrop()
                try? await Task.sleep(for: retryDelay)
            }
        }
    }
}

/// A weak reference that can cross into the sender task.
private struct WeakBox<T: AnyObject & Sendable>: Sendable {
    weak var value: T?
    init(_ value: T?) { self.value = value }
}
