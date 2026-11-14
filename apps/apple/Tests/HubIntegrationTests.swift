import Foundation
import XCTest
@testable import HandOver

/// Against a real hub. Skipped when none answers. Start one in mock mode from the repo root:
///
///     HANDOVER_PORT=8097 HANDOVER_HTTPS_PORT=8098 HANDOVER_CERTS=/nonexistent HANDOVER_CHECK=mock \
///       HANDOVER_NO_NETWORK=1 .venv/bin/python -m server.main
///
/// Another address: `TEST_RUNNER_HANDOVER_TEST_HUB=host:port xcodebuild test ...`.
final class HubIntegrationTests: XCTestCase {
    private var hub: HubURL!

    override func setUp() async throws {
        let address = ProcessInfo.processInfo.environment["HANDOVER_TEST_HUB"] ?? "127.0.0.1:8097"
        hub = try XCTUnwrap(HubURL(parsing: address))
        var request = URLRequest(url: hub.api("lessons"))
        request.timeoutInterval = 1.5
        do {
            _ = try await URLSession.shared.data(for: request)
        } catch {
            throw XCTSkip("No hub at \(hub.displayName); start one to run this test.")
        }
    }

    func testListsLessonsLoadsOneAndReceivesState() async throws {
        let client = HubClient(hub: hub)
        let lessons = try await client.lessons()
        XCTAssertFalse(lessons.isEmpty, "the repo ships lessons/demo-v1")
        let first = try XCTUnwrap(lessons.first)
        let lesson = try await client.lesson(id: first.id)
        XCTAssertEqual(lesson.id, first.id)
        XCTAssertEqual(lesson.steps.count, first.steps)

        do {
            _ = try await client.lesson(id: "no-such-lesson-here")
            XCTFail("expected a 404")
        } catch let error as HubError {
            XCTAssertEqual(error, .http(status: 404, detail: "lesson not found"))
        }

        let socket = UISocket(hub: hub)
        let log = EventLog(socket.events)
        await socket.start()
        // The hub sends the full state on connect.
        try await eventually("first state", timeout: .seconds(5)) {
            log.messages.contains { if case .state = $0 { true } else { false } }
        }
        XCTAssertTrue(log.states.contains(.connected))
        await socket.stop()
    }

    /// Selects a lesson and moves through it with the from guard. Changes only the hub's in-memory session.
    func testSelectNextAndBack() async throws {
        let lessons = try await HubClient(hub: hub).lessons()
        let target = try XCTUnwrap(lessons.first { $0.steps >= 2 })
        let socket = UISocket(hub: hub)
        let log = EventLog(socket.events)
        await socket.start()
        try await eventually("connected", timeout: .seconds(5)) { log.states.contains(.connected) }

        await socket.selectLesson(target.id)
        try await eventually("lesson selected", timeout: .seconds(5)) {
            log.latestState?.lessonId == target.id && log.latestState?.step == 0
        }
        let sent = await socket.next()
        XCTAssertTrue(sent)
        try await eventually("advance 0 to 1", timeout: .seconds(5)) {
            log.messages.contains(.advance(Advance(from: 0, to: 1, reason: .button)))
        }
        try await eventually("state at step 1", timeout: .seconds(5)) { log.latestState?.step == 1 }
        let back = await socket.back()
        XCTAssertTrue(back)
        try await eventually("back at step 0", timeout: .seconds(5)) { log.latestState?.step == 0 }
        await socket.stop()
    }

    /// AppModel end to end: connect, load the library, select, and get the lesson fetched from the state.
    @MainActor
    func testAppModelFollowsTheHub() async throws {
        let suite = "handover.tests.integration"
        UserDefaults.standard.removePersistentDomain(forName: suite)
        let model = AppModel(defaults: try XCTUnwrap(UserDefaults(suiteName: suite)))
        model.connect(to: hub)
        try await eventually("connected and library loaded", timeout: .seconds(5)) {
            await MainActor.run { model.connection == .connected && !model.lessons.isEmpty }
        }
        XCTAssertEqual(model.recents, [hub])
        let target = try XCTUnwrap(model.lessons.last)
        model.select(lesson: target.id)
        try await eventually("lesson fetched", timeout: .seconds(5)) {
            await MainActor.run { model.lesson?.id == target.id && model.state.lessonId == target.id }
        }
        XCTAssertEqual(model.lesson?.steps.count, target.steps)
        XCTAssertEqual(model.currentStep?.n, 1)
        XCTAssertNotNil(model.mediaURL("clips/01.mp4")?.query?.hasPrefix("v="))
        model.disconnect()
        XCTAssertEqual(model.connection, .idle)
    }

    func testCameraHelloIsAnswered() async throws {
        let hello = CameraHello(deviceId: "ios-integration-test", name: "Integration test", platform: .ios, source: .phone)
        let camera = CameraSocket(hub: hub, hello: hello)
        let log = EventLog(camera.events)
        await camera.start()
        // After hello the hub sends camera_status and state to cameras (CONTRACT.md section 6, W8).
        try await eventually("camera_status after hello", timeout: .seconds(5)) {
            log.messages.contains { if case .cameraStatus = $0 { true } else { false } }
        }
        await camera.stop()
    }
}
