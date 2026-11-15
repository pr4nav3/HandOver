import CoreGraphics
import Foundation
import ImageIO
import Observation

/// The newest live frame from the hub's active camera, decoded.
struct LiveFrame {
    let image: CGImage
    let receivedAt: Date
    var size: CGSize { CGSize(width: image.width, height: image.height) }
}

/// The hub's live frames, kept apart from `AppModel` so a frame (up to 15 a second) redraws only the view that
/// draws it, never the whole Learn screen. Screens read `hasFrame`, `hasLast` and `aspect`, which change only when
/// the picture appears, goes or changes shape; only `LiveFrameView` reads `frame` and `last`. Frames from the
/// socket are decoded off the main thread; when they arrive faster than they decode, only the newest is decoded.
@MainActor
@Observable
final class LiveFeed {
    /// The newest frame, or nil when the camera is not sending.
    private(set) var frame: LiveFrame?
    /// The last picture shown, kept after the camera drops so "Camera lost" can show it dimmed.
    private(set) var last: CGImage?
    /// A frame is on screen. Changes only when that flips.
    private(set) var hasFrame = false
    /// A last picture is kept. Changes only when that flips.
    private(set) var hasLast = false
    /// Width over height of the newest frame. Changes only when the shape changes.
    private(set) var aspect: CGFloat?

    @ObservationIgnored private var pending: Data?
    @ObservationIgnored private var isDecoding = false
    /// Bumped by `clear`, so a frame that was decoding when the camera dropped is not shown after it.
    @ObservationIgnored private var generation = 0

    /// A JPEG from the socket. Decoded on a background thread, then shown.
    func receive(jpeg: Data) {
        pending = jpeg
        guard !isDecoding else { return }
        isDecoding = true
        Task { await drain() }
    }

    /// Shows a decoded frame now (previews, tests and `AppModel.ingest`).
    func show(_ image: CGImage, at date: Date = Date()) {
        frame = LiveFrame(image: image, receivedAt: date)
        last = image
        if !hasFrame { hasFrame = true }
        if !hasLast { hasLast = true }
        let shape = image.height > 0 ? CGFloat(image.width) / CGFloat(image.height) : nil
        if aspect != shape { aspect = shape }
    }

    /// The camera stopped sending: no current frame. The last picture stays for "Camera lost".
    func clear() {
        generation += 1
        pending = nil
        frame = nil
        if hasFrame { hasFrame = false }
    }

    /// Forgets the last picture too (another lesson, another hub).
    func reset() {
        clear()
        last = nil
        if hasLast { hasLast = false }
        if aspect != nil { aspect = nil }
    }

    private func drain() async {
        while let data = pending {
            pending = nil
            let started = generation
            let decoded = await Task.detached(priority: .userInitiated) { Self.decode(jpeg: data).map(Decoded.init) }.value
            if started == generation, let decoded { show(decoded.image) }
        }
        isDecoding = false
    }

    nonisolated static func decode(jpeg: Data) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(jpeg as CFData, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(source, 0, [kCGImageSourceShouldCacheImmediately: true] as CFDictionary)
    }

    /// A decoded picture crossing back from the decode thread. CGImage is immutable, so this is safe.
    private struct Decoded: @unchecked Sendable {
        let image: CGImage
    }
}
