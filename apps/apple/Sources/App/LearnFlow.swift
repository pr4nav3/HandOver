import Foundation
import Observation

/// How HandOver sees the learner's hands during a lesson.
enum LearnCamera: String, CaseIterable, Identifiable, Sendable {
    /// This device's back camera, propped up facing the work.
    case thisDevice
    /// Meta Ray-Ban glasses over Bluetooth (iPhone only, experimental).
    case glasses
    /// A second phone in Be the Camera, or the hub's web capture page on a laptop.
    case otherDevice

    static let key = "handover.learn.camera"

    var id: String { rawValue }

    /// The saved choice, or nil before the first lesson.
    static func saved(_ defaults: UserDefaults = .standard) -> LearnCamera? {
        defaults.string(forKey: key).flatMap(LearnCamera.init(rawValue:))
    }

    /// True when the hub should send live frames back to this app: only when another device is the camera.
    /// When this device is the camera it shows its own preview, so it asks the hub for none (`/ws/ui?frames=0`).
    var wantsHubFrames: Bool { self == .otherDevice }

    /// The glasses need the Meta toolkit, which only the iPhone build links.
    static var glassesAvailable: Bool { GlassesFeature.toolkitLinked }

    @MainActor var title: String {
        switch self {
        case .thisDevice: DeviceWord.this.firstLetterCapitalized
        case .glasses: "Meta glasses"
        case .otherDevice: "Another device"
        }
    }

    @MainActor var symbol: String {
        switch self {
        case .thisDevice:
            #if os(macOS)
            "laptopcomputer"
            #else
            DeviceWord.isPad ? "ipad" : "iphone"
            #endif
        case .glasses: "eyeglasses"
        case .otherDevice: "qrcode"
        }
    }

    /// What it is, in one line.
    @MainActor var line: String {
        switch self {
        case .thisDevice: "Uses the \(DeviceWord.noun)'s camera to watch your hands."
        case .glasses: "Wear them. Guidance plays in their speakers."
        case .otherDevice: "A second phone or a laptop camera watches."
        }
    }

    /// How to set it up, in one line.
    var setup: String {
        switch self {
        case .thisDevice:
            #if os(macOS)
            "Point the Mac's camera at your work."
            #else
            "Prop it up so the back camera sees your hands."
            #endif
        case .glasses: "Needs the Meta AI app with Developer Mode on."
        case .otherDevice: "Scan the code on that device to start its camera."
        }
    }
}

/// Starting and ending a lesson, the camera choice and which tab is open. The root view owns one and puts it in
/// the environment. The hub has one current lesson for everyone; `isRunning` says this app is following it.
@MainActor
@Observable
final class LearnFlow {
    struct PendingStart: Equatable {
        var lessonId: String
        var step: Int?
    }

    /// The open tab (iPhone) or sidebar item (iPad, Mac).
    var section: AppSection = .library
    /// True from Start until End (or the hub drops the lesson).
    private(set) var isRunning = false
    /// The lesson this app started, so Learn can tell the hub to switch back if it moved on.
    private(set) var runningLessonId: String?
    private(set) var camera: LearnCamera
    private(set) var hasChosenCamera: Bool
    /// The camera sheet is open; with `pending`, its button starts that lesson.
    var showCameraSheet = false
    /// A pairing QR can send the app straight to the requested Be the Camera mode. CameraView consumes it.
    private(set) var cameraLaunchIntent: CameraLaunchIntent?
    private(set) var pending: PendingStart?
    /// The glasses, made the first time they are picked and kept so setup survives closing the sheet.
    private(set) var glasses: GlassesController?
    /// A select_lesson sent and not yet answered: its lesson and when it went out. A late `lesson_id: null` (from
    /// an earlier End) can still arrive in that window and must not end the new lesson.
    private(set) var pendingSelect: (lessonId: String, sentAt: Date)?
    /// How long a select waits for its answer before a null lesson counts again.
    static let selectAnswerWindow: TimeInterval = 5

    @ObservationIgnored private let defaults: UserDefaults
    /// Called after the camera changes between "needs live frames from the hub" and "does not", so the
    /// viewer socket can reconnect with the right `frames` setting.
    @ObservationIgnored var onFramesPreferenceChange: (() -> Void)?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let saved = LearnCamera.saved(defaults)
        hasChosenCamera = saved != nil
        var initial = saved ?? .thisDevice
        if initial == .glasses && !LearnCamera.glassesAvailable { initial = .thisDevice }
        camera = initial
    }

    /// Start (or Continue) on a lesson. The first time, the camera sheet asks how HandOver should see your hands;
    /// after that the lesson starts at once with the saved camera, shown as "Camera: ..., Change".
    func requestStart(_ lessonId: String, at step: Int? = nil, model: AppModel) {
        if hasChosenCamera {
            start(lessonId, at: step, model: model)
        } else {
            pending = PendingStart(lessonId: lessonId, step: step)
            showCameraSheet = true
        }
    }

    /// Opens the camera sheet to change the camera only.
    func changeCamera() {
        pending = nil
        showCameraSheet = true
    }

    /// Opens Be the Camera after a purpose-built desktop QR is scanned.
    func openCamera(_ intent: CameraLaunchIntent) {
        cameraLaunchIntent = intent
        section = .camera
    }

    func consumeCameraLaunch(_ intent: CameraLaunchIntent) {
        if cameraLaunchIntent == intent { cameraLaunchIntent = nil }
    }

    /// The sheet's button: saves the camera, closes the sheet, and starts the pending lesson if any.
    func confirm(_ choice: LearnCamera, model: AppModel) {
        choose(choice)
        showCameraSheet = false
        if let pending {
            self.pending = nil
            start(pending.lessonId, at: pending.step, model: model)
        }
    }

    /// The sheet closed without its button.
    func cancelSheet() {
        pending = nil
        showCameraSheet = false
    }

    func choose(_ choice: LearnCamera) {
        // Before any choice the viewer socket asks for frames (see LiveFrames).
        let framesBefore = hasChosenCamera ? camera.wantsHubFrames : true
        camera = choice
        hasChosenCamera = true
        defaults.set(choice.rawValue, forKey: LearnCamera.key)
        if choice.wantsHubFrames != framesBefore { onFramesPreferenceChange?() }
    }

    /// The glasses controller, made on first use.
    func glassesController() -> GlassesController {
        if let glasses { return glasses }
        let made = GlassesController.make()
        glasses = made
        return made
    }

    /// Tells the hub to switch lessons (then `goto` once it has), and opens Learn.
    func start(_ lessonId: String, at step: Int? = nil, model: AppModel, now: Date = Date()) {
        pendingSelect = (lessonId, now)
        model.select(lesson: lessonId)
        if let step, step > 0 {
            Task {
                // goto applies to the hub's current lesson, so wait until the hub switched (at most 3 s).
                for _ in 0..<30 where model.state.lessonId != lessonId {
                    try? await Task.sleep(for: .milliseconds(100))
                }
                if model.state.lessonId == lessonId { model.goto(step: step) }
            }
        }
        runningLessonId = lessonId
        isRunning = true
        section = .learn
    }

    /// Ends the lesson and goes back to Home: tells the hub (end_lesson stops the run and unloads the lesson),
    /// and this app stops following it and stops sending camera frames.
    func end(model: AppModel? = nil) {
        // End can be driven by the hub as well as the close button. Stop process-wide sound here, before the
        // SwiftUI transition, so speech and a verification chime never outlive the lesson screen.
        SpokenGuide.shared.endLessonAudio()
        Chime.shared.stop()
        model?.endLesson(lessonId: runningLessonId)
        isRunning = false
        runningLessonId = nil
        pendingSelect = nil
        glasses?.stop()
        section = .library
    }

    /// The hub's lesson changed. Returns true when the lesson this app follows is gone and Learn should end: the
    /// hub has no lesson, and no select_lesson of ours is still waiting for its answer.
    func hubLessonChanged(to lessonId: String?, now: Date = Date()) -> Bool {
        if let pendingSelect {
            if lessonId == pendingSelect.lessonId || now.timeIntervalSince(pendingSelect.sentAt) > Self.selectAnswerWindow {
                self.pendingSelect = nil
            } else if lessonId == nil {
                return false
            }
        }
        return lessonId == nil && isRunning
    }

    /// Shows a running lesson without telling the hub (previews and snapshots).
    func showRunning(_ lessonId: String?) {
        runningLessonId = lessonId
        isRunning = true
        section = .learn
    }
}

/// Adds `frames=0` to the viewer socket when this device is the camera, so the hub does not send this device's
/// own frames back to it. Read on every (re)connect.
enum LiveFrames {
    static func adjust(_ url: URL, defaults: UserDefaults = .standard) -> URL {
        guard url.path == "/ws/ui", let camera = LearnCamera.saved(defaults), !camera.wantsHubFrames else { return url }
        guard var c = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return url }
        let kept = (c.queryItems ?? []).filter { $0.name != "frames" }
        c.queryItems = kept + [URLQueryItem(name: "frames", value: "0")]
        return c.url ?? url
    }
}
