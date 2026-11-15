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
        #expect(OtherDeviceKind.phone.link(hub: hub) == hub.link)
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

    func setBusy(_ value: Bool) { busy = value }

    func trySend(_ jpeg: Data) async -> Bool {
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
        try await waitUntil { await sink.attempts == 1 }
        #expect(await tally.dropped == 1)
        #expect(await sink.accepted == 0)

        await sink.setBusy(false)
        try? await Task.sleep(for: .milliseconds(100))
        #expect(await sink.attempts == 1, "the dropped frame is never retried")

        slot.put(try #require(Self.frame(width: 640, height: 360)))
        try await waitUntil { await sink.accepted == 1 }
        #expect(await tally.sent == [CGSize(width: 640, height: 360)])
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
