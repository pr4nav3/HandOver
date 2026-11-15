import SwiftUI

/// A short camera choice: connection first, then two equal primary sources. Meta setup advances one action at
/// a time; secondary-device pairing stays available without competing with the common path.
struct CameraChoiceSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow
    @Environment(AccountStore.self) private var accounts: AccountStore?
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var choice: LearnCamera = .thisDevice
    @State private var otherKind: OtherDeviceKind = .phone

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: HOSpace.l) {
                    VStack(alignment: .leading, spacing: HOSpace.xs) {
                        Text("Choose your camera")
                            .hoFont(.title, theme)
                            .foregroundStyle(theme.colors.ink)
                            .accessibilityAddTraits(.isHeader)
                        Text("What should watch your work?")
                            .font(theme.fonts.callout)
                            .foregroundStyle(theme.colors.ink2)
                    }
                    connectionStatus
                    primaryChoices
                    details
                }
                .padding(HOSpace.l)
                .frame(maxWidth: 560)
                .frame(maxWidth: .infinity)
            }
            .safeAreaInset(edge: .bottom) { footer }
            .hoPaperBackground()
            .navigationTitle("Camera")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { flow.cancelSheet() }
                }
            }
        }
        .onAppear { choice = flow.camera }
        .onChange(of: choice, initial: true) { _, new in
            if new == .glasses, LearnCamera.glassesAvailable { _ = flow.glassesController() }
        }
        .presentationDetents([.large])
        #if os(macOS)
        .frame(idealWidth: 520, idealHeight: 680)
        #endif
    }

    private var footer: some View {
        Group {
            if canConfirm {
                Button {
                    Haptics.impact(.medium)
                    flow.confirm(choice, model: model)
                } label: {
                    Text(flow.pending == nil ? "Use \(choice.title)" : "Start Lesson").frame(maxWidth: .infinity)
                }
                .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                .disabled(model.hub == nil)
            } else {
                Text("Connect your glasses above to continue")
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink2)
                    .frame(maxWidth: .infinity)
                    .frame(minHeight: HOSize.controlLarge)
            }
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .frame(maxWidth: 560)
        .frame(maxWidth: .infinity)
        .background(.bar)
    }

    @ViewBuilder private var details: some View {
        switch choice {
        case .thisDevice:
            HOBanner(symbol: "checkmark.circle.fill", tone: .good,
                     text: "Ready to use \(DeviceWord.this.lowercased()).")
        case .glasses:
            glassesDetails
        case .otherDevice:
            otherDeviceDetails
        }
    }

    private var canConfirm: Bool {
        guard choice == .glasses else { return true }
        return flow.glasses?.state.isStreaming == true
    }

    private var connectionStatus: some View {
        HStack(spacing: HOSpace.s) {
            Image(systemName: model.connection.isConnected ? "checkmark.circle.fill" : "arrow.clockwise")
                .foregroundStyle(model.connection.isConnected ? theme.colors.good : theme.colors.caution)
            VStack(alignment: .leading, spacing: 2) {
                Text(connectionTitle).font(theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
                if let user = accounts?.user {
                    Text("Signed in as \(user.name)").font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(HOSpace.m)
        .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
            .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
        .accessibilityElement(children: .combine)
    }

    private var connectionTitle: String {
        guard let hub = model.hub else { return "Not paired with a Mac" }
        return model.connection.isConnected ? "Connected to \(hub.host)" : "Connecting to \(hub.host)"
    }

    @ViewBuilder private var primaryChoices: some View {
        #if os(iOS)
        HStack(spacing: HOSpace.s) {
            PrimaryCameraCard(option: .thisDevice, selected: choice == .thisDevice, available: true) { pick(.thisDevice) }
            PrimaryCameraCard(option: .glasses, selected: choice == .glasses,
                              available: LearnCamera.glassesAvailable) { pick(.glasses) }
        }
        Button { pick(.otherDevice) } label: {
            Label("Use another device", systemImage: "qrcode")
                .font(theme.fonts.callout)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(HOButtonStyle(choice == .otherDevice ? .secondary : .quiet, size: .small, fullWidth: true))
        #else
        VStack(spacing: HOSpace.s) {
            ForEach(LearnCamera.allCases) { option in
                CameraOptionRow(option: option, selected: option == choice,
                                available: option != .glasses || LearnCamera.glassesAvailable) { pick(option) }
            }
        }
        #endif
    }

    private func pick(_ option: LearnCamera) {
        Haptics.tap()
        choice = option
    }

    @ViewBuilder private var glassesDetails: some View {
        if LearnCamera.glassesAvailable, let glasses = flow.glasses {
            RecordGlassesCard(controller: glasses) { choice = .thisDevice }
        } else if !LearnCamera.glassesAvailable {
            HOBanner(symbol: "eyeglasses", tone: .neutral,
                     text: "Meta glasses work with the iPhone app. On \(DeviceWord.this), pick another camera.")
        }
    }

    @ViewBuilder private var otherDeviceDetails: some View {
        VStack(alignment: .leading, spacing: HOSpace.m) {
            Picker("Device", selection: $otherKind) {
                ForEach(OtherDeviceKind.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            if let hub = model.hub {
                let link = otherKind.link(hub: hub)
                HStack(alignment: .top, spacing: HOSpace.l) {
                    QRCodeView(text: link.absoluteString, side: 128)
                    VStack(alignment: .leading, spacing: HOSpace.s) {
                        ForEach(Array(otherKind.steps.enumerated()), id: \.offset) { index, step in
                            NumberedLine(number: index + 1, text: step)
                        }
                        Text(otherKind.shownLink(hub: hub))
                            .font(theme.fonts.footnote.monospaced())
                            .foregroundStyle(theme.colors.accentInk)
                            .textSelection(.enabled)
                            .lineLimit(2)
                    }
                }
                .raisedCard()
                if otherKind == .browser {
                    Text("On the computer running the hub, open localhost:\(hub.port)/capture instead.")
                        .font(theme.fonts.footnote)
                        .foregroundStyle(theme.colors.ink2)
                }
            } else {
                HOBanner(symbol: "wifi.exclamationmark", text: "Connect to a hub in Settings first.")
            }
        }
    }
}

#if os(iOS)
private struct PrimaryCameraCard: View {
    let option: LearnCamera
    let selected: Bool
    let available: Bool
    let action: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: HOSpace.s) {
                HStack {
                    SymbolTile(symbol: option.symbol, tone: selected ? .accent : .neutral, side: 42)
                    Spacer(minLength: 0)
                    Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(selected ? theme.colors.accentInk : theme.colors.ink3)
                }
                Text(option == .thisDevice ? "iPhone Camera" : "Meta Glasses")
                    .font(theme.fonts.headline)
                    .foregroundStyle(theme.colors.ink)
                    .multilineTextAlignment(.leading)
                Text(option == .thisDevice ? "Use this phone" : "Use what you see")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
            }
            .padding(HOSpace.m)
            .frame(maxWidth: .infinity, minHeight: 142, alignment: .topLeading)
            .background(selected ? theme.colors.accentSoft : theme.colors.raised,
                        in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                .strokeBorder(selected ? theme.colors.accentInk.opacity(0.5) : theme.colors.line,
                              lineWidth: HOLine.width))
        }
        .buttonStyle(.plain)
        .disabled(!available)
        .opacity(available ? 1 : 0.5)
        .accessibilityLabel(option == .thisDevice ? "iPhone Camera" : "Meta Glasses")
        .accessibilityValue(selected ? "Selected" : "")
    }
}
#endif

/// Which second device is the camera.
enum OtherDeviceKind: String, CaseIterable, Identifiable {
    case phone, browser
    var id: String { rawValue }

    var title: String {
        switch self {
        case .phone: "Second Phone"
        case .browser: "Laptop or Browser"
        }
    }

    var steps: [String] {
        switch self {
        case .phone: ["Scan this code with the second phone.", "HandOver opens its camera automatically.", "Point it at your hands."]
        case .browser: ["Open this link in a browser.", "Allow the camera and point it at your hands."]
        }
    }

    /// The second phone opens HandOver on this hub; a browser opens the hub's capture page (it needs https for the
    /// camera, so it uses the hub's https port).
    func link(hub: HubURL) -> URL {
        switch self {
        case .phone: return hub.cameraLink(.phone)
        case .browser: return CaptureLink.url(hub: hub)
        }
    }

    func shownLink(hub: HubURL) -> String {
        switch self {
        case .phone: return "Opens HandOver and connects automatically"
        case .browser: return CaptureLink.url(hub: hub).absoluteString
        }
    }
}

/// The hub's web capture page. Browsers only open the camera over https, so it points at the https port.
enum CaptureLink {
    static func url(hub: HubURL) -> URL {
        var c = URLComponents()
        c.scheme = "https"
        c.host = hub.host
        c.port = hub.isSecure ? hub.port : HubURL.defaultHTTPSPort
        c.path = "/capture"
        return c.url ?? hub.base.appending(path: "capture")
    }
}

/// One selectable camera option: symbol, title, what it is and how to set it up.
private struct CameraOptionRow: View {
    let option: LearnCamera
    let selected: Bool
    let available: Bool
    let action: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: HOSpace.m) {
                SymbolTile(symbol: option.symbol, tone: selected ? .accent : .neutral)
                VStack(alignment: .leading, spacing: HOSpace.xxs) {
                    HStack(spacing: HOSpace.s) {
                        Text(option.title).font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
                        if option == .glasses {
                            Text(GlassesFeature.experimentalLabel)
                                .font(theme.fonts.badge)
                                .foregroundStyle(theme.colors.ink2)
                                .padding(.horizontal, HOSpace.xs + 2)
                                .padding(.vertical, 2)
                                .overlay(Capsule().strokeBorder(theme.colors.line, lineWidth: HOLine.width))
                        }
                    }
                    Text(option.line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink)
                    Text(available ? option.setup : "iPhone only.")
                        .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                }
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(selected ? theme.colors.accentInk : theme.colors.ink3)
            }
            .padding(HOSpace.m)
            .background(selected ? theme.colors.accentSoft : theme.colors.raised,
                        in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
                .strokeBorder(selected ? theme.colors.accentInk.opacity(0.5) : theme.colors.line, lineWidth: HOLine.width))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .opacity(available ? 1 : 0.55)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

/// A short numbered list under a title.
struct SetupSteps: View {
    let title: String
    let steps: [String]
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            Text(title).font(theme.fonts.headline).foregroundStyle(theme.colors.ink)
            ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                NumberedLine(number: index + 1, text: step)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .raisedCard()
    }
}

/// "1" in a small circle, then the line.
struct NumberedLine: View {
    let number: Int
    let text: String
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: HOSpace.s) {
            Text("\(number)")
                .font(theme.fonts.footnote.weight(.semibold))
                .foregroundStyle(theme.colors.accentInk)
                .frame(width: 22, height: 22)
                .background(theme.colors.accentSoft, in: Circle())
                .accessibilityHidden(true)
            Text(text)
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }
}

/// "Camera: This iPhone" with Change, so the choice is never hidden. Draws nothing outside the app shell.
struct CameraChoiceRow: View {
    @Environment(LearnFlow.self) private var flow: LearnFlow?
    @Environment(\.theme) private var theme

    var body: some View {
        if let flow {
            HStack(spacing: HOSpace.s) {
                Image(systemName: flow.camera.symbol).foregroundStyle(theme.colors.ink2).accessibilityHidden(true)
                Text("Camera: \(flow.hasChosenCamera ? flow.camera.title : "Choose when you start")")
                    .font(theme.fonts.callout)
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(1)
                Spacer(minLength: HOSpace.s)
                Button("Change") { Haptics.tap(); flow.changeCamera() }
                    .buttonStyle(HOButtonStyle(.quiet, size: .small))
            }
            .padding(.leading, HOSpace.m)
            .padding(.trailing, HOSpace.xs)
            .padding(.vertical, HOSpace.xxs)
            .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
                .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
            .accessibilityElement(children: .combine)
        }
    }
}
