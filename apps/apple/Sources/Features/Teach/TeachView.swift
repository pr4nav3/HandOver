import SwiftUI

/// Placeholder. The Teach builder replaces this (see README.md in this folder).
struct TeachView: View {
    var body: some View {
        ContentUnavailableView("Make a lesson", systemImage: "video.badge.plus",
                               description: Text("Pick a video of the task and HandOver cuts it into steps."))
            .navigationTitle("Teach")
    }
}

#Preview {
    NavigationStack { TeachView() }.environment(AppModel.preview())
}
