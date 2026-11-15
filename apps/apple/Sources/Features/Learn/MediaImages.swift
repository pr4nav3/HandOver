import CoreGraphics
import Foundation
import ImageIO
import Observation

/// Lesson stills (frames/NN.jpg) for step thumbnails and the clip poster, fetched once per URL, downsampled,
/// and kept for the session. URLs carry `?v=<rev>`, so a recut lesson fetches fresh ones.
@MainActor
@Observable
final class MediaImages {
    static let shared = MediaImages()

    private(set) var images: [URL: CGImage] = [:]
    @ObservationIgnored private var loading: Set<URL> = []
    @ObservationIgnored private let limit = 48
    @ObservationIgnored private let maxPixels: Int

    init(maxPixels: Int = 1280) { self.maxPixels = maxPixels }

    /// The image if it is here; otherwise starts loading it and returns nil (the view redraws when it lands).
    func image(_ url: URL?) -> CGImage? {
        guard let url else { return nil }
        if let hit = images[url] { return hit }
        load(url)
        return nil
    }

    /// Puts an image in the cache (previews and snapshot tests).
    func store(_ image: CGImage, for url: URL) {
        if images.count >= limit { images.removeAll() }
        images[url] = image
    }

    private func load(_ url: URL) {
        guard !loading.contains(url) else { return }
        loading.insert(url)
        let maxPixels = self.maxPixels
        Task { [weak self] in
            defer { self?.loading.remove(url) }
            guard let (data, response) = try? await URLSession.shared.data(from: url),
                  (response as? HTTPURLResponse)?.statusCode ?? 200 < 400,
                  let image = Self.decode(data, maxPixels: maxPixels) else { return }
            self?.store(image, for: url)
        }
    }

    nonisolated static func decode(_ data: Data, maxPixels: Int) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixels,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceShouldCacheImmediately: true,
        ]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }
}
