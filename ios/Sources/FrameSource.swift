// UNTESTED: written on Windows, never compiled.

import Foundation
import UIKit

/// A camera that produces JPEG frames at about 1 fps.
///
/// Threading: call `start()` and `stop()` on the main thread. `onFrame` may be called on any
/// queue; the consumer hops to the main actor itself. Set `onFrame` before calling `start()`.
protocol FrameSource: AnyObject {
    var onFrame: ((Data) -> Void)? { get set }
    func start()
    func stop()
}

// MARK: - JPEG helper

enum JPEGEncoder {
    static let defaultMaxLongSide: CGFloat = 960
    static let defaultQuality: CGFloat = 0.6

    /// Downscales so the long side is at most `maxLongSide` pixels, then JPEG-encodes.
    /// Safe to call off the main thread (UIGraphicsImageRenderer is thread safe).
    static func encode(_ image: UIImage,
                       maxLongSide: CGFloat = JPEGEncoder.defaultMaxLongSide,
                       quality: CGFloat = JPEGEncoder.defaultQuality) -> Data? {
        let pixelWidth = image.size.width * image.scale
        let pixelHeight = image.size.height * image.scale
        let longSide = max(pixelWidth, pixelHeight)
        guard longSide > 0 else { return nil }

        if longSide <= maxLongSide {
            return image.jpegData(compressionQuality: quality)
        }

        let factor = maxLongSide / longSide
        let target = CGSize(width: max(1, (pixelWidth * factor).rounded()),
                            height: max(1, (pixelHeight * factor).rounded()))
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        let renderer = UIGraphicsImageRenderer(size: target, format: format)
        let scaled = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))
        }
        return scaled.jpegData(compressionQuality: quality)
    }
}

// MARK: - 1 fps throttle

/// Lets one frame through per `interval` seconds. Thread safe.
final class FrameThrottle {
    private let interval: TimeInterval
    private let lock = NSLock()
    private var last: TimeInterval?

    /// `slack` absorbs jitter so a 2 fps source does not drop to 0.67 fps.
    init(interval: TimeInterval = 1.0, slack: TimeInterval = 0.1) {
        self.interval = max(0, interval - slack)
    }

    func shouldEmit() -> Bool {
        let now = ProcessInfo.processInfo.systemUptime
        lock.lock()
        defer { lock.unlock() }
        if let last = last, now - last < interval {
            return false
        }
        last = now
        return true
    }

    func reset() {
        lock.lock()
        last = nil
        lock.unlock()
    }
}

/// A Bool shared between the main thread and capture/toolkit queues.
final class LockedFlag {
    private let lock = NSLock()
    private var storage: Bool

    init(_ initial: Bool = false) {
        storage = initial
    }

    var value: Bool {
        lock.lock()
        defer { lock.unlock() }
        return storage
    }

    func set(_ newValue: Bool) {
        lock.lock()
        storage = newValue
        lock.unlock()
    }
}

// MARK: - Glasses stub for builds without the Meta toolkit

// Exactly one GlassesCameraSource exists: the real one in GlassesCameraSource.swift is compiled
// under the opposite condition. This stub is used when the package is removed, or when
// HANDOVER_NO_GLASSES is set (see README). It falls back to the phone camera immediately.
#if HANDOVER_NO_GLASSES || !canImport(MWDATCore) || !canImport(MWDATCamera)
final class GlassesCameraSource: FrameSource {
    static let isAvailable = false

    var onFrame: ((Data) -> Void)?
    /// Called on the main thread.
    var onFallback: ((String) -> Void)?
    /// Called on the main thread.
    var onStatus: ((String) -> Void)?

    @MainActor
    static func configureToolkit() {}

    @MainActor
    static func handleOpenURL(_ url: URL) {}

    func start() {
        let handler = onFallback
        DispatchQueue.main.async {
            handler?("glasses support is not in this build")
        }
    }

    func stop() {}
}
#endif
