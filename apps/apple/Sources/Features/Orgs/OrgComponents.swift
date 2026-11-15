import CoreImage
import CoreImage.CIFilterBuiltins
import SwiftUI

/// An org's avatar (DESIGN.md 3.24): rounded square, letters in `accentInk` on `accentSoft` (Mono: `ink` on
/// `well`), SF Rounded semibold at 42% of the side.
struct OrgAvatar: View {
    let name: String
    var size: CGFloat = 44
    @Environment(\.theme) private var theme

    var body: some View {
        Text(AvatarChoice.initials(name))
            .font(.system(size: size * 0.42, weight: .semibold, design: .rounded))
            .foregroundStyle(theme.isMono ? theme.colors.ink : theme.colors.accentInk)
            .frame(width: size, height: size)
            .background(theme.isMono ? theme.colors.well : theme.colors.accentSoft,
                        in: RoundedRectangle(cornerRadius: size * 0.28, style: .continuous))
            .accessibilityHidden(true)
    }
}

/// A QR code, black on white with a 4-module quiet zone in every theme so every scanner reads it.
struct QRCodeView: View {
    let text: String
    var side: CGFloat = 160

    var body: some View {
        Group {
            if let image = Self.make(text) {
                Image(decorative: image, scale: 1)
                    .interpolation(.none)
                    .resizable()
                    .aspectRatio(1, contentMode: .fit)
            } else {
                Color.white
            }
        }
        .frame(width: side, height: side)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .accessibilityLabel("QR code")
    }

    static func make(_ text: String) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage else { return nil }
        // 10 pixels per module, on white with a 4-module quiet zone all round.
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 10, y: 10))
        let canvas = scaled.extent.insetBy(dx: -40, dy: -40)
        let framed = scaled.composited(over: CIImage(color: .white).cropped(to: canvas))
        return FrameEncoder.shared.context.createCGImage(framed, from: canvas)
    }
}

/// An org row (DESIGN.md 3.24): avatar 44, name, member count, role badge above Member.
struct OrgRow: View {
    let org: OrgSummary
    @Environment(\.theme) private var theme

    var body: some View {
        HORow(title: org.name, meta: org.members == 1 ? "1 member" : "\(org.members) members") {
            OrgAvatar(name: org.name)
        } trailing: {
            if let role = org.role, role != .learner { RolePill(text: role.title) }
        }
        .accessibilityElement(children: .combine)
    }
}

/// An invite code card (DESIGN.md 3.25): the code grouped in fours, its QR, what it does, Share and Copy.
struct InviteCodeCard: View {
    let code: String
    let invite: OrgInvite
    let orgName: String
    let hub: HubURL?
    var onRevoke: (() -> Void)?
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var copied = false

    private var link: URL { InviteCode.link(code: code, hub: hub) }
    private var shareText: String { "Join \(orgName) on HandOver: \(code). Or open \(link.absoluteString)." }

    var body: some View {
        let layout = sizeClass == .compact ? AnyLayout(VStackLayout(spacing: HOSpace.l)) : AnyLayout(HStackLayout(alignment: .top, spacing: HOSpace.xl))
        layout {
            QRCodeView(text: link.absoluteString)
            VStack(alignment: .leading, spacing: HOSpace.s) {
                Text(InviteCode.grouped(code))
                    .font(.system(.title2, design: .monospaced).weight(.medium))
                    .tracking(1)
                    .foregroundStyle(theme.colors.ink)
                    .textSelection(.enabled)
                    .accessibilityLabel("Invite code \(InviteCode.spoken(code))")
                InviteMeta(invite: invite)
                HStack(spacing: HOSpace.s) {
                    ShareLink(item: link, subject: Text("Join \(orgName)"), message: Text(shareText)) {
                        Label("Share", systemImage: "square.and.arrow.up")
                    }
                    .buttonStyle(HOButtonStyle(.secondary, size: .small))
                    Button {
                        Haptics.tap()
                        Clipboard.copy(code)
                        copied = true
                    } label: {
                        Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                    }
                    .buttonStyle(HOButtonStyle(.secondary, size: .small))
                    if let onRevoke {
                        Button("Revoke", role: .destructive, action: onRevoke)
                            .buttonStyle(HOButtonStyle(.quiet, size: .small))
                    }
                }
                .padding(.top, HOSpace.xs)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(HOSpace.l)
        .hoCard()
        .task(id: copied) {
            guard copied else { return }
            try? await Task.sleep(for: .seconds(2))
            copied = false
        }
    }
}

/// "Joins as Member", "Expires ...", "Used 2 times, 8 uses left".
struct InviteMeta: View {
    let invite: OrgInvite
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Joins as \(invite.role.title)")
            if let date = invite.expiryDate {
                Text("\(invite.isExpired() ? "Expired" : "Expires") \(date.formatted(date: .abbreviated, time: .shortened))")
            }
            if invite.isCode {
                Text(usesLine)
            }
        }
        .font(theme.fonts.callout)
        .foregroundStyle(theme.colors.ink2)
    }

    private var usesLine: String {
        let used = invite.uses ?? 0
        let usedText = used == 0 ? "Not used yet" : (used == 1 ? "Used once" : "Used \(used) times")
        guard let left = invite.usesLeft else { return "\(usedText), no limit" }
        return "\(usedText), \(left == 1 ? "1 use" : "\(left) uses") left"
    }
}

enum Clipboard {
    @MainActor static func copy(_ text: String) {
        #if os(iOS)
        UIPasteboard.general.string = text
        #else
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        #endif
    }
}
