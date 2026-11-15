import AVFoundation

/// The short tone played when the camera moves the step on: two soft sine notes (E6 then B6) with a quick
/// attack and a gentle decay, synthesized once into a buffer and played through AVAudioEngine.
@MainActor
final class Chime {
    static let shared = Chime()

    private var engine: AVAudioEngine?
    private var player: AVAudioPlayerNode?
    private var buffer: AVAudioPCMBuffer?

    func play() {
        if engine == nil { setUp() }
        guard let engine, let player, let buffer else { return }
        if !engine.isRunning { try? engine.start() }
        guard engine.isRunning else { return }
        player.scheduleBuffer(buffer, at: nil, options: .interrupts)
        player.play()
    }

    /// Interrupts a verification tone immediately when Learn closes and discards the render graph, so no
    /// scheduled buffer can survive a route or scene transition. The next `play` builds a clean graph.
    func stop() {
        player?.stop()
        engine?.stop()
        engine?.reset()
        player = nil
        engine = nil
        buffer = nil
    }

    private func setUp() {
        let engine = AVAudioEngine()
        let player = AVAudioPlayerNode()
        guard let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1),
              let buffer = Self.render(format: format) else { return }
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        self.engine = engine
        self.player = player
        self.buffer = buffer
    }

    /// Two notes, 0.11 s apart, each with a 6 ms attack and an exponential decay. 0.42 s in all.
    static func render(format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let rate = format.sampleRate
        let length = AVAudioFrameCount(rate * 0.42)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: length),
              let data = buffer.floatChannelData?[0] else { return nil }
        buffer.frameLength = length
        let notes: [(start: Double, freq: Double)] = [(0, 1318.5), (0.11, 1975.5)]
        for i in 0..<Int(length) {
            let t = Double(i) / rate
            var sample = 0.0
            for note in notes where t >= note.start {
                let local = t - note.start
                let attack = min(1, local / 0.006)
                let decay = exp(-local * 9)
                sample += sin(2 * .pi * note.freq * local) * attack * decay * 0.16
            }
            data[i] = Float(sample)
        }
        return buffer
    }
}
