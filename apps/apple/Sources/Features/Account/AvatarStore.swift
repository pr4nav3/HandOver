import CryptoKit
import Foundation
import ImageIO
import SwiftUI
import UniformTypeIdentifiers

/// How a person's avatar looks: initials on one of eight colors, or a photo kept on this device only.
struct AvatarChoice: Equatable, Sendable {
    var colorIndex = 0
    /// A small JPEG, never uploaded.
    var photo: Data?

    /// The eight swatches (SCREENS.md 25.5). White initials read at 4.5:1 or better on each.
    static let palette: [(name: String, color: Color)] = [
        ("Blue", Color(red: 0.24, green: 0.37, blue: 0.85)),
        ("Teal", Color(red: 0.05, green: 0.45, blue: 0.47)),
        ("Violet", Color(red: 0.42, green: 0.30, blue: 0.75)),
        ("Berry", Color(red: 0.67, green: 0.18, blue: 0.42)),
        ("Olive", Color(red: 0.36, green: 0.40, blue: 0.13)),
        ("Slate", Color(red: 0.30, green: 0.35, blue: 0.42)),
        ("Rust", Color(red: 0.66, green: 0.27, blue: 0.13)),
        ("Green", Color(red: 0.13, green: 0.45, blue: 0.24)),
    ]

    var color: Color { Self.palette[((colorIndex % Self.palette.count) + Self.palette.count) % Self.palette.count].color }

    /// "Sam Rivera" to "SR", "sam" to "S", "" to "?".
    static func initials(_ name: String) -> String {
        let words = name.split(whereSeparator: { $0.isWhitespace || $0 == "-" || $0 == "_" }).filter { !$0.isEmpty }
        let letters = words.prefix(2).compactMap(\.first).map { String($0).uppercased() }
        return letters.isEmpty ? "?" : letters.joined()
    }
}

/// Saves avatar choices: the color in UserDefaults, the photo as a file in Application Support.
struct AvatarStore: @unchecked Sendable {
    let defaults: UserDefaults
    /// Where photos go; nil keeps them in memory only (previews).
    let folder: URL?

    init(defaults: UserDefaults = .standard, folder: URL? = AvatarStore.defaultFolder) {
        self.defaults = defaults
        self.folder = folder
    }

    static var defaultFolder: URL? {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first?
            .appending(path: "HandOver").appending(path: "Avatars")
    }

    func load(key: String?) -> AvatarChoice {
        let name = Self.fileName(key)
        var choice = AvatarChoice()
        choice.colorIndex = defaults.integer(forKey: "handover.avatar.color." + name)
        if let folder { choice.photo = try? Data(contentsOf: folder.appending(path: name + ".jpg")) }
        return choice
    }

    func save(_ choice: AvatarChoice, key: String?) {
        let name = Self.fileName(key)
        defaults.set(choice.colorIndex, forKey: "handover.avatar.color." + name)
        guard let folder else { return }
        let file = folder.appending(path: name + ".jpg")
        if let photo = choice.photo {
            try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try? photo.write(to: file, options: [.atomic, .completeFileProtection])
        } else {
            try? FileManager.default.removeItem(at: file)
        }
    }

    private static func fileName(_ key: String?) -> String {
        let digest = SHA256.hash(data: Data((key ?? "device").utf8))
        return digest.prefix(12).map { String(format: "%02x", $0) }.joined()
    }

    /// A square-ish JPEG no larger than 320 px on its long side, from any image data the picker gives.
    static func downscaled(_ data: Data) -> Data? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                        kCGImageSourceCreateThumbnailWithTransform: true,
                                        kCGImageSourceThumbnailMaxPixelSize: 320]
        guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: 0.8] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { return nil }
        return out as Data
    }
}
