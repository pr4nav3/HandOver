import SwiftUI

/// Settings (SCREENS.md 17): hub, appearance, learn, account, organizations and about. Keeps the type name the
/// shell shows.
struct SettingsView: View {
    var body: some View {
        AccountScope { SettingsList() }
    }
}

private struct SettingsList: View {
    @Environment(AppModel.self) private var model
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @AppStorage(ThemeStore.themeKey) private var themeID = ThemeID.fallback.rawValue
    @AppStorage(ThemeStore.appearanceKey) private var appearance = ThemeAppearance.system.rawValue
    @AppStorage(CaptionSize.storageKey) private var captionSize = CaptionSize.medium.rawValue
    @AppStorage(SettingsKeys.captions) private var captions = true
    @AppStorage(SettingsKeys.voiceNext) private var voiceNext = false
    @AppStorage(SettingsKeys.stepResults) private var stepResults = true
    @AppStorage(Haptics.storageKey) private var haptics = true
    @State private var pairing = false
    @State private var connector = HubConnector()
    @State private var askSpeech = false
    @State private var signingIn = false
    @State private var forgetting: HubURL?
    @State private var replayed = false

    var body: some View {
        Form {
            hubSection
            appearanceSection
            learnSection
            spokenSection
            if accounts.support.hasAccounts { accountSection }
            aboutSection
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .hoPaperBackground()
        .navigationTitle("Settings")
        #if os(iOS)
        .fullScreenCover(isPresented: $pairing, onDismiss: { connector.reset() }) { pairingCover }
        #else
        .sheet(isPresented: $pairing, onDismiss: { connector.reset() }) { pairingCover.frame(width: 520, height: 600) }
        #endif
        .sheet(isPresented: $askSpeech) {
            PermissionCard(permission: .speech) { allowed in
                askSpeech = false
                guard allowed else { return }
                Task {
                    if AppPermission.microphone.status == .notAsked { await AppPermission.microphone.request() }
                    voiceNext = AppPermission.microphone.status == .allowed
                }
            }
            .presentationDetents([.medium])
        }
        .sheet(isPresented: $signingIn) { SignInSheet() }
        .confirmationDialog("Remove \(forgetting?.host ?? "this hub")?",
                            isPresented: Binding(get: { forgetting != nil }, set: { if !$0 { forgetting = nil } }),
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) {
                if let hub = forgetting { Haptics.warning(); model.forget(hub) }
            }
        } message: {
            Text("This device forgets the address. Your lessons stay on the hub.")
        }
    }

    // MARK: - Hub

    private var hubSection: some View {
        Section("Hub") {
            if let hub = model.hub {
                NavigationLink { HubDetailView(hub: hub) } label: {
                    HubRow(hub: hub, status: model.connection.label)
                        .padding(.horizontal, -HOSpace.l).padding(.vertical, -HOSpace.m)
                }
            }
            Button { Haptics.tap(); pairing = true } label: {
                SettingsLabel(model.hub == nil ? "Connect to a Hub" : "Connect to Another Hub", symbol: "qrcode.viewfinder").fillingRow()
            }
            .buttonStyle(.plain)
            ForEach(model.recents.filter { $0 != model.hub }.prefix(5), id: \.self) { hub in
                Button { Haptics.tap(); connector.test(hub, app: model, accounts: accounts); pairing = true } label: {
                    HubRow(hub: hub).padding(.horizontal, -HOSpace.l).padding(.vertical, -HOSpace.m)
                }
                .buttonStyle(.plain)
                .contextMenu { Button("Remove", systemImage: "trash", role: .destructive) { forgetting = hub } }
                #if os(iOS)
                .swipeActions { Button("Remove", role: .destructive) { forgetting = hub } }
                #endif
            }
        }
    }

    private var pairingCover: some View {
        HubPairingCover(connector: connector,
                        test: { hub in
                            connector.test(hub, app: model, accounts: accounts) { _ in pairing = false }
                        },
                        onClose: { pairing = false })
            .environment(model)
            .environment(accounts)
    }

    // MARK: - Appearance

    private var appearanceSection: some View {
        Section {
            NavigationLink { ThemePickerView() } label: {
                LabeledContent { Text(ThemeID(stored: themeID).name) } label: { SettingsLabel("Theme", symbol: "paintpalette") }
            }
            LabeledContent { AppearancePicker(selection: $appearance).frame(maxWidth: 220) } label: {
                SettingsLabel("Appearance", symbol: "circle.lefthalf.filled")
            }
        } header: {
            Text("Appearance")
        } footer: {
            Text("Themes with one look keep it.")
        }
    }

    // MARK: - Learn

    private var learnSection: some View {
        Section {
            Toggle(isOn: $captions) { SettingsLabel("Captions", symbol: "captions.bubble") }
            Picker(selection: $captionSize) {
                ForEach(CaptionSize.allCases) { Text($0.title).tag($0.rawValue) }
            } label: {
                SettingsLabel("Caption Size", symbol: "textformat.size")
            }
            CaptionPreview(size: CaptionSize(rawValue: captionSize) ?? .medium)
            Toggle(isOn: Binding(get: { voiceNext }, set: setVoiceNext)) { SettingsLabel("Voice Next", symbol: "waveform") }
            Toggle(isOn: $stepResults) { SettingsLabel("Step Results", symbol: "flag.checkered") }
            #if os(iOS)
            Toggle(isOn: $haptics) { SettingsLabel("Haptics", symbol: "hand.tap") }
            #endif
        } header: {
            Text("Learn")
        } footer: {
            Text(voiceFooter)
        }
    }

    private var voiceFooter: String {
        if AppPermission.speech.status == .unavailable {
            return "Voice Next needs speech recognition, which this build of HandOver cannot use yet."
        }
        return "Voice Next listens for \u{201C}next\u{201D} and \u{201C}back\u{201D} while a lesson is open, and ignores the expert's clip while it plays. Turn it off in a noisy room."
    }

    private func setVoiceNext(_ on: Bool) {
        Haptics.tap()
        guard on else {
            voiceNext = false
            return
        }
        switch (AppPermission.speech.status, AppPermission.microphone.status) {
        case (.allowed, .allowed): voiceNext = true
        case (.unavailable, _), (_, .unavailable): voiceNext = false
        default: askSpeech = true
        }
    }

    // MARK: - Spoken guidance (from Learn)

    private var spokenSection: some View {
        Section {
            SpokenGuidanceSettings()
        } header: {
            Text("Spoken Guidance")
        } footer: {
            Text("Reads each step aloud, and the mistake to avoid, with the voice on this device.")
        }
    }

    // MARK: - Account

    private var accountSection: some View {
        Section("Account") {
            if let user = accounts.user {
                NavigationLink { ProfileView() } label: {
                    HStack(spacing: HOSpace.m) {
                        AvatarView(name: user.name, choice: accounts.avatar, size: 36)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(user.name).font(theme.fonts.bodyMedium)
                            Text(user.roleTitle).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                        }
                    }
                }
                NavigationLink { OrgsListView() } label: { SettingsLabel("Organizations", symbol: "person.3") }
            } else {
                Button { Haptics.tap(); signingIn = true } label: {
                    SettingsLabel(accounts.support.setupNeeded ? "Set Up This Hub" : "Sign In", symbol: "person.crop.circle").fillingRow()
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - About

    private var aboutSection: some View {
        Section("About") {
            LabeledContent { Text(AppInfo.version) } label: { SettingsLabel("Version", symbol: "info.circle") }
            VStack(alignment: .leading, spacing: HOSpace.xs) {
                SettingsLabel("Privacy", symbol: "hand.raised")
                Text("The hub never saves your camera frames. Checks send frames to the hub's check service and nothing is kept.")
                    .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
            }
            NavigationLink { LicensesView() } label: { SettingsLabel("Open Source Licenses", symbol: "doc.text") }
            Button {
                Haptics.tap()
                OnboardingStore().replayWelcome()
                replayed = true
            } label: {
                SettingsLabel(replayed ? "Welcome Shows Next Launch" : "Show Welcome Again", symbol: "sparkles").fillingRow()
            }
            .buttonStyle(.plain)
            .disabled(replayed)
        }
    }
}

/// A settings row label with a symbol tile (Vibeflux `SettingsLabel`).
struct SettingsLabel: View {
    let title: String
    let symbol: String
    @Environment(\.theme) private var theme

    init(_ title: String, symbol: String) {
        self.title = title
        self.symbol = symbol
    }

    var body: some View {
        HStack(spacing: HOSpace.m) {
            SymbolTile(symbol: symbol, side: 30)
            Text(title).font(theme.fonts.body).foregroundStyle(theme.colors.ink)
        }
    }

    /// For a whole-row button: fills the row so all of it takes the tap.
    func fillingRow() -> some View {
        frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
    }
}

/// The live preview line on a black bar for the caption size (SCREENS.md 17).
struct CaptionPreview: View {
    let size: CaptionSize
    @Environment(\.theme) private var theme

    var body: some View {
        Text("Fold the top corner down to meet the center.")
            .font(.system(size: 17 * size.scale, weight: .semibold))
            .foregroundStyle(theme.colors.captionInk)
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .padding(.horizontal, HOSpace.m)
            .padding(.vertical, HOSpace.s)
            .frame(maxWidth: .infinity)
            .background(theme.colors.captionFill, in: RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            .padding(HOSpace.s)
            .background(theme.colors.stage, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
            .animation(HOMotion.snappy, value: size)
            .accessibilityLabel("Caption preview at \(size.title)")
    }
}

/// Hub details: address with Copy, status, checks, Reconnect Now and Remove This Hub.
struct HubDetailView: View {
    let hub: HubURL
    @Environment(AppModel.self) private var model
    @Environment(\.theme) private var theme
    @Environment(\.dismiss) private var dismiss
    @State private var confirmRemove = false
    @State private var copied = false

    var body: some View {
        Form {
            Section {
                LabeledContent("Address") {
                    HStack(spacing: HOSpace.s) {
                        Text(hub.displayName).font(theme.fonts.code).textSelection(.enabled)
                        Button(copied ? "Copied" : "Copy") {
                            Haptics.tap()
                            Clipboard.copy(hub.base.absoluteString)
                            copied = true
                        }
                        .buttonStyle(HOButtonStyle(.quiet, size: .small))
                    }
                }
                LabeledContent("Status") {
                    HStack(spacing: HOSpace.s) {
                        StatusDot(color: model.connection.isConnected ? theme.colors.good : theme.colors.caution)
                        Text(model.connection.label)
                    }
                }
                LabeledContent("Checks", value: checks)
            }
            Section {
                Button("Reconnect Now") { Haptics.tap(); model.connect(to: hub) }
                Button("Remove This Hub", role: .destructive) { confirmRemove = true }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .hoPaperBackground()
        .navigationTitle(hub.host)
        .confirmationDialog("Remove \(hub.host)?", isPresented: $confirmRemove, titleVisibility: .visible) {
            Button("Remove", role: .destructive) {
                Haptics.warning()
                model.forget(hub)
                dismiss()
            }
        } message: {
            Text("This device forgets the address. Your lessons stay on the hub.")
        }
    }

    private var checks: String {
        let state = model.state
        if state.checkOffline { return "Off: \(LearnStatus.offlineMeta(state.checkOfflineReason))" }
        if state.checkMode == .mock { return "Simulated checks" }
        return state.checkMode == nil ? "Not reported" : "Camera checks"
    }
}

/// The open source this app uses. HandOver for Apple uses only Apple's frameworks.
struct LicensesView: View {
    @Environment(\.theme) private var theme

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.m) {
                Text("HandOver for iPhone, iPad and Mac is built only with Apple's own frameworks (SwiftUI, AVFoundation, ScreenCaptureKit, Speech, Core Image). It includes no third-party code, so there are no third-party licenses to list.")
                    .font(theme.fonts.body).foregroundStyle(theme.colors.ink)
                Text("The sample lesson art in onboarding comes from HandOver's own synthetic fortune teller lesson.")
                    .font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
            }
            .padding(HOSpace.l)
            .frame(maxWidth: 640, alignment: .leading)
        }
        .hoPaperBackground()
        .navigationTitle("Open Source Licenses")
    }
}

enum AppInfo {
    static var version: String {
        let v = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0"
        let b = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        return b.map { "\(v) (\($0))" } ?? v
    }
}

#Preview {
    NavigationStack { SettingsView() }
        .environment(AppModel.preview())
        .environment(AccountStore.preview())
        .handOverTheme(.system, dark: false)
}
