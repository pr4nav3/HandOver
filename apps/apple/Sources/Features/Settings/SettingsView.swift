import SwiftUI

/// Placeholder with just enough to connect. The Settings builder replaces this (see README.md here).
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var address = ""

    var body: some View {
        Form {
            Section("Hub") {
                LabeledContent("Status", value: model.connection.label)
                if let hub = model.hub { LabeledContent("Address", value: hub.displayName) }
                TextField("192.168.1.20:8000", text: $address)
                    .autocorrectionDisabled()
                    #if os(iOS)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.URL)
                    #endif
                    .onSubmit(connect)
                Button("Connect", action: connect).disabled(address.isEmpty)
                if let error = model.errorMessage { Text(error).foregroundStyle(.red) }
            }
            if !model.recents.isEmpty {
                Section("Recent") {
                    ForEach(model.recents, id: \.self) { hub in
                        Button(hub.displayName) { model.connect(to: hub) }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .navigationTitle("Settings")
    }

    private func connect() {
        if model.connect(text: address) { address = "" }
    }
}

#Preview {
    NavigationStack { SettingsView() }.environment(AppModel.preview())
}
