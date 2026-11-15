@preconcurrency import AVFoundation
import SwiftUI

/// The shutter (DESIGN.md 3.8): a 72 point white ring around a 60 point red circle that morphs into a 28 point
/// rounded square while recording. Reduce Motion swaps the shape without the morph.
struct RecordShutterButton: View {
    enum Mode: Equatable { case ready, recording, finishing, disabled }
    var mode: Mode
    var action: () -> Void
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle().strokeBorder(.white, lineWidth: 4).frame(width: 72, height: 72)
                RoundedRectangle(cornerRadius: square ? 6 : 30, style: .continuous)
                    .fill(mode == .disabled ? Color(red: 0x8E / 255, green: 0x8E / 255, blue: 0x93 / 255) : theme.colors.record)
                    .frame(width: square ? 28 : 60, height: square ? 28 : 60)
                if mode == .finishing {
                    ProgressView().tint(.white).controlSize(.large)
                }
            }
            .frame(width: 72, height: 72)
            .contentShape(Circle())
            .animation(reduceMotion ? nil : HOMotion.shutter, value: square)
        }
        .buttonStyle(ShutterPress())
        .disabled(mode == .disabled || mode == .finishing)
        .accessibilityLabel(mode == .recording ? "Stop recording" : "Record")
        .keyboardShortcut(.space, modifiers: [])
    }

    private var square: Bool { mode == .recording || mode == .finishing }
}

private struct ShutterPress: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.92 : 1)
            .animation(HOMotion.press, value: configuration.isPressed)
    }
}

/// The red timer pill (DESIGN.md 3.9): a solid white dot and the time, ticking from the recording start.
struct RecordTimerPill: View {
    var elapsed: () -> TimeInterval
    var paused: Bool
    @Environment(\.theme) private var theme

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.25)) { _ in
            let seconds = elapsed()
            HStack(spacing: 6) {
                Image(systemName: paused ? "pause.fill" : "circle.fill").font(.system(size: 8, weight: .bold))
                Text(RecordModel.clock(seconds)).font(theme.fonts.timer)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, HOSpace.s + 2)
            .padding(.vertical, HOSpace.xs)
            .background(paused ? Color(white: 0.3) : theme.colors.record, in: Capsule())
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(paused ? "Paused" : "Recording")
            .accessibilityValue("\(Int(seconds / 10) * 10) seconds")
        }
    }
}

/// The narration meter (DESIGN.md 3.9): 24 bars, 3 points wide with 2 point gaps, white at 90%. With Reduce
/// Motion it is one level bar.
struct RecordLevelMeter: View {
    var levels: [Float]
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Group {
            if reduceMotion {
                let level = CGFloat(levels.suffix(5).max() ?? 0)
                Capsule().fill(.white.opacity(0.25))
                    .overlay(alignment: .leading) {
                        Capsule().fill(.white.opacity(0.9)).frame(width: max(3, 120 * level))
                    }
                    .frame(width: 120, height: 4)
            } else {
                HStack(alignment: .center, spacing: 2) {
                    ForEach(Array(levels.enumerated()), id: \.offset) { _, level in
                        Capsule().fill(.white.opacity(0.9))
                            .frame(width: 3, height: max(3, 24 * CGFloat(level)))
                    }
                }
                .frame(width: 120, height: 24)
            }
        }
        .accessibilityHidden(true)
    }
}

/// The glasses card (DESIGN.md 3.17): tile, title, status line with a dot, battery only when the toolkit reports
/// it, the action for the state, and the entitlement note.
struct RecordGlassesCard: View {
    var controller: GlassesController
    var usePhone: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        let state = controller.state
        VStack(alignment: .leading, spacing: HOSpace.m) {
            HStack(alignment: .top, spacing: HOSpace.m) {
                Image(systemName: "eyeglasses")
                    .font(.title3)
                    .foregroundStyle(theme.colors.ink)
                    .frame(width: HOSize.tile + 4, height: HOSize.tile + 4)
                    .background(theme.colors.well, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text(state == .notRegistered || state == .unavailable ? (controller.deviceName ?? "Ray-Ban Meta") : state.title)
                        .font(theme.fonts.headline)
                        .foregroundStyle(theme.colors.ink)
                    HStack(spacing: HOSpace.xs) {
                        if state.isBusy { ProgressView().controlSize(.mini) } else {
                            Circle().fill(dot(state)).frame(width: 7, height: 7)
                        }
                        Text(status(state)).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                    }
                    if let message = state.message {
                        Text(message).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                if let battery = controller.battery {
                    Label("\(battery)%", systemImage: batterySymbol(battery))
                        .font(theme.fonts.badge)
                        .foregroundStyle(theme.colors.ink2)
                }
            }
            actions(state)
        }
        .padding(HOSpace.l)
        .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
            .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
    }

    @ViewBuilder private func actions(_ state: GlassesState) -> some View {
        HStack(spacing: HOSpace.s) {
            switch state {
            case .unavailable:
                EmptyView()
            case .notRegistered:
                Button("Connect Glasses") { controller.connect() }.buttonStyle(HOButtonStyle(.primary, size: .small))
            case .developerModeOff, .metaAIMissing:
                Button("Open Meta AI") { openMetaAI() }.buttonStyle(HOButtonStyle(.secondary, size: .small))
                Button("Try Again") { controller.connect() }.buttonStyle(HOButtonStyle(.secondary, size: .small))
            case .waitingForMetaAI:
                Button("Cancel") { controller.cancel() }.buttonStyle(HOButtonStyle(.secondary, size: .small))
            case .noDevice:
                Button("Try Again") { controller.connect() }.buttonStyle(HOButtonStyle(.secondary, size: .small))
            case .permissionNeeded:
                Button("Allow") { controller.allowCamera() }.buttonStyle(HOButtonStyle(.primary, size: .small))
            case .paused:
                Button("Resume") { controller.connect() }.buttonStyle(HOButtonStyle(.secondary, size: .small))
            case .powerLimit, .lost, .failed:
                Button(state == .lost ? "Reconnect" : "Try Again") { controller.connect() }
                    .buttonStyle(HOButtonStyle(.secondary, size: .small))
                Button("Use iPhone", action: usePhone).buttonStyle(HOButtonStyle(.secondary, size: .small))
            case .batteryLow, .tooHot:
                Button("Use iPhone", action: usePhone).buttonStyle(HOButtonStyle(.secondary, size: .small))
            case .connecting, .streaming:
                EmptyView()
            }
        }
    }

    private func status(_ state: GlassesState) -> String {
        switch state {
        case .unavailable: "Not available in this build"
        case .notRegistered: "Not connected to HandOver"
        case .streaming: "Streaming"
        case .connecting: "Connecting"
        case .waitingForMetaAI: "Waiting"
        default: state.title
        }
    }

    private func dot(_ state: GlassesState) -> Color {
        switch state {
        case .streaming: theme.colors.good
        case .batteryLow, .tooHot, .powerLimit, .lost, .failed, .developerModeOff: theme.colors.caution
        default: theme.colors.idle
        }
    }

    private func batterySymbol(_ level: Int) -> String {
        switch level {
        case ..<13: "battery.0percent"
        case ..<38: "battery.25percent"
        case ..<63: "battery.50percent"
        case ..<88: "battery.75percent"
        default: "battery.100percent"
        }
    }

    private func openMetaAI() {
        #if os(iOS)
        if let url = URL(string: "fb-viewapp://") { UIApplication.shared.open(url) }
        #endif
    }
}

/// The camera preview layer in SwiftUI.
#if os(iOS)
struct RecordCameraPreview: UIViewRepresentable {
    let layer: AVCaptureVideoPreviewLayer

    func makeUIView(context: Context) -> PreviewHost {
        let view = PreviewHost()
        view.previewLayer = layer
        return view
    }

    func updateUIView(_ view: PreviewHost, context: Context) {}

    final class PreviewHost: UIView {
        var previewLayer: AVCaptureVideoPreviewLayer? {
            didSet {
                oldValue?.removeFromSuperlayer()
                if let previewLayer { layer.addSublayer(previewLayer) }
            }
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            // No implicit animation: the layer follows the view's size at once when the phone turns.
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            previewLayer?.frame = bounds
            CATransaction.commit()
        }
    }
}
#else
struct RecordCameraPreview: NSViewRepresentable {
    let layer: AVCaptureVideoPreviewLayer

    func makeNSView(context: Context) -> PreviewHost {
        let view = PreviewHost()
        view.wantsLayer = true
        view.previewLayer = layer
        return view
    }

    func updateNSView(_ view: PreviewHost, context: Context) {}

    final class PreviewHost: NSView {
        var previewLayer: AVCaptureVideoPreviewLayer? {
            didSet {
                oldValue?.removeFromSuperlayer()
                if let previewLayer { layer?.addSublayer(previewLayer) }
            }
        }

        override func layout() {
            super.layout()
            previewLayer?.frame = bounds
        }
    }
}
#endif

/// A still from a take for the thumbnail and the review sheet.
enum RecordTakeThumbnail {
    static func make(_ url: URL) async -> CGImage? {
        let generator = AVAssetImageGenerator(asset: AVURLAsset(url: url))
        generator.appliesPreferredTrackTransform = true
        generator.maximumSize = CGSize(width: 240, height: 240)
        return try? await generator.image(at: CMTime(seconds: 0.5, preferredTimescale: 600)).image
    }
}
