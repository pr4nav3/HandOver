import Foundation
import Testing
@testable import HandOver

/// A camera that records nothing, with switches for each outcome.
@MainActor
private final class FakeCaptureEngine: RecordCaptureEngine {
    var access = RecordCaptureAccess(camera: true, microphone: true)
    var startError: (any Error)?
    var started: URL?
    var paused = 0
    var resumed = 0
    var level: Float? = 0.5
    var stopError: (any Error)?
    var sessions = 0

    func requestAccess() async -> RecordCaptureAccess { access }
    func start(camera: RecordCamera?, withAudio: Bool) async throws {
        if let startError { throw startError }
        sessions += 1
    }
    func stopSession() {}
    func startRecording(to url: URL) throws { started = url }
    func stopRecording() async throws -> URL {
        if let stopError { throw stopError }
        return started ?? URL(fileURLWithPath: "/tmp/none.mov")
    }
    var canPause: Bool { true }
    func pauseRecording() { paused += 1 }
    func resumeRecording() { resumed += 1 }
    func audioLevel() -> Float? { level }
    func cameras() -> [RecordCamera] { [RecordCamera(id: "b", name: "Back Camera", kind: .back)] }
}

/// A clock the test moves by hand.
@MainActor
private final class Clock {
    var now = Date(timeIntervalSince1970: 1_000)
    func advance(_ seconds: TimeInterval) { now = now.addingTimeInterval(seconds) }
}

@MainActor
struct RecordModelTests {
    private func make(_ engine: FakeCaptureEngine = FakeCaptureEngine()) -> (RecordModel, FakeCaptureEngine, Clock) {
        let clock = Clock()
        let model = RecordModel(engine: engine, now: { clock.now },
                                folder: FileManager.default.temporaryDirectory.appending(path: "handover-test-takes"))
        return (model, engine, clock)
    }

    @Test func recordPauseResumeStop() async {
        let (model, engine, clock) = make()
        await model.prepare()
        #expect(model.phase == .ready)
        await model.shutter()
        #expect(model.phase == .recording && model.startCount == 1)
        #expect(engine.started?.pathExtension == "mov")
        clock.advance(10)
        model.pause()
        #expect(model.phase == .paused && engine.paused == 1)
        clock.advance(30)
        #expect(model.elapsed() == 10, "paused time does not count")
        model.resume()
        clock.advance(5)
        #expect(model.elapsed() == 15)
        await model.shutter()
        #expect(model.phase == .review && model.stopCount == 1)
        #expect(model.takes.count == 1 && model.takes[0].duration == 15)
        model.model_keepAndRecordAgainCheck()
    }

    @Test func cameraRefusedAsksForSettings() async {
        let engine = FakeCaptureEngine()
        engine.access = RecordCaptureAccess(camera: false, microphone: true)
        let (model, _, _) = make(engine)
        await model.prepare()
        #expect(model.phase == .needsAccess(camera: true, microphone: false))
    }

    @Test func microphoneRefusedOffersRecordingWithoutSound() async {
        let engine = FakeCaptureEngine()
        engine.access = RecordCaptureAccess(camera: true, microphone: false)
        let (model, _, _) = make(engine)
        await model.prepare()
        #expect(model.phase == .needsAccess(camera: false, microphone: true))
        await model.continueWithoutSound()
        #expect(model.phase == .ready && !model.withAudio)
        await model.prepare()
        #expect(model.phase == .ready, "the choice sticks")
    }

    @Test func aBuildWithoutMicrophoneTextNeverAsks() async {
        let engine = FakeCaptureEngine()
        engine.access = RecordCaptureAccess(camera: true, microphone: false, microphoneDeclared: false)
        let (model, _, _) = make(engine)
        await model.prepare()
        #expect(model.phase == .ready && !model.withAudio && model.microphoneMissingFromBuild)
    }

    @Test func glassesBringNoMicrophone() async {
        let engine = FakeCaptureEngine()
        engine.access = RecordCaptureAccess(camera: true, microphone: false, usesMicrophone: false)
        let (model, _, _) = make(engine)
        await model.prepare()
        #expect(model.phase == .ready && !model.withAudio && !model.microphoneMissingFromBuild)
    }

    @Test func sessionErrorsShowTheirWords() async {
        let engine = FakeCaptureEngine()
        engine.startError = RecorderError.cannotAddCamera
        let (model, _, _) = make(engine)
        await model.prepare()
        #expect(model.phase == .failed("The camera is busy in another app. Close it, then try again."))
    }

    @Test func discardWhileRecording() async {
        let (model, _, _) = make()
        await model.prepare()
        model.startRecording()
        await model.discardRecording()
        #expect(model.phase == .ready && model.takes.isEmpty)
    }

    @Test func silenceIsNoticedAfterThreeSeconds() async {
        let (model, _, clock) = make()
        await model.prepare()
        model.startRecording()
        model.sample(0.5)
        clock.advance(2)
        model.sample(0.01)
        #expect(!model.isSilent)
        clock.advance(1.5)
        model.sample(0.01)
        #expect(model.isSilent)
        model.sample(0.4)
        #expect(!model.isSilent)
        #expect(model.levels.count == 24)
    }

    @Test func meterMath() {
        #expect(RecordModel.normalize(decibels: -160) == 0)
        #expect(RecordModel.normalize(decibels: 0) == 1)
        #expect(RecordModel.normalize(decibels: -25) == 0.5)
        #expect(RecordModel.normalize(decibels: .nan) == 0)
        #expect(RecordModel.smooth(previous: 0, next: 1) == 0.6, "rises fast")
        #expect(RecordModel.smooth(previous: 1, next: 0) == 0.75, "falls slowly")
        #expect(RecordModel.clock(42) == "00:42")
        #expect(RecordModel.clock(3729) == "1:02:09")
    }

    @Test func glassesFallBackOnlyOnFailures() {
        #expect(GlassesFallback.shouldFallBack(.lost) && GlassesFallback.shouldFallBack(.tooHot))
        #expect(GlassesFallback.shouldFallBack(.failed("x")))
        #expect(!GlassesFallback.shouldFallBack(.connecting) && !GlassesFallback.shouldFallBack(.permissionNeeded))
        #expect(GlassesState.streaming(width: 504, height: 896, fps: 15).title == "Glasses, 504 x 896, 15 fps")
        #expect(GlassesTransport.current == .bluetooth, "Bluetooth Classic is the only transport")
        #expect(GlassesTransport.frameRate == 15)
        #expect(GlassesFeature.experimentalLabel == "Experimental")
        #expect(!GlassesFeature.requirement.contains("Hotspot"))
    }
}

@MainActor
private extension RecordModel {
    /// After review, Record Again returns to the camera with the take removed.
    func model_keepAndRecordAgainCheck() {
        discardLatest()
        #expect(phase == .ready && takes.isEmpty)
    }
}

/// The signed configuration is the free one: Bluetooth Classic keys in Info.plist and no Wi-Fi entitlements.
struct RecordSigningConfigTests {
    static var plist: [String: Any] {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().appending(path: "../Support/Info.plist")
        guard let data = try? Data(contentsOf: url),
              let dict = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else { return [:] }
        return dict
    }

    @Test func infoPlistHasBluetoothClassicKeys() {
        let plist = Self.plist
        #expect((plist["UISupportedExternalAccessoryProtocols"] as? [String]) == ["com.meta.ar.wearable"])
        let modes = plist["UIBackgroundModes"] as? [String] ?? []
        #expect(modes.contains("bluetooth-peripheral") && modes.contains("external-accessory"))
    }
}
