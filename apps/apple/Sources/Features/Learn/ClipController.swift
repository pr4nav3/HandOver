import AVFoundation
import Foundation
import Observation

/// Plays the expert's clip for the current step: looping, with the step's WebVTT captions parsed and kept in
/// sync (AVPlayer does not render sidecar VTT). Two player slots make a double buffer: the next step's clip
/// (`state.next_clip`, else step + 1) loads paused in the spare slot, so the swap on advance is instant.
@MainActor
@Observable
final class ClipController {
    enum Phase: Equatable, Sendable {
        /// No clip (no lesson, or done).
        case idle
        case loading
        case playing
        case failed
    }

    @MainActor
    final class Slot {
        let url: URL
        let player: AVQueuePlayer
        let looper: AVPlayerLooper
        var captions: CaptionCues?
        var captionTask: Task<Void, Never>?
        /// The layer this player draws into, made when first shown and reused wherever the clip moves.
        private(set) lazy var surface = PlayerSurface(player: player)

        init(url: URL, captionsURL: URL?, muted: Bool) {
            self.url = url
            let item = AVPlayerItem(url: url)
            player = AVQueuePlayer()
            player.isMuted = muted
            player.preventsDisplaySleepDuringVideoPlayback = false
            looper = AVPlayerLooper(player: player, templateItem: item)
            if let captionsURL {
                captionTask = Task { [weak self] in
                    guard let (data, response) = try? await URLSession.shared.data(from: captionsURL),
                          (response as? HTTPURLResponse)?.statusCode ?? 200 < 400,
                          let text = String(data: data, encoding: .utf8) else { return }
                    self?.captions = CaptionCues(parsing: text)
                }
            }
        }

        func tearDown() {
            captionTask?.cancel()
            looper.disableLooping()
            player.pause()
            player.removeAllItems()
        }

        var isReady: Bool { player.currentItem?.status == .readyToPlay }
        var hasFailed: Bool {
            looper.status == .failed || player.currentItem?.status == .failed
        }
    }

    /// The two slots; `active` is on screen.
    private(set) var slots: [Slot?] = [nil, nil]
    private(set) var active = 0
    private(set) var phase: Phase = .idle
    /// The caption line showing now, or nil between cues.
    private(set) var caption: String?
    var isMuted = false {
        didSet { for slot in slots { slot?.player.isMuted = isMuted } }
    }
    /// Lowered while spoken guidance talks, so it never talks over the narration.
    var isDucked = false {
        didSet { for slot in slots { slot?.player.volume = isDucked ? 0.15 : 1 } }
    }
    /// A fixed caption for previews and snapshots, where no clip plays.
    @ObservationIgnored private var stillCaption: String?
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var paused = false
    @ObservationIgnored private var wanted: (clip: URL, captions: URL?)?

    init() {}

    /// A controller that shows `caption` and plays nothing (previews, snapshot tests).
    static func still(caption: String?, phase: Phase = .playing) -> ClipController {
        let c = ClipController()
        c.stillCaption = caption
        c.caption = caption
        c.phase = phase
        return c
    }

    var isStill: Bool { stillCaption != nil || (phase != .idle && slots.allSatisfy { $0 == nil }) }
    var activeSlot: Slot? { slots[active] }

    /// Shows `clip` now. Instant when it is the preloaded one; otherwise it loads in place.
    func show(clip: URL?, captions: URL?) {
        if stillCaption != nil { return }
        guard let clip else {
            wanted = nil
            for slot in slots { slot?.tearDown() }
            slots = [nil, nil]
            phase = .idle
            caption = nil
            return
        }
        wanted = (clip, captions)
        if slots[active]?.url == clip { return }
        let spare = 1 - active
        if slots[spare]?.url != clip {
            slots[spare]?.tearDown()
            slots[spare] = Slot(url: clip, captionsURL: captions, muted: isMuted)
            slots[spare]?.player.volume = isDucked ? 0.15 : 1
        }
        slots[active]?.player.pause()
        active = spare
        let slot = slots[spare]!
        slot.player.seek(to: .zero)
        if !paused { slot.player.play() }
        phase = slot.isReady ? .playing : .loading
        caption = nil
        startTicker()
    }

    /// Loads `clip` paused in the spare slot, so a later `show` of it is instant.
    func preload(clip: URL?, captions: URL?) {
        guard stillCaption == nil, let clip, slots[active]?.url != clip else { return }
        let spare = 1 - active
        if slots[spare]?.url == clip { return }
        slots[spare]?.tearDown()
        let slot = Slot(url: clip, captionsURL: captions, muted: isMuted)
        slot.player.pause()
        slot.player.volume = isDucked ? 0.15 : 1
        slots[spare] = slot
    }

    func replay() {
        activeSlot?.player.seek(to: .zero)
        if !paused { activeSlot?.player.play() }
    }

    /// Paused only when the app is in the background or on the done screen.
    func pause() {
        paused = true
        activeSlot?.player.pause()
    }

    func resume() {
        paused = false
        if phase != .failed { activeSlot?.player.play() }
    }

    /// Try Again after "Clip did not load."
    func retry() {
        guard let wanted else { return }
        slots[active]?.tearDown()
        slots[active] = nil
        let target = wanted
        self.wanted = nil
        show(clip: target.clip, captions: target.captions)
    }

    func stop() {
        ticker?.cancel()
        ticker = nil
        for slot in slots { slot?.tearDown() }
        slots = [nil, nil]
        phase = .idle
    }

    private func startTicker() {
        guard ticker == nil else { return }
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                self?.tick()
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
    }

    private func tick() {
        guard let slot = activeSlot else { return }
        if slot.hasFailed {
            if phase != .failed { phase = .failed }
            return
        }
        if phase == .loading, slot.isReady { phase = .playing }
        let seconds = slot.player.currentTime().seconds
        let text = seconds.isFinite ? slot.captions?.text(at: seconds) : nil
        if text != caption { caption = text }
    }
}
