@preconcurrency import AVFoundation
import Foundation
import CoreGraphics
import Speech
#if os(iOS)
import UIKit
#endif

/// The state of one system permission, in the terms the pre-prompt cards need.
enum PermissionStatus: Equatable, Sendable {
    /// Never asked: show the card, then the system prompt.
    case notAsked
    case allowed
    /// Denied or restricted: the card offers Open Settings instead.
    case denied
    /// The app cannot ask: the Info.plist has no usage text for it, or the device has no such hardware.
    case unavailable
}

/// The permissions HandOver asks for, each just before first use (SCREENS.md 25.8).
enum AppPermission: String, CaseIterable, Identifiable, Sendable {
    case localNetwork, camera, microphone, speech, screenRecording

    var id: String { rawValue }

    var symbol: String {
        switch self {
        case .localNetwork: "network"
        case .camera: "camera"
        case .microphone: "mic"
        case .speech: "waveform"
        case .screenRecording: "macwindow"
        }
    }

    var title: String {
        switch self {
        case .localNetwork: "Find your hub"
        case .camera: "Use the camera"
        case .microphone: "Record your voice"
        case .speech: "Hear \u{201C}next\u{201D} and \u{201C}back\u{201D}"
        case .screenRecording: "Capture one window"
        }
    }

    @MainActor var line: String {
        switch self {
        case .localNetwork:
            #if os(iOS)
            "HandOver looks for the hub on your Wi-Fi. \(DeviceWord.this.firstLetterCapitalized) will ask to allow devices on your local network."
            #else
            "HandOver looks for the hub on your Wi-Fi."
            #endif
        case .camera:
            "The camera scans the hub's code and shows your work while you learn. Frames go to your hub only and are not saved."
        case .microphone:
            "Talk through each step while you record. HandOver uses your words to find where steps start and end."
        case .speech:
            "Speech is recognized on this device to move between steps."
        case .screenRecording:
            "HandOver captures only the call window you pick and sends it to your hub as your camera. Nothing else on your screen is captured, and nothing is saved. macOS asks for Screen Recording permission for this."
        }
    }

    /// The Info.plist key the system needs before it will show the prompt.
    var usageKey: String? {
        switch self {
        case .localNetwork: "NSLocalNetworkUsageDescription"
        case .camera: "NSCameraUsageDescription"
        case .microphone: "NSMicrophoneUsageDescription"
        case .speech: "NSSpeechRecognitionUsageDescription"
        case .screenRecording: nil
        }
    }

    var status: PermissionStatus {
        if let usageKey, Bundle.main.object(forInfoDictionaryKey: usageKey) == nil { return .unavailable }
        switch self {
        case .localNetwork:
            // iOS has no API to read it; the card shows once, before the first connect.
            return UserDefaults.standard.bool(forKey: Self.localNetworkKey) ? .allowed : .notAsked
        case .camera: return Self.map(AVCaptureDevice.authorizationStatus(for: .video))
        case .microphone: return Self.map(AVCaptureDevice.authorizationStatus(for: .audio))
        case .screenRecording:
            #if os(macOS)
            if CGPreflightScreenCaptureAccess() { return .allowed }
            return UserDefaults.standard.bool(forKey: Self.screenAskedKey) ? .denied : .notAsked
            #else
            return .unavailable
            #endif
        case .speech:
            switch SFSpeechRecognizer.authorizationStatus() {
            case .authorized: return .allowed
            case .denied, .restricted: return .denied
            case .notDetermined: return .notAsked
            @unknown default: return .notAsked
            }
        }
    }

    /// Shows the system prompt. True when allowed.
    @discardableResult
    func request() async -> Bool {
        guard status != .unavailable else { return false }
        switch self {
        case .localNetwork:
            // The system prompt appears on the first connection to a local address, which comes next.
            UserDefaults.standard.set(true, forKey: Self.localNetworkKey)
            return true
        case .camera: return await AVCaptureDevice.requestAccess(for: .video)
        case .microphone: return await AVCaptureDevice.requestAccess(for: .audio)
        case .screenRecording:
            #if os(macOS)
            UserDefaults.standard.set(true, forKey: Self.screenAskedKey)
            return CGRequestScreenCaptureAccess()
            #else
            return false
            #endif
        case .speech:
            return await withCheckedContinuation { c in
                SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
            }
        }
    }

    /// Mac shows pre-prompts only for the camera and microphone (SCREENS.md 25.8).
    var needsCard: Bool {
        #if os(macOS)
        return self == .camera || self == .microphone || self == .screenRecording
        #else
        return true
        #endif
    }

    static let localNetworkKey = "handover.permission.localNetworkCardShown"
    static let screenAskedKey = "handover.permission.screenRecordingAsked"

    private static func map(_ status: AVAuthorizationStatus) -> PermissionStatus {
        switch status {
        case .authorized: .allowed
        case .denied, .restricted: .denied
        case .notDetermined: .notAsked
        @unknown default: .notAsked
        }
    }
}

/// Camera access for Camera mode and the scanner: asks the system only when the person already said yes
/// on the card, or when it was asked before.
enum CameraPermission {
    static func request() async -> Bool {
        switch AppPermission.camera.status {
        case .allowed: return true
        case .notAsked: return await AppPermission.camera.request()
        case .denied, .unavailable: return false
        }
    }
}

/// "this iPhone", "this iPad", "this Mac", for copy.
@MainActor
enum DeviceWord {
    static var this: String {
        #if os(macOS)
        return "this Mac"
        #else
        return isPad ? "this iPad" : "this iPhone"
        #endif
    }

    static var noun: String {
        #if os(macOS)
        return "Mac"
        #else
        return isPad ? "iPad" : "iPhone"
        #endif
    }

    #if os(iOS)
    static var isPad: Bool { UIDevice.current.userInterfaceIdiom == .pad }
    #endif
}

extension String {
    var firstLetterCapitalized: String {
        guard let first else { return self }
        return first.uppercased() + dropFirst()
    }
}
