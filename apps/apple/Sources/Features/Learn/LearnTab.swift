import SwiftUI
#if os(iOS)
import UIKit
#else
import AppKit
#endif

/// The Learn tab: the running lesson with its camera, or "No lesson running" with a way to pick one. It never
/// shows a lesson this app did not start, so an old lesson left on the hub does not trap anyone.
struct LearnTab: View {
    /// Draws this still as the learner's camera instead of opening one, and these clips (snapshots).
    var stillCamera: CGImage?
    var clips: ClipController?

    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow

    var body: some View {
        Group {
            if flow.isRunning {
                LearnRunScreen(stillCamera: stillCamera, clips: clips)
            } else {
                LearnEmptyState()
            }
        }
        .navigationTitle("Learn")
    }
}

/// No lesson running: what to do next.
struct LearnEmptyState: View {
    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow
    @Environment(\.theme) private var theme

    var body: some View {
        Group {
            if model.hub == nil {
                HOEmptyState(symbol: "desktopcomputer", title: "Connect to your hub first",
                             message: "The hub is HandOver running on a computer near you. It has the lessons.") {
                    Button("Open Settings") { flow.section = .settings }
                        .buttonStyle(HOButtonStyle(.primary, size: .large))
                }
            } else {
                HOEmptyState(symbol: "play.rectangle", title: "No lesson running",
                             message: "Pick a lesson on Home. HandOver plays each step and tells you when it is done.") {
                    VStack(spacing: HOSpace.m) {
                        Button("Pick a Lesson") { Haptics.tap(); flow.section = .library }
                            .buttonStyle(HOButtonStyle(.primary, size: .large))
                        CameraChoiceRow().frame(maxWidth: 320)
                    }
                }
            }
        }
        .hoPaperBackground()
    }
}

/// A lesson in progress: Learn, plus whichever camera was chosen. "This iPhone" streams the back camera to the hub
/// and shows its native preview in the tile; "Meta glasses" streams the glasses' frames and falls back to the
/// phone camera with a banner if they stop; "Another device" shows the frames the hub forwards.
struct LearnRunScreen: View {
    var stillCamera: CGImage?
    var clips: ClipController?

    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.theme) private var theme
    @State private var phone = CameraStreamer()
    @State private var glassesSender = CameraStreamer()
    /// The glasses stopped and the phone camera took over.
    @State private var fellBack = false

    private enum Active: Equatable { case phone, glasses, other }

    private var active: Active {
        switch flow.camera {
        case .thisDevice: .phone
        case .glasses: fellBack || !LearnCamera.glassesAvailable ? .phone : .glasses
        case .otherDevice: .other
        }
    }

    private var isLive: Bool { !model.isPreview && stillCamera == nil }

    var body: some View {
        LearnView(usesOwnCamera: .constant(active != .other), ownCameraPreview: active == .other ? nil : ownPreview,
                  onClose: { end() }, onLibrary: { end() }, onChangeCamera: { flow.changeCamera() },
                  notice: notice, ownChip: ownChip, clips: clips)
            .task(id: runKey) { await run() }
            .onChange(of: flow.glasses?.frame) { _, frame in
                if active == .glasses, let frame { glassesSender.push(frame) }
            }
            .onChange(of: flow.glasses?.state) { _, state in
                guard active == .glasses, let state, GlassesFallback.shouldFallBack(state) else { return }
                fellBack = true
            }
            .onChange(of: flow.camera) { _, _ in fellBack = false }
            .onDisappear { stopAll() }
    }

    private var runKey: String { "\(active)|\(scenePhase == .active)|\(model.hub?.description ?? "")" }

    private func end() {
        stopAll()
        flow.end(model: model)
    }

    private func stopAll() {
        phone.stop()
        glassesSender.stop()
    }

    /// Starts the chosen camera and stops the other. Runs again when the camera or the app's state changes.
    private func run() async {
        guard isLive else { return }
        guard scenePhase == .active else {
            stopAll()
            return
        }
        switch active {
        case .other:
            stopAll()
        case .phone:
            glassesSender.stop()
            await phone.start { model.makeCameraSocket(source: .phone) }
        case .glasses:
            phone.stop()
            let glasses = flow.glassesController()
            if !glasses.state.isStreaming && !glasses.state.isBusy { glasses.connect() }
            await glassesSender.startPushing { model.makeCameraSocket(source: .glasses) }
            // No video from the glasses in time: use the phone camera and say so.
            try? await Task.sleep(for: GlassesFallback.connectTimeout)
            if !Task.isCancelled, active == .glasses, !glasses.state.isStreaming { fellBack = true }
        }
    }

    // MARK: - What the tile shows

    private var ownPreview: AnyView {
        if let stillCamera {
            return AnyView(Image(decorative: stillCamera, scale: 1).resizable().aspectRatio(contentMode: .fit))
        }
        if active == .glasses {
            if let frame = flow.glasses?.frame {
                return AnyView(Image(decorative: frame, scale: 1).resizable().aspectRatio(contentMode: .fit))
            }
            return AnyView(TilePlaceholder(symbol: "eyeglasses", text: "Connecting to glasses"))
        }
        switch phone.phase {
        case .streaming:
            if let capture = phone.captureSession { return AnyView(CameraPreview(capture: capture, deviceID: phone.deviceID)) }
            return AnyView(TilePlaceholder(symbol: "video", text: nil))
        case .denied: return AnyView(TilePlaceholder(symbol: "video.slash", text: "Camera off"))
        case .noCamera: return AnyView(TilePlaceholder(symbol: "video.slash", text: "No camera"))
        case .replaced: return AnyView(TilePlaceholder(symbol: "iphone.slash", text: "Paused"))
        case .idle, .starting: return AnyView(TilePlaceholder(symbol: "video", text: nil, loading: isLive))
        }
    }

    private var ownChip: SourceChip? {
        active == .glasses ? SourceChip(symbol: "eyeglasses", name: "Glasses") : nil
    }

    private var notice: LearnNotice? {
        let noun = DeviceWord.noun
        if flow.camera == .glasses, fellBack {
            return LearnNotice(symbol: "eyeglasses", text: "The glasses stopped. Using the \(noun) camera instead.",
                               actionTitle: "Try Glasses") {
                fellBack = false
            }
        }
        switch active {
        case .other:
            guard !model.state.cameraConnected, isLive else { return nil }
            return LearnNotice(symbol: "qrcode", tone: .neutral, text: "Waiting for the other camera to connect.",
                               actionTitle: "Show Code") { flow.changeCamera() }
        case .phone:
            switch phone.phase {
            case .denied:
                return LearnNotice(symbol: "video.slash", text: "HandOver can't use the camera. Allow it in Settings.",
                                   actionTitle: "Settings") { Self.openSettings() }
            case .noCamera:
                return LearnNotice(symbol: "video.slash", text: "No camera here. Pick another camera.",
                                   actionTitle: "Change") { flow.changeCamera() }
            case .replaced:
                return LearnNotice(symbol: "iphone.slash", text: "Another device took over as the camera.",
                                   actionTitle: "Use \(noun)") { Task { await phone.start { model.makeCameraSocket(source: .phone) } } }
            default:
                if phone.isActiveCamera == false {
                    return LearnNotice(symbol: "pause.circle", tone: .neutral,
                                       text: "Another camera is active. This one takes over if it stops.")
                }
                return nil
            }
        case .glasses:
            return nil
        }
    }

    private static func openSettings() {
        #if os(iOS)
        if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
        #else
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera") {
            NSWorkspace.shared.open(url)
        }
        #endif
    }
}

/// The camera tile before a picture arrives.
private struct TilePlaceholder: View {
    let symbol: String
    let text: String?
    var loading = false

    var body: some View {
        VStack(spacing: HOSpace.xs) {
            if loading {
                ProgressView().tint(.white)
            } else {
                Image(systemName: symbol).font(.body).foregroundStyle(.white.opacity(0.6))
            }
            if let text {
                Text(text).font(.caption).foregroundStyle(.white.opacity(0.8)).multilineTextAlignment(.center)
            }
        }
        .padding(HOSpace.s)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
