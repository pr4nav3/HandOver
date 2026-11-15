import Foundation
import Testing
@testable import HandOver

struct HubURLTests {
    @Test(arguments: [
        ("192.168.1.20", "http://192.168.1.20:8000"),
        ("  192.168.1.20:8000\n", "http://192.168.1.20:8000"),
        ("Studio-Mac.local", "http://studio-mac.local:8000"),
        ("localhost:8097", "http://localhost:8097"),
        ("http://192.168.1.20:8000/", "http://192.168.1.20:8000"),
        ("HTTP://10.0.0.5", "http://10.0.0.5"),
        ("https://hub.example.com/api/lessons?x=1#top", "https://hub.example.com"),
        ("ws://192.168.1.20:8000/ws/camera", "http://192.168.1.20:8000"),
        ("wss://192.168.1.20:9443/ws/ui", "https://192.168.1.20:9443"),
        ("https://192.168.1.20:8443/capture?pair=4821", "http://192.168.1.20:8000"),
        ("http://user:pw@10.0.0.5:8000", "http://10.0.0.5:8000"),
        ("handover://connect?hub=http%3A%2F%2F192.168.1.20%3A8000", "http://192.168.1.20:8000"),
        ("handover://connect?hub=192.168.1.30", "http://192.168.1.30:8000"),
        ("handover://192.168.1.40:8001", "http://192.168.1.40:8001"),
        ("handover://studio.local", "http://studio.local:8000"),
    ])
    func parses(input: String, expected: String) throws {
        let hub = try #require(HubURL(parsing: input))
        #expect(hub.base.absoluteString == expected)
    }

    @Test(arguments: ["", "   ", "http://", "ftp://10.0.0.1", "not a host", "handover://connect", "10.0.0.1:99999",
                      "handover://connect?hub=handover://10.0.0.1", "://x"])
    func rejects(input: String) {
        #expect(HubURL(parsing: input) == nil)
    }

    @Test func ipv6() throws {
        let hub = try #require(HubURL(parsing: "[fe80::1]:8000"))
        #expect(hub.port == 8000)
        #expect(hub.displayName == "[fe80::1]:8000")
        #expect(hub.uiSocket.absoluteString == "ws://[fe80::1]:8000/ws/ui")
    }

    @Test func derivedURLs() throws {
        let hub = try #require(HubURL(parsing: "192.168.1.20"))
        #expect(hub.displayName == "192.168.1.20:8000")
        #expect(hub.uiSocket.absoluteString == "ws://192.168.1.20:8000/ws/ui")
        #expect(hub.cameraSocket.absoluteString == "ws://192.168.1.20:8000/ws/camera")
        #expect(hub.api("lessons").absoluteString == "http://192.168.1.20:8000/api/lessons")
        #expect(hub.fileURL(lesson: "demo-v1", path: "clips/01.mp4", rev: 42).absoluteString
            == "http://192.168.1.20:8000/lessons/demo-v1/clips/01.mp4?v=42")
        #expect(hub.fileURL(lesson: "demo-v1", path: "../../etc/passwd").absoluteString
            == "http://192.168.1.20:8000/lessons/demo-v1/etc/passwd", "no climbing out of the lesson folder")
        let secure = try #require(HubURL(parsing: "https://hub.example.com"))
        #expect(secure.cameraSocket.absoluteString == "wss://hub.example.com/ws/camera")
        #expect(secure.port == 443)
    }

    @Test func linkRoundTrip() throws {
        let hub = try #require(HubURL(parsing: "10.1.2.3:8000"))
        #expect(hub.link.scheme == "handover")
        #expect(HubURL(parsing: hub.link.absoluteString) == hub)
    }

    @Test func pairingLinkCarriesACameraIntent() throws {
        let glasses = try #require(URL(string: "handover://connect?hub=http%3A%2F%2F10.1.2.3%3A8000&camera=glasses"))
        let phone = try #require(URL(string: "handover://connect?hub=http%3A%2F%2F10.1.2.3%3A8000&camera=phone"))
        let plain = try #require(URL(string: "handover://connect?hub=http%3A%2F%2F10.1.2.3%3A8000"))
        #expect(HubURL(parsing: glasses.absoluteString)?.displayName == "10.1.2.3:8000")
        #expect(CameraLaunchIntent(url: glasses) == .glasses)
        #expect(CameraLaunchIntent(url: phone) == .phone)
        #expect(CameraLaunchIntent(url: plain) == nil)
        let hub = try #require(HubURL(parsing: "10.1.2.3:8000"))
        #expect(CameraLaunchIntent(url: hub.cameraLink(.glasses)) == .glasses)
        #expect(HubURL(parsing: hub.cameraLink(.glasses).absoluteString) == hub)
    }

    @Test func pairingLinkCarriesOnlyAnOpaqueAccountHandoffClaim() throws {
        let claim = String(repeating: "a", count: 43)
        let link = try #require(URL(string:
            "handover://connect?hub=http%3A%2F%2F10.1.2.3%3A8000&camera=glasses&handoff=\(claim)"))
        #expect(AccountHandoffIntent(url: link)?.claim == claim)
        #expect(HubURL(parsing: link.absoluteString)?.displayName == "10.1.2.3:8000")
        #expect(AccountHandoffIntent(url: try #require(URL(string: "handover://connect?hub=10.1.2.3&handoff=short"))) == nil)
    }

    @Test func codableAsPlainString() throws {
        let hub = try #require(HubURL(parsing: "10.1.2.3"))
        let data = try JSONEncoder().encode([hub])
        #expect(String(decoding: data, as: UTF8.self) == #"["http:\/\/10.1.2.3:8000"]"#)
        #expect(try JSONDecoder().decode([HubURL].self, from: data) == [hub])
    }

    @Test func recentsAreUniqueNewestFirstAndCapped() throws {
        let defaults = try #require(UserDefaults(suiteName: "handover.tests.recents"))
        defaults.removePersistentDomain(forName: "handover.tests.recents")
        let store = HubRecents(defaults: defaults)
        var list: [HubURL] = []
        for i in 1...8 { list = HubRecents.adding(try #require(HubURL(parsing: "10.0.0.\(i)")), to: list) }
        list = HubRecents.adding(try #require(HubURL(parsing: "http://10.0.0.5:8000")), to: list)
        #expect(list.count == HubRecents.limit)
        #expect(list.first?.host == "10.0.0.5")
        #expect(Set(list).count == list.count)
        store.save(list)
        #expect(store.load() == list)
    }
}
