import SwiftUI

/// Camera mode (SCREENS.md 10): this device as the learner's camera. A start screen first (so the camera only
/// turns on when asked); then the full-screen live view with what is sent, the step, Next and Back.
/// On the Mac the source can also be a window, such as a WhatsApp call showing the learner's glasses.
struct CameraView: View {
    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow
    @Environment(\.theme) private var theme
    @State private var running = false
    @State private var askCamera = false
    #if os(iOS)
    @State private var runningGlasses = false
    @State private var glasses = GlassesController.make()
    #endif
    #if os(macOS)
    @State private var pickingWindow = false
    @State private var askScreen = false
    @State private var window: WindowCandidate?
    #endif

    var body: some View {
        Group {
            #if os(macOS)
            if let window {
                WindowModeScreen(window: window) { self.window = nil }
            } else if running {
                CameraModeScreen { running = false }
            } else {
                start
            }
            #else
            start
            #endif
        }
        .navigationTitle("Be the Camera")
        #if os(iOS)
        .fullScreenCover(isPresented: $running) { CameraModeScreen { running = false }.environment(model) }
        .fullScreenCover(isPresented: $runningGlasses) {
            GlassesCameraModeScreen(glasses: glasses) { runningGlasses = false }.environment(model)
        }
        #endif
        .sheet(isPresented: $askCamera) {
            PermissionCard(permission: .camera) { allowed in
                askCamera = false
                if allowed { running = true }
            }
            .presentationDetents([.medium])
        }
        #if os(macOS)
        .sheet(isPresented: $askScreen) {
            PermissionCard(permission: .screenRecording) { allowed in
                askScreen = false
                if allowed || WindowCatalog.hasPermission { pickingWindow = true }
            }
            .frame(width: 460, height: 420)
        }
        .sheet(isPresented: $pickingWindow) {
            WindowPicker { picked in
                pickingWindow = false
                window = picked
            } onCancel: { pickingWindow = false }
            .frame(minWidth: 640, minHeight: 520)
        }
        #endif
        .onChange(of: flow.cameraLaunchIntent, initial: true) { _, intent in
            guard let intent, model.hub != nil else { return }
            switch intent {
            case .phone: begin()
            #if os(iOS)
            case .glasses: beginGlasses()
            #else
            case .glasses: break
            #endif
            }
            flow.consumeCameraLaunch(intent)
        }
    }

    private var start: some View {
        ScrollView {
            VStack(spacing: HOSpace.l) {
                VStack(spacing: HOSpace.s) {
                    SymbolTile(symbol: "viewfinder", side: 56)
                    Text("Choose a camera")
                        .hoFont(.display, theme).foregroundStyle(theme.colors.ink).multilineTextAlignment(.center)
                    Text("Your live view appears on the laptop. Nothing is recorded.")
                        .font(theme.fonts.body).foregroundStyle(theme.colors.ink2).multilineTextAlignment(.center)
                        .frame(maxWidth: 360)
                }
                .padding(.top, HOSpace.xl)
                hubStatus.frame(maxWidth: 420)
                VStack(spacing: HOSpace.s) {
                    #if os(iOS)
                    Button { beginGlasses() } label: { Label("Meta Glasses", systemImage: "eyeglasses") }
                        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                        .disabled(model.hub == nil || !GlassesFeature.toolkitLinked)
                    Button { begin() } label: { Label("This iPhone", systemImage: "iphone") }
                        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                        .disabled(model.hub == nil)
                    if !GlassesFeature.toolkitLinked { Text("Meta glasses are unavailable in this build.").font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2) }
                    #else
                    Button { begin() } label: { Label("This Mac's Camera", systemImage: "video.fill") }
                        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                        .disabled(model.hub == nil)
                    #endif
                    #if os(macOS)
                    Button { beginWindow() } label: { Label("From a Window", systemImage: "macwindow") }
                        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
                        .disabled(model.hub == nil)
                    #endif
                }
                .frame(maxWidth: 420)
            }
            .padding(HOSpace.l)
            .frame(maxWidth: .infinity)
        }
        .hoPaperBackground()
    }

    /// Which hub the frames go to, or what to do first.
    @ViewBuilder private var hubStatus: some View {
        if model.hub != nil {
            HOBanner(symbol: model.connection.isConnected ? "checkmark.circle.fill" : "arrow.clockwise",
                     tone: model.connection.isConnected ? .good : .caution,
                     text: model.connection.isConnected ? "Connected to your hub" : "Connecting to your hub")
        } else {
            HOBanner(symbol: "qrcode.viewfinder", text: "Scan the pairing code on your Mac first.")
        }
    }

    private func begin() {
        Haptics.tap()
        switch AppPermission.camera.status {
        case .notAsked: askCamera = true
        default: running = true
        }
    }

    #if os(iOS)
    private func beginGlasses() {
        Haptics.tap()
        runningGlasses = true
    }
    #endif

    #if os(macOS)
    private func beginWindow() {
        Haptics.tap()
        if WindowCatalog.hasPermission { pickingWindow = true } else { askScreen = true }
    }
    #endif
}

#if os(iOS)
/// Ray-Ban Meta camera mode: the toolkit's newest raw frame is previewed here and fed into the same
/// newest-frame JPEG sender as the iPhone camera. The sender identifies itself as `source: glasses`, so the
/// laptop's YOU pane and the live checker need no special path.
struct GlassesCameraModeScreen: View {
    var glasses: GlassesController
    var onClose: () -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var streamer = CameraStreamer()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if glasses.state.isStreaming, let frame = glasses.frame {
                Image(decorative: frame, scale: 1)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .ignoresSafeArea()
                CameraChrome(info: info, onClose: close,
                             onNext: { Task { await streamer.next() } },
                             onBack: { Task { await streamer.back() } }) {
                    VideoPill(symbol: "eyeglasses", text: "Meta glasses", tone: .neutral)
                }
            } else {
                VStack(spacing: HOSpace.l) {
                    HStack {
                        Button(action: close) { Image(systemName: "xmark").font(.body.weight(.semibold)) }
                            .buttonStyle(HOIconButtonStyle(onVideo: true))
                            .accessibilityLabel("Stop Camera")
                        Spacer()
                    }
                    Spacer()
                    RecordGlassesCard(controller: glasses, usePhone: close)
                        .frame(maxWidth: 520)
                    if streamer.connection.isConnected {
                        Text("Connected. Waiting for glasses video.")
                            .font(.footnote).foregroundStyle(.white.opacity(0.7)).multilineTextAlignment(.center)
                    }
                    Spacer()
                }
                .padding(HOSpace.l)
            }
        }
        .environment(\.colorScheme, .dark)
        .task(id: scenePhase) {
            if scenePhase == .active {
                await start()
            } else if scenePhase == .background {
                suspendForBackground()
            }
        }
        .onDisappear { stop() }
        .sensoryFeedback(trigger: model.lastAdvance) { _, new in new?.reason == .camera ? .success : nil }
        .sensoryFeedback(.warning, trigger: model.mistake?.message)
    }

    private func start() async {
        let sender = streamer
        glasses.onFrame = { sender.push($0) }
        await streamer.startPushing { model.makeCameraSocket(source: .glasses) }
        if let frame = glasses.frame { streamer.push(frame) }
        if !glasses.state.isStreaming && !glasses.state.isBusy { glasses.connect() }
    }

    private func stop() {
        glasses.onFrame = nil
        streamer.stop()
        glasses.stop()
    }

    /// Meta AI necessarily backgrounds HandOver for registration and camera permission. Do not cancel that
    /// in-flight SDK task: it owns the callback that brings us back. An active video session is still stopped,
    /// matching Meta's sample lifecycle, and `start()` creates a fresh one on return.
    private func suspendForBackground() {
        glasses.onFrame = nil
        streamer.stop()
        if glasses.state.isStreaming { glasses.stop() }
    }

    private func close() {
        stop()
        onClose()
    }

    private var info: CameraChromeInfo {
        CameraChromeInfo.make(hub: model.hub, lesson: model.lesson, state: streamer.state ?? model.state,
                              connection: streamer.connection, sending: streamer.isSending, fps: streamer.sentFPS,
                              size: streamer.frameSize, active: streamer.isActiveCamera,
                              throttled: streamer.isThrottled, sourceName: "Meta glasses")
    }
}
#endif

/// The live camera with its chrome. Starts streaming on appear, stops on disappear and in the background.
struct CameraModeScreen: View {
    var onClose: () -> Void
    /// Draws the chrome over a still frame with fixed numbers (snapshots).
    var preview: CameraChromeInfo?

    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @State private var streamer = CameraStreamer()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if preview == nil {
                switch streamer.phase {
                case .streaming:
                    if let capture = streamer.captureSession { CameraPreview(capture: capture, deviceID: streamer.deviceID).ignoresSafeArea() }
                case .denied:
                    CameraProblem(symbol: "video.slash", title: "HandOver cannot use the camera",
                                  message: "Allow it in Settings to send your work to the hub.", settings: true)
                case .noCamera:
                    CameraProblem(symbol: "video.slash", title: "No camera here",
                                  message: "This device has no camera HandOver can use.")
                case .replaced:
                    CameraProblem(symbol: "iphone.slash", title: "Another device took over",
                                  message: "\(DeviceWord.this.firstLetterCapitalized) stopped sending. Tap to send again.",
                                  action: ("Send Again", { Task { await start() } }))
                case .idle, .starting:
                    ProgressView().tint(.white)
                }
            } else if let image = SampleLesson.frame(4) {
                Image(decorative: image, scale: 1).resizable().aspectRatio(contentMode: .fit).ignoresSafeArea()
            }
            CameraChrome(info: preview ?? info, onClose: close, onNext: { Task { await streamer.next() } },
                         onBack: { Task { await streamer.back() } }) {
                sourceMenu
            }
        }
        .environment(\.colorScheme, .dark)
        .task { if preview == nil { await start() } }
        .onDisappear { streamer.stop() }
        .onChange(of: scenePhase) { _, phase in
            guard preview == nil else { return }
            if phase == .background { streamer.stop() }
            if phase == .active, streamer.phase == .idle { Task { await start() } }
        }
        .sensoryFeedback(trigger: model.lastAdvance) { _, new in new?.reason == .camera ? .success : nil }
        .sensoryFeedback(.warning, trigger: model.mistake?.message)
    }

    private func start() async {
        await streamer.start { model.makeCameraSocket(source: .phone) }
    }

    private func close() {
        streamer.stop()
        onClose()
    }

    private var info: CameraChromeInfo {
        CameraChromeInfo.make(hub: model.hub, lesson: model.lesson, state: streamer.state ?? model.state,
                              connection: streamer.connection, sending: streamer.isSending, fps: streamer.sentFPS,
                              size: streamer.frameSize, active: streamer.isActiveCamera,
                              throttled: streamer.isThrottled, sourceName: currentSourceName)
    }

    private var currentSourceName: String {
        streamer.choices.first { $0.id == streamer.deviceID }?.name ?? "Camera"
    }

    @ViewBuilder
    private var sourceMenu: some View {
        if streamer.choices.count > 1 {
            Menu {
                ForEach(streamer.choices) { choice in
                    Button {
                        Haptics.tap()
                        Task { await streamer.switchCamera(to: choice.id) }
                    } label: {
                        Label(choice.name, systemImage: choice.id == streamer.deviceID ? "checkmark" : choice.symbol)
                    }
                }
            } label: {
                VideoPill(symbol: "camera", text: currentSourceName, tone: .neutral)
            }
            .menuStyle(.button)
            .buttonStyle(.plain)
            .accessibilityLabel("Camera: \(currentSourceName)")
        }
    }
}

/// What the camera chrome shows, computed from the streamer and the hub state.
struct CameraChromeInfo: Equatable {
    var hubName: String
    var connecting: Bool
    var reconnecting: Bool
    var sending: Bool
    var fps: Double
    var size: CGSize
    /// From `camera_status`; nil before the hub says.
    var active: Bool?
    var stepLine: String?
    var status: LearnStatus?
    var canStep: Bool
    var canBack: Bool
    var throttled: Bool
    var sourceName: String

    static func make(hub: HubURL?, lesson: Lesson?, state: HubState, connection: ConnectionState, sending: Bool,
                     fps: Double, size: CGSize, active: Bool?, throttled: Bool, sourceName: String) -> CameraChromeInfo {
        var line: String?
        if state.hasLesson, state.total > 0 {
            if state.isDone {
                line = "Lesson done"
            } else {
                let title = lesson?.id == state.lessonId && lesson?.steps.indices.contains(state.step) == true
                    ? lesson?.steps[state.step].title ?? "" : ""
                line = "Step \(state.step + 1) of \(state.total)" + (title.isEmpty ? "" : ": \(title)")
            }
        }
        let step = lesson?.steps.indices.contains(state.step) == true ? lesson?.steps[state.step] : nil
        let connected = connection.isConnected
        var retrying = false
        if case .retrying = connection { retrying = true }
        return CameraChromeInfo(
            hubName: hub?.host ?? "the hub", connecting: connection == .connecting, reconnecting: retrying,
            sending: sending, fps: fps, size: size, active: active, stepLine: line,
            status: state.hasLesson ? LearnStatus.resolve(state, step: step) : nil,
            canStep: connected && state.hasLesson && state.total > 0 && !state.isDone,
            canBack: connected && state.hasLesson && state.position > 0, throttled: throttled, sourceName: sourceName)
    }
}

/// Glass chrome over the live picture: what is being sent, real numbers, the step, Next and Back.
struct CameraChrome<Source: View>: View {
    let info: CameraChromeInfo
    var onClose: () -> Void
    var onNext: () -> Void
    var onBack: () -> Void
    @ViewBuilder var source: Source
    @Environment(\.theme) private var theme
    @State private var showStats = true

    var body: some View {
        GeometryReader { geo in
            chrome(short: HOLayout.isShort(geo.size.height))
        }
    }

    private func chrome(short: Bool) -> some View {
        VStack(spacing: HOSpace.s) {
            HStack(alignment: .top, spacing: HOSpace.s) {
                Button { Haptics.tap(); onClose() } label: { Image(systemName: "xmark").font(.body.weight(.semibold)) }
                    .buttonStyle(HOIconButtonStyle(onVideo: true))
                    .accessibilityLabel("Stop Camera")
                    .keyboardShortcut(.cancelAction)
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    captureIndicator
                    if showStats, info.sending || info.fps > 0 {
                        VideoPill(symbol: "speedometer", text: statsText, tone: .neutral)
                            .onTapGesture { showStats.toggle() }
                    }
                }
                Spacer(minLength: 0)
                source
            }
            if info.throttled {
                VideoPill(symbol: "thermometer.medium", text: "\(DeviceWord.noun) is warm. Sending fewer frames.")
            }
            if info.active == false {
                VideoPill(symbol: "pause.circle", text: "Another camera is active. This one takes over if it stops.", tone: .neutral)
            }
            Spacer()
            bottomPanel(short: short)
        }
        .padding(HOSpace.l)
    }

    private var captureIndicator: some View {
        Group {
            if info.reconnecting {
                VideoPill(symbol: "arrow.clockwise", text: "Reconnecting", tone: .caution)
            } else if info.connecting {
                VideoPill(symbol: "antenna.radiowaves.left.and.right", text: "Connecting", tone: .neutral)
            } else if info.sending {
                VideoPill(symbol: "dot.radiowaves.left.and.right", text: "Sending live", tone: .bad, recordDot: true)
            } else {
                VideoPill(symbol: "pause.fill", text: "Paused", tone: .idle)
            }
        }
        .accessibilityAddTraits(.updatesFrequently)
    }

    private var statsText: String {
        let fps = info.fps.formatted(.number.precision(.fractionLength(1)))
        var parts = ["\(fps) fps"]
        if info.size.width > 0 { parts.append("\(Int(info.size.width)) x \(Int(info.size.height))") }
        if let active = info.active { parts.append(active ? "Active camera" : "Standby") }
        return parts.joined(separator: ", ")
    }

    /// The step, its status, Back and Next. On a short screen (iPhone landscape) they sit in one row, so the
    /// panel covers less of the picture.
    private func bottomPanel(short: Bool) -> some View {
        let layout = short ? AnyLayout(HStackLayout(alignment: .center, spacing: HOSpace.l))
                           : AnyLayout(VStackLayout(alignment: .leading, spacing: HOSpace.m))
        return layout {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    Text(info.stepLine ?? "No lesson started")
                        .font(theme.fonts.headline)
                        .foregroundStyle(.white)
                        .lineLimit(2)
                    if info.stepLine == nil {
                        Text("Start a lesson on any screen connected to this hub.")
                            .font(theme.fonts.footnote)
                            .foregroundStyle(.white.opacity(0.7))
                    }
                }
                Spacer(minLength: HOSpace.s)
                if let status = info.status { StatusBadge(status: status, overVideo: true) }
            }
            HStack(spacing: HOSpace.s) {
                if info.canBack {
                    Button { Haptics.impact(.medium); onBack() } label: { Label("Back", systemImage: "chevron.left") }
                        .buttonStyle(GlassCapsuleButtonStyle())
                        .keyboardShortcut(.leftArrow, modifiers: [])
                }
                Button { Haptics.impact(.medium); onNext() } label: {
                    Text("Next").font(theme.fonts.headline).frame(maxWidth: .infinity, minHeight: HOSize.controlLarge)
                }
                .buttonStyle(NextOnVideoStyle())
                .keyboardShortcut(.rightArrow, modifiers: [])
                .disabled(!info.canStep)
            }
            .frame(maxWidth: short ? 280 : .infinity)
        }
        .padding(short ? HOSpace.m : HOSpace.l)
        .hoGlassPanel()
        .frame(maxWidth: short ? 720 : 560)
        .frame(maxWidth: .infinity)
    }
}

/// The accent Next button over video.
private struct NextOnVideoStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.theme) private var theme

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(isEnabled ? theme.colors.onAccent : .white.opacity(0.4))
            .background(isEnabled ? theme.colors.accent.opacity(configuration.isPressed ? 0.82 : 1) : .white.opacity(0.12),
                        in: RoundedRectangle(cornerRadius: HORadius.controlLarge, style: .continuous))
    }
}

/// A centered problem over the black camera area.
struct CameraProblem: View {
    let symbol: String
    let title: String
    let message: String
    var settings = false
    var action: (String, () -> Void)?

    var body: some View {
        VStack(spacing: HOSpace.m) {
            Image(systemName: symbol).font(.system(size: 44, weight: .light)).foregroundStyle(.white.opacity(0.7))
            Text(title).font(.title3.weight(.semibold)).foregroundStyle(.white).multilineTextAlignment(.center)
            Text(message).font(.subheadline).foregroundStyle(.white.opacity(0.7)).multilineTextAlignment(.center)
            if settings { OpenSettingsButton().frame(maxWidth: 280) }
            if let action {
                Button(action.0) { Haptics.tap(); action.1() }
                    .buttonStyle(HOButtonStyle(.primary, size: .large))
            }
        }
        .padding(HOSpace.xl)
        .frame(maxWidth: 420)
    }
}

#Preview("Camera mode") {
    CameraModeScreen(onClose: {}, preview: CameraChromeInfo(
        hubName: "192.168.1.20", connecting: false, reconnecting: false, sending: true, fps: 4.8,
        size: CGSize(width: 960, height: 540), active: true, stepLine: "Step 4 of 8: Fold all four corners to center",
        status: .watching, canStep: true, canBack: true, throttled: false, sourceName: "Back Camera"))
        .environment(AppModel.preview())
        .environment(LearnFlow())
        .handOverTheme(.system, dark: true)
}
