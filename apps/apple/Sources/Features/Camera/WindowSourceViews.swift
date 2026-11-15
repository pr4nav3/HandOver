#if os(macOS)
import SwiftUI

/// Pick the window to stream: live stills of each window, call apps (WhatsApp, Messenger, FaceTime) first.
struct WindowPicker: View {
    var onPick: (WindowCandidate) -> Void
    var onCancel: () -> Void
    @Environment(\.theme) private var theme
    @State private var windows: [WindowCandidate]?
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Group {
                if let windows, !windows.isEmpty {
                    ScrollView {
                        VStack(alignment: .leading, spacing: HOSpace.l) {
                            Text("Start the video call first, then pick its window. Only the window you pick is captured.")
                                .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: HOSpace.m, alignment: .top)],
                                      spacing: HOSpace.m) {
                                ForEach(windows) { window in
                                    Button { Haptics.tap(); onPick(window) } label: { WindowTile(window: window) }
                                        .buttonStyle(.plain)
                                }
                            }
                        }
                        .padding(HOSpace.xl)
                    }
                } else if windows != nil {
                    HOEmptyState(symbol: "macwindow", title: "No windows to capture",
                                 message: "Open the call on this Mac, then look again.") {
                        Button("Look Again") { Task { await load() } }.buttonStyle(HOButtonStyle(.primary))
                    }
                } else if let error {
                    HOEmptyState(symbol: "lock", title: "Screen Recording is off for HandOver", message: error, tone: .caution) {
                        Button("Open Settings") {
                            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
                                NSWorkspace.shared.open(url)
                            }
                        }
                        .buttonStyle(HOButtonStyle(.primary))
                    }
                } else {
                    HOEmptyState(title: "Finding windows", loading: true)
                }
            }
            .hoPaperBackground()
            .navigationTitle("From a Window")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: onCancel) }
                ToolbarItem(placement: .primaryAction) {
                    Button { Task { await load() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        do {
            windows = try await WindowCatalog.windows()
            error = nil
        } catch {
            windows = nil
            self.error = "Allow HandOver in System Settings > Privacy & Security > Screen & System Audio Recording, then quit and reopen HandOver."
        }
    }
}

private struct WindowTile: View {
    let window: WindowCandidate
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            ZStack {
                theme.colors.well
                if let thumb = window.thumbnail {
                    Image(decorative: thumb, scale: 1).resizable().aspectRatio(contentMode: .fit)
                } else {
                    Image(systemName: "macwindow").font(.largeTitle).foregroundStyle(theme.colors.ink3)
                }
            }
            .frame(height: 120)
            .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            HStack(spacing: HOSpace.xs) {
                if window.isCallApp {
                    Image(systemName: "video.fill").font(.caption).foregroundStyle(theme.colors.accentInk)
                }
                Text(window.appName).font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink).lineLimit(1)
            }
            Text(window.title).font(theme.fonts.caption).foregroundStyle(theme.colors.ink2).lineLimit(1)
        }
        .padding(HOSpace.s)
        .hoCard()
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(window.appName), \(window.title)")
    }
}

/// Streaming a window: the cropped picture that is sent, a clear capture indicator, the glasses toggle and
/// the crop editor, with the same step controls as the camera.
struct WindowModeScreen: View {
    let window: WindowCandidate
    var onClose: () -> Void
    @Environment(AppModel.self) private var model
    @Environment(\.theme) private var theme
    @State private var streamer = WindowStreamer()
    @State private var feed = PhoneCameraFeed.shared
    @State private var editingCrop = false
    @AppStorage("handover.windowIsGlasses") private var isGlasses = true

    var body: some View {
        ZStack {
            Color.black
            switch streamer.phase {
            case .ended(let reason):
                CameraProblem(symbol: "macwindow.badge.plus", title: "Stopped capturing", message: reason,
                              action: ("Pick a Window", onClose))
            default:
                if let image = feed.image {
                    Image(decorative: image, scale: 1).resizable().aspectRatio(contentMode: .fit)
                } else {
                    ProgressView().tint(.white)
                }
            }
            CameraChrome(info: info, onClose: close, onNext: { Task { await streamer.next() } },
                         onBack: { Task { await streamer.back() } }) {
                VStack(alignment: .trailing, spacing: HOSpace.s) {
                    Toggle("This is my glasses view", isOn: $isGlasses)
                        .toggleStyle(.switch)
                        .font(theme.fonts.badge)
                        .foregroundStyle(.white)
                        .padding(.horizontal, HOSpace.m)
                        .frame(minHeight: 32)
                        .hoGlassCapsule()
                    Button { Haptics.tap(); editingCrop = true } label: {
                        Label(streamer.cropIsAutomatic ? "Crop: Automatic" : "Crop: Yours", systemImage: "crop")
                    }
                    .buttonStyle(GlassCapsuleButtonStyle())
                    .disabled(streamer.fullFrame == nil)
                }
            }
        }
        .environment(\.colorScheme, .dark)
        .task { await start() }
        .onDisappear { streamer.stop() }
        .onChange(of: isGlasses) { _, on in
            if let hub = model.hub { Task { await streamer.setGlasses(on, hub: hub) } }
        }
        .sheet(isPresented: $editingCrop) {
            CropEditor(streamer: streamer) { editingCrop = false }
                .frame(minWidth: 640, minHeight: 520)
        }
    }

    private func start() async {
        guard let hub = model.hub else { return }
        await streamer.start(window: window, glasses: isGlasses, hub: hub)
    }

    private func close() {
        streamer.stop()
        onClose()
    }

    private var info: CameraChromeInfo {
        var i = CameraChromeInfo.make(hub: model.hub, lesson: model.lesson, state: streamer.state ?? model.state,
                                      connection: streamer.connection, sending: streamer.isSending, fps: streamer.sentFPS,
                                      size: streamer.frameSize, active: streamer.isActiveCamera, throttled: false,
                                      sourceName: window.appName)
        if streamer.phase == .streaming {
            // The capture indicator names the window, so it is always clear what is being captured.
            i.hubName = "\(model.hub?.host ?? "the hub") from \(window.appName)"
        }
        return i
    }
}

/// Adjust the crop on the whole window: drag the rectangle or its corners. Saved for this app.
struct CropEditor: View {
    let streamer: WindowStreamer
    var onDone: () -> Void
    @Environment(\.theme) private var theme
    @State private var rect = CallCrop.full

    var body: some View {
        NavigationStack {
            VStack(spacing: HOSpace.l) {
                Text("Drag the corners to fit the call's video. HandOver remembers this for \(streamer.window?.appName ?? "this app").")
                    .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                if let frame = streamer.fullFrame {
                    CropCanvas(image: frame, rect: $rect)
                } else {
                    HOEmptyState(title: "Waiting for the window", loading: true)
                }
            }
            .padding(HOSpace.xl)
            .hoPaperBackground()
            .navigationTitle("Crop")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: onDone) }
                ToolbarItem { Button("Automatic") { streamer.autoCrop(); rect = streamer.crop } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { streamer.setCrop(rect); onDone() }
                }
            }
        }
        .onAppear { rect = streamer.crop }
    }
}

/// The window still with a draggable crop rectangle (normalized, top-left origin).
struct CropCanvas: View {
    let image: CGImage
    @Binding var rect: CGRect
    @State private var start: CGRect?

    var body: some View {
        GeometryReader { geo in
            let fit = Self.fit(CGSize(width: image.width, height: image.height), in: geo.size)
            ZStack(alignment: .topLeading) {
                Image(decorative: image, scale: 1).resizable().frame(width: fit.width, height: fit.height)
                let box = CGRect(x: rect.minX * fit.width, y: rect.minY * fit.height,
                                 width: rect.width * fit.width, height: rect.height * fit.height)
                Path { p in
                    p.addRect(CGRect(origin: .zero, size: fit))
                    p.addRect(box)
                }
                .fill(.black.opacity(0.5), style: FillStyle(eoFill: true))
                Rectangle().strokeBorder(.white, lineWidth: 2)
                    .frame(width: box.width, height: box.height)
                    .offset(x: box.minX, y: box.minY)
                    .gesture(drag(fit: fit) { r, dx, dy in r.offsetBy(dx: dx, dy: dy) })
                ForEach(0..<4, id: \.self) { corner in
                    Circle().fill(.white).frame(width: 14, height: 14)
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                        .position(x: corner % 2 == 0 ? box.minX : box.maxX, y: corner < 2 ? box.minY : box.maxY)
                        .gesture(drag(fit: fit) { r, dx, dy in Self.move(corner: corner, of: r, dx: dx, dy: dy) })
                        .accessibilityLabel("Crop corner")
                }
            }
            .frame(width: fit.width, height: fit.height)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func drag(fit: CGSize, _ change: @escaping (CGRect, CGFloat, CGFloat) -> CGRect) -> some Gesture {
        DragGesture()
            .onChanged { value in
                let base = start ?? rect
                if start == nil { start = rect }
                let moved = change(base, value.translation.width / fit.width, value.translation.height / fit.height)
                rect = Self.clamp(moved)
            }
            .onEnded { _ in start = nil }
    }

    static func move(corner: Int, of r: CGRect, dx: CGFloat, dy: CGFloat) -> CGRect {
        var minX = r.minX, minY = r.minY, maxX = r.maxX, maxY = r.maxY
        if corner % 2 == 0 { minX += dx } else { maxX += dx }
        if corner < 2 { minY += dy } else { maxY += dy }
        return CGRect(x: min(minX, maxX - 0.1), y: min(minY, maxY - 0.1),
                      width: max(0.1, maxX - minX), height: max(0.1, maxY - minY))
    }

    static func clamp(_ r: CGRect) -> CGRect {
        let w = min(1, max(0.1, r.width)), h = min(1, max(0.1, r.height))
        return CGRect(x: min(max(0, r.minX), 1 - w), y: min(max(0, r.minY), 1 - h), width: w, height: h)
    }

    static func fit(_ size: CGSize, in box: CGSize) -> CGSize {
        guard size.width > 0, size.height > 0 else { return .zero }
        let s = min(box.width / size.width, box.height / size.height)
        return CGSize(width: size.width * s, height: size.height * s)
    }
}
#endif
