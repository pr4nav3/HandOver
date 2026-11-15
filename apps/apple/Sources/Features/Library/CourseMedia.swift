import CoreGraphics
import Foundation
import ImageIO
import SwiftUI

/// Where a course's pictures live on the hub.
enum CourseMedia {
    /// Cover candidates, best first: the chosen cover, the produced cover, then the first step's frame.
    static func coverCandidates(hub: HubURL, lessonId: String, coverURL: String?, rev: Int? = nil) -> [URL] {
        var out: [URL] = []
        if let coverURL, let url = resolve(hub: hub, lessonId: lessonId, path: coverURL, rev: rev),
           !coverURL.hasSuffix("/frames/01.jpg") {
            out.append(url)
        }
        out.append(hub.fileURL(lesson: lessonId, path: "produced/cover.jpg", rev: rev))
        out.append(hub.fileURL(lesson: lessonId, path: "frames/01.jpg", rev: rev))
        return out
    }

    /// A step's reference frame.
    static func frame(hub: HubURL, lessonId: String, step: Step, rev: Int? = nil) -> URL {
        hub.fileURL(lesson: lessonId, path: step.refFrame, rev: rev)
    }

    /// A `/lessons/<id>/<file>` path from the hub, or a path relative to the lesson folder, as a URL.
    static func resolve(hub: HubURL, lessonId: String, path: String, rev: Int? = nil) -> URL? {
        let prefix = "/lessons/\(lessonId)/"
        if path.hasPrefix(prefix) {
            return hub.fileURL(lesson: lessonId, path: String(path.dropFirst(prefix.count)), rev: rev)
        }
        if path.hasPrefix("/") {
            return URL(string: path, relativeTo: hub.base)?.absoluteURL
        }
        return hub.fileURL(lesson: lessonId, path: path, rev: rev)
    }
}

/// Decoded pictures from the hub, kept in memory and shared by every screen. Previews and snapshot tests put
/// real frames in with `store(_:for:)` so they render without a network.
@MainActor
final class HubImageCache {
    static let shared = HubImageCache()

    private var images: [URL: CGImage] = [:]
    private var missing: Set<URL> = []
    private var order: [URL] = []
    private let limit = 300

    func image(for url: URL) -> CGImage? { images[url] }
    func isMissing(_ url: URL) -> Bool { missing.contains(url) }

    func store(_ image: CGImage, for url: URL) {
        if images[url] == nil { order.append(url) }
        images[url] = image
        missing.remove(url)
        while order.count > limit { images[order.removeFirst()] = nil }
    }

    func markMissing(_ url: URL) { missing.insert(url) }

    /// Forget everything (pull to refresh, a recut that changed the frames).
    func clear() {
        images = [:]
        missing = []
        order = []
    }

    /// Loads a picture, downscaled to at most `maxPixels` on its long side.
    func load(_ url: URL, maxPixels: Int = 1200) async -> CGImage? {
        if let hit = images[url] { return hit }
        if missing.contains(url) { return nil }
        let request = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 15)
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse else { return nil }
        guard http.statusCode == 200 else {
            if http.statusCode == 404 { markMissing(url) }
            return nil
        }
        guard let image = await Task.detached(priority: .utility, operation: { Self.decode(data, maxPixels: maxPixels) }).value
        else { return nil }
        store(image, for: url)
        return image
    }

    nonisolated static func decode(_ data: Data, maxPixels: Int) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixels,
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }

    /// Reads a local image file (previews and tests).
    nonisolated static func decode(file: URL, maxPixels: Int = 1200) -> CGImage? {
        guard let data = try? Data(contentsOf: file) else { return nil }
        return decode(data, maxPixels: maxPixels)
    }
}

/// A picture from the hub on the `stage` color, trying each candidate URL in order. While loading, and when
/// nothing loads, it shows the stage with a quiet symbol, never a fake picture.
struct HubImage: View {
    var candidates: [URL]
    var symbol: String = "photo"
    var contentMode: ContentMode = .fill
    @Environment(\.theme) private var theme
    @State private var image: CGImage?

    init(_ candidates: [URL], symbol: String = "photo", contentMode: ContentMode = .fill) {
        self.candidates = candidates
        self.symbol = symbol
        self.contentMode = contentMode
        // Cached pictures show on the first frame (and in ImageRenderer snapshots).
        _image = State(initialValue: candidates.lazy.compactMap { HubImageCache.shared.image(for: $0) }.first)
    }

    init(_ url: URL?, symbol: String = "photo", contentMode: ContentMode = .fill) {
        self.init(url.map { [$0] } ?? [], symbol: symbol, contentMode: contentMode)
    }

    var body: some View {
        Rectangle()
            .fill(theme.colors.stage)
            .overlay {
                if let image {
                    Image(decorative: image, scale: 1)
                        .resizable()
                        .aspectRatio(contentMode: contentMode)
                        .transition(.opacity)
                } else {
                    Image(systemName: symbol)
                        .font(.title3)
                        .foregroundStyle(.white.opacity(0.35))
                        .accessibilityHidden(true)
                }
            }
            .clipped()
            .task(id: candidates) {
                if image != nil { return }
                for url in candidates {
                    if let loaded = await HubImageCache.shared.load(url) {
                        withAnimation(.easeOut(duration: 0.15)) { image = loaded }
                        return
                    }
                    if Task.isCancelled { return }
                }
            }
    }
}
