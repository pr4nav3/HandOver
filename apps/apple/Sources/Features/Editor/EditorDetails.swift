import PhotosUI
import SwiftUI

/// Lesson details (SCREENS.md 14.2): cover, title and description on hubs with the course routes, plus the
/// production style with Re-render when produced videos exist.
struct LessonDetailsForm: View {
    var store: EditorStore
    var hub: HubURL?
    @Environment(\.theme) private var theme
    @State private var coverItem: PhotosPickerItem?
    @State private var style = ProductionStyle()

    var body: some View {
        Form {
            if store.capabilities.course {
                coverSection
                Section("Title") {
                    TextField("Title", text: Binding(get: { store.course?.title ?? store.lesson.title },
                                                     set: { store.update(title: String($0.prefix(120))) }),
                              prompt: Text("Fold a fortune teller"))
                }
                Section {
                    TextField("Description", text: Binding(get: { store.course?.description ?? "" },
                                                           set: { store.update(description: String($0.prefix(300))) }),
                              prompt: Text("What learners will make, and what they need."), axis: .vertical)
                        .lineLimit(2...6)
                } header: {
                    Text("Description")
                } footer: {
                    Text("\((store.course?.description ?? "").count) of 300 characters")
                }
            } else {
                Section {
                    Text(store.lesson.title).font(theme.fonts.headline)
                } footer: {
                    Text("This hub saves steps only. Update the hub to change the cover, title and description here.")
                }
            }
            if store.capabilities.production { productionSection }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .background(theme.colors.paper)
        .disabled(!store.permissions.canEdit)
        .onAppear { style = store.style }
        .onChange(of: coverItem) { _, item in
            guard let item else { return }
            Task {
                defer { coverItem = nil }
                guard let data = try? await item.loadTransferable(type: Data.self) else { return }
                let file = FileManager.default.temporaryDirectory.appending(path: "cover-\(UUID().uuidString).jpg")
                guard (try? data.write(to: file)) != nil else { return }
                await store.uploadCover(file)
                try? FileManager.default.removeItem(at: file)
            }
        }
    }

    private var coverSection: some View {
        Section("Cover") {
            if let hub {
                HubImage(CourseMedia.coverCandidates(hub: hub, lessonId: store.lessonId, coverURL: store.course?.coverURL,
                                                     rev: store.revision), symbol: "photo")
                    .aspectRatio(16 / 9, contentMode: .fit)
                    .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
                    .id(store.course?.coverURL)
            }
            Menu("Choose Cover") {
                Menu("Use a Step Frame") {
                    ForEach(Array(store.lesson.steps.enumerated()), id: \.offset) { index, step in
                        Button("Step \(index + 1): \(step.title)") { Task { await store.useFrameAsCover(step: index) } }
                    }
                }
                PhotosPicker(selection: $coverItem, matching: .images) { Text("Choose Photo") }
                if store.course?.cover != nil {
                    Button("Remove", role: .destructive) { Task { await store.removeCover() } }
                }
            }
        }
    }

    private var productionSection: some View {
        Section {
            Picker("Title Cards", selection: $style.titleCards) {
                ForEach(ProductionStyle.TitleCards.allCases, id: \.self) { Text($0.title).tag($0) }
            }
            Toggle("Zoom Toward the Action", isOn: $style.zoom)
            Toggle("Highlight Key Moments", isOn: $style.highlight)
            Toggle("Burn In Captions", isOn: $style.burnCaptions)
            HStack {
                Button("Re-render") { Task { await store.rerender(style) } }
                    .disabled(store.produceBusy || style == store.style)
                Spacer()
                if store.produceBusy { ProgressView().controlSize(.small) }
            }
        } header: {
            Text("Produced Video")
        } footer: {
            Text("The produced course adds title cards, a gentle zoom and highlights. The original clips stay as they are.")
        }
    }
}

/// The publish sheet (SCREENS.md 15.2).
struct EditorPublishSheet: View {
    var store: EditorStore
    var canPublishToEveryone: Bool
    @Environment(\.dismiss) private var dismiss
    @Environment(\.theme) private var theme
    @State private var audience: EditorPublishPlan.Audience?
    @State private var unlisted = false
    @State private var working = false
    @State private var showAccess = false

    var body: some View {
        NavigationStack {
            if let plan = store.publishPlan(canPublishToEveryone: canPublishToEveryone), let course = store.course {
                Form {
                    Section("Who Can Find It") {
                        ForEach(plan.audiences) { option in
                            Button {
                                audience = option
                                Haptics.tap()
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(option.title).foregroundStyle(theme.colors.ink)
                                        if let detail = option.detail {
                                            Text(detail).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
                                        }
                                    }
                                    Spacer()
                                    if audience == option {
                                        Image(systemName: "checkmark").foregroundStyle(theme.colors.accentInk)
                                    }
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityAddTraits(audience == option ? .isSelected : [])
                        }
                        if let audience, case .org = audience.kind {
                            Text("Members of \(audience.title.replacingOccurrences(of: "Publish to ", with: "")) see it on their Home and on the org page.")
                                .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                        }
                    }
                    Section {
                        Toggle("Unlisted", isOn: $unlisted)
                    } footer: {
                        Text("Not shown in Library. Share the link instead.")
                    }
                    Section("Checklist") {
                        Label("\(plan.steps) steps", systemImage: "list.number")
                        Label("\(plan.camera) checked by camera", systemImage: "viewfinder")
                        Label("\(plan.manual) manual", systemImage: "hand.tap")
                        ForEach(plan.warnings, id: \.self) { warning in
                            Label(warning, systemImage: "exclamationmark.triangle").foregroundStyle(theme.colors.caution)
                        }
                    }
                    if store.permissions.canManage {
                        Section {
                            Button("Manage Access") { showAccess = true }
                        }
                    }
                    if store.permissions.canUnpublish && course.status != .draft {
                        Section {
                            Button("Unpublish", role: .destructive) {
                                Task {
                                    await store.unpublish()
                                    dismiss()
                                }
                            }
                        }
                    }
                }
                .formStyle(.grouped)
                .navigationTitle("Publish \(course.title)")
                #if os(iOS)
                .navigationBarTitleDisplayMode(.inline)
                #endif
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) {
                        Button(plan.primaryTitle) {
                            guard let audience else { return }
                            working = true
                            Task {
                                let ok = await store.publish(to: audience, unlisted: unlisted)
                                working = false
                                if ok {
                                    Haptics.success()
                                    dismiss()
                                }
                            }
                        }
                        .disabled(audience == nil || !plan.canPublish || working)
                    }
                }
                .onAppear {
                    audience = plan.current(course)
                    unlisted = course.status == .unlisted
                }
                .navigationDestination(isPresented: $showAccess) { EditorAccessView(store: store) }
            }
        }
        #if os(iOS)
        .presentationDetents([.medium, .large])
        #else
        .frame(minWidth: 460, minHeight: 520)
        #endif
    }
}

/// Access (SCREENS.md 15.3): who may edit or take a course besides its owner.
struct EditorAccessView: View {
    var store: EditorStore
    @Environment(\.theme) private var theme
    @State private var people: [HubUser] = []
    @State private var role: Course.Access.Role = .learner

    var body: some View {
        let access = store.course?.access ?? []
        Form {
            if !candidates(access).isEmpty {
                Section("Invite by Name") {
                    Picker("Role", selection: $role) {
                        Text("Editor").tag(Course.Access.Role.editor)
                        Text("Learner").tag(Course.Access.Role.learner)
                    }
                    ForEach(candidates(access)) { person in
                        Button("Invite \(person.name)") {
                            Task { await store.setAccess(access + [Course.Access(userId: person.id, name: person.name, role: role)]) }
                        }
                    }
                }
            }
            Section {
                if let owner = store.course?.owner {
                    LabeledContent(owner.name, value: "Owner")
                }
                ForEach(access) { entry in
                    Picker(entry.name, selection: Binding(
                        get: { entry.role },
                        set: { new in
                            Task {
                                await store.setAccess(access.map { $0.userId == entry.userId ? Course.Access(userId: $0.userId, name: $0.name, role: new) : $0 })
                            }
                        })) {
                        Text("Editor").tag(Course.Access.Role.editor)
                        Text("Learner").tag(Course.Access.Role.learner)
                    }
                    .swipeActions {
                        Button("Remove", role: .destructive) {
                            Haptics.warning()
                            Task { await store.setAccess(access.filter { $0.userId != entry.userId }) }
                        }
                    }
                    .contextMenu {
                        Button("Remove", role: .destructive) {
                            Task { await store.setAccess(access.filter { $0.userId != entry.userId }) }
                        }
                    }
                }
            } header: {
                Text("People")
            } footer: {
                Text("Owners publish and manage access. Editors change steps. Learners take the lesson.")
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Access")
        .task { people = await store.hubPeople() }
    }

    private func candidates(_ access: [Course.Access]) -> [HubUser] {
        let taken = Set(access.map(\.userId) + [store.course?.owner?.id].compactMap { $0 })
        return people.filter { !taken.contains($0.id) }
    }
}
