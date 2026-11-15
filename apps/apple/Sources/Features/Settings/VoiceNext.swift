@preconcurrency import AVFoundation
import Foundation
import Speech

/// Settings keys owned here, and the ones Learn reads (kept as the same strings as `LearnSettings`).
enum SettingsKeys {
    /// Voice Next: listen for "next" and "back". Off by default and stays off until the learner turns it on.
    static let voiceNext = "handover.learn.voiceNext"
    static let captions = "handover.learn.captions"
    static let stepResults = "handover.learn.stepResults"
    static let speakMistakes = "handover.learn.speakMistakes"
    static let keepScreenOn = "handover.learn.keepScreenOn"
}

/// Listens for "next" and "back" with on-device speech recognition, for Learn to use while a lesson is open
/// and Voice Next is on. Learn should pause it while the expert's clip is audible (DESIGN.md 5).
///
///     let voice = VoiceNextListener()
///     try voice.start { command in command == .next ? model.next(reason: .voice) : model.back() }
@MainActor
final class VoiceNextListener {
    enum Command: Sendable { case next, back }

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var handled = 0
    private(set) var isListening = false

    /// True when Voice Next is on in Settings and speech is allowed.
    static var isEnabled: Bool {
        UserDefaults.standard.bool(forKey: SettingsKeys.voiceNext) && AppPermission.speech.status == .allowed
    }

    /// Words heard so far to a command: the newest "next" or "back" after `from` words.
    nonisolated static func command(in transcript: String, after from: Int) -> (Command, Int)? {
        let words = transcript.lowercased().split(whereSeparator: { !$0.isLetter }).map(String.init)
        guard words.count > from else { return nil }
        for (i, word) in words.enumerated().dropFirst(from).reversed() {
            if word == "next" { return (.next, i + 1) }
            if word == "back" { return (.back, i + 1) }
        }
        return nil
    }

    func start(onCommand: @escaping @MainActor (Command) -> Void) throws {
        guard !isListening, let recognizer, recognizer.isAvailable, AppPermission.microphone.status == .allowed else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        request.contextualStrings = ["next", "back"]
        self.request = request
        handled = 0

        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.mixWithOthers, .defaultToSpeaker])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        #endif
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in request.append(buffer) }
        engine.prepare()
        try engine.start()
        isListening = true

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let failed = error != nil
            Task { @MainActor in
                guard let self else { return }
                if let text, let (command, count) = Self.command(in: text, after: self.handled) {
                    self.handled = count
                    onCommand(command)
                }
                if failed { self.stop() }
            }
        }
    }

    func stop() {
        guard isListening else { return }
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
        isListening = false
    }
}
