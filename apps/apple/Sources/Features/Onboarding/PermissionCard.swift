import SwiftUI

/// The plain-words card shown just before a system permission prompt (SCREENS.md 25.8). Continue shows the
/// system prompt; Not Now goes back without spending it. Already denied: Open Settings instead.
struct PermissionCard: View {
    let permission: AppPermission
    /// Called with true when the permission is allowed (or needs no prompt), false on Not Now or a no.
    var onDone: (Bool) -> Void

    @Environment(\.theme) private var theme
    @State private var status: PermissionStatus = .notAsked
    @State private var asking = false

    var body: some View {
        VStack(spacing: HOSpace.l) {
            Spacer(minLength: HOSpace.l)
            SymbolTile(symbol: permission.symbol, side: 56)
            VStack(spacing: HOSpace.s) {
                Text(permission.title)
                    .hoFont(.title, theme)
                    .foregroundStyle(theme.colors.ink)
                    .multilineTextAlignment(.center)
                Text(line)
                    .font(theme.fonts.body)
                    .foregroundStyle(theme.colors.ink2)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 360)
            }
            Spacer(minLength: HOSpace.l)
            VStack(spacing: HOSpace.s) {
                if status == .denied {
                    OpenSettingsButton()
                } else {
                    Button {
                        Haptics.tap()
                        Task { await allow() }
                    } label: {
                        if asking { ProgressView() } else { Text("Continue") }
                    }
                    .buttonStyle(HOButtonStyle(.primary, size: .large, fullWidth: true))
                    .keyboardShortcut(.defaultAction)
                    .disabled(asking)
                }
                Button("Not Now") { Haptics.tap(); onDone(false) }
                    .buttonStyle(HOButtonStyle(.quiet, size: .large, fullWidth: true))
            }
        }
        .padding(HOSpace.xl)
        .frame(maxWidth: 520)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .hoPaperBackground()
        .onAppear { status = permission.status }
        .accessibilityElement(children: .contain)
    }

    private var line: String {
        status == .denied ? permission.line + " It is off in Settings." : permission.line
    }

    private func allow() async {
        if status == .allowed || status == .unavailable {
            onDone(status == .allowed)
            return
        }
        asking = true
        let ok = await permission.request()
        asking = false
        status = permission.status
        onDone(ok)
    }
}

#Preview("Camera card") {
    PermissionCard(permission: .camera) { _ in }
        .handOverTheme(.system, dark: false)
}
