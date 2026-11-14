import SwiftUI

/// Placeholder. The Learn builder replaces this (see README.md in this folder).
struct LearnView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 16) {
            if let lesson = model.lesson {
                Text(lesson.title).font(.headline)
                Text(model.state.isDone ? "Done" : "Step \(model.state.step + 1) of \(model.state.total)")
                    .foregroundStyle(.secondary)
                if let step = model.currentStep { Text(step.title).font(.title2) }
                Text(model.state.status.rawValue.capitalized).font(.caption).foregroundStyle(.secondary)
                if let mistake = model.mistake { Text(mistake.message).foregroundStyle(.orange) }
                HStack {
                    Button("Back", systemImage: "chevron.left") { model.back() }.disabled(!model.canGoBack)
                    Button("Next", systemImage: "chevron.right") { model.next() }.disabled(!model.canGoNext)
                }
                .buttonStyle(.bordered)
            } else {
                ContentUnavailableView("Pick a lesson", systemImage: "play.rectangle",
                                       description: Text("Choose one in the Library to start."))
            }
        }
        .padding()
        .navigationTitle("Learn")
    }
}

#Preview {
    NavigationStack { LearnView() }.environment(AppModel.preview(playing: true))
}
