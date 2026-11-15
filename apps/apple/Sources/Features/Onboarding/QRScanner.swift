@preconcurrency import AVFoundation
import SwiftUI

/// The camera reading QR codes with `AVCaptureMetadataOutput`, behind a full-bleed preview. Pattern from
/// Vibeflux `PairingView.swift`. Calls `onCode` once per distinct code.
struct QRCameraView {
    let onCode: @MainActor (String) -> Void

    final class ScannerLayerView: PlatformView, AVCaptureMetadataOutputObjectsDelegate {
        var onCode: (@MainActor (String) -> Void)?
        private let session = AVCaptureSession()
        private var lastCode: String?
        private let preview = AVCaptureVideoPreviewLayer()

        func start() {
            #if os(macOS)
            wantsLayer = true
            layer?.addSublayer(preview)
            #else
            layer.addSublayer(preview)
            #endif
            preview.videoGravity = .resizeAspectFill
            preview.session = session
            guard let device = CameraCapture.defaultDevice(),
                  let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) else { return }
            session.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else { return }
            session.addOutput(output)
            output.setMetadataObjectsDelegate(self, queue: .main)
            if output.availableMetadataObjectTypes.contains(.qr) { output.metadataObjectTypes = [.qr] }
            let box = SessionBox(session: session)
            DispatchQueue.global(qos: .userInitiated).async { box.session.startRunning() }
        }

        func stop() {
            let box = SessionBox(session: session)
            DispatchQueue.global(qos: .userInitiated).async { box.session.stopRunning() }
        }

        /// Lets the same code be read again (after a bad code was dismissed).
        func reset() { lastCode = nil }

        #if os(macOS)
        override func layout() {
            super.layout()
            preview.frame = bounds
        }
        #else
        override func layoutSubviews() {
            super.layoutSubviews()
            preview.frame = bounds
            if let connection = preview.connection, connection.isVideoRotationAngleSupported(rotationAngle) {
                connection.videoRotationAngle = rotationAngle
            }
        }

        private var rotationAngle: CGFloat {
            switch window?.windowScene?.effectiveGeometry.interfaceOrientation {
            case .landscapeLeft?: 180
            case .landscapeRight?: 0
            case .portraitUpsideDown?: 270
            default: 90
            }
        }
        #endif

        nonisolated func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject],
                                        from connection: AVCaptureConnection) {
            let text = (objects.first as? AVMetadataMachineReadableCodeObject)?.stringValue
            MainActor.assumeIsolated {
                guard let text, text != lastCode else { return }
                lastCode = text
                onCode?(text)
            }
        }
    }

    private struct SessionBox: @unchecked Sendable { let session: AVCaptureSession }
}

#if os(macOS)
typealias PlatformView = NSView

extension QRCameraView: NSViewRepresentable {
    func makeNSView(context: Context) -> ScannerLayerView {
        let view = ScannerLayerView()
        view.onCode = onCode
        view.start()
        return view
    }

    func updateNSView(_ view: ScannerLayerView, context: Context) { view.onCode = onCode }

    static func dismantleNSView(_ view: ScannerLayerView, coordinator: ()) { view.stop() }
}
#else
typealias PlatformView = UIView

extension QRCameraView: UIViewRepresentable {
    func makeUIView(context: Context) -> ScannerLayerView {
        let view = ScannerLayerView()
        view.onCode = onCode
        view.start()
        return view
    }

    func updateUIView(_ view: ScannerLayerView, context: Context) { view.onCode = onCode }

    static func dismantleUIView(_ view: ScannerLayerView, coordinator: ()) { view.stop() }
}
#endif

/// Four rounded corner brackets of a rounded square, the viewfinder mark.
struct CornerBrackets: Shape {
    var radius: CGFloat
    /// How far each bracket runs along its edge, as a fraction of the side.
    var reach: CGFloat = 0.22

    func path(in rect: CGRect) -> Path {
        var p = Path()
        let r = min(radius, rect.width / 2, rect.height / 2)
        let len = max(r, min(rect.width, rect.height) * reach)
        let (minX, minY, maxX, maxY) = (rect.minX, rect.minY, rect.maxX, rect.maxY)
        // Top left.
        p.move(to: CGPoint(x: minX, y: minY + len))
        p.addLine(to: CGPoint(x: minX, y: minY + r))
        p.addArc(center: CGPoint(x: minX + r, y: minY + r), radius: r, startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
        p.addLine(to: CGPoint(x: minX + len, y: minY))
        // Top right.
        p.move(to: CGPoint(x: maxX - len, y: minY))
        p.addLine(to: CGPoint(x: maxX - r, y: minY))
        p.addArc(center: CGPoint(x: maxX - r, y: minY + r), radius: r, startAngle: .degrees(270), endAngle: .degrees(0), clockwise: false)
        p.addLine(to: CGPoint(x: maxX, y: minY + len))
        // Bottom right.
        p.move(to: CGPoint(x: maxX, y: maxY - len))
        p.addLine(to: CGPoint(x: maxX, y: maxY - r))
        p.addArc(center: CGPoint(x: maxX - r, y: maxY - r), radius: r, startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false)
        p.addLine(to: CGPoint(x: maxX - len, y: maxY))
        // Bottom left.
        p.move(to: CGPoint(x: minX + len, y: maxY))
        p.addLine(to: CGPoint(x: minX + r, y: maxY))
        p.addArc(center: CGPoint(x: minX + r, y: maxY - r), radius: r, startAngle: .degrees(90), endAngle: .degrees(180), clockwise: false)
        p.addLine(to: CGPoint(x: minX, y: maxY - len))
        return p
    }
}

/// A sideways shake for a bad code or wrong passcode: 8 points, 2 cycles (DESIGN.md 2.8).
struct ShakeEffect: GeometryEffect {
    var amount: Double
    var animatableData: Double {
        get { amount }
        set { amount = newValue }
    }

    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 8 * sin(amount * .pi * 4), y: 0))
    }
}

/// The full-screen scanner (SCREENS.md 3.1): camera, a dim with a rounded square window, white corner
/// brackets that close in and turn green when a code is read, a title and hint, and type and paste fallbacks.
/// Forced dark, since it sits on the camera.
struct QRScannerScreen: View {
    var title: String
    var hint: String
    /// Returns nil for a good code (the caller takes over), or the words for a bad one.
    var handle: @MainActor (String) -> String?
    var typeTitle: String = "Enter Address"
    var onType: (() -> Void)?
    var onCancel: () -> Void
    /// Draws the overlay with no camera (screenshots, previews).
    var staticPreview = false

    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var access = AppPermission.camera.status
    @State private var found = false
    @State private var problem: String?
    @State private var shake = 0.0
    @State private var askingFirst = false

    private var cameraWorks: Bool { staticPreview || (CameraCapture.isAvailable && access == .allowed) }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if !staticPreview, cameraWorks {
                QRCameraView { code in receive(code) }
                    .ignoresSafeArea()
                    .transition(.opacity)
            }
            viewfinder
            chrome
        }
        .environment(\.colorScheme, .dark)
        .task {
            guard !staticPreview, CameraCapture.isAvailable else { return }
            if access == .notAsked { askingFirst = true }
        }
        .sheet(isPresented: $askingFirst) {
            PermissionCard(permission: .camera) { allowed in
                askingFirst = false
                access = AppPermission.camera.status
                if !allowed && access == .notAsked { onCancel() }
            }
            .presentationDetents([.medium])
        }
    }

    private var viewfinder: some View {
        GeometryReader { geo in
            let full = min(geo.size.width - 96, 280)
            let side = full * (found ? 0.86 : 1)
            let shape = RoundedRectangle(cornerRadius: side * 0.14, style: .continuous)
            ZStack {
                if cameraWorks {
                    Rectangle().fill(.black.opacity(0.5))
                        .mask {
                            Rectangle().overlay { shape.frame(width: side, height: side).blendMode(.destinationOut) }
                                .compositingGroup()
                        }
                    CornerBrackets(radius: side * 0.14)
                        .stroke(found ? theme.colors.good : .white,
                                style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
                        .frame(width: side, height: side)
                        .modifier(ShakeEffect(amount: shake))
                } else {
                    shape.strokeBorder(.white.opacity(0.3), style: StrokeStyle(lineWidth: 2, dash: [8, 8]))
                        .frame(width: full, height: full)
                        .overlay {
                            Image(systemName: "qrcode").font(.system(size: 64, weight: .light)).foregroundStyle(.white.opacity(0.3))
                        }
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
            .animation(reduceMotion ? nil : HOMotion.layout, value: found)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private var chrome: some View {
        VStack(spacing: HOSpace.l) {
            HStack {
                Spacer()
                Button { Haptics.tap(); onCancel() } label: {
                    Image(systemName: "xmark").font(.body.weight(.semibold))
                }
                .buttonStyle(HOIconButtonStyle(onVideo: true))
                .accessibilityLabel("Cancel")
                .keyboardShortcut(.cancelAction)
            }
            VStack(spacing: HOSpace.s) {
                Text(title).font(.title2.weight(.semibold)).foregroundStyle(.white)
                Text(hint).font(.subheadline).foregroundStyle(.white.opacity(0.7)).multilineTextAlignment(.center)
            }
            .padding(.horizontal, HOSpace.xl)
            Spacer()
            VStack(spacing: HOSpace.m) {
                if let problem {
                    Label(problem, systemImage: "exclamationmark.triangle.fill")
                        .font(.footnote.weight(.medium)).foregroundStyle(.white)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .hoGlassCapsule()
                        .transition(reduceMotion ? .opacity : .move(edge: .bottom).combined(with: .opacity))
                }
                if !cameraWorks {
                    Text(cameraMessage).font(.footnote).foregroundStyle(.white.opacity(0.7)).multilineTextAlignment(.center)
                    if access == .denied { OpenSettingsButton() }
                }
                HStack(spacing: HOSpace.s) {
                    if let onType {
                        Button { Haptics.tap(); onType() } label: { Label(typeTitle, systemImage: "keyboard") }
                            .buttonStyle(GlassCapsuleButtonStyle())
                    }
                    PasteButton(payloadType: String.self) { strings in
                        if let text = strings.first { Task { @MainActor in receive(text) } }
                    }
                    .buttonBorderShape(.capsule)
                    .labelStyle(.titleAndIcon)
                    .tint(.white.opacity(0.2))
                }
            }
            .padding(.horizontal, HOSpace.xl)
            .animation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion), value: problem)
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.top, HOSpace.s)
        .padding(.bottom, HOSpace.l)
    }

    private var cameraMessage: String {
        switch access {
        case .denied: "HandOver cannot use the camera. Allow it in Settings, or \(onType == nil ? "paste the code" : "enter the address")."
        default: CameraCapture.isAvailable ? "Waiting for the camera." : "No camera here. \(onType == nil ? "Paste the code" : "Enter the address") instead."
        }
    }

    private func receive(_ text: String) {
        guard !found else { return }
        if let bad = handle(text) {
            Haptics.error()
            if !reduceMotion { withAnimation(.default) { shake += 1 } }
            problem = bad
            Task {
                try? await Task.sleep(for: .seconds(3))
                if problem == bad { problem = nil }
            }
        } else {
            found = true
            problem = nil
            Haptics.soft()
        }
    }
}

/// White text in a glass capsule, for buttons over the camera.
struct GlassCapsuleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.white)
            .padding(.horizontal, HOSpace.l)
            .frame(minHeight: HOSize.control)
            .hoGlassCapsule(interactive: true)
            .opacity(configuration.isPressed ? 0.8 : 1)
    }
}

/// Opens this app's page in the system Settings.
struct OpenSettingsButton: View {
    var body: some View {
        Button("Open Settings") {
            Haptics.tap()
            #if os(iOS)
            if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
            #else
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera") {
                NSWorkspace.shared.open(url)
            }
            #endif
        }
        .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
    }
}

#Preview("Scanner") {
    QRScannerScreen(title: "Scan the hub's code",
                    hint: "On the computer running HandOver, open http://localhost:8000 and click Show Code.",
                    handle: { _ in nil }, onType: {}, onCancel: {}, staticPreview: true)
        .handOverTheme(.system, dark: true)
}
