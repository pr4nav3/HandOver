import Foundation
import Testing
@testable import HandOver

struct MessageRoutingTests {
    private let state = #"{"type":"state","lesson_id":"a","step":1,"total":3,"status":"watching"}"#

    @Test func binaryIsAFrameOnlyOnTheViewerSocket() {
        #expect(HubMessage.route(.binary(sampleJPEG), on: .ui) == .frame(sampleJPEG))
        #expect(HubMessage.route(.binary(sampleJPEG), on: .camera) == nil)
        #expect(HubMessage.route(.binary(Data([0x89, 0x50, 0x4E, 0x47])), on: .ui) == nil, "not a JPEG")
        #expect(HubMessage.route(.binary(Data()), on: .ui) == nil)
    }

    @Test func textIsJSONOnBothSockets() {
        for channel in [HubMessage.Channel.ui, .camera] {
            guard case .state(let s)? = HubMessage.route(.text(state), on: channel) else {
                Issue.record("no state on \(channel)")
                continue
            }
            #expect(s.step == 1)
        }
        #expect(HubMessage.route(.text("garbage"), on: .ui) == nil)
    }

    @Test func outgoingCommands() {
        #expect(HubCommand.selectLesson(id: "demo-v1").text == #"{"id":"demo-v1","type":"select_lesson"}"#)
        #expect(HubCommand.next(reason: .button, from: 3).text == #"{"from":3,"reason":"button","type":"next"}"#)
        #expect(HubCommand.next(reason: .voice, from: nil).text == #"{"reason":"voice","type":"next"}"#)
        #expect(HubCommand.back(from: 0).text == #"{"from":0,"type":"back"}"#)
        #expect(HubCommand.goto(step: 2).text == #"{"step":2,"type":"goto"}"#)
        #expect(HubCommand.dismissMistake.text == #"{"type":"dismiss_mistake"}"#)
        #expect(HubCommand.hold(true).text == #"{"hold":true,"type":"hold"}"#)
        #expect(HubCommand.endLesson(lessonId: "demo-v1", runId: "r7").text
            == #"{"lesson_id":"demo-v1","run_id":"r7","type":"end_lesson"}"#)
        #expect(HubCommand.endLesson(lessonId: "demo-v1", runId: nil).text == #"{"lesson_id":"demo-v1","type":"end_lesson"}"#)
        #expect(HubCommand.endLesson(lessonId: nil, runId: nil).text == #"{"type":"end_lesson"}"#)
        let hello = CameraHello(deviceId: "ios-1", name: "iPhone camera", platform: .ios, source: .glasses)
        #expect(HubCommand.hello(hello).text
            == #"{"device_id":"ios-1","name":"iPhone camera","platform":"ios","source":"glasses","type":"hello"}"#)
    }

    /// End names the lesson this app runs, and the run only when the hub is on that lesson.
    @Test func endLessonCarriesTheCurrentIds() throws {
        let data = Data(#"{"type":"state","lesson_id":"demo-v1","rev":1,"step":0,"total":3,"run_id":"r7"}"#.utf8)
        let state = try JSONDecoder().decode(HubState.self, from: data)
        #expect(state.runId == "r7")
        var ids = AppModel.endIds(lessonId: "demo-v1", state: state)
        #expect(ids.lessonId == "demo-v1" && ids.runId == "r7")
        ids = AppModel.endIds(lessonId: nil, state: state)
        #expect(ids.lessonId == "demo-v1" && ids.runId == "r7")
        ids = AppModel.endIds(lessonId: "other", state: state)
        #expect(ids.lessonId == "other" && ids.runId == nil, "another lesson's run is never sent")
        ids = AppModel.endIds(lessonId: nil, state: .empty)
        #expect(ids.lessonId == nil && ids.runId == nil)
    }

    @Test func reconnectPolicy() {
        #expect(ReconnectPolicy.decide(closeCode: 4000) == .stop(reason: "Replaced by a newer connection from this device"))
        #expect(ReconnectPolicy.decide(closeCode: 1011) == .now)
        #expect(ReconnectPolicy.decide(closeCode: 1013) == .backoff)
        #expect(ReconnectPolicy.decide(closeCode: 1006) == .backoff)
        #expect(ReconnectPolicy.decide(closeCode: nil) == .backoff)
    }

    @Test func backoffGrowsToTheCap() {
        var b = Backoff(jitter: 0)
        let delays = (0..<7).map { _ in b.next() }
        #expect(delays == [.milliseconds(500), .seconds(1), .seconds(2), .seconds(4), .seconds(8), .seconds(10), .seconds(10)])
        b.reset()
        #expect(b.next() == .milliseconds(500))
        var jittered = Backoff(jitter: 0.2)
        #expect(jittered.next(random: 1) == .milliseconds(400))
    }
}

/// HubSocket against a scripted transport.
struct HubSocketTests {
    private let url = URL(string: "ws://hub.test:8000/ws/ui")!

    @Test func routesTextAndBinarySeparately() async throws {
        let net = FakeNetwork()
        let socket = HubSocket(url: url, channel: .ui, backoff: quickBackoff, makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("connected") { log.states.contains(.connected) }
        t.push(text: #"{"type":"state","lesson_id":"a","step":0,"total":2,"status":"manual"}"#)
        t.push(.binary(sampleJPEG))
        t.push(.binary(Data([1, 2, 3])))
        t.push(text: "{oops")
        t.push(text: #"{"type":"advance","from":0,"to":1,"reason":"button"}"#)
        try await eventually("three messages") { log.messages.count == 3 }
        let m = log.messages
        guard case .state = m[0] else { Issue.record("first is \(m[0])"); return }
        #expect(m[1] == .frame(sampleJPEG))
        #expect(m[2] == .advance(Advance(from: 0, to: 1, reason: .button)))
        await socket.stop()
    }

    @Test func helloFirstThenQueuedCommandsAndBinaryFromHubIgnored() async throws {
        let net = FakeNetwork()
        let hello = CameraHello(deviceId: "ios-test", name: "iPhone camera", platform: .ios, source: .phone)
        let socket = HubSocket(url: url, channel: .camera, greeting: .hello(hello), backoff: quickBackoff,
                               makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.send(.next(reason: .button, from: 0))  // queued before connecting
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("two sent") { t.sentTexts.count == 2 }
        #expect(t.sentTexts[0] == HubCommand.hello(hello).text)
        #expect(t.sentTexts[1] == HubCommand.next(reason: .button, from: 0).text)
        t.push(.binary(sampleJPEG))
        t.push(text: #"{"type":"camera_status","active":true}"#)
        try await eventually("camera status") { !log.messages.isEmpty }
        #expect(log.messages == [.cameraStatus(CameraStatus(active: true))])
        await socket.stop()
    }

    @Test func staleNavigationIsDroppedFromTheQueue() async throws {
        let net = FakeNetwork()
        let socket = HubSocket(url: url, channel: .ui, backoff: quickBackoff, navigationTTL: .milliseconds(20),
                               makeTransport: net.factory)
        await socket.send(.next(reason: .button, from: 2))
        await socket.send(.selectLesson(id: "a"))
        try await Task.sleep(for: .milliseconds(60))
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("select sent") { t.sentTexts.count == 1 }
        try await Task.sleep(for: .milliseconds(30))
        #expect(t.sentTexts == [HubCommand.selectLesson(id: "a").text])
        await socket.stop()
    }

    @Test func reconnectsAfterADropAndGreetsAgain() async throws {
        let net = FakeNetwork()
        let hello = CameraHello(deviceId: "d", name: "n", platform: .ios, source: .phone)
        let socket = HubSocket(url: url, channel: .camera, greeting: .hello(hello), backoff: quickBackoff,
                               makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        let first = try await net.transport(0)
        try await eventually("connected") { log.states.contains(.connected) }
        first.drop(code: 1006)
        let second = try await net.transport(1)
        try await eventually("hello again") { second.sentTexts.first == HubCommand.hello(hello).text }
        #expect(log.states.contains { if case .retrying = $0 { true } else { false } })
        try await eventually("connected twice") { log.states.filter { $0 == .connected }.count == 2 }
        await socket.stop()
    }

    @Test func retriesWhenOpeningFails() async throws {
        let net = FakeNetwork([FakeTransport(openError: SocketClosed(code: 0)), FakeTransport(openError: SocketClosed(code: 1013))])
        let socket = HubSocket(url: url, channel: .ui, backoff: quickBackoff, makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        try await eventually("third attempt connects") { net.transports.count == 3 && log.states.last == .connected }
        await socket.stop()
    }

    @Test func replacedStopsForGood() async throws {
        let net = FakeNetwork()
        let socket = HubSocket(url: url, channel: .camera, backoff: quickBackoff, makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("connected") { log.states.contains(.connected) }
        t.drop(code: 4000)
        try await eventually("stopped") { if case .stopped = log.states.last { true } else { false } }
        try await Task.sleep(for: .milliseconds(80))
        #expect(net.transports.count == 1, "no reconnect after 4000")
    }

    @Test func stalledReconnectsAtOnce() async throws {
        let net = FakeNetwork()
        let socket = HubSocket(url: url, channel: .ui, backoff: Backoff(base: .seconds(30), cap: .seconds(30), jitter: 0),
                               makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("connected") { log.states.contains(.connected) }
        t.drop(code: 1011)
        _ = try await net.transport(1)  // would take 30 s with backoff
        #expect(!log.states.contains { if case .retrying = $0 { true } else { false } })
        await socket.stop()
    }

    @Test func framesAreSentOnlyWhenIdle() async throws {
        let net = FakeNetwork([FakeTransport(holdFrames: true)])
        let socket = HubSocket(url: url, channel: .camera, backoff: quickBackoff, makeTransport: net.factory)
        let log = EventLog(socket.events)
        #expect(await socket.sendFrameIfIdle(sampleJPEG) == false, "not connected yet")
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("connected") { log.states.contains(.connected) }
        #expect(await socket.sendFrameIfIdle(sampleJPEG))
        #expect(await socket.sendFrameIfIdle(sampleJPEG) == false, "previous frame still in flight")
        try await eventually("frame held") { t.isHoldingFrame }
        #expect(await socket.isSendingFrame)
        t.releaseFrame()
        try await eventually("frame done") { await !socket.isSendingFrame }
        #expect(t.sentFrames == 1)
        #expect(await socket.framesSent == 1)
        #expect(await socket.sendFrameIfIdle(sampleJPEG))
        try await eventually("second frame held") { t.isHoldingFrame }
        t.releaseFrame()
        try await eventually("second frame") { t.sentFrames == 2 }
        await socket.stop()
    }
}

/// UISocket and CameraSocket put the guard and the frame rules on top of HubSocket.
struct SocketWrapperTests {
    private let hub = HubURL(parsing: "hub.test:8000")!

    private func state(_ step: Int, total: Int = 4, status: String = "watching") -> String {
        #"{"type":"state","lesson_id":"a","rev":1,"step":\#(step),"total":\#(total),"status":"\#(status)"}"#
    }

    @Test func uiSocketSendsOneNextPerPositionWithFrom() async throws {
        let net = FakeNetwork()
        let socket = UISocket(hub: hub, backoff: quickBackoff, makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        let t = try await net.transport(0)
        #expect(await socket.next() == false, "no state yet")
        t.push(text: state(1))
        try await eventually("state") { !log.messages.isEmpty }
        #expect(await socket.next())
        #expect(await socket.next() == false, "double tap")
        t.push(text: state(2))
        try await eventually("second state") { log.messages.count == 2 }
        #expect(await socket.back())
        try await eventually("two sent") { t.sentTexts.count == 2 }
        #expect(t.sentTexts == [HubCommand.next(reason: .button, from: 1).text, HubCommand.back(from: 2).text])
        await socket.stop()
    }

    @Test func cameraSocketFrameRules() async throws {
        let net = FakeNetwork()
        let hello = CameraHello(deviceId: "ios-x", name: "iPhone camera", platform: .ios, source: .phone)
        let socket = CameraSocket(hub: hub, hello: hello, backoff: quickBackoff, makeTransport: net.factory)
        let log = EventLog(socket.events)
        await socket.start()
        let t = try await net.transport(0)
        try await eventually("connected") { log.states.contains(.connected) }
        #expect(t.sentTexts.first == HubCommand.hello(hello).text)
        #expect(await socket.send(frame: Data([0x00, 0x01])) == false, "not a JPEG")
        #expect(await socket.send(frame: sampleJPEG + Data(count: CameraSocket.maxFrameBytes)) == false, "over 2 MB")
        #expect(await socket.send(frame: sampleJPEG))
        #expect(await socket.send(frame: sampleJPEG) == false, "under 0.2 s since the last one")
        try await eventually("one frame") { t.sentFrames == 1 }
        try await Task.sleep(for: .milliseconds(220))
        #expect(await socket.send(frame: sampleJPEG))
        try await eventually("two frames") { t.sentFrames == 2 }
        await socket.stop()
    }
}
