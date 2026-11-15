import CoreGraphics
import Foundation
import Observation

/// The glasses recording source (SCREENS.md 12.2), off by default and marked Experimental. Turn it on with the
/// user default `handover.feature.glasses` (or the launch argument `-handover.feature.glasses YES`).
///
/// It needs Meta's Wearables Device Access Toolkit (MWDAT 1.0.1, linked with Swift Package Manager; API names as
/// in ios/Sources/GlassesCameraSource.swift). The only transport is Bluetooth Classic, through the
/// External Accessory protocol `com.meta.ar.wearable` and the bluetooth-peripheral and external-accessory
/// background modes in Info.plist. It needs no Hotspot or Wi-Fi Info entitlement, so a free personal team signs
/// it. Not tested on glasses yet, so the card never claims it works, and every failure falls back to the phone.
enum GlassesFeature {
    static let key = "handover.feature.glasses"
    static var isEnabled: Bool { UserDefaults.standard.bool(forKey: key) }
    /// The label for the source switcher and the card.
    static let experimentalLabel = "Experimental"
    /// The note under the glasses card.
    static let requirement = "Streams over Bluetooth. If the glasses stop, HandOver switches to the iPhone camera and tells you."

    /// True when this build links the toolkit.
    static var toolkitLinked: Bool {
        #if canImport(MWDATCore) && canImport(MWDATCamera) && os(iOS)
        true
        #else
        false
        #endif
    }
}

/// How the glasses stream: Bluetooth Classic only. It carries far less than the glasses' own Wi-Fi, so frames
/// are `.medium` or `.low` at 15 fps (see `attempts` in GlassesToolkit.swift).
enum GlassesTransport: Sendable {
    case bluetooth

    static let current = GlassesTransport.bluetooth

    /// The frame rate every attempt uses.
    static let frameRate = 15
}

/// Where the glasses are in registration, permission and streaming. Copy per state is in SCREENS.md 12.2.
enum GlassesState: Equatable, Sendable {
    /// This build has no toolkit, or the platform has none (Mac).
    case unavailable
    case notRegistered
    case developerModeOff
    case metaAIMissing
    case waitingForMetaAI
    case noDevice
    case permissionNeeded
    case connecting
    /// Measured from arriving frames, never the requested values.
    case streaming(width: Int, height: Int, fps: Int)
    case paused
    case batteryLow
    case tooHot
    case powerLimit
    case lost
    case failed(String)

    var title: String {
        switch self {
        case .unavailable: "Ray-Ban Meta"
        case .notRegistered: "Ray-Ban Meta"
        case .developerModeOff: "Turn on Developer Mode"
        case .metaAIMissing: "Install Meta AI"
        case .waitingForMetaAI: "Waiting for Meta AI"
        case .noDevice: "Glasses not found"
        case .permissionNeeded: "Allow camera access"
        case .connecting: "Connecting"
        case .streaming(let w, let h, let fps): "Glasses, \(w) x \(h), \(fps) fps"
        case .paused: "Paused"
        case .batteryLow: "Glasses battery low"
        case .tooHot: "Glasses too hot"
        case .powerLimit: "Glasses need a break"
        case .lost: "Glasses disconnected"
        case .failed: "Glasses stopped"
        }
    }

    var message: String? {
        switch self {
        case .unavailable: "This build does not include the Meta glasses toolkit."
        case .notRegistered: "HandOver asks the Meta AI app for access to your glasses camera."
        case .developerModeOff:
            "In the Meta AI app: Settings > App Info, tap the version 5 times, then turn on Developer Mode."
        case .metaAIMissing: "Install the Meta AI app and pair your glasses, then try again."
        case .waitingForMetaAI: "Approve HandOver in the Meta AI app."
        case .noDevice: "Put on your glasses and make sure they are connected to this iPhone."
        case .permissionNeeded: "The glasses need permission to share their camera with HandOver."
        case .connecting, .streaming: nil
        case .paused: "The glasses paused the camera."
        case .batteryLow: "Charge the glasses or switch to the iPhone camera."
        case .tooHot: "Let them cool down, or switch to the iPhone camera."
        case .powerLimit: "They hit a power limit. Try again, or switch to the iPhone camera."
        case .lost: "The glasses stopped sending video."
        case .failed(let why): why
        }
    }

    var isBusy: Bool { self == .connecting || self == .waitingForMetaAI }
    var isStreaming: Bool { if case .streaming = self { return true } else { return false } }
    /// Errors that offer "Use iPhone".
    var offersPhone: Bool { [.batteryLow, .tooHot, .powerLimit, .lost].contains(self) || { if case .failed = self { true } else { false } }() }
}

/// Talks to the glasses. The MWDAT implementation lives in GlassesToolkit.swift; without the toolkit every
/// action leaves the state at `.unavailable`.
@MainActor
@Observable
final class GlassesController {
    private(set) var state: GlassesState
    private(set) var deviceName: String?
    /// Only when the toolkit reports a value (DESIGN.md 3.17 honesty rule).
    private(set) var battery: Int?
    /// The newest preview frame while streaming.
    private(set) var frame: CGImage?
    private(set) var isRecording = false

    @ObservationIgnored var toolkit: GlassesToolkitBridge?
    /// Gets every new frame without observing `frame`, so a sender does not redraw its screen once per frame.
    @ObservationIgnored var onFrame: (@MainActor (CGImage) -> Void)?

    init(state: GlassesState? = nil) {
        self.state = state ?? (GlassesFeature.toolkitLinked ? .notRegistered : .unavailable)
    }

    func set(state: GlassesState) { self.state = state }
    func set(device: String?, battery: Int?) {
        deviceName = device
        self.battery = battery
    }
    func set(frame: CGImage?) {
        self.frame = frame
        if let frame { onFrame?(frame) }
    }
    func set(recording: Bool) { isRecording = recording }

    /// Primary action for the current state (Connect Glasses, Try Again, Allow, Resume, Reconnect).
    func connect() { toolkit?.connect(self) }
    func allowCamera() { toolkit?.allowCamera(self) }
    func cancel() { toolkit?.stop(self) }
    func stop() { toolkit?.stop(self) }
    func startRecording(to url: URL) throws {
        guard let toolkit else { throw RecorderError.failed(GlassesState.unavailable.message ?? "") }
        try toolkit.startRecording(self, to: url)
    }
    func stopRecording() async throws -> URL {
        guard let toolkit else { throw RecorderError.notRecording }
        return try await toolkit.stopRecording(self)
    }

    /// Meta AI sends HandOver back with a URL after registration. The app hands it here.
    static func handle(url: URL) {
        GlassesToolkitHooks.handle(url)
    }
}

/// What the toolkit file provides.
@MainActor
protocol GlassesToolkitBridge: AnyObject {
    func connect(_ controller: GlassesController)
    func allowCamera(_ controller: GlassesController)
    func stop(_ controller: GlassesController)
    func startRecording(_ controller: GlassesController, to url: URL) throws
    func stopRecording(_ controller: GlassesController) async throws -> URL
}

extension GlassesController {
    /// A controller wired to the toolkit when this build has it.
    static func make() -> GlassesController {
        let controller = GlassesController()
        controller.toolkit = GlassesToolkitHooks.makeBridge()
        return controller
    }
}

/// The glasses as a recording engine for `RecordModel`. Video only (see GlassesWriter); no pause.
@MainActor
final class GlassesCaptureEngine: RecordCaptureEngine {
    let controller: GlassesController
    init(controller: GlassesController) { self.controller = controller }

    func requestAccess() async -> RecordCaptureAccess {
        RecordCaptureAccess(camera: true, microphone: false, usesMicrophone: false)
    }

    func start(camera: RecordCamera?, withAudio: Bool) async throws {
        if controller.state == .unavailable { throw RecorderError.failed(GlassesState.unavailable.message ?? "") }
        if !controller.state.isStreaming && !controller.state.isBusy { controller.connect() }
    }

    func stopSession() {}
    func startRecording(to url: URL) throws { try controller.startRecording(to: url) }
    func stopRecording() async throws -> URL { try await controller.stopRecording() }
    var canPause: Bool { false }
    func pauseRecording() {}
    func resumeRecording() {}
    func audioLevel() -> Float? { nil }
    func cameras() -> [RecordCamera] { [] }
}

/// When the glasses source gives up and the recorder moves to the phone camera on its own.
enum GlassesFallback {
    /// Connecting this long without a frame counts as a failure.
    static let connectTimeout: Duration = .seconds(15)

    /// States that send the recorder back to the phone camera.
    static func shouldFallBack(_ state: GlassesState) -> Bool {
        switch state {
        case .batteryLow, .tooHot, .powerLimit, .lost, .failed: true
        default: false
        }
    }
}
