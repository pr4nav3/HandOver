import SwiftUI

/// Places the course screens push inside the section's NavigationStack.
enum CourseRoute: Hashable {
    case detail(String)
    case editor(String)
}

/// Starting a lesson from a screen. Hands the request to the app's `LearnFlow`, which asks for a camera the
/// first time, tells the hub (`select_lesson`, then `goto`) and opens the Learn tab with its End button.
@MainActor
@Observable
final class LessonLauncher {
    struct Request: Equatable {
        var lessonId: String
        var step: Int?
        var serial: Int
    }

    private(set) var request: Request?
    private var serial = 0

    func start(_ id: String, at step: Int? = nil, model: AppModel) {
        serial += 1
        request = Request(lessonId: id, step: step, serial: serial)
    }

    func clear() { request = nil }
}

private struct LessonLaunchPresenter: ViewModifier {
    var launcher: LessonLauncher
    @Environment(AppModel.self) private var model
    @Environment(LearnFlow.self) private var flow: LearnFlow?

    func body(content: Content) -> some View {
        content.onChange(of: launcher.request) { _, request in
            guard let request else { return }
            launcher.clear()
            if let flow {
                flow.requestStart(request.lessonId, at: request.step, model: model)
            } else {
                model.select(lesson: request.lessonId)
            }
        }
    }
}

extension View {
    func lessonLauncher(_ launcher: LessonLauncher) -> some View {
        modifier(LessonLaunchPresenter(launcher: launcher))
    }
}
