import SwiftUI

/// The connecting and result states (SCREENS.md 3.3): spinner, a green check that draws in, or a failure
/// that says what to do.
struct ConnectStatusView: View {
    let phase: HubConnector.Phase
    var onRetry: () -> Void = {}
    var onEdit: () -> Void = {}
    var onCancel: () -> Void = {}

    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var showCheck = false

    var body: some View {
        VStack(spacing: HOSpace.l) {
            Spacer()
            symbol.frame(height: 72)
            VStack(spacing: HOSpace.s) {
                Text(title)
                    .hoFont(.title, theme)
                    .foregroundStyle(theme.colors.ink)
                    .multilineTextAlignment(.center)
                Text(message)
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 340)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .contentTransition(.opacity)
            Spacer()
            actions
        }
        .padding(.horizontal, HOSpace.xl)
        .padding(.bottom, HOSpace.l)
        .frame(maxWidth: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion), value: phase)
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var symbol: some View {
        switch phase {
        case .idle, .testing:
            ProgressView().controlSize(.large)
        case .connected:
            ZStack {
                if showCheck || reduceMotion { check }
            }
            .onAppear {
                if reduceMotion { showCheck = true } else { withAnimation(.easeOut(duration: 0.5)) { showCheck = true } }
            }
        case .failed(_, let result):
            Image(systemName: Self.failure(result).symbol)
                .font(.system(size: 52, weight: .regular))
                .foregroundStyle(theme.colors.caution)
                .transition(.opacity)
        }
    }

    @ViewBuilder
    private var check: some View {
        let image = Image(systemName: "checkmark.circle.fill")
            .font(.system(size: 64, weight: .regular))
            .foregroundStyle(theme.colors.good)
        if reduceMotion {
            image.transition(.opacity)
        } else if #available(iOS 26.0, macOS 26.0, *) {
            image.transition(.symbolEffect(.drawOn))
        } else {
            image.symbolEffect(.bounce, options: .nonRepeating, value: showCheck)
        }
    }

    @ViewBuilder
    private var actions: some View {
        switch phase {
        case .idle, .testing:
            Button("Cancel") { Haptics.tap(); onCancel() }
                .buttonStyle(HOButtonStyle(.quiet, size: .large, fullWidth: true))
                .keyboardShortcut(.cancelAction)
        case .connected:
            Color.clear.frame(height: HOSize.controlLarge)
        case .failed(_, let result):
            VStack(spacing: HOSpace.s) {
                if case .localNetworkDenied = result {
                    OpenSettingsButton()
                } else {
                    Button("Try Again") { Haptics.tap(); onRetry() }
                        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                        .keyboardShortcut(.defaultAction)
                }
                Button("Edit Address") { Haptics.tap(); onEdit() }
                    .buttonStyle(HOButtonStyle(.secondary, size: .large, fullWidth: true))
            }
        }
    }

    private var title: String {
        switch phase {
        case .idle: "Connecting"
        case .testing(let hub): "Connecting to \(hub.host)"
        case .connected(let hub, _): "Connected to \(hub.host)"
        case .failed(let hub, let result): Self.failure(result).title(hub.host)
        }
    }

    private var message: String {
        switch phase {
        case .idle, .testing: "Checking that a HandOver hub is there."
        case .connected(_, let lessons):
            switch lessons {
            case 0: "No lessons on this hub yet."
            case 1: "1 lesson on this hub."
            default: "\(lessons) lessons on this hub."
            }
        case .failed(_, let result): Self.failure(result).message
        }
    }

    private struct Failure {
        let symbol: String
        let title: (String) -> String
        let message: String
    }

    private static func failure(_ result: HubProbeResult) -> Failure {
        switch result {
        case .notAHub:
            Failure(symbol: "questionmark.circle", title: { _ in "No hub at that address" },
                    message: "Something answered, but it is not HandOver. Check the address and port.")
        case .localNetworkDenied:
            Failure(symbol: "lock", title: { _ in "Local network is off for HandOver" },
                    message: "Turn on Local Network for HandOver in Settings > Privacy & Security > Local Network.")
        case .unreachable, .hub:
            Failure(symbol: "wifi.exclamationmark", title: { "Cannot reach \($0)" },
                    message: "Make sure this device and the hub are on the same Wi-Fi, and that the hub is running.")
        }
    }
}

/// Typed address with recent hubs above it (SCREENS.md 3.2 and 3.4).
struct AddressEntryView: View {
    var onConnect: (HubURL) -> Void
    var onCancel: (() -> Void)?

    @Environment(AppModel.self) private var model
    @Environment(\.theme) private var theme
    @State private var address = ""
    @State private var forgetting: HubURL?
    @FocusState private var focused: Bool

    private var parsed: HubURL? { HubURL(parsing: address) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                if !model.recents.isEmpty {
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        SectionHeader("Recent")
                        VStack(spacing: 0) {
                            ForEach(Array(model.recents.prefix(5).enumerated()), id: \.element) { index, hub in
                                if index > 0 { Divider().padding(.leading, 60) }
                                Button { Haptics.tap(); onConnect(hub) } label: { HubRow(hub: hub, isCurrent: hub == model.hub) }
                                    .buttonStyle(HORowButtonStyle())
                                    .contextMenu {
                                        Button("Remove", systemImage: "trash", role: .destructive) { forgetting = hub }
                                    }
                            }
                        }
                        .hoCard()
                    }
                }
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    SectionHeader("Hub address")
                    TextField("192.168.1.20:8000", text: $address)
                        .font(theme.fonts.code)
                        .textFieldStyle(.plain)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        #endif
                        .submitLabel(.go)
                        .focused($focused)
                        .onSubmit(connect)
                        .padding(.horizontal, HOSpace.m)
                        .frame(minHeight: HOSize.control)
                        .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
                            .strokeBorder(focused ? theme.colors.accent : theme.colors.lineStrong, lineWidth: focused ? 1 : HOLine.width))
                    Text("Find it on the hub computer. HandOver uses port 8000 unless you set another.")
                        .font(theme.fonts.footnote)
                        .foregroundStyle(theme.colors.ink2)
                }
                Button("Connect", action: connect)
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .keyboardShortcut(.defaultAction)
                    .disabled(parsed == nil)
            }
            .padding(HOSpace.l)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .hoPaperBackground()
        .navigationTitle("Enter Address")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            if let onCancel {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: onCancel) }
            }
        }
        .onAppear { focused = model.recents.isEmpty }
        .confirmationDialog("Remove \(forgetting?.displayName ?? "this hub")?",
                            isPresented: Binding(get: { forgetting != nil }, set: { if !$0 { forgetting = nil } }),
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) {
                if let hub = forgetting { Haptics.warning(); model.forget(hub) }
            }
        } message: {
            Text("This device forgets the address. Your lessons stay on the hub.")
        }
    }

    private func connect() {
        guard let hub = parsed else { return }
        Haptics.tap()
        onConnect(hub)
    }
}

/// A hub row (DESIGN.md 3.10): computer tile, address, and Connected for the hub in use.
struct HubRow: View {
    let hub: HubURL
    var isCurrent = false
    var status: String?
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.m) {
            SymbolTile(symbol: "desktopcomputer", tone: .neutral, side: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text(hub.host).font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
                Text(status ?? (isCurrent ? "Connected" : hub.displayName))
                    .font(isCurrent || status != nil ? theme.fonts.callout : theme.fonts.code)
                    .foregroundStyle(theme.colors.ink2)
            }
            Spacer(minLength: 0)
            if isCurrent {
                Image(systemName: "checkmark").font(.body.weight(.semibold)).foregroundStyle(theme.colors.accentInk)
            }
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isCurrent ? .isSelected : [])
    }
}

/// A section header in `section` type, `ink2` (DESIGN.md 2.2).
struct SectionHeader: View {
    let text: String
    @Environment(\.theme) private var theme

    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(theme.fonts.section)
            .foregroundStyle(theme.colors.ink2)
            .padding(.horizontal, HOSpace.xs)
            .accessibilityAddTraits(.isHeader)
    }
}

/// The whole connect journey in one cover: scanner, then the test and its result. Used by onboarding and
/// by Settings, Connect to Another Hub.
struct HubPairingCover: View {
    let connector: HubConnector
    /// Runs the test for a found or typed hub.
    var test: (HubURL) -> Void
    var onClose: () -> Void
    var startWithAddress = false

    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var typing = false

    var body: some View {
        ZStack {
            if connector.phase == .idle, !typing {
                QRScannerScreen(
                    title: "Scan the hub's code",
                    hint: "Point the camera at a QR code with the hub's address, like http://192.168.1.20:8000.",
                    handle: { text in
                        guard let hub = HubURL(parsing: text) else { return "That code is not a HandOver hub." }
                        Task {
                            try? await Task.sleep(for: .milliseconds(reduceMotion ? 0 : 450))
                            test(hub)
                        }
                        return nil
                    },
                    onType: { typing = true },
                    onCancel: onClose)
                .transition(.opacity)
            } else if connector.phase == .idle {
                NavigationStack {
                    AddressEntryView(onConnect: { hub in test(hub) }, onCancel: {
                        if startWithAddress { onClose() } else { typing = false }
                    })
                }
                .transition(.opacity)
            } else {
                ConnectStatusView(phase: connector.phase,
                                  onRetry: { if let hub = connector.phase.hub { test(hub) } },
                                  onEdit: { typing = true; connector.reset() },
                                  onCancel: { connector.reset() })
                    .hoPaperBackground()
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.25), value: connector.phase)
        .animation(.easeInOut(duration: 0.25), value: typing)
        .onAppear { typing = startWithAddress || !CameraCapture.isAvailable }
    }
}
