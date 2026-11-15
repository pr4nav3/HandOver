import AVFoundation
import Observation
import SwiftUI

/// What is spoken and in what order. Pure, so tests drive it with made-up times.
/// - Never two at once: a line starts only when the one before has finished.
/// - No repeats: the same words are dropped if they started, or are waiting, within the last 3 s.
/// - Mistakes go to the front of the line; at most 3 lines wait, the oldest step line is dropped first.
struct SpeechQueue: Equatable, Sendable {
    enum Kind: Equatable, Sendable {
        case step, mistake, result, done
    }

    struct Line: Equatable, Sendable {
        var text: String
        var kind: Kind
    }

    static let repeatWindow: TimeInterval = 3
    static let maxPending = 3

    private(set) var speaking: Line?
    private(set) var pending: [Line] = []
    private var lastStarted: [String: Date] = [:]

    /// Adds a line. Returns the line to start now when nothing is speaking.
    mutating func enqueue(_ text: String, kind: Kind, at now: Date) -> Line? {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if speaking?.text == text || pending.contains(where: { $0.text == text }) { return nil }
        if let last = lastStarted[text], now.timeIntervalSince(last) < Self.repeatWindow { return nil }
        let line = Line(text: text, kind: kind)
        if kind == .mistake {
            let firstNonMistake = pending.firstIndex { $0.kind != .mistake } ?? pending.endIndex
            pending.insert(line, at: firstNonMistake)
        } else {
            pending.append(line)
        }
        while pending.count > Self.maxPending {
            if let i = pending.firstIndex(where: { $0.kind == .step }) { pending.remove(at: i) } else { pending.removeFirst() }
        }
        return speaking == nil ? startNext(at: now) : nil
    }

    /// The line on air finished. Returns the next one to start.
    mutating func finished(at now: Date) -> Line? {
        speaking = nil
        return startNext(at: now)
    }

    /// Drops everything waiting (a new lesson, Learn closing).
    mutating func clear() {
        pending.removeAll()
        speaking = nil
    }

    private mutating func startNext(at now: Date) -> Line? {
        guard !pending.isEmpty else { return nil }
        let line = pending.removeFirst()
        speaking = line
        lastStarted[line.text] = now
        lastStarted = lastStarted.filter { now.timeIntervalSince($0.value) < Self.repeatWindow * 4 }
        return line
    }
}

/// Spoken guidance for a learner wearing glasses or headphones (the glasses' open-ear speakers are a Bluetooth
/// route). Speaks through whatever route is active with the best installed English voice, ducks other audio
/// while it talks, and asks Learn to duck the clip so it never talks over the narration.
@MainActor
@Observable
final class SpokenGuide: NSObject {
    static let shared = SpokenGuide()

    static let enabledKey = "handover.learn.spokenGuidance"
    static let verbosityKey = "handover.learn.spokenVerbosity"

    enum Verbosity: String, CaseIterable, Identifiable, Sendable {
        case stepsAndMistakes, mistakesOnly
        var id: String { rawValue }
        var title: String { self == .stepsAndMistakes ? "Steps and Mistakes" : "Mistakes Only" }
    }

    /// The output route, when it is Bluetooth.
    struct Route: Equatable, Sendable {
        var name: String
        var isGlasses: Bool
    }

    private(set) var isSpeaking = false
    private(set) var bluetoothRoute: Route?
    @ObservationIgnored private var queue = SpeechQueue()
    @ObservationIgnored private let synth = AVSpeechSynthesizer()
    @ObservationIgnored private lazy var voice: AVSpeechSynthesisVoice? = Self.bestVoice()

    override init() {
        super.init()
        synth.delegate = self
        #if os(iOS)
        refreshRoute()
        NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil,
                                               queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refreshRoute() }
        }
        #endif
    }

    /// On when the person turned it on; with no choice yet, on while a Bluetooth route is connected.
    var isEnabled: Bool {
        get {
            access(keyPath: \.isEnabledStorage)
            if let stored = UserDefaults.standard.object(forKey: Self.enabledKey) as? Bool { return stored }
            return bluetoothRoute != nil
        }
        set {
            withMutation(keyPath: \.isEnabledStorage) {
                UserDefaults.standard.set(newValue, forKey: Self.enabledKey)
            }
            if !newValue { stop() }
        }
    }
    @ObservationIgnored private var isEnabledStorage = 0

    var verbosity: Verbosity {
        Verbosity(rawValue: UserDefaults.standard.string(forKey: Self.verbosityKey) ?? "") ?? .stepsAndMistakes
    }

    /// Queues a line if guidance is on and the verbosity allows it.
    func say(_ text: String, kind: SpeechQueue.Kind) {
        guard isEnabled else { return }
        if verbosity == .mistakesOnly, kind != .mistake { return }
        if let line = queue.enqueue(text, kind: kind, at: Date()) { start(line) }
    }

    /// Speaks a mistake even with guidance off (the Speak Mistakes setting).
    func sayMistake(_ text: String) {
        if let line = queue.enqueue(text, kind: .mistake, at: Date()) { start(line) }
    }

    func stop() {
        queue.clear()
        synth.stopSpeaking(at: .immediate)
        finish()
    }

    private func start(_ line: SpeechQueue.Line) {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers, .allowBluetoothA2DP])
        try? session.setActive(true)
        #endif
        isSpeaking = true
        let utterance = AVSpeechUtterance(string: line.text)
        utterance.voice = voice
        utterance.prefersAssistiveTechnologySettings = true
        synth.speak(utterance)
    }

    private func next() {
        if let line = queue.finished(at: Date()) { start(line) } else { finish() }
    }

    private func finish() {
        guard isSpeaking else { return }
        isSpeaking = false
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    /// The best installed en-US voice: Premium, then Enhanced, then the default.
    static func bestVoice(language: String = "en-US") -> AVSpeechSynthesisVoice? {
        let voices = AVSpeechSynthesisVoice.speechVoices().filter { $0.language == language }
        func rank(_ q: AVSpeechSynthesisVoiceQuality) -> Int {
            switch q {
            case .premium: 3
            case .enhanced: 2
            default: 1
            }
        }
        return voices.max { rank($0.quality) < rank($1.quality) } ?? AVSpeechSynthesisVoice(language: language)
    }

    #if os(iOS)
    private func refreshRoute() {
        let bluetooth: Set<AVAudioSession.Port> = [.bluetoothA2DP, .bluetoothHFP, .bluetoothLE]
        let output = AVAudioSession.sharedInstance().currentRoute.outputs.first { bluetooth.contains($0.portType) }
        bluetoothRoute = output.map { Route(name: $0.portName, isGlasses: Self.looksLikeGlasses($0.portName)) }
    }
    #endif

    nonisolated static func looksLikeGlasses(_ name: String) -> Bool {
        let n = name.lowercased()
        return n.contains("ray-ban") || n.contains("rayban") || n.contains("meta") || n.contains("glasses")
    }
}

extension SpokenGuide: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.next() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.next() }
    }
}

/// The small speaker in Learn's top bar while audio goes to glasses or Bluetooth headphones. Tap toggles
/// spoken guidance.
struct SpokenGuideIndicator: View {
    var guide: SpokenGuide = .shared
    @Environment(\.theme) private var theme

    var body: some View {
        if let route = guide.bluetoothRoute {
            Button {
                Haptics.tap()
                guide.isEnabled.toggle()
            } label: {
                HStack(spacing: 4) {
                    Image(systemName: route.isGlasses ? "eyeglasses" : "headphones")
                    Image(systemName: guide.isEnabled ? "speaker.wave.2.fill" : "speaker.slash")
                }
                .font(theme.fonts.badge)
                .foregroundStyle(guide.isEnabled ? theme.colors.accentInk : theme.colors.ink2)
                .padding(.horizontal, 8)
                .frame(minHeight: HOSize.badge)
                .background(guide.isEnabled ? theme.colors.accentSoft : theme.colors.well, in: Capsule())
                .frame(minHeight: HOSize.touch)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(guide.isEnabled ? "Spoken guidance on, through \(route.name)"
                                : "Spoken guidance off, \(route.name) connected")
            .accessibilityHint("Double tap to turn spoken guidance \(guide.isEnabled ? "off" : "on")")
        }
    }
}

/// The two Settings rows for spoken guidance, ready for the Settings screen to embed.
struct SpokenGuidanceSettings: View {
    var guide: SpokenGuide = .shared
    @AppStorage(SpokenGuide.verbosityKey) private var verbosity = SpokenGuide.Verbosity.stepsAndMistakes.rawValue

    var body: some View {
        Toggle("Spoken Guidance", isOn: Binding(get: { guide.isEnabled }, set: { guide.isEnabled = $0 }))
        if guide.isEnabled {
            Picker("Speak", selection: $verbosity) {
                ForEach(SpokenGuide.Verbosity.allCases) { Text($0.title).tag($0.rawValue) }
            }
        }
    }
}
