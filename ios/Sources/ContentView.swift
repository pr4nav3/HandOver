// Compiles with Xcode on macOS against MWDAT 1.0.1; not yet run on a device.

import SwiftUI
import UIKit
import Combine

enum CameraKind: String, CaseIterable, Identifiable {
    case phone = "Phone"
    case glasses = "Glasses"

    var id: String { rawValue }
    /// `source` value in the hello message.
    var hubSource: String { self == .phone ? "phone" : "glasses" }
}

/// Owns the hub client and the active FrameSource; switches to the phone camera on glasses fallback.
@MainActor
final class SessionController: ObservableObject {
    let hub = HubClient()

    @Published var selected: CameraKind = .phone
    @Published private(set) var running = false
    /// The source actually producing frames (differs from `selected` after a fallback).
    @Published private(set) var liveKind: CameraKind = .phone
    @Published private(set) var note: String?
    @Published private(set) var cameraStatus: String?

    private var source: FrameSource?
    private var host = ""
    private var resumeOnActive = false

    init() {
        hub.onReplaced = { [weak self] in
            self?.handleReplaced()
        }
    }

    func start(host: String) {
        note = nil
        start(host: host, kind: selected)
    }

    func stop() {
        resumeOnActive = false
        halt()
    }

    func selectionChanged(_ kind: CameraKind) {
        guard running, kind != liveKind else { return }
        note = nil
        hub.setSource(kind.hubSource)
        startSource(kind)
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .background:
            // Backgrounding ends the DAT session anyway; stop cleanly and resume on return.
            if running {
                resumeOnActive = true
                halt()
            }
        case .active:
            if resumeOnActive {
                resumeOnActive = false
                start(host: host, kind: liveKind)
            }
        default:
            break
        }
    }

    // MARK: - Private

    private func start(host: String, kind: CameraKind) {
        self.host = host
        cameraStatus = nil
        hub.setSource(kind.hubSource)
        hub.connect(to: host)
        startSource(kind)
        running = true
        UIApplication.shared.isIdleTimerDisabled = true
    }

    private func halt() {
        source?.stop()
        source = nil
        hub.disconnect()
        running = false
        UIApplication.shared.isIdleTimerDisabled = false
    }

    private func startSource(_ kind: CameraKind) {
        source?.stop()
        source = nil
        liveKind = kind
        cameraStatus = nil

        switch kind {
        case .phone:
            let phone = PhoneCameraSource()
            phone.onFrame = SessionController.makeFrameHandler(hub: hub)
            phone.onError = SessionController.makeMessageHandler(controller: self, isFallback: false)
            source = phone
            phone.start()
        case .glasses:
            let glasses = GlassesCameraSource()
            glasses.onFrame = SessionController.makeFrameHandler(hub: hub)
            glasses.onStatus = SessionController.makeMessageHandler(controller: self, isFallback: false)
            glasses.onFallback = SessionController.makeMessageHandler(controller: self, isFallback: true)
            source = glasses
            glasses.start()
        }
    }

    fileprivate func receiveMessage(_ message: String, isFallback: Bool) {
        guard running else { return }
        if isFallback {
            guard liveKind == .glasses else { return }
            note = "Glasses unavailable (\(message)). Using the phone camera."
            hub.setSource(CameraKind.phone.hubSource)
            startSource(.phone)
        } else {
            cameraStatus = message
        }
    }

    private func handleReplaced() {
        resumeOnActive = false
        source?.stop()
        source = nil
        running = false
        UIApplication.shared.isIdleTimerDisabled = false
        note = "Another connection from this phone replaced this one. Tap Start to reconnect."
    }

    // Handlers are built in nonisolated functions so the closures are not main-actor
    // isolated; sources call them from their own queues and we hop to the main actor here.

    nonisolated private static func makeFrameHandler(hub: HubClient) -> (Data) -> Void {
        return { [weak hub] data in
            guard let hub = hub else { return }
            Task { @MainActor in
                hub.send(frame: data)
            }
        }
    }

    nonisolated private static func makeMessageHandler(controller: SessionController,
                                                       isFallback: Bool) -> (String) -> Void {
        return { [weak controller] message in
            guard let controller = controller else { return }
            Task { @MainActor in
                controller.receiveMessage(message, isFallback: isFallback)
            }
        }
    }
}

// MARK: - Views

struct ContentView: View {
    @StateObject private var controller = SessionController()
    @AppStorage("hubHost") private var host: String = ""
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    setupSection
                    HubPanel(hub: controller.hub,
                             running: controller.running,
                             liveKind: controller.liveKind,
                             note: controller.note,
                             cameraStatus: controller.cameraStatus)
                }
                .padding()
            }
            .navigationTitle("HandOver Camera")
        }
        .onChange(of: scenePhase) { _, newPhase in
            controller.scenePhaseChanged(newPhase)
        }
        .onChange(of: controller.selected) { _, newKind in
            controller.selectionChanged(newKind)
        }
    }

    private var trimmedHost: String {
        host.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var setupSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Hub address")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField("192.168.1.20:8000", text: $host)
                .textFieldStyle(.roundedBorder)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.go)
                .disabled(controller.running)

            Picker("Source", selection: $controller.selected) {
                ForEach(CameraKind.allCases) { kind in
                    Text(kind.rawValue).tag(kind)
                }
            }
            .pickerStyle(.segmented)

            Button {
                if controller.running {
                    controller.stop()
                } else {
                    controller.start(host: trimmedHost)
                }
            } label: {
                Text(controller.running ? "Stop" : "Start")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .tint(controller.running ? .red : .accentColor)
            .disabled(!controller.running && trimmedHost.isEmpty)
        }
    }
}

private struct HubPanel: View {
    @ObservedObject var hub: HubClient
    let running: Bool
    let liveKind: CameraKind
    let note: String?
    let cameraStatus: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                connectionPill
                if running && hub.isSending {
                    HStack(spacing: 4) {
                        Circle().fill(Color.red).frame(width: 10, height: 10)
                        Text("REC").font(.caption.bold()).foregroundStyle(.red)
                    }
                }
                Spacer()
                Text(hub.active ? "Active" : "Idle")
                    .font(.subheadline.bold())
                    .foregroundStyle(hub.active ? Color.green : Color.secondary)
            }

            if running {
                Text("Camera: \(liveKind.rawValue)")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if let cameraStatus = cameraStatus {
                Text(cameraStatus)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if let note = note {
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(.orange)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(stepLine)
                    .font(.title.bold())
                if let title = hub.stepTitle, hub.hasState, hub.status != "done" {
                    Text(title)
                        .font(.title3)
                }
                if hub.hasState && !hub.status.isEmpty {
                    Text(hub.status.capitalized)
                        .font(.headline)
                        .foregroundStyle(statusColor)
                }
            }

            if let mistake = hub.mistakeMessage, !mistake.isEmpty {
                Text(mistake)
                    .font(.title3.bold())
                    .foregroundStyle(Color(red: 1.0, green: 0.7, blue: 0.0))
            }
            if let error = hub.errorMessage, !error.isEmpty {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }

            HStack(spacing: 16) {
                Button {
                    hub.back()
                } label: {
                    Text("Back")
                        .font(.title2.bold())
                        .frame(maxWidth: .infinity, minHeight: 80)
                }
                .buttonStyle(.bordered)

                Button {
                    hub.next()
                } label: {
                    Text("Next")
                        .font(.title2.bold())
                        .frame(maxWidth: .infinity, minHeight: 80)
                }
                .buttonStyle(.borderedProminent)
            }
            .disabled(!hub.canNavigate)

            Text("Frames sent: \(hub.framesSent)")
                .font(.footnote.monospacedDigit())
                .foregroundStyle(.secondary)
            if !hub.urlString.isEmpty {
                Text(hub.urlString)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var stepLine: String {
        guard hub.hasState else { return "Waiting for hub" }
        guard hub.total > 0 else { return "No lesson selected" }
        if hub.status == "done" { return "Done" }
        return "Step \(hub.step + 1) of \(hub.total)"
    }

    private var statusColor: Color {
        switch hub.status {
        case "verified", "done": return .green
        case "checking": return .blue
        case "manual": return .purple
        default: return .secondary
        }
    }

    private var connectionPill: some View {
        let label: String
        let color: Color
        if hub.replaced {
            label = "Replaced"
            color = .red
        } else if hub.connected {
            label = "Connected"
            color = .green
        } else if hub.connecting {
            label = "Connecting..."
            color = .orange
        } else {
            label = "Offline"
            color = .gray
        }
        return Text(label)
            .font(.caption.bold())
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(Capsule().fill(color.opacity(0.2)))
            .foregroundStyle(color)
    }
}

#Preview {
    ContentView()
}
