import CoreGraphics
import Foundation
import ImageIO
import Observation
import Testing
import UniformTypeIdentifiers
@testable import HandOver

/// What keeps rotation instant: live frames redraw only their own view, layouts reuse the camera preview and the
/// player layer instead of rebuilding them, and the layout picks stay stable.
@MainActor
struct RotationTests {
    /// A solid JPEG of the given size.
    static func jpeg(width: Int, height: Int) throws -> Data {
        let context = try #require(CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: 0,
                                             space: CGColorSpaceCreateDeviceRGB(),
                                             bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue))
        context.setFillColor(CGColor(red: 0.2, green: 0.4, blue: 0.6, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let image = try #require(context.makeImage())
        let data = NSMutableData()
        let dest = try #require(CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(dest, image, nil)
        #expect(CGImageDestinationFinalize(dest))
        return data as Data
    }

    static func image(width: Int, height: Int) throws -> CGImage {
        let data = try jpeg(width: width, height: height)
        return try #require(LiveFeed.decode(jpeg: data))
    }

    /// True when reading `read` registers a dependency that `change` then fires.
    static func fires(_ read: () -> Void, when change: () -> Void) -> Bool {
        let fired = Flag()
        withObservationTracking(read) { fired.set() }
        change()
        return fired.value
    }

    final class Flag: @unchecked Sendable {
        private let lock = NSLock()
        private var raw = false
        var value: Bool { lock.withLock { raw } }
        func set() { lock.withLock { raw = true } }
    }

    // MARK: - Live frames

    @Test func framesDoNotTouchTheScreenModel() throws {
        let model = AppModel.preview()
        let jpeg = try Self.jpeg(width: 64, height: 36)
        model.ingest(.frame(jpeg))
        // What the Learn screen reads from the model. A frame must not invalidate any of it.
        let screen = {
            _ = model.state
            _ = model.session
            _ = model.lesson
            _ = model.mistake
            _ = model.connection
            _ = model.hub
        }
        #expect(!Self.fires(screen) { model.ingest(.frame(jpeg)) })
        #expect(!Self.fires(screen) { model.live.show(try! Self.image(width: 64, height: 36)) })
        #expect(model.live.frame?.size == CGSize(width: 64, height: 36))
    }

    @Test func screenFlagsChangeOnlyWhenThePictureDoes() throws {
        let feed = LiveFeed()
        let flags = {
            _ = feed.hasFrame
            _ = feed.hasLast
            _ = feed.aspect
        }
        let wide = try Self.image(width: 64, height: 36)
        #expect(Self.fires(flags) { feed.show(wide) }, "the first frame appears")
        #expect(!Self.fires(flags) { feed.show(wide) }, "another frame of the same shape")
        #expect(!Self.fires(flags) { feed.show(try! Self.image(width: 128, height: 72)) }, "same shape, larger")
        #expect(Self.fires(flags) { feed.show(try! Self.image(width: 36, height: 64)) }, "the camera turned")
        #expect(Self.near(feed.aspect, 36.0 / 64.0))
        // The frame view does follow every frame.
        #expect(Self.fires({ _ = feed.frame }) { feed.show(wide) })
    }

    @Test func clearKeepsTheLastPictureAndResetForgetsIt() throws {
        let feed = LiveFeed()
        feed.show(try Self.image(width: 64, height: 36))
        feed.clear()
        #expect(feed.frame == nil)
        #expect(!feed.hasFrame)
        #expect(feed.hasLast && feed.last != nil, "Camera lost shows the last picture dimmed")
        feed.reset()
        #expect(!feed.hasLast && feed.last == nil && feed.aspect == nil)
    }

    @Test func socketFramesDecodeOffTheMainThreadAndStopAfterClear() async throws {
        let feed = LiveFeed()
        feed.receive(jpeg: try Self.jpeg(width: 64, height: 36))
        for _ in 0..<200 where feed.frame == nil { try await Task.sleep(for: .milliseconds(10)) }
        #expect(feed.frame?.size == CGSize(width: 64, height: 36))

        feed.reset()
        feed.receive(jpeg: try Self.jpeg(width: 32, height: 32))
        feed.clear()
        try await Task.sleep(for: .milliseconds(300))
        #expect(feed.frame == nil, "a frame decoding when the camera dropped is not shown after it")
    }

    static func near(_ a: CGFloat?, _ b: CGFloat) -> Bool { a.map { abs($0 - b) < 1e-9 } ?? false }

    // MARK: - Reused surfaces

    @Test func aNewLayoutTakesTheSurfaceAndTheOldOneNeverTakesItBack() {
        let surface = PlatformView()
        let upright = SurfaceHost(), sideways = SurfaceHost()
        upright.adopt(surface)
        #expect(surface.superview === upright)
        sideways.adopt(surface)
        #expect(surface.superview === sideways, "the new layout shows the same view")
        upright.adopt(surface)
        #expect(surface.superview === sideways, "an update to the old layout on its way out changes nothing")
        #expect(sideways.isShowing && !upright.isShowing)

        let next = PlatformView()
        sideways.adopt(next)
        #expect(next.superview === sideways)
        #expect(surface.superview == nil, "a replaced surface leaves its container")
    }

    @Test func aCaptureHasOnePreviewJoinedToItsSession() {
        let capture = CameraCapture()
        let first = capture.previewView()
        #expect(first === capture.previewView())
        #expect(first.preview.session === capture.session)
    }

    @Test func glassesFramesReachTheSenderWithoutObservation() throws {
        let glasses = GlassesController(state: .unavailable)
        let got = Flag()
        glasses.onFrame = { _ in got.set() }
        glasses.set(frame: nil)
        #expect(!got.value, "no frame, nothing to send")
        glasses.set(frame: try Self.image(width: 8, height: 8))
        #expect(got.value)
    }

    // MARK: - Layout picks

    @Test func liveAspectFromTheFeedMatchesTheFrameSize() {
        for size in [CGSize(width: 960, height: 540), CGSize(width: 540, height: 960), nil, .zero] {
            for own in [false, true] {
                let aspect = size.flatMap { $0.height > 0 ? $0.width / $0.height : nil }
                #expect(LearnLayout.liveAspect(frame: size, ownCamera: own, landscape: true)
                        == LearnLayout.liveAspect(frameAspect: aspect, ownCamera: own, landscape: true))
            }
        }
    }

    @Test func eachPhoneOrientationHasOneLayout() {
        // The same size always gives the same layout, so nothing flips back and forth while the phone turns.
        let portrait = CGSize(width: 402, height: 778), landscape = CGSize(width: 750, height: 381)
        #expect(LearnLayout.pickTouch(size: portrait, compactHeight: false) == .pip)
        #expect(LearnLayout.pickTouch(size: landscape, compactHeight: true) == .sideBySide(phone: true))
        #expect(LearnLayout.pickTouch(size: landscape, compactHeight: false) == .sideBySide(phone: true),
                "before the size class catches up, the size alone gives the same layout")
        #expect(!HOLayout.isPhone, "the Mac is never treated as a phone")
    }
}
