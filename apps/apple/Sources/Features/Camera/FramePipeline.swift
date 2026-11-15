import CoreGraphics
import CoreImage
import CoreVideo
import Foundation
import Metal
import Synchronization

/// Frame sizes and pace for the camera socket. By default 640 px on the long side at JPEG quality 0.5, about 15
/// frames a second, so the learner's feed on the big screen moves smoothly. The hub samples frames for its checks on
/// its own, so a faster feed does not mean more checks. The user default `handover.camera.sharpFrames` sends the
/// older 960 px frames at quality 0.6 instead. Never upscaled, even dimensions.
enum FrameSizing {
    static let sharpKey = "handover.camera.sharpFrames"
    static let smoothLongSide: CGFloat = 640
    static let sharpLongSide: CGFloat = 960
    /// About 15 frames a second. The socket and the hub may enforce a longer gap; frames that arrive too soon are
    /// dropped, never queued.
    static let sendGap: Duration = .milliseconds(66)

    static var isSharp: Bool { UserDefaults.standard.bool(forKey: sharpKey) }
    static var longSide: CGFloat { isSharp ? sharpLongSide : smoothLongSide }
    static var jpegQuality: CGFloat { isSharp ? 0.6 : 0.5 }

    /// The size a `source` frame is sent at.
    static func target(for source: CGSize, longSide: CGFloat = FrameSizing.longSide) -> CGSize {
        guard source.width > 0, source.height > 0 else { return .zero }
        let scale = min(1, longSide / max(source.width, source.height))
        func even(_ v: CGFloat) -> CGFloat { max(2, (v * scale / 2).rounded() * 2) }
        return CGSize(width: even(source.width), height: even(source.height))
    }

    /// The scale factor from `source` to `target(for:)`.
    static func scale(for source: CGSize, longSide: CGFloat = FrameSizing.longSide) -> CGFloat {
        guard source.width > 0, source.height > 0 else { return 1 }
        return min(1, longSide / max(source.width, source.height))
    }
}

/// Keeps the camera useful when iOS raises its thermal state. The old emergency path fell all the way to one
/// frame every two seconds. That made a finished physical step take several seconds just to reach the hub (and
/// the motion gate needs more than one frame to know the hands have stopped). These bounded rates shed most of
/// the encoding/upload work while keeping enough fresh observations for completion detection.
enum ThermalFramePolicy {
    static let seriousGap: Duration = .milliseconds(250)  // 4 fps
    static let criticalGap: Duration = .milliseconds(500) // 2 fps

    static func sendGap(for state: ProcessInfo.ThermalState) -> Duration {
        switch state {
        case .serious: seriousGap
        case .critical: criticalGap
        case .nominal, .fair: FrameSizing.sendGap
        @unknown default: seriousGap
        }
    }
}

/// Downscales camera frames and encodes JPEGs on one shared Metal-backed `CIContext` (creating a context
/// per frame is the slow part, so there is exactly one).
final class FrameEncoder: Sendable {
    static let shared = FrameEncoder()

    let context: CIContext
    private let colorSpace = CGColorSpace(name: CGColorSpace.sRGB) ?? CGColorSpaceCreateDeviceRGB()

    init() {
        if let device = MTLCreateSystemDefaultDevice() {
            context = CIContext(mtlDevice: device, options: [.cacheIntermediates: false, .name: "HandOver frames"])
        } else {
            context = CIContext(options: [.cacheIntermediates: false])
        }
    }

    /// The frame scaled to the send size, as a CGImage (also what the floating preview shows).
    func downscale(_ buffer: CVPixelBuffer, longSide: CGFloat = FrameSizing.longSide) -> CGImage? {
        downscale(CIImage(cvPixelBuffer: buffer), longSide: longSide)
    }

    func downscale(_ image: CIImage, longSide: CGFloat = FrameSizing.longSide) -> CGImage? {
        let extent = image.extent
        let target = FrameSizing.target(for: extent.size, longSide: longSide)
        guard target.width > 0 else { return nil }
        let sx = target.width / extent.width, sy = target.height / extent.height
        let scaled = image.transformed(by: CGAffineTransform(translationX: -extent.minX, y: -extent.minY))
            .applyingFilter("CILanczosScaleTransform", parameters: [kCIInputScaleKey: sy, kCIInputAspectRatioKey: sx / sy])
        let rect = CGRect(origin: .zero, size: target)
        return context.createCGImage(scaled.cropped(to: rect), from: rect, format: .RGBA8, colorSpace: colorSpace)
    }

    /// A frame that is larger than the send size (glasses frames, for example), scaled down; smaller ones as is.
    func fitted(_ image: CGImage, longSide: CGFloat = FrameSizing.longSide) -> CGImage? {
        guard CGFloat(max(image.width, image.height)) > longSide else { return image }
        return downscale(CIImage(cgImage: image), longSide: longSide)
    }

    /// JPEG through the shared Metal-backed context, at quality 0.5 (0.6 for sharp frames). Call it off the main
    /// thread; the send loop does.
    func jpeg(_ image: CGImage, quality: CGFloat = FrameSizing.jpegQuality) -> Data? {
        let options = [CIImageRepresentationOption(rawValue: kCGImageDestinationLossyCompressionQuality as String): quality]
        return context.jpegRepresentation(of: CIImage(cgImage: image), colorSpace: colorSpace, options: options)
    }
}

/// One slot holding only the newest frame. The capture side puts; the sender takes the moment it is free.
/// Older frames are simply replaced, so the hub always sees the latest moment and nothing queues up.
final class LatestFrameSlot<Frame: Sendable>: Sendable {
    private struct State {
        var frame: Frame?
        var waiter: CheckedContinuation<Frame?, Never>?
        var closed = false
        var replaced = 0
    }

    private let state = Mutex(State())

    /// How many frames were dropped because a newer one arrived first.
    var replacedCount: Int { state.withLock { $0.replaced } }

    func put(_ frame: Frame) {
        let waiter = state.withLock { s -> CheckedContinuation<Frame?, Never>? in
            guard !s.closed else { return nil }
            if let w = s.waiter {
                s.waiter = nil
                return w
            }
            if s.frame != nil { s.replaced += 1 }
            s.frame = frame
            return nil
        }
        waiter?.resume(returning: frame)
    }

    /// The newest frame, waiting for one if the slot is empty. Nil once closed.
    func take() async -> Frame? {
        await withCheckedContinuation { c in
            let ready = state.withLock { s -> Frame?? in
                if s.closed { return .some(nil) }
                if let f = s.frame {
                    s.frame = nil
                    return .some(f)
                }
                s.waiter?.resume(returning: nil)
                s.waiter = c
                return .none
            }
            if let ready { c.resume(returning: ready) }
        }
    }

    /// The newest frame if there is one, without waiting.
    func poll() -> Frame? {
        state.withLock { s in
            defer { s.frame = nil }
            return s.frame
        }
    }

    func close() {
        let waiter = state.withLock { s -> CheckedContinuation<Frame?, Never>? in
            s.closed = true
            s.frame = nil
            defer { s.waiter = nil }
            return s.waiter
        }
        waiter?.resume(returning: nil)
    }
}

/// Frames actually sent in the last few seconds, as frames per second.
struct SendRate: Sendable {
    let window: TimeInterval
    private(set) var times: [TimeInterval] = []

    init(window: TimeInterval = 5) { self.window = window }

    mutating func record(_ t: TimeInterval) {
        times.append(t)
        trim(now: t)
    }

    mutating func trim(now: TimeInterval) {
        times.removeAll { now - $0 > window }
    }

    /// Frames in the last `window` seconds divided by the time covered: the whole window, or less when
    /// streaming started more recently (`since`), but never under one second.
    func fps(now: TimeInterval, since start: TimeInterval) -> Double {
        let count = times.filter { now - $0 <= window }.count
        return Double(count) / max(1, min(window, now - start))
    }
}

/// Where encoded frames go. `trySend` returns false when the frame was dropped because the sink is busy (the
/// previous frame is still going out), not connected, or the frame came too soon. Dropped frames are never retried.
protocol FrameSink: Sendable {
    /// True when a frame sent now would go out: connected, the previous frame finished, the gap passed. Checked
    /// before encoding, so no frame is encoded only to be thrown away (during a reconnect, for example).
    func isReady() async -> Bool
    func trySend(_ jpeg: Data) async -> Bool
}

extension CameraSocket: FrameSink {
    func isReady() async -> Bool { await canSendFrame }
    func trySend(_ jpeg: Data) async -> Bool { await send(frame: jpeg) }
}
