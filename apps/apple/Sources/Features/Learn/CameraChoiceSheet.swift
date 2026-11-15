import SwiftUI

/// "How should HandOver see your hands?": This iPhone, Meta glasses or Another device, each with what it is and
/// how to set it up. Opened before the first lesson and from every "Camera: ..., Change" row.
struct CameraChoiceSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var choice: LearnCamera = .thisDevice
    @State private var otherKind: OtherDeviceKind = .phone

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: HOSpace.l) {
                    VStack(alignment: .leading, spacing: HOSpace.xs) {
                        Text("How should HandOver see your hands?")
                            .hoFont(.title, theme)
                            .foregroundStyle(theme.colors.ink)
                            .accessibilityAddTraits(.isHeader)
                        Text("A camera watches your hands so HandOver knows when each step is done. Pick one; you can change it any time.")
                            .font(theme.fonts.callout)
                            .foregroundStyle(theme.colors.ink2)
                    }
                    VStack(spacing: HOSpace.s) {
                        ForEach(LearnCamera.allCases) { option in
                            CameraOptionRow(option: option, selected: option == choice,
                                            available: option != .glasses || LearnCamera.glassesAvailable) {
                                Haptics.tap()
                                choice = option
                            }
                        }
                    }
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
        Button {
            Haptics.impact(.medium)
            flow.confirm(choice, model: model)
        } label: {
            Text(flow.pending == nil ? "Done" : "Start Lesson").frame(maxWidth: .infinity)
        }
        .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
        .disabled(choice == .glasses && !LearnCamera.glassesAvailable)
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .frame(maxWidth: 560)
        .frame(maxWidth: .infinity)
        .background(.bar)
    }

    @ViewBuilder private var details: some View {
        switch choice {
        case .thisDevice:
            SetupSteps(title: "Before you start", steps: thisDeviceSteps)
        case .glasses:
            glassesDetails
        case .otherDevice:
            otherDeviceDetails
        }
    }

    private var thisDeviceSteps: [String] {
        #if os(macOS)
        ["Point the Mac's camera at your table.", "Keep your hands in view while you work."]
        #else
        ["Stand the \(DeviceWord.noun) up with the screen facing you.",
         "Check that the back camera sees your hands and the table.",
         "Turn the sound up so you hear the guidance."]
        #endif
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
