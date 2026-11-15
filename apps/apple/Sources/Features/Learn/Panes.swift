import AVFoundation
import SwiftUI

// The two video panes of Learn (DESIGN.md 3.4, 3.5): the expert clip with its caption bar, and the learner's
// camera. Both are aspect fit on `stage` black, never cropped.

#if os(iOS)
private final class PlayerUIView: UIView {
    override static var layerClass: AnyClass { AVPlayerLayer.self }
    var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }
}

/// An AVPlayerLayer, aspect fit.
struct PlayerLayerView: UIViewRepresentable {
    var player: AVPlayer

    func makeUIView(context: Context) -> UIView {
        let view = PlayerUIView()
        view.playerLayer.videoGravity = .resizeAspect
        view.playerLayer.player = player
        view.backgroundColor = .clear
        return view
    }

    func updateUIView(_ view: UIView, context: Context) {
        (view as? PlayerUIView)?.playerLayer.player = player
    }
}
#else
private final class PlayerNSView: NSView {
    let playerLayer = AVPlayerLayer()
    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer = playerLayer
        playerLayer.videoGravity = .resizeAspect
    }

    required init?(coder: NSCoder) { nil }
}

/// An AVPlayerLayer, aspect fit.
struct PlayerLayerView: NSViewRepresentable {
    var player: AVPlayer

    func makeNSView(context: Context) -> NSView {
        let view = PlayerNSView()
        view.playerLayer.player = player
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        (view as? PlayerNSView)?.playerLayer.player = player
    }
}
#endif

/// The caption bar: `captionFill` behind `captionText` in white, centered, at most 2 lines. Longer cues shrink
/// to 0.85x before truncating. With Reduce Transparency the fill is 90% black.
struct CaptionBar: View {
    var text: String
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @AppStorage(CaptionSize.storageKey) private var size = CaptionSize.defaultForPlatform.rawValue
    @ScaledMetric(relativeTo: .body) private var body17: CGFloat = 17

    var body: some View {
        let scale = (CaptionSize(rawValue: size) ?? .medium).scale
        Text(text)
            .font(.system(size: min(body17, 34) * scale, weight: .semibold))
            .foregroundStyle(theme.colors.captionInk)
            .multilineTextAlignment(.center)
            .lineLimit(2)
            .minimumScaleFactor(0.85)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(reduceTransparency ? Color.black.opacity(0.9) : theme.colors.captionFill,
                        in: RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            .accessibilityHidden(true)
    }
}

extension CaptionSize {
    /// Mac is usually the big screen in the room: Large there, Medium elsewhere (SCREENS.md 7.6).
    static var defaultForPlatform: CaptionSize {
        #if os(macOS)
        .large
        #else
        .medium
        #endif
    }
}

/// The expert's clip pane.
struct ClipPane: View {
    var clips: ClipController
    var poster: CGImage?
    var radius: CGFloat
    var hasLesson: Bool
    var stepNumber: Int?
    var captionsOn: Bool
    /// False when the clip is the small tile and the caption moves under the large pane.
    var showsCaption = true
    /// The small PiP tile: no controls, no messages.
    var isTile = false
    /// Room kept under the caption, so it clears a PiP tile resting in a bottom corner.
    var captionBottomInset: CGFloat = 0
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showControls = false
    @State private var spinnerDue = false

    var body: some View {
        ZStack {
            theme.colors.stage
            if hasLesson {
                if let poster, clips.phase != .playing || clips.isStill {
                    Image(decorative: poster, scale: 1).resizable().aspectRatio(contentMode: .fit)
                }
                ForEach(0..<2, id: \.self) { i in
                    if let slot = clips.slots[i] {
                        PlayerLayerView(player: slot.player)
                            .opacity(i == clips.active && clips.phase == .playing ? 1 : 0)
                            .allowsHitTesting(false)
                    }
                }
                .animation(reduceMotion ? nil : HOMotion.clip, value: clips.active)
                overlays
            } else {
                Text("No lesson selected")
                    .font(theme.fonts.callout)
                    .foregroundStyle(.white.opacity(0.6))
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture {
            guard !isTile, hasLesson else { return }
            showControls = true
        }
        .task(id: showControls) {
            guard showControls else { return }
            try? await Task.sleep(for: .seconds(3))
            showControls = false
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel(stepNumber.map { "Expert clip for step \($0), \(clips.phase == .playing ? "playing" : "loading")" }
                            ?? "Expert clip")
        .accessibilityValue(captionsOn ? (clips.caption ?? "") : "")
    }

    @ViewBuilder
    private var overlays: some View {
        switch clips.phase {
        case .loading:
            ProgressView()
                .tint(.white)
                .opacity(spinnerDue ? 1 : 0)
                .task {
                    spinnerDue = false
                    try? await Task.sleep(for: .milliseconds(500))
                    spinnerDue = true
                }
        case .failed:
            if !isTile {
                VStack(spacing: HOSpace.s) {
                    Image(systemName: "exclamationmark.triangle").font(.title2).foregroundStyle(.white.opacity(0.6))
                    Text("Clip did not load.").font(theme.fonts.callout).foregroundStyle(.white.opacity(0.8))
                    Button("Try Again") { Haptics.tap(); clips.retry() }
                        .buttonStyle(HOButtonStyle(.quiet, size: .small, onVideo: true))
                }
                .environment(\.colorScheme, .dark)
            }
        case .idle, .playing:
            EmptyView()
        }
        if showsCaption, captionsOn, !isTile, let caption = clips.caption, clips.phase != .failed {
            VStack {
                Spacer()
                CaptionBar(text: caption).padding(HOSpace.m).padding(.bottom, captionBottomInset)
            }
        }
        if showControls && !isTile {
            VStack {
                HStack {
                    Spacer()
                    ClipControls(clips: clips)
                }
                Spacer()
            }
            .padding(HOSpace.s)
            .transition(.opacity)
        }
    }
}

/// Replay, Mute and Captions in a glass capsule (shown on tap, hidden after 3 s).
struct ClipControls: View {
    var clips: ClipController
    @AppStorage(LearnSettings.captionsKey) private var captionsOn = true

    var body: some View {
        HStack(spacing: 0) {
            Button { Haptics.tap(); clips.replay() } label: { Image(systemName: "gobackward") }
                .accessibilityLabel("Replay")
            Button { Haptics.tap(); clips.isMuted.toggle() } label: {
                Image(systemName: clips.isMuted ? "speaker.slash" : "speaker.wave.2")
            }
            .accessibilityLabel(clips.isMuted ? "Unmute" : "Mute")
            Button { Haptics.tap(); captionsOn.toggle() } label: {
                Image(systemName: captionsOn ? "captions.bubble.fill" : "captions.bubble")
            }
            .accessibilityLabel(captionsOn ? "Captions Off" : "Captions On")
        }
        .buttonStyle(TouchIconStyle())
        .foregroundStyle(.white)
        .font(.body.weight(.medium))
        .padding(.horizontal, HOSpace.xs)
        .hoGlassCapsule(interactive: true)
    }
}

private struct TouchIconStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .frame(width: HOSize.touch, height: HOSize.touch)
            .contentShape(Rectangle())
            .opacity(configuration.isPressed ? 0.6 : 1)
    }
}

/// Where the learner's camera picture comes from right now.
enum LiveSource {
    /// Frames from the hub (another device is the camera).
    case hub(CGImage)
    /// This device's own camera preview (camera mode), drawn by the Camera feature.
    case own(AnyView)
    /// No camera yet.
    case waiting
    /// The camera dropped: the last frame dimmed.
    case lost(CGImage?)
    /// The hub socket is down: a placeholder, never a frozen frame.
    case reconnecting
}

/// The chip at the top left of the live pane: symbol plus name.
struct SourceChip: Equatable {
    var symbol: String
    var name: String
    var isRecording = false

    /// From `state.camera`. A recording (`source` file, or the replay platform) reads "Recording" in caution.
    @MainActor
    static func from(camera: CameraInfo?, ownCamera: Bool) -> SourceChip? {
        if ownCamera {
            #if os(iOS)
            return SourceChip(symbol: UIDevice.current.userInterfaceIdiom == .pad ? "ipad" : "iphone",
                              name: UIDevice.current.userInterfaceIdiom == .pad ? "This iPad" : "This iPhone")
            #else
            return SourceChip(symbol: "video", name: "This Mac")
            #endif
        }
        guard let camera else { return nil }
        if camera.source == .file || camera.platform == .replay {
            return SourceChip(symbol: "film", name: "Recording", isRecording: true)
        }
        switch camera.source {
        case .glasses: return SourceChip(symbol: "eyeglasses", name: "Glasses")
        case .phone: return SourceChip(symbol: "iphone", name: camera.name)
        case .browser, .file: return SourceChip(symbol: "video", name: camera.name)
        }
    }
}

/// The learner's camera pane.
struct LivePane: View {
    var source: LiveSource
    var chip: SourceChip?
    var radius: CGFloat
    var isTile = false
    @Environment(\.theme) private var theme

    var body: some View {
        ZStack {
            theme.colors.stage
            switch source {
            case .hub(let image):
                Image(decorative: image, scale: 1).resizable().aspectRatio(contentMode: .fit)
            case .own(let view):
                view
            case .waiting:
                placeholder(symbol: "video", title: "Waiting for camera",
                            hint: "Open HandOver on your phone and tap Be the Camera.")
            case .lost(let last):
                if let last {
                    Image(decorative: last, scale: 1).resizable().aspectRatio(contentMode: .fit).opacity(0.4)
                }
                if !isTile {
                    VStack {
                        Spacer()
                        CaptionBar(text: "Camera lost. Keep going with Next.").padding(HOSpace.m)
                    }
                }
            case .reconnecting:
                placeholder(symbol: "wifi.exclamationmark", title: "Reconnecting", hint: nil)
            }
            if let chip, !isTile {
                VStack {
                    HStack {
                        VideoPill(symbol: chip.symbol, text: chip.name, tone: chip.isRecording ? .caution : .neutral,
                                  recordDot: chip.isRecording)
                        Spacer()
                    }
                    Spacer()
                }
                .padding(HOSpace.s)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        switch source {
        case .hub, .own: "Your camera, live"
        case .lost: "Your camera, lost"
        case .waiting: "Your camera, waiting for camera"
        case .reconnecting: "Your camera, reconnecting"
        }
    }

    @ViewBuilder
    private func placeholder(symbol: String, title: String, hint: String?) -> some View {
        VStack(spacing: HOSpace.xs) {
            Image(systemName: symbol)
                .font(isTile ? .body : .title2)
                .foregroundStyle(.white.opacity(0.4))
            if !isTile {
                Text(title).font(theme.fonts.callout.weight(.medium)).foregroundStyle(.white.opacity(0.8))
                if let hint {
                    Text(hint)
                        .font(theme.fonts.footnote)
                        .foregroundStyle(.white.opacity(0.6))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 260)
                }
            }
        }
        .padding(HOSpace.m)
    }
}
