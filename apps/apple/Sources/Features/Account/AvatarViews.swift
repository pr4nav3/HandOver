import PhotosUI
import SwiftUI

/// A person's avatar: their photo (kept on this device only) or initials on their color.
struct AvatarView: View {
    var name: String
    var choice: AvatarChoice
    var size: CGFloat = 44

    var body: some View {
        ZStack {
            if let data = choice.photo, let image = PlatformImage.decode(data) {
                image.resizable().aspectRatio(contentMode: .fill)
            } else {
                choice.color
                Text(AvatarChoice.initials(name))
                    .font(.system(size: size * 0.42, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.5)
                    .contentTransition(.opacity)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().strokeBorder(Color.primary.opacity(0.08), lineWidth: HOLine.width))
        .accessibilityHidden(true)
    }
}

/// Someone else's avatar in lists: letters on `well` in `ink2` (DESIGN.md 3.24).
struct PersonAvatar: View {
    var name: String
    var size: CGFloat = 36
    @Environment(\.theme) private var theme

    var body: some View {
        Text(AvatarChoice.initials(name))
            .font(.system(size: size * 0.42, weight: .semibold, design: .rounded))
            .foregroundStyle(theme.colors.ink2)
            .frame(width: size, height: size)
            .background(theme.colors.well, in: Circle())
            .accessibilityHidden(true)
    }
}

enum PlatformImage {
    static func decode(_ data: Data) -> Image? {
        #if os(iOS)
        UIImage(data: data).map { Image(uiImage: $0) }
        #else
        NSImage(data: data).map { Image(nsImage: $0) }
        #endif
    }
}

/// The avatar picker (SCREENS.md 25.5): a 96 point preview, eight color swatches, and a photo from the system
/// picker (no library permission needed). The photo stays on this device.
struct AvatarEditor: View {
    var name: String
    @Environment(AccountStore.self) private var accounts
    @Environment(\.theme) private var theme
    @State private var item: PhotosPickerItem?

    var body: some View {
        VStack(spacing: HOSpace.xl) {
            AvatarView(name: name, choice: accounts.avatar, size: 96)
                .hoAnimation(HOMotion.snappy, value: accounts.avatar)
            HStack(spacing: 0) {
                ForEach(AvatarChoice.palette.indices, id: \.self) { i in
                    Button {
                        Haptics.tap()
                        accounts.setAvatarColor(i)
                    } label: {
                        Circle()
                            .fill(AvatarChoice.palette[i].color)
                            .frame(width: 28, height: 28)
                            .padding(3)
                            .overlay(Circle().strokeBorder(theme.colors.ink, lineWidth: accounts.avatar.colorIndex == i ? 2 : 0))
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AvatarChoice.palette[i].name)
                    .accessibilityAddTraits(accounts.avatar.colorIndex == i ? .isSelected : [])
                }
            }
            .opacity(accounts.avatar.photo == nil ? 1 : 0.4)
            HStack(spacing: HOSpace.s) {
                PhotosPicker(selection: $item, matching: .images, photoLibrary: .shared()) {
                    Label("Choose Photo", systemImage: "photo")
                }
                .buttonStyle(HOButtonStyle(.secondary))
                if accounts.avatar.photo != nil {
                    Button("Remove Photo") {
                        Haptics.tap()
                        accounts.setAvatarPhoto(nil)
                    }
                    .buttonStyle(HOButtonStyle(.quiet))
                }
            }
        }
        .onChange(of: item) { _, picked in
            guard let picked else { return }
            Task {
                if let data = try? await picked.loadTransferable(type: Data.self) {
                    accounts.setAvatarPhoto(data)
                    Haptics.tap()
                }
                item = nil
            }
        }
    }
}
