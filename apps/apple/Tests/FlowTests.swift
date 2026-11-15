import CoreGraphics
import Foundation
import SwiftUI
import Testing
@testable import HandOver

/// The first-run flow: the camera choice, starting and ending a lesson, the viewer socket's `frames` setting,
/// and the camera streamer dropping frames while the socket is busy.
@MainActor
struct LearnFlowTests {
    static func defaults() -> UserDefaults {
        let name = "handover.tests.flow.\(UUID().uuidString)"
        return UserDefaults(suiteName: name) ?? .standard
    }

    @Test func firstStartAsksForACameraThenStarts() {
        let model = AppModel.preview()
        let flow = LearnFlow(defaults: Self.defaults())
        #expect(!flow.hasChosenCamera)
        flow.requestStart("fortune", at: 2, model: model)
        #expect(flow.showCameraSheet)
        #expect(flow.pending == LearnFlow.PendingStart(lessonId: "fortune", step: 2))
        #expect(!flow.isRunning)
        flow.confirm(.otherDevice, model: model)
        #expect(!flow.showCameraSheet)
        #expect(flow.isRunning)
        #expect(flow.section == .learn)
        #expect(flow.camera == .otherDevice)
    }

    @Test func laterStartsUseTheSavedCamera() {
        let defaults = Self.defaults()
        let model = AppModel.preview()
        LearnFlow(defaults: defaults).choose(.thisDevice)
        let flow = LearnFlow(defaults: defaults)
        #expect(flow.hasChosenCamera && flow.camera == .thisDevice)
        flow.requestStart("fortune", model: model)
        #expect(!flow.showCameraSheet)
        #expect(flow.isRunning && flow.section == .learn)
    }

    @Test func endGoesHomeAndStopsFollowing() {
        let flow = LearnFlow(defaults: Self.defaults())
        flow.showRunning("fortune")
        flow.end()
        #expect(!flow.isRunning)
        #expect(flow.runningLessonId == nil)
        #expect(flow.section == .library)
    }

    /// A late `lesson_id: null` from our own End can land after Start on a new lesson; it must not end it. Once
    /// the hub answers with the new lesson, or the wait runs out, a null ends Learn again.
    @Test func lateNullAfterStartDoesNotEndTheNewLesson() {
        let model = AppModel.preview()
        let flow = LearnFlow(defaults: Self.defaults())
        flow.choose(.thisDevice)
        let t0 = Date(timeIntervalSince1970: 1_000)
        flow.start("bike", model: model, now: t0)
        #expect(!flow.hubLessonChanged(to: nil, now: t0.addingTimeInterval(0.3)), "late null while select waits")
        #expect(flow.isRunning)
        #expect(!flow.hubLessonChanged(to: "bike", now: t0.addingTimeInterval(0.5)))
        #expect(flow.pendingSelect == nil)
        #expect(flow.hubLessonChanged(to: nil, now: t0.addingTimeInterval(9)), "a real unload ends Learn")

        // No answer at all: after the window, a null counts again.
        flow.start("wheel", model: model, now: t0)
        #expect(flow.hubLessonChanged(to: nil, now: t0.addingTimeInterval(LearnFlow.selectAnswerWindow + 1)))
        flow.end()
        #expect(flow.pendingSelect == nil)
        #expect(!flow.hubLessonChanged(to: nil), "nothing running, nothing to end")
    }

    @Test func changeCameraOnlyNeverStartsALesson() {
        let model = AppModel.preview()
        let flow = LearnFlow(defaults: Self.defaults())
        flow.changeCamera()
        #expect(flow.showCameraSheet && flow.pending == nil)
        flow.confirm(.thisDevice, model: model)
        #expect(!flow.isRunning)
        flow.requestStart("fortune", model: model)
        flow.cancelSheet()
        #expect(flow.pending == nil && !flow.showCameraSheet)
    }

    @Test func pairingQRCodeOpensAndConsumesTheRequestedCamera() {
        let flow = LearnFlow(defaults: Self.defaults())
        flow.openCamera(.glasses)
        #expect(flow.section == .camera)
        #expect(flow.cameraLaunchIntent == .glasses)
        flow.consumeCameraLaunch(.phone)
        #expect(flow.cameraLaunchIntent == .glasses)
        flow.consumeCameraLaunch(.glasses)
        #expect(flow.cameraLaunchIntent == nil)
    }

    @Test func reconnectsOnlyWhenTheFramesSettingFlips() {
        let flow = LearnFlow(defaults: Self.defaults())
        var reconnects = 0
        flow.onFramesPreferenceChange = { reconnects += 1 }
        flow.choose(.otherDevice)   // frames on before any choice, still on
        #expect(reconnects == 0)
        flow.choose(.thisDevice)
        #expect(reconnects == 1)
        flow.choose(.glasses)
        #expect(reconnects == 1)
        flow.choose(.otherDevice)
        #expect(reconnects == 2)
    }

    @Test func viewerSocketAsksForNoFramesWhenThisDeviceIsTheCamera() throws {
        let defaults = Self.defaults()
        let ui = try #require(URL(string: "ws://192.168.1.20:8000/ws/ui"))
        let camera = try #require(URL(string: "ws://192.168.1.20:8000/ws/camera"))
        #expect(LiveFrames.adjust(ui, defaults: defaults) == ui, "frames on before any choice")
        defaults.set(LearnCamera.thisDevice.rawValue, forKey: LearnCamera.key)
        #expect(LiveFrames.adjust(ui, defaults: defaults).absoluteString == "ws://192.168.1.20:8000/ws/ui?frames=0")
        #expect(LiveFrames.adjust(camera, defaults: defaults) == camera)
        defaults.set(LearnCamera.otherDevice.rawValue, forKey: LearnCamera.key)
        #expect(LiveFrames.adjust(ui, defaults: defaults) == ui)
    }

    @Test func captureLinkUsesTheHubsHTTPSPort() throws {
        let hub = try #require(HubURL(parsing: "192.168.1.20:8000"))
        #expect(CaptureLink.url(hub: hub).absoluteString == "https://192.168.1.20:8443/capture")
        #expect(OtherDeviceKind.phone.link(hub: hub) == hub.cameraLink(.phone))
    }

    @Test func metaCallbackLinksGoToTheGlasses() throws {
        let meta = try #require(URL(string: "handover://?metaWearablesAction=register&status=ok"))
        let connect = try #require(URL(string: "handover://connect?hub=http%3A%2F%2F192.168.1.20%3A8000"))
        #expect(GlassesLink.isMetaCallback(meta))
        #expect(!GlassesLink.isMetaCallback(connect))
    }

    @Test func everyStatusThatNeedsAnActionSaysWhatToDo() {
        #expect(LearnView.nextHint(.watching)?.contains("moves on") == true)
        #expect(LearnView.nextHint(.manual)?.contains("tap Next") == true)
        #expect(LearnView.nextHint(.noCamera)?.contains("tap Next") == true)
        #expect(LearnView.nextHint(.done) == nil)
    }

    @Test func homeAndCameraTabNames() {
        #expect(AppSection.library.title == "Home")
        #expect(AppSection.camera.title == "Be the Camera")
    }
}

/// A sink that is busy until told otherwise and remembers what it accepted.
private actor BusySink: FrameSink {
    var busy = true
    private(set) var accepted = 0
    private(set) var attempts = 0

    /// Readiness checks, each one before a frame would be encoded.
    private(set) var checks = 0
    /// When true, isReady says yes but the send still fails (the socket closed in between).
    var failSends = false

    func setBusy(_ value: Bool) { busy = value }
    func setFailSends(_ value: Bool) { failSends = value }

    func isReady() async -> Bool {
        checks += 1
        return !busy
    }

    func trySend(_ jpeg: Data) async -> Bool {
        if failSends {
            attempts += 1
            return false
        }
        attempts += 1
        guard !busy else { return false }
        accepted += 1
        return true
    }
}

private actor Tally {
    private(set) var sent: [CGSize] = []
    private(set) var dropped = 0
    func send(_ size: CGSize) { sent.append(size) }
    func drop() { dropped += 1 }
}

struct FrameDropTests {
    static func frame(width: Int, height: Int) -> CameraFrameImage? {
        SyntheticFrames.noise(width: width, height: height).map(CameraFrameImage.init)
    }

    /// While the socket is busy a frame is dropped, not queued: after it frees up, only the next new frame goes
    /// out, never the dropped one.
    @Test func dropsFramesWhileTheSocketIsBusy() async throws {
        let sink = BusySink()
        let tally = Tally()
        let slot = LatestFrameSlot<CameraFrameImage>()
        let loop = Task.detached {
            await CameraStreamer.sendLoop(sink: sink, slot: slot, didSend: { await tally.send($0) },
                                          didDrop: { await tally.drop() }, minGap: { .zero })
        }
        slot.put(try #require(Self.frame(width: 320, height: 240)))
        try await waitUntil { await tally.dropped == 1 }
        #expect(await sink.attempts == 0, "a frame is not encoded or sent while the socket is busy")
        #expect(await sink.accepted == 0)

        await sink.setBusy(false)
        try? await Task.sleep(for: .milliseconds(150))
        #expect(await sink.attempts == 0, "the dropped frame is never retried")

        slot.put(try #require(Self.frame(width: 640, height: 360)))
        try await waitUntil { await sink.accepted == 1 }
        #expect(await tally.sent == [CGSize(width: 640, height: 360)])
        slot.close()
        await loop.value
    }

    /// While the socket is not open (a reconnect), frames from a fast camera are dropped before encoding, and the
    /// loop waits a frame interval after each drop instead of spinning through every frame.
    @Test func waitsAfterADropInsteadOfSpinning() async throws {
        let sink = BusySink()
        let tally = Tally()
        let slot = LatestFrameSlot<CameraFrameImage>()
        let frame = try #require(Self.frame(width: 320, height: 240))
        let loop = Task.detached {
            await CameraStreamer.sendLoop(sink: sink, slot: slot, didSend: { await tally.send($0) },
                                          didDrop: { await tally.drop() }, retryDelay: .milliseconds(66),
                                          minGap: { .zero })
        }
        // A camera putting a frame every 5 ms for 330 ms: about 66 frames.
        let feeder = Task.detached {
            for _ in 0..<66 {
                slot.put(frame)
                try? await Task.sleep(for: .milliseconds(5))
            }
        }
        await feeder.value
        let checks = await sink.checks
        #expect(checks >= 2 && checks <= 12, "\(checks) readiness checks in 330 ms; one per 66 ms expected")
        #expect(await sink.attempts == 0)

        // Ready but the send fails: the loop also waits before the next try.
        await sink.setBusy(false)
        await sink.setFailSends(true)
        let before = await sink.attempts
        let feeder2 = Task.detached {
            for _ in 0..<66 {
                slot.put(frame)
                try? await Task.sleep(for: .milliseconds(5))
            }
        }
        await feeder2.value
        let failed = await sink.attempts - before
        #expect(failed >= 1 && failed <= 12, "\(failed) failed sends in 330 ms; one per 66 ms expected")
        slot.close()
        await loop.value
    }

    /// Frames larger than the send size are scaled to 640 on the long side before they go out (glasses frames).
    @Test func scalesLargeFramesToTheSendSize() async throws {
        let sink = BusySink()
        await sink.setBusy(false)
        let tally = Tally()
        let slot = LatestFrameSlot<CameraFrameImage>()
        let loop = Task.detached {
            await CameraStreamer.sendLoop(sink: sink, slot: slot, didSend: { await tally.send($0) }, minGap: { .zero })
        }
        slot.put(try #require(Self.frame(width: 1920, height: 1080)))
        try await waitUntil { await sink.accepted == 1 }
        #expect(await tally.sent == [CGSize(width: 640, height: 360)])
        slot.close()
        await loop.value
    }

    private func waitUntil(_ condition: @Sendable () async -> Bool) async throws {
        for _ in 0..<200 {
            if await condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        Issue.record("timed out")
    }
}
