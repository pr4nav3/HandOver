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
        setIdleTimer(disabled: true)

        tasks.append(Task { [weak self] in
            await socket.start()
            for await event in socket.events {
                self?.handle(event)
            }
        })
        let owner = WeakBox(self)
        tasks.append(Task.detached(priority: .userInitiated) {
            await CameraStreamer.sendLoop(socket: socket, slot: slot) { size in
                await owner.value?.didSend(size: size)
            } minGap: {
                await owner.value?.minGap ?? CameraSocket.minFrameGap
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
        feed.setRunning(false)
        setIdleTimer(disabled: false)
        if phase == .streaming || phase == .starting { phase = .idle }
        connection = .idle
        isActiveCamera = nil
        sentFPS = 0
    }

    /// Switches camera without dropping the socket.
    func switchCamera(to id: String) async {
        deviceID = id
        guard let capture else { return }
        _ = await capture.start(deviceID: id)
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

    private var minGap: Duration { isThrottled ? .seconds(2) : CameraSocket.minFrameGap }

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

    /// Takes the newest frame, encodes it, sends it, waits for that send to finish and for the hub's minimum
    /// gap, then takes the newest again. Nothing queues: frames that arrive meanwhile replace each other.
    nonisolated static func sendLoop(socket: CameraSocket, slot: LatestFrameSlot<CameraFrameImage>,
                                     encoder: FrameEncoder = .shared,
                                     didSend: @Sendable (CGSize) async -> Void,
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
            guard let jpeg = encoder.jpeg(frame.image) else { continue }
            let before = await socket.framesSent
            guard await socket.send(frame: jpeg) else {
                // Not connected yet, or the previous frame is still going out. Try again shortly with
                // whatever is newest then.
                try? await Task.sleep(for: .milliseconds(80))
                continue
            }
            lastSent = clock.now
            // The socket sends in the background; wait until it reports this frame out (or 3 s).
            let deadline = clock.now + .seconds(3)
            while clock.now < deadline, !Task.isCancelled, await socket.framesSent == before {
                try? await Task.sleep(for: .milliseconds(10))
            }
            if await socket.framesSent > before {
                await didSend(CGSize(width: frame.image.width, height: frame.image.height))
            }
        }
    }
}

/// A weak reference that can cross into the sender task.
private struct WeakBox<T: AnyObject & Sendable>: Sendable {
    weak var value: T?
    init(_ value: T?) { self.value = value }
}
