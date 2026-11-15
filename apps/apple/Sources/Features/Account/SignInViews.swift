import SwiftUI

/// A text field in the HandOver look (DESIGN.md 3.16): `raised` fill, `lineStrong` edge, accent while focused.
struct HOField<Accessory: View>: View {
    var label: String
    @Binding var text: String
    var placeholder: String = ""
    var secure = false
    var monospaced = false
    var footer: String?
    var error: String?
    var shake: Double = 0
    @ViewBuilder var accessory: Accessory

    @Environment(\.theme) private var theme
    @FocusState private var focused: Bool

    private var prompt: Text { Text(placeholder).foregroundStyle(theme.colors.ink3) }

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.xs) {
            Text(label)
                .font(theme.fonts.section)
                .foregroundStyle(theme.colors.ink2)
                .padding(.horizontal, HOSpace.xs)
            HStack(spacing: HOSpace.s) {
                Group {
                    if secure {
                        SecureField(label, text: $text, prompt: prompt)
                    } else {
                        TextField(label, text: $text, prompt: prompt)
                    }
                }
                .font(monospaced ? theme.fonts.code : theme.fonts.body)
                .textFieldStyle(.plain)
                .focused($focused)
                .accessibilityLabel(label)
                accessory
            }
            .padding(.horizontal, HOSpace.m)
            .frame(minHeight: HOSize.control)
            .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
                .strokeBorder(error != nil ? theme.colors.bad : (focused ? theme.colors.accent : theme.colors.lineStrong),
                              lineWidth: focused || error != nil ? 1 : HOLine.width))
            .modifier(ShakeEffect(amount: shake))
            if let error {
                Text(error).font(theme.fonts.footnote).foregroundStyle(theme.colors.bad)
                    .padding(.horizontal, HOSpace.xs)
                    .transition(.opacity)
            } else if let footer {
                Text(footer).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                    .padding(.horizontal, HOSpace.xs)
            }
        }
    }
}

extension HOField where Accessory == EmptyView {
    init(label: String, text: Binding<String>, placeholder: String = "", secure: Bool = false, monospaced: Bool = false,
         footer: String? = nil, error: String? = nil, shake: Double = 0) {
        self.init(label: label, text: text, placeholder: placeholder, secure: secure, monospaced: monospaced,
                  footer: footer, error: error, shake: shake, accessory: { EmptyView() })
    }
}

/// A passcode field with a show or hide button.
struct PasscodeField: View {
    var label = "Passcode"
    @Binding var text: String
    var error: String?
    var shake: Double = 0
    var showStrength = false
    @State private var visible = false
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.xs) {
            HOField(label: label, text: $text, secure: !visible, error: error, shake: shake) {
                Button {
                    visible.toggle()
                } label: {
                    Image(systemName: visible ? "eye.slash" : "eye").foregroundStyle(theme.colors.ink3)
                        .frame(width: 32, height: 32)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(visible ? "Hide passcode" : "Show passcode")
            }
            .textContentTypeIfAvailable(showStrength)
            if showStrength, error == nil { StrengthMeter(strength: PasscodeStrength(text)) }
        }
    }
}

private extension View {
    @ViewBuilder
    func textContentTypeIfAvailable(_ new: Bool) -> some View {
        #if os(iOS)
        textContentType(new ? .newPassword : .password)
        #else
        self
        #endif
    }
}

/// The 3-segment strength bar and its one line (SCREENS.md 25.4).
struct StrengthMeter: View {
    let strength: PasscodeStrength
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.xs) {
            HStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { i in
                    RoundedRectangle(cornerRadius: 2, style: .continuous)
                        .fill(i < strength.segments ? color : theme.colors.well)
                        .frame(height: 4)
                }
            }
            Text(strength.hint).font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                .contentTransition(.opacity)
        }
        .padding(.horizontal, HOSpace.xs)
        .hoAnimation(HOMotion.snappy, value: strength)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Passcode strength: \(strength.hint)")
    }

    private var color: Color {
        switch strength {
        case .tooShort, .easy: theme.colors.caution
        case .okay: theme.colors.accent
        case .strong: theme.colors.good
        }
    }
}

/// Sign in with name and passcode (SCREENS.md 4.1). A wrong passcode shakes the field and says so.
struct SignInForm: View {
    /// Off where the page already says there is no cloud account (onboarding).
    var showsFooter = true
    var onSignedIn: () -> Void
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var name = ""
    @State private var passcode = ""
    @State private var error: String?
    @State private var shake = 0.0
    @State private var working = false

    var canSubmit: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && passcode.count >= PasscodeStrength.minimum && !working
    }

    var body: some View {
        VStack(spacing: HOSpace.l) {
            HOField(label: "Name", text: $name, placeholder: "Sam Rivera")
                .nameContentType()
            PasscodeField(text: $passcode, error: error, shake: shake)
                .onSubmit(submit)
            Button(action: submit) {
                if working { ProgressView() } else { Text("Sign In") }
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .keyboardShortcut(.defaultAction)
            .disabled(!canSubmit)
            if showsFooter {
                Text("Passcodes stay on this hub. HandOver has no cloud account.")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
            }
        }
        .hoAnimation(HOMotion.snappy, value: error)
    }

    private func submit() {
        guard canSubmit else { return }
        Haptics.tap()
        working = true
        error = nil
        Task {
            defer { working = false }
            do {
                try await accounts.signIn(name: name.trimmingCharacters(in: .whitespaces), passcode: passcode)
                Haptics.success()
                onSignedIn()
            } catch {
                Haptics.error()
                if !reduceMotion { withAnimation(.default) { shake += 1 } }
                self.error = error.friendlyMessage
            }
        }
    }
}

private extension View {
    func nameContentType() -> some View {
        #if os(iOS)
        textContentType(.username).textInputAutocapitalization(.words).autocorrectionDisabled()
        #else
        textContentType(.username).autocorrectionDisabled()
        #endif
    }
}

/// First-run owner setup (SCREENS.md 4.5) in two calm steps. The hub takes a name and passcode; hub name and
/// sign-up policy are not hub features yet, so they are not asked.
struct OwnerSetupForm: View {
    var hubName: String
    var onDone: () -> Void
    /// Another device finished setup first.
    var onTaken: () -> Void

    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var page = 0
    @State private var name = ""
    @State private var passcode = ""
    @State private var confirm = ""
    @State private var confirmTouched = false
    @State private var error: String?
    @State private var taken = false
    @State private var working = false

    /// Start on the account page with a passcode typed (previews and snapshots).
    var startOnAccount = false
    var startPasscode = ""

    private var mismatch: Bool { confirmTouched && !confirm.isEmpty && confirm != passcode }
    private var canFinish: Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && passcode.count >= PasscodeStrength.minimum
            && confirm == passcode && !working
    }

    var body: some View {
        VStack(spacing: HOSpace.l) {
            if taken {
                takenCard
            } else if page == 0 {
                intro
            } else {
                form
            }
        }
        .animation(HOMotion.resolve(HOMotion.panel, reduceMotion: reduceMotion), value: page)
        .onAppear {
            if startOnAccount { page = 1 }
            if !startPasscode.isEmpty { passcode = startPasscode }
        }
    }

    private var intro: some View {
        VStack(spacing: HOSpace.l) {
            VStack(alignment: .leading, spacing: HOSpace.m) {
                Label("You become the hub owner.", systemImage: "person.crop.circle.badge.checkmark")
                Label("Owners add people and manage organizations.", systemImage: "person.3")
                Label("Your passcode stays on this hub.", systemImage: "lock")
            }
            .font(theme.fonts.callout)
            .foregroundStyle(theme.colors.ink)
            .labelStyle(SetupLabelStyle())
            .padding(HOSpace.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .hoCard()
            Button("Continue") { Haptics.tap(); page = 1 }
                .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                .keyboardShortcut(.defaultAction)
        }
        .transition(.asymmetric(insertion: .opacity, removal: .move(edge: .leading).combined(with: .opacity)))
    }

    private var form: some View {
        VStack(spacing: HOSpace.l) {
            Text("Your owner account")
                .hoFont(.title, theme)
                .foregroundStyle(theme.colors.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            HOField(label: "Name", text: $name, placeholder: "Sam Rivera",
                    footer: "Shown on lessons you teach and in your organizations.")
                .nameContentType()
            PasscodeField(text: $passcode, showStrength: true)
            PasscodeField(label: "Confirm Passcode", text: $confirm, error: mismatch ? "Passcodes do not match." : nil)
                .onChange(of: confirm) { _, new in if new.count >= passcode.count { confirmTouched = true } }
                .onSubmit { confirmTouched = true; finish() }
            if let error {
                Text(error).font(theme.fonts.footnote).foregroundStyle(theme.colors.bad)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Button(action: finish) {
                if working { ProgressView() } else { Text("Finish Setup") }
            }
            .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
            .keyboardShortcut(.defaultAction)
            .disabled(!canFinish)
        }
        .transition(.asymmetric(insertion: .move(edge: .trailing).combined(with: .opacity), removal: .opacity))
    }

    private var takenCard: some View {
        VStack(spacing: HOSpace.l) {
            HOEmptyState(symbol: "person.badge.key", title: "Already set up",
                         message: "Someone else set up this hub. Sign in with the account they give you.")
                .frame(height: 220)
            Button("Sign In") { Haptics.tap(); onTaken() }
                .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
        }
    }

    private func finish() {
        guard canFinish else { return }
        Haptics.tap()
        working = true
        error = nil
        Task {
            defer { working = false }
            do {
                try await accounts.setupOwner(name: name.trimmingCharacters(in: .whitespaces), passcode: passcode)
                Haptics.success()
                onDone()
            } catch HubError.http(let status, _) where status == 409 {
                Haptics.warning()
                taken = true
            } catch {
                Haptics.error()
                self.error = error.friendlyMessage
            }
        }
    }
}

private struct SetupLabelStyle: LabelStyle {
    @Environment(\.theme) private var theme
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: HOSpace.m) {
            configuration.icon.foregroundStyle(theme.colors.accentInk).frame(width: 24)
            configuration.title
        }
    }
}

/// Sign in as a sheet, from Settings or Profile.
struct SignInSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: HOSpace.xl) {
                    VStack(spacing: HOSpace.s) {
                        Text(accounts.support.setupNeeded ? "Set Up \(accounts.hub?.host ?? "the Hub")"
                                                          : "Sign In to \(accounts.hub?.host ?? "the Hub")")
                            .hoFont(.title, theme)
                            .foregroundStyle(theme.colors.ink)
                            .multilineTextAlignment(.center)
                        Text(accounts.support.setupNeeded
                             ? "No one has an account here yet. Make the first one and you run this hub."
                             : "Use the name and passcode you have on this hub.")
                            .font(theme.fonts.callout)
                            .foregroundStyle(theme.colors.ink2)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.top, HOSpace.l)
                    if accounts.support.setupNeeded {
                        OwnerSetupForm(hubName: accounts.hub?.host ?? "this hub", onDone: { dismiss() },
                                       onTaken: { Task { await accounts.refresh() } })
                    } else {
                        SignInForm(showsFooter: false) { dismiss() }
                        Text("No account yet? Ask the person who runs this hub to add you. Passcodes stay on the hub.")
                            .font(theme.fonts.footnote)
                            .foregroundStyle(theme.colors.ink2)
                            .multilineTextAlignment(.center)
                    }
                }
                .padding(HOSpace.l)
                .frame(maxWidth: 480)
                .frame(maxWidth: .infinity)
            }
            .hoPaperBackground()
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
        }
        .presentationDetents([.large])
    }
}
