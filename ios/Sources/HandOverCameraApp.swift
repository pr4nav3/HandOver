// UNTESTED: written on Windows, never compiled.

import SwiftUI
import UIKit

@main
struct HandOverCameraApp: App {
    init() {
        // No-op in builds without the glasses toolkit (stub in FrameSource.swift).
        GlassesCameraSource.configureToolkit()
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onOpenURL { url in
                    // The Meta AI app returns here after registration / permission prompts.
                    GlassesCameraSource.handleOpenURL(url)
                }
        }
    }
}
