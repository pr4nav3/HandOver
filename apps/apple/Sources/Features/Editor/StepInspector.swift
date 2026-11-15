import SwiftUI

/// The step inspector keeps the decisions needed for one step visible. Less frequent production controls stay
/// collapsed so reviewing titles, timing and checks does not become a long settings form.
struct EditorStepInspector: View {
    var store: EditorStore
    var index: Int
    var hub: HubURL?
    @Environment(\.theme) private var theme
    @State private var confirmDelete = false
    @State private var voice: String?
    @State private var showCaptions = false
    @State private var showVoiceover = false

    var body: some View {
        if let step = store.lesson.steps[safe: index] {
            Form {
                titleSection(step)
                timeSection(step)
                checkSection(step)
                mistakeSection
                if store.capabilities.captions { captionsDisclosure(step) }
                if store.capabilities.voiceover { voiceoverDisclosure(step) }
                Section {
                    Button("Delete Step", systemImage: "trash", role: .destructive) { confirmDelete = true }
                        .disabled(store.lesson.steps.count < 2 || store.isBusy)
                }
            }
            .formStyle(.grouped)
            .scrollContentBackground(.hidden)
            .background(theme.colors.paper)
            .disabled(!store.permissions.canEdit)
            .confirmationDialog("Delete Step \(index + 1)?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete Step", role: .destructive) {
                    Haptics.warning()
                    Task { await store.perform(.delete(n: index + 1)) }
                }
            } message: {
                Text("Its time joins the step before it.")
            }
        } else {
            HOEmptyState(symbol: "list.number", title: "No step selected")
        }
    }

    // MARK: - Sections

    private func titleSection(_ step: Step) -> some View {
        Section {
            TextField("Step title", text: binding(\.title) { EditorStepFields(title: $0) },
                      prompt: Text("Fold the corners to the center"))
        } header: {
            Text("Step \(index + 1) of \(store.lesson.steps.count)").sectionHeaderStyle(theme)
        }
    }

    private func timeSection(_ step: Step) -> some View {
        Section("Time") {
            EditorTimeField(label: "Start", seconds: step.startSeconds ?? 0, disabled: store.isBusy) { value in
                Task { await store.setTimes(step: index, start: value, end: nil) }
            }
            EditorTimeField(label: "End", seconds: step.endSeconds ?? 0, disabled: store.isBusy) { value in
                Task { await store.setTimes(step: index, start: nil, end: value) }
            }
        }
    }

    private func checkSection(_ step: Step) -> some View {
        Section {
            Picker("How it is checked", selection: Binding(
                get: { step.checkType },
                set: { store.update(step: index, EditorStepFields(checkType: $0)) })) {
                Label("Camera", systemImage: "viewfinder").tag(Step.CheckType.camera)
                Label("Manual", systemImage: "hand.tap").tag(Step.CheckType.manual)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            if index == 0 && !step.isManual {
                Text("Step 1 is often better as Manual: the camera has nothing to compare to yet.")
                    .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
            }
            if !step.isManual {
                TextField("Check question", text: binding(\.checkQuestion) { EditorStepFields(checkQuestion: $0) },
                          prompt: Text("Is the paper folded into a small square with four flaps?"), axis: .vertical)
                    .lineLimit(1...4)
                if let hub {
                    HubImage(hub.fileURL(lesson: store.lessonId, path: step.refFrame, rev: store.revision), contentMode: .fit)
                        .aspectRatio(16 / 9, contentMode: .fit)
                        .frame(maxHeight: 128)
                        .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
                        .accessibilityLabel("Reference frame for step \(index + 1)")
                }
                if store.capabilities.selfTest { selfTest(step) }
            }
        } header: {
            Text("How It Is Checked").sectionHeaderStyle(theme)
        }
    }

    @ViewBuilder private func selfTest(_ step: Step) -> some View {
        Button {
            Task { await store.testQuestion(step: index) }
        } label: {
            HStack {
                Label("Test This Question", systemImage: "checkmark.seal")
                Spacer()
                if store.testing == index { ProgressView().controlSize(.small) }
            }
        }
        .disabled(store.testing != nil || store.isBusy)
        if let result = step.selfTest {
            EditorSelfTestCard(result: result, isFirstStep: index == 0) {
                store.update(step: index, EditorStepFields(checkType: .manual))
            }
        }
    }

    private var mistakeSection: some View {
        Section {
            TextField("What do people get wrong here?", text: binding(\.commonMistake) { EditorStepFields(commonMistake: $0) },
                      prompt: Text("Flip it over first."), axis: .vertical)
                .lineLimit(1...3)
        } header: {
            Text("Feedback when stuck").sectionHeaderStyle(theme)
        }
    }

    private func captionsDisclosure(_ step: Step) -> some View {
        Section {
            DisclosureGroup(isExpanded: $showCaptions) {
                captionsFields(step)
            } label: {
                Label("Captions", systemImage: "captions.bubble")
            }
        }
    }

    @ViewBuilder private func captionsFields(_ step: Step) -> some View {
        let list = store.cues[index] ?? []
        ForEach(Array(list.enumerated()), id: \.element.id) { cueIndex, cue in
            HStack(alignment: .firstTextBaseline, spacing: HOSpace.s) {
                Text(TimeCode.format(cue.start))
                    .font(theme.fonts.code)
                    .foregroundStyle(theme.colors.ink2)
                TextField("Caption", text: Binding(
                    get: { cue.text },
                    set: { text in
                        var next = list
                        next[cueIndex].text = text
                        store.update(captions: next, step: index)
                    }), axis: .vertical)
            }
            .swipeActions {
                Button("Delete", role: .destructive) {
                    var next = list
                    next.remove(at: cueIndex)
                    store.update(captions: next, step: index)
                }
            }
            .contextMenu {
                Button("Delete Line", systemImage: "trash", role: .destructive) {
                    var next = list
                    next.remove(at: cueIndex)
                    store.update(captions: next, step: index)
                }
            }
        }
        Button("Add Line", systemImage: "plus") {
            let length = CourseFormat.expertSeconds(step) ?? 2
            let start = min(list.last.map { $0.end } ?? 0, max(0, length - 0.5))
            var next = list
            next.append(EditorCaptionCue(start: start, end: min(length, start + 2), text: ""))
            store.update(captions: next, step: index)
        }
    }

    private func voiceoverDisclosure(_ step: Step) -> some View {
        let info = store.voiceover
        return Section {
            DisclosureGroup(isExpanded: $showVoiceover) {
                Picker("Voice", selection: $voice) {
                    Text("Hub Default").tag(String?.none)
                    ForEach(EditorVoiceCatalog.all) { Text($0.name).tag(String?.some($0.id)) }
                }
                HStack {
                    Button("Regenerate") { Task { await store.regenerateVoiceover(step: index, voice: voice) } }
                    Spacer()
                    if store.voiceBusy { ProgressView().controlSize(.small) }
                    if info != nil {
                        Button("Remove", role: .destructive) { Task { await store.removeVoiceover() } }
                    }
                }
                .buttonStyle(.borderless)
                .disabled(store.voiceBusy || store.isBusy)
            } label: {
                Label(info?.covers(step: index + 1) == true ? "Voiceover on" : "Original sound",
                      systemImage: "waveform")
            }
        }
        .onAppear { voice = info?.voice }
    }

    /// A text binding that edits on this device at once and saves after a pause.
    private func binding(_ key: KeyPath<Step, String>, _ make: @escaping (String) -> EditorStepFields) -> Binding<String> {
        Binding(get: { store.lesson.steps[safe: index]?[keyPath: key] ?? "" },
                set: { store.update(step: index, make($0)) })
    }
}

/// "Test This Question" results (SCREENS.md 14.3).
struct EditorSelfTestCard: View {
    var result: Step.SelfTest
    var isFirstStep: Bool
    var makeManual: () -> Void
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            row("On this step's frame", result.own, expected: .yes)
            if !isFirstStep { row("On the previous step's frame", result.prev, expected: .no) }
            Text(result.ok ? "Works. The question tells this step apart."
                 : "Might misfire. Try a more specific question, or make this step Manual.")
                .font(theme.fonts.callout)
                .foregroundStyle(result.ok ? theme.colors.good : theme.colors.caution)
            if !result.ok {
                Button("Make Manual", action: makeManual).buttonStyle(HOButtonStyle(.quiet, size: .small))
            }
            if result.mock == true {
                Label("Simulated check. This result does not test the question.", systemImage: "testtube.2")
                    .font(theme.fonts.footnote)
                    .foregroundStyle(theme.colors.caution)
            }
        }
        .padding(.vertical, HOSpace.xs)
        .accessibilityElement(children: .combine)
    }

    private func row(_ label: String, _ verdict: Verdict, expected: Verdict) -> some View {
        HStack {
            Text(label).font(theme.fonts.body).foregroundStyle(theme.colors.ink)
            Spacer()
            Text(verdict.rawValue.capitalized)
                .font(theme.fonts.bodyMedium)
                .foregroundStyle(verdict == expected ? theme.colors.good : theme.colors.caution)
        }
    }
}

/// A time in `MM:SS.s` with 0.1 s steppers; commits on Return or a stepper tap.
struct EditorTimeField: View {
    var label: String
    var seconds: Double
    var disabled: Bool
    var commit: (Double) -> Void
    @State private var text = ""
    @Environment(\.theme) private var theme

    var body: some View {
        LabeledContent(label) {
            HStack(spacing: HOSpace.s) {
                TextField(label, text: $text)
                    .labelsHidden()
                    .font(theme.fonts.code)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: 90)
                    .onSubmit { if let value = TimeCode.seconds(text) { commit(value) } else { text = TimeCode.format(seconds) } }
                Stepper(label, onIncrement: { commit(seconds + 0.1) }, onDecrement: { commit(max(0, seconds - 0.1)) })
                    .labelsHidden()
            }
        }
        .disabled(disabled)
        .onAppear { text = TimeCode.format(seconds) }
        .onChange(of: seconds) { text = TimeCode.format(seconds) }
    }
}

fileprivate extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
