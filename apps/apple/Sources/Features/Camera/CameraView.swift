import SwiftUI

/// Placeholder. The Camera builder replaces this (see README.md in this folder).
struct CameraView: View {
    var body: some View {
        ContentUnavailableView("Use this device as the camera", systemImage: "camera",
                               description: Text("The hub watches your hands through it to know when a step is done."))
            .navigationTitle("Camera")
    }
}

#Preview {
    NavigationStack { CameraView() }.environment(AppModel.preview())
}
