import Foundation
import Observation

/// What the recorder needs from a camera. `CameraRecorder` is the AVFoundation one; tests and previews use fakes.
@MainActor
protocol RecordCaptureEngine: AnyObject {
    /// Camera and microphone access, asking when not decided yet.
    func requestAccess() async -> RecordCaptureAccess
    /// Builds and starts the session for `camera` (nil picks the default). Throws a message to show.
    func start(camera: RecordCamera?, withAudio: Bool) async throws
    func stopSession()
    func startRecording(to url: URL) throws
    /// Finishes the file. Returns when it is closed, or throws why it failed.
    func stopRecording() async throws -> URL
    var canPause: Bool { get }
    func pauseRecording()
    func resumeRecording()
    /// The narration level, 0...1, read at about 20 per second.
    func audioLevel() -> Float?
    /// Cameras to choose from (Mac: built-in, Continuity Camera, Desk View, external).
    func cameras() -> [RecordCamera]
}

struct RecordCaptureAccess: Equatable, Sendable {
    var camera: Bool
    var microphone: Bool
    /// False when this build has no microphone usage text, so asking would end the app.
    var microphoneDeclared = true
    /// False for sources that bring no sound of their own path through the microphone (the glasses).
    var usesMicrophone = true
}

struct RecordCamera: Identifiable, Hashable, Sendable {
    enum Kind: Sendable { case back, front, builtIn, continuity, deskView, external }
    var id: String
    var name: String
    var kind: Kind

    var symbol: String {
        switch self.kind {
        case .back, .front, .continuity: "iphone"
        case .builtIn: "laptopcomputer"
        case .deskView: "rectangle.on.rectangle.angled"
        case .external: "web.camera"
        }
    }
}

/// One finished recording in this session.
struct RecordTake: Identifiable, Equatable, Sendable {
    var id = UUID()
    var url: URL
    var duration: TimeInterval
    var recordedAt: Date
}

/// The recorder (SCREENS.md 12): permissions, the session, start, pause, resume and stop, the timer, the
/// narration meter, and the takes. Haptics and the blink read the counters.
@MainActor
@Observable
final class RecordModel {
    enum Phase: Equatable {
        case starting
        case needsAccess(camera: Bool, microphone: Bool)
        case ready
        case recording
        case paused
        case finishing
        case review
        case failed(String)
    }

    private(set) var phase: Phase = .starting
    private(set) var takes: [RecordTake] = []
    /// The 24 newest narration levels, 0...1, oldest first (DESIGN.md 3.9).
    private(set) var levels: [Float] = Array(repeating: 0, count: 24)
    /// True after 3 s of silence while recording ("No sound. Check the mic.").
    private(set) var isSilent = false
    private(set) var withAudio = true
    /// This build has no microphone usage text, so it records without sound (the app would end if it asked).
    private(set) var microphoneMissingFromBuild = false
    private(set) var cameras: [RecordCamera] = []
    var camera: RecordCamera?
    /// Bumped on start and stop, for haptics and the blink.
    private(set) var startCount = 0
    private(set) var stopCount = 0

    private(set) var engine: any RecordCaptureEngine
    private let now: () -> Date
    @ObservationIgnored private var choseSilence = false
    @ObservationIgnored private var recordingStarted: Date?
    @ObservationIgnored private var pausedTotal: TimeInterval = 0
    @ObservationIgnored private var pausedAt: Date?
    @ObservationIgnored private var lastSound: Date?
    @ObservationIgnored private var meterTask: Task<Void, Never>?
    @ObservationIgnored private let folder: URL

    init(engine: any RecordCaptureEngine, now: @escaping () -> Date = Date.init,
         folder: URL = FileManager.default.temporaryDirectory.appending(path: "handover-takes", directoryHint: .isDirectory)) {
        self.engine = engine
        self.now = now
        self.folder = folder
    }

    var isRecording: Bool { phase == .recording || phase == .paused }
    var latestTake: RecordTake? { takes.last }

    /// Seconds recorded so far, not counting pauses.
    func elapsed(at date: Date? = nil) -> TimeInterval {
        guard let recordingStarted else { return 0 }
        let t = date ?? now()
        let pausedNow = pausedAt.map { t.timeIntervalSince($0) } ?? 0
        return max(0, t.timeIntervalSince(recordingStarted) - pausedTotal - pausedNow)
    }

    /// Asks for access and starts the camera.
    func prepare() async {
        phase = .starting
        let access = await engine.requestAccess()
        guard access.camera else {
            phase = .needsAccess(camera: true, microphone: !access.microphone)
            return
        }
        guard access.usesMicrophone else {
            withAudio = false
            microphoneMissingFromBuild = false
            await startSession()
            return
        }
        if !access.microphone && !choseSilence && access.microphoneDeclared {
            phase = .needsAccess(camera: false, microphone: true)
            return
        }
        microphoneMissingFromBuild = !access.microphoneDeclared
        withAudio = !choseSilence && access.microphone && access.microphoneDeclared
        await startSession()
    }

    /// "Record Without Sound" after the microphone was refused.
    func continueWithoutSound() async {
        choseSilence = true
        withAudio = false
        await startSession()
    }

    /// Switches between the phone camera and the glasses (never while recording).
    func use(engine: any RecordCaptureEngine) async {
        guard !isRecording, engine !== self.engine else { return }
        meterTask?.cancel()
        self.engine.stopSession()
        self.engine = engine
        camera = nil
        await prepare()
    }

    func select(_ camera: RecordCamera) async {
        guard !isRecording, camera != self.camera else { return }
        self.camera = camera
        await startSession()
    }

    private func startSession() async {
        phase = .starting
        cameras = engine.cameras()
        if camera == nil { camera = cameras.first }
        do {
            try await engine.start(camera: camera, withAudio: withAudio)
            phase = .ready
            startMeter()
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
    }

    /// The shutter: start when ready, stop when recording or paused.
    func shutter() async {
        switch phase {
        case .ready, .review: startRecording()
        case .recording, .paused: await stopRecording()
        default: break
        }
    }

    func startRecording() {
        guard phase == .ready || phase == .review else { return }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let stamp = Int(now().timeIntervalSince1970)
        let url = folder.appending(path: "take-\(stamp)-\(takes.count + 1).mov")
        do {
            try engine.startRecording(to: url)
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            return
        }
        recordingStarted = now()
        pausedTotal = 0
        pausedAt = nil
        lastSound = now()
        isSilent = false
        phase = .recording
        startCount += 1
    }

    func pause() {
        guard phase == .recording, engine.canPause else { return }
        engine.pauseRecording()
        pausedAt = now()
        phase = .paused
    }

    func resume() {
        guard phase == .paused else { return }
        engine.resumeRecording()
        if let pausedAt { pausedTotal += now().timeIntervalSince(pausedAt) }
        pausedAt = nil
        lastSound = now()
        phase = .recording
    }

    func stopRecording() async {
        guard isRecording else { return }
        let duration = elapsed()
        phase = .finishing
        stopCount += 1
        do {
            let url = try await engine.stopRecording()
            takes.append(RecordTake(url: url, duration: duration, recordedAt: now()))
            phase = .review
        } catch {
            phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
        }
        recordingStarted = nil
    }

    /// "Record Again": throws the newest take away and returns to the camera.
    func discardLatest() {
        if let take = takes.popLast() { try? FileManager.default.removeItem(at: take.url) }
        phase = .ready
    }

    /// Close while recording ("Discard"): stops and deletes the file.
    func discardRecording() async {
        guard isRecording else { return }
        phase = .finishing
        if let url = try? await engine.stopRecording() { try? FileManager.default.removeItem(at: url) }
        recordingStarted = nil
        phase = .ready
    }

    /// Back to the camera after review without discarding (the take stays in the takes list).
    func keepAndContinue() { if phase == .review { phase = .ready } }

    func shutdown() {
        meterTask?.cancel()
        meterTask = nil
        engine.stopSession()
    }

    // MARK: - Meter

    private func startMeter() {
        meterTask?.cancel()
        guard withAudio else { return }
        meterTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(50))
                guard let self else { return }
                self.sample(self.engine.audioLevel())
            }
        }
    }

    /// Takes one meter reading: smooths it into the bars and tracks silence.
    func sample(_ level: Float?) {
        let value = level ?? 0
        let smoothed = Self.smooth(previous: levels.last ?? 0, next: value)
        levels.removeFirst()
        levels.append(smoothed)
        guard phase == .recording else {
            isSilent = false
            return
        }
        if value > Self.silenceLevel { lastSound = now() }
        isSilent = lastSound.map { now().timeIntervalSince($0) >= 3 } ?? false
    }

    static let silenceLevel: Float = 0.06

    /// Rises fast, falls slowly, like the Voice Memos meter.
    static func smooth(previous: Float, next: Float) -> Float {
        next >= previous ? previous + (next - previous) * 0.6 : previous + (next - previous) * 0.25
    }

    /// Average power in dBFS (-160...0) as 0...1 for the bars: -50 dB and below is silent.
    static func normalize(decibels: Float) -> Float {
        guard decibels.isFinite else { return 0 }
        let floor: Float = -50
        return max(0, min(1, (decibels - floor) / -floor))
    }

    /// "00:42", "1:02:09".
    static func clock(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds))
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        func two(_ v: Int) -> String { v < 10 ? "0\(v)" : "\(v)" }
        return h > 0 ? "\(h):\(two(m)):\(two(s))" : "\(two(m)):\(two(s))"
    }

    /// The review sheet's title field (SCREENS.md 12.4): "Lesson Nov 14".
    static func defaultTitle(_ date: Date) -> String {
        "Lesson \(date.formatted(.dateTime.month(.abbreviated).day()))"
    }

    /// Puts the model in a state for previews and snapshots.
    func preview(phase: Phase, elapsed: TimeInterval = 0, levels: [Float]? = nil, takes: [RecordTake] = []) {
        self.phase = phase
        if let levels { self.levels = Array(levels.suffix(24)) }
        self.takes = takes
        if phase == .recording || phase == .paused { recordingStarted = now().addingTimeInterval(-elapsed) }
    }
}
