import SwiftUI

/// One theme's card (THEMES.md, Theme picker): a mini preview in the theme's own fixed colors (both looks side
/// by side for themes that follow the system), then the name and its one line.
struct ThemeCard: View {
    let id: ThemeID
    var selected: Bool
    var compact = false
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            HStack(spacing: 0) {
                switch id.looks {
                case .followsSystem:
                    ThemeSwatch(id: id, dark: false, tight: compact)
                    ThemeSwatch(id: id, dark: true, tight: compact)
                case .alwaysLight:
                    ThemeSwatch(id: id, dark: false, tight: compact)
                case .alwaysDark:
                    ThemeSwatch(id: id, dark: true, tight: compact)
                }
            }
            .frame(height: compact ? 64 : 76)
            .clipShape(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: HORadius.control, style: .continuous)
                .strokeBorder(theme.colors.line, lineWidth: HOLine.width))
            .overlay(alignment: .topTrailing) {
                if selected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.body)
                        .symbolRenderingMode(.palette)
                        .foregroundStyle(theme.colors.onAccent, theme.colors.accent)
                        .padding(6)
                }
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(id.name).font(compact ? theme.fonts.callout : theme.fonts.bodyMedium).foregroundStyle(theme.colors.ink)
                    .lineLimit(1).minimumScaleFactor(0.8)
                if !compact {
                    Text(id.blurb).font(theme.fonts.caption).foregroundStyle(theme.colors.ink2).lineLimit(2)
                }
            }
            .padding(.horizontal, 2)
        }
        .padding(HOSpace.s)
        .background(theme.colors.raised, in: RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous)
            .strokeBorder(selected ? theme.colors.accent : theme.colors.line, lineWidth: selected ? 2 : HOLine.width))
        .contentShape(RoundedRectangle(cornerRadius: HORadius.card, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(id.name), \(id.blurb), \(Self.looksWords(id.looks))")
        .accessibilityAddTraits(selected ? [.isSelected, .isButton] : .isButton)
    }

    static func looksWords(_ looks: ThemeID.Looks) -> String {
        switch looks {
        case .followsSystem: "follows system"
        case .alwaysLight: "always light"
        case .alwaysDark: "always dark"
        }
    }
}

/// Paper with a raised card, a line of ink, a line of ink2 and an accent pill, drawn in one fixed look.
struct ThemeSwatch: View {
    let id: ThemeID
    let dark: Bool
    /// Smaller insets, for compact cards in narrow grid columns.
    var tight = false

    var body: some View {
        let look = HOTheme(id, dark: dark)
        let c = look.colors
        ZStack {
            c.paper
            GrainOverlay()
            VStack(alignment: .leading, spacing: 5) {
                Capsule().fill(c.ink).frame(maxWidth: 34).frame(height: 5)
                Capsule().fill(c.ink2).frame(maxWidth: 24).frame(height: 4)
                Spacer(minLength: 0)
                Capsule().fill(c.accent).frame(maxWidth: 26).frame(height: 10)
            }
            .padding(tight ? 6 : 8)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(c.raised, in: RoundedRectangle(cornerRadius: 7, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).strokeBorder(c.line, lineWidth: HOLine.width))
            .padding(tight ? 5 : 9)
        }
        .environment(\.theme, look)
        .environment(\.colorScheme, dark ? .dark : .light)
    }
}

/// The theme picker for Settings, Appearance (THEMES.md, Theme picker): appearance, search, then the four
/// groups as a grid. Picking applies at once to the whole app.
struct ThemePickerView: View {
    @AppStorage(ThemeStore.themeKey) private var stored = ThemeID.fallback.rawValue
    @AppStorage(ThemeStore.appearanceKey) private var appearance = ThemeAppearance.system.rawValue
    @Environment(\.theme) private var theme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var query = ""

    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: HOSpace.m, alignment: .top), count: sizeClass == .compact ? 2 : 4)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: HOSpace.xl) {
                VStack(alignment: .leading, spacing: HOSpace.s) {
                    AppearancePicker(selection: $appearance)
                    Text("Themes with one look keep it.")
                        .font(theme.fonts.footnote).foregroundStyle(theme.colors.ink2)
                        .padding(.horizontal, HOSpace.xs)
                }
                ForEach(ThemeID.Group.allCases) { group in
                    let themes = group.themes.filter(matches)
                    if !themes.isEmpty {
                        VStack(alignment: .leading, spacing: HOSpace.s) {
                            SectionHeader(group.title)
                            LazyVGrid(columns: columns, spacing: HOSpace.m) {
                                ForEach(themes) { id in
                                    Button { pick(id) } label: { ThemeCard(id: id, selected: id.rawValue == stored) }
                                        .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                }
                if ThemeID.allCases.filter(matches).isEmpty {
                    HOEmptyState(symbol: "magnifyingglass", title: "No themes match", message: "Try another word.")
                }
            }
            .padding(sizeClass == .compact ? HOSpace.l : HOSpace.xl)
        }
        .hoPaperBackground()
        .searchable(text: $query, prompt: "Search \(ThemeID.allCases.count) themes")
        .navigationTitle("Theme")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
    }

    private func matches(_ id: ThemeID) -> Bool {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return true }
        return [id.name, id.blurb, id.group.title, id.keywords].joined(separator: " ").lowercased().contains(needle)
    }

    private func pick(_ id: ThemeID) {
        Haptics.tap()
        stored = id.rawValue
    }
}

/// System, Light, Dark.
struct AppearancePicker: View {
    @Binding var selection: String

    var body: some View {
        Picker("Appearance", selection: $selection) {
            ForEach(ThemeAppearance.allCases) { Text($0.title).tag($0.rawValue) }
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .sensoryFeedback(.selection, trigger: selection)
    }
}

#Preview("Theme picker") {
    NavigationStack { ThemePickerView() }
        .handOverTheme(.system, dark: false)
}
