import Foundation

/// One WebSocket message, either way.
enum SocketMessage: Sendable, Equatable {
    case text(String)
    case binary(Data)
}

/// Everything the hub sends on /ws/ui or /ws/camera, decoded.
enum HubMessage: Sendable, Equatable {
    case state(HubState)
    case advance(Advance)
    case mistake(MistakeMessage)
    case error(ErrorMessage)
    case cameraStatus(CameraStatus)
    /// A live JPEG from the active camera (/ws/ui only).
    case frame(Data)
    /// A message type this app does not know. Ignored, per the contract.
    case unknown(type: String)

    /// Which socket a message came in on decides what binary means: on /ws/ui it is a live JPEG, on
    /// /ws/camera the hub never sends binary, so any is dropped.
    enum Channel: Sendable {
        case ui, camera
    }

    /// Decodes one socket message. Nil for anything to ignore: invalid JSON, a known type with the wrong
    /// shape, binary on the camera socket, or binary that is not a JPEG.
    static func route(_ message: SocketMessage, on channel: Channel) -> HubMessage? {
        switch message {
        case .binary(let data):
            guard channel == .ui, isJPEG(data) else { return nil }
            return .frame(data)
        case .text(let text):
            return decode(text: text)
        }
    }

    static func decode(text: String) -> HubMessage? {
        let data = Data(text.utf8)
        let decoder = JSONDecoder()
        guard let envelope = try? decoder.decode(Envelope.self, from: data), let type = envelope.type else { return nil }
        do {
            switch type {
            case "state": return .state(try decoder.decode(HubState.self, from: data))
            case "advance": return .advance(try decoder.decode(Advance.self, from: data))
            case "mistake": return .mistake(try decoder.decode(MistakeMessage.self, from: data))
            case "error": return .error(try decoder.decode(ErrorMessage.self, from: data))
            case "camera_status": return .cameraStatus(try decoder.decode(CameraStatus.self, from: data))
            default: return .unknown(type: type)
            }
        } catch {
            return nil
        }
    }

    /// JPEGs start with FF D8.
    static func isJPEG(_ data: Data) -> Bool {
        data.count >= 2 && data[data.startIndex] == 0xFF && data[data.startIndex + 1] == 0xD8
    }

    private struct Envelope: Decodable {
        var type: String?
    }
}

/// What a client sends on /ws/ui (CONTRACT.md section 7). `next` and `back` on /ws/camera use the same
/// shape (section 6).
enum HubCommand: Sendable, Equatable {
    enum NextReason: String, Sendable {
        case button, voice
    }

    case selectLesson(id: String)
    /// `from` is the position the client was showing; the hub drops the command when it moved on.
    case next(reason: NextReason, from: Int?)
    case back(from: Int?)
    case goto(step: Int)
    case dismissMistake
    case hold(Bool)
    /// Stops the run and unloads the lesson. The ids name the lesson and run this screen shows; the hub ignores
    /// an End whose ids no longer match (a stale End must not unload a lesson someone else started).
    case endLesson(lessonId: String?, runId: String?)
    case hello(CameraHello)

    var isNavigation: Bool {
        switch self {
        case .next, .back: true
        default: false
        }
    }

    /// The JSON text to send.
    var text: String {
        var object: [String: JSONValue]
        switch self {
        case .selectLesson(let id):
            object = ["type": .string("select_lesson"), "id": .string(id)]
        case .next(let reason, let from):
            object = ["type": .string("next"), "reason": .string(reason.rawValue)]
            if let from { object["from"] = .int(from) }
        case .back(let from):
            object = ["type": .string("back")]
            if let from { object["from"] = .int(from) }
        case .goto(let step):
            object = ["type": .string("goto"), "step": .int(step)]
        case .dismissMistake:
            object = ["type": .string("dismiss_mistake")]
        case .hold(let held):
            object = ["type": .string("hold"), "hold": .bool(held)]
        case .endLesson(let lessonId, let runId):
            object = ["type": .string("end_lesson")]
            if let lessonId { object["lesson_id"] = .string(lessonId) }
            if let runId { object["run_id"] = .string(runId) }
        case .hello(let hello):
            object = [
                "type": .string("hello"), "device_id": .string(hello.deviceId), "name": .string(hello.name),
                "platform": .string(hello.platform.rawValue), "source": .string(hello.source.rawValue),
            ]
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let data = (try? encoder.encode(object)) ?? Data("{}".utf8)
        return String(decoding: data, as: UTF8.self)
    }
}

/// The camera's hello (CONTRACT.md section 6). The hub cuts `device_id` to 128 and `name` to 64
/// characters, and ignores the whole hello when `platform` or `source` is outside its lists.
struct CameraHello: Sendable, Equatable {
    var deviceId: String
    var name: String
    var platform: CameraInfo.Platform
    var source: CameraInfo.Source

    /// The hello this device sends. The hub only accepts ios, web and replay as platforms, so the Mac app
    /// also says ios and names itself "Mac camera".
    static func thisDevice(source: CameraInfo.Source, deviceId: String) -> CameraHello {
        #if os(macOS)
        let name = "Mac camera"
        #else
        let name = source == .glasses ? "Ray-Ban Meta via iPhone" : "iPhone camera"
        #endif
        return CameraHello(deviceId: deviceId, name: name, platform: .ios, source: source)
    }

    /// A stable id for this install, kept in UserDefaults, so the hub can replace an older connection
    /// from the same device (close 4000) instead of counting two cameras.
    static func deviceId(defaults: UserDefaults = .standard) -> String {
        let key = "handover.deviceId"
        if let existing = defaults.string(forKey: key), !existing.isEmpty { return existing }
        #if os(macOS)
        let fresh = "mac-" + UUID().uuidString.lowercased()
        #else
        let fresh = "ios-" + UUID().uuidString.lowercased()
        #endif
        defaults.set(fresh, forKey: key)
        return fresh
    }
}
