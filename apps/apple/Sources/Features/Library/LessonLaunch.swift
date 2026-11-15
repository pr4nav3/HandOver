import SwiftUI

/// Places the course screens push inside the section's NavigationStack.
enum CourseRoute: Hashable {
    case detail(String)
    case editor(String)
}

/// Starting a lesson: tells the hub (`select_lesson`, then `goto` once the hub is on it) and shows Learn, as a
/// full screen cover on iPhone and iPad (SCREENS.md 1) and pushed on Mac.
@MainActor
@Observable
final class LessonLauncher {
    var isPresented = false

    func start(_ id: String, at step: Int? = nil, model: AppModel) {
        model.select(lesson: id)
        if let step, step > 0 {
            Task {
                // goto applies to the hub's current lesson, so wait until the hub switched (at most 3 s).
                for _ in 0..<30 where model.state.lessonId != id {
                    try? await Task.sleep(for: .milliseconds(100))
                }
                if model.state.lessonId == id { model.goto(step: step) }
            }
        }
        isPresented = true
    }
}

private struct LessonLaunchPresenter: ViewModifier {
    @Bindable var launcher: LessonLauncher

    func body(content: Content) -> some View {
        #if os(iOS)
        content.fullScreenCover(isPresented: $launcher.isPresented) {
            NavigationStack {
                LearnView()
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Close", systemImage: "xmark") { launcher.isPresented = false }
                        }
                    }
            }
        }
        #else
        content.navigationDestination(isPresented: $launcher.isPresented) { LearnView() }
        #endif
    }
}

extension View {
    func lessonLauncher(_ launcher: LessonLauncher) -> some View {
        modifier(LessonLaunchPresenter(launcher: launcher))
    }
}
