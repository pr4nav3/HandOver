import SwiftUI

/// Placeholder. The Library builder replaces this (see README.md in this folder).
struct LibraryView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            if model.lessons.isEmpty {
                ContentUnavailableView("No lessons yet", systemImage: "books.vertical",
                                       description: Text(model.hub == nil ? "Connect to a hub in Settings." : "Lessons made on this hub show up here."))
            } else {
                List(model.lessons) { lesson in
                    Button {
                        model.select(lesson: lesson.id)
                    } label: {
                        LabeledContent(lesson.title, value: "\(lesson.steps) steps")
                    }
                }
            }
        }
        .navigationTitle("Library")
        .refreshable { await model.refreshLessons() }
    }
}

#Preview {
    NavigationStack { LibraryView() }.environment(AppModel.preview())
}
