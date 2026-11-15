#if os(macOS)
import CoreGraphics
import CoreImage
import CoreMedia
import Foundation
import Observation
@preconcurrency import ScreenCaptureKit

/// A window the person can stream from, for example a WhatsApp video call showing their glasses' view.
struct WindowCandidate: Identifiable, Hashable, @unchecked Sendable {
    let id: CGWindowID
    let title: String
    let appName: String
    let bundleID: String
    let size: CGSize
    var thumbnail: CGImage?
    let window: SCWindow

    /// Call apps first, so the glasses call is at the top of the picker.
    var priority: Int { WindowCatalog.callApps[bundleID] ?? 100 }
    var isCallApp: Bool { WindowCatalog.callApps[bundleID] != nil }

    static func == (a: Self, b: Self) -> Bool { a.id == b.id && a.thumbnail === b.thumbnail }
    func hash(into h: inout Hasher) { h.combine(id) }
}

/// Lists windows with ScreenCaptureKit. Only on-screen, normal windows of other apps, at least 200 points wide.
enum WindowCatalog {
    /// Bundle ids of call apps, by priority.
    static let callApps: [String: Int] = [
        "net.whatsapp.WhatsApp": 0,
        "com.facebook.archon": 1,           // Messenger for Mac
        "com.facebook.archon.developerID": 1,
        "com.apple.FaceTime": 2,
    ]

    static var hasPermission: Bool { CGPreflightScreenCaptureAccess() }

    static func windows(thumbnails: Bool = true) async throws -> [WindowCandidate] {
        let content = try await SCShareableContent.excludingDesktopWindows(true, onScreenWindowsOnly: true)
        let me = Bundle.main.bundleIdentifier
        var list = content.windows.compactMap { w -> WindowCandidate? in
            guard w.windowLayer == 0, w.frame.width >= 200, w.frame.height >= 150,
                  let app = w.owningApplication, app.bundleIdentifier != me else { return nil }
            let title = (w.title ?? "").trimmingCharacters(in: .whitespaces)
            return WindowCandidate(id: w.windowID, title: title.isEmpty ? app.applicationName : title,
                                   appName: app.applicationName, bundleID: app.bundleIdentifier,
                                   size: w.frame.size, thumbnail: nil, window: w)
        }
        list.sort { ($0.priority, $0.appName, $0.title) < ($1.priority, $1.appName, $1.title) }
        guard thumbnails else { return list }
        for i in list.indices {
            list[i].thumbnail = try? await thumbnail(list[i].window)
        }
        return list
    }

    /// A small still of one window, for the picker. Only that window is captured.
    static func thumbnail(_ window: SCWindow) async throws -> CGImage {
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let config = SCStreamConfiguration()
        let scale = min(1, 320 / max(window.frame.width, 1))
        config.width = max(2, Int(window.frame.width * scale))
        config.height = max(2, Int(window.frame.height * scale))
        config.showsCursor = false
        return try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
    }
}

/// Streams one chosen window to the hub as a camera (Glasses via WhatsApp call). Captures 3 frames per second
/// of that window only, crops to the call's video (found automatically, adjustable, remembered per app),
/// downscales to 960 px and sends JPEG 0.6 through the camera socket. Stops when the window closes.
@MainActor
@Observable
final class WindowStreamer {
    enum Phase: Equatable {
        case idle
        case starting
        case streaming
        /// The window closed or capture stopped; the words say why.
        case ended(String)
    }

    private(set) var phase: Phase = .idle
    private(set) var connection: ConnectionState = .idle
    private(set) var isActiveCamera: Bool?
    private(set) var state: HubState?
    private(set) var sentFPS: Double = 0
    private(set) var frameSize: CGSize = .zero
    private(set) var window: WindowCandidate?
    private(set) var isGlasses = true
    /// The crop, normalized with a top-left origin.
    private(set) var crop = CallCrop.full
    /// The newest whole-window frame, for the crop editor.
    private(set) var fullFrame: CGImage?
    /// True while the crop came from detection rather than the person.
    private(set) var cropIsAutomatic = true

    var isSending: Bool { phase == .streaming && connection.isConnected }

    @ObservationIgnored private var stream: SCStream?
    @ObservationIgnored private var output: StreamOutput?
    @ObservationIgnored private var socket: CameraSocket?
    @ObservationIgnored private var slot: LatestFrameSlot<CameraFrameImage>?
    @ObservationIgnored private var tasks: [Task<Void, Never>] = []
    @ObservationIgnored private var rate = SendRate()
    @ObservationIgnored private var startedAt: TimeInterval = 0
    @ObservationIgnored private let memory = CallCropMemory()
    @ObservationIgnored private let feed: PhoneCameraFeed

    init(feed: PhoneCameraFeed = .shared) { self.feed = feed }

    /// The camera hello name for a window, "Glasses via WhatsApp call".
    static func cameraName(app: String, glasses: Bool) -> String {
        "\(glasses ? "Glasses" : "Phone") via \(app) call"
    }

    func start(window: WindowCandidate, glasses: Bool, hub: HubURL) async {
        stop()
        self.window = window
        isGlasses = glasses
        phase = .starting
        if let saved = memory.crop(for: window.bundleID) {
            crop = saved
            cropIsAutomatic = false
        } else {
            crop = CallCrop.full
            cropIsAutomatic = true
        }

        let hello = CameraHello(deviceId: CameraHello.deviceId() + "-window",
                                name: Self.cameraName(app: window.appName, glasses: glasses),
                                platform: .ios, source: glasses ? .glasses : .phone)
        let socket = CameraSocket(hub: hub, hello: hello)
        let slot = LatestFrameSlot<CameraFrameImage>()
        self.socket = socket
        self.slot = slot

        let filter = SCContentFilter(desktopIndependentWindow: window.window)
        let config = SCStreamConfiguration()
        let scale = min(2, 1920 / max(window.size.width, 1))
        config.width = max(2, Int(window.size.width * scale))
        config.height = max(2, Int(window.size.height * scale))
        config.minimumFrameInterval = CMTime(value: 1, timescale: 3)
        config.pixelFormat = kCVPixelFormatType_32BGRA
        config.showsCursor = false
        config.queueDepth = 3

        let output = StreamOutput { [weak self] frame in
            Task { @MainActor in self?.receive(frame, slot: slot) }
        } onStop: { [weak self] reason in
            Task { @MainActor in self?.ended(reason) }
        }
        self.output = output
        let stream = SCStream(filter: filter, configuration: config, delegate: output)
        do {
            try stream.addStreamOutput(output, type: .screen, sampleHandlerQueue: output.queue)
            try await stream.startCapture()
        } catch {
            phase = .ended("Could not capture that window. \(error.localizedDescription)")
            return
        }
        self.stream = stream
        phase = .streaming
        startedAt = ProcessInfo.processInfo.systemUptime
        rate = SendRate()
        feed.setRunning(true)

        tasks.append(Task { [weak self] in
            await socket.start()
            for await event in socket.events { self?.handle(event) }
        })
        let owner = WindowWeakBox(self)
        tasks.append(Task.detached(priority: .userInitiated) {
            await CameraStreamer.sendLoop(socket: socket, slot: slot) { size in
                await owner.value?.didSend(size: size)
            } minGap: {
                // 3 frames a second at most: the call window does not change faster than that matters.
                .milliseconds(333)
            }
        })
        tasks.append(Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                self?.tick()
            }
        })
    }

    func stop() {
        tasks.forEach { $0.cancel() }
        tasks = []
        slot?.close()
        slot = nil
        if let stream {
            let box = StreamBox(stream: stream)
            Task { try? await box.stream.stopCapture() }
        }
        stream = nil
        output = nil
        if let socket { Task { await socket.stop() } }
        socket = nil
        feed.setRunning(false)
        if phase == .streaming || phase == .starting { phase = .idle }
        connection = .idle
        isActiveCamera = nil
        sentFPS = 0
    }

    func setGlasses(_ on: Bool, hub: HubURL) async {
        guard on != isGlasses, let window else { return }
        await start(window: window, glasses: on, hub: hub)
    }

    /// The person's crop, saved for this app.
    func setCrop(_ rect: CGRect) {
        crop = rect.intersection(CallCrop.full)
        cropIsAutomatic = false
        if let window { memory.save(crop, for: window.bundleID) }
    }

    /// Back to the automatic crop, forgetting the saved one.
    func autoCrop() {
        if let window { memory.forget(window.bundleID) }
        cropIsAutomatic = true
        if let fullFrame { crop = CallCrop.detect(in: fullFrame) }
    }

    @discardableResult
    func next() async -> Bool { await socket?.next() ?? false }

    @discardableResult
    func back() async -> Bool { await socket?.back() ?? false }

    // MARK: - Private

    private var detectedOnce = false

    private func receive(_ frame: CameraFrameImage, slot: LatestFrameSlot<CameraFrameImage>) {
        guard phase == .streaming else { return }
        fullFrame = frame.image
        if cropIsAutomatic, !detectedOnce {
            crop = CallCrop.detect(in: frame.image)
            detectedOnce = true
        }
        let size = CGSize(width: frame.image.width, height: frame.image.height)
        let rect = CallCrop.pixels(crop, in: size)
        guard let cropped = frame.image.cropping(to: rect),
              let scaled = FrameEncoder.shared.downscale(CIImage(cgImage: cropped)) else { return }
        slot.put(CameraFrameImage(image: scaled))
        feed.publish(scaled)
    }

    private func handle(_ event: HubSocket.Event) {
        switch event {
        case .state(let new):
            connection = new
            if case .stopped(let reason) = new { ended(reason) }
            if !new.isConnected { isActiveCamera = nil }
        case .message(.cameraStatus(let status)): isActiveCamera = status.active
        case .message(.state(let state)): self.state = state
        default: break
        }
    }

    private func ended(_ reason: String) {
        stop()
        phase = .ended(reason)
    }

    private func didSend(size: CGSize) {
        let now = ProcessInfo.processInfo.systemUptime
        rate.record(now)
        frameSize = size
        sentFPS = rate.fps(now: now, since: startedAt)
    }

    private func tick() {
        let now = ProcessInfo.processInfo.systemUptime
        rate.trim(now: now)
        sentFPS = rate.fps(now: now, since: startedAt)
    }
}

/// Receives frames from ScreenCaptureKit on its own queue and reports the stream stopping.
private final class StreamOutput: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {
    let queue = DispatchQueue(label: "com.handover.window.frames", qos: .userInitiated)
    private let onFrame: @Sendable (CameraFrameImage) -> Void
    private let onStop: @Sendable (String) -> Void
    private let context = FrameEncoder.shared.context

    init(onFrame: @escaping @Sendable (CameraFrameImage) -> Void, onStop: @escaping @Sendable (String) -> Void) {
        self.onFrame = onFrame
        self.onStop = onStop
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sampleBuffer.isValid,
              let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false) as? [[SCStreamFrameInfo: Any]],
              let raw = attachments.first?[.status] as? Int, SCFrameStatus(rawValue: raw) == .complete,
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let image = CIImage(cvPixelBuffer: buffer)
        guard let cg = context.createCGImage(image, from: image.extent) else { return }
        onFrame(CameraFrameImage(image: cg))
    }

    func stream(_ stream: SCStream, didStopWithError error: any Error) {
        onStop("The window closed or capture stopped, so HandOver stopped sending it.")
    }
}

private struct StreamBox: @unchecked Sendable { let stream: SCStream }

private struct WindowWeakBox: Sendable {
    weak var value: WindowStreamer?
    init(_ value: WindowStreamer?) { self.value = value }
}
#endif
