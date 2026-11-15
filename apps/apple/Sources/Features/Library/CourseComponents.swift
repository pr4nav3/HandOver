import SwiftUI

// Small pieces shared by Library, Lesson detail, Teach and the editor (DESIGN.md 3.10, 3.15.1, 3.21, 3.23).

/// What a course card or row shows, from either the course API or a legacy lesson list.
struct CourseCardItem: Identifiable, Hashable, Sendable {
    var id: String
    var title: String
    var covers: [URL]
    var steps: Int
    var duration: Double?
    /// Shown as a badge when it is not published (only owners and editors see such courses).
    var status: CourseStatus?
    var progress: CourseProgress?
    var ownerId: String?
    var ownerName: String?

    var meta: String { CourseFormat.meta(steps: steps, duration: duration) }
    var badge: CourseStatus? { status == .published ? nil : status }
}

/// "Draft", "Published" or "Unlisted" (SCREENS.md 15.1), plus "Processing" while a job runs.
struct CourseStatusBadge: View {
    enum Kind: Hashable { case status(CourseStatus), processing, failed }
    var kind: Kind
    @Environment(\.theme) private var theme

    init(_ status: CourseStatus) { kind = .status(status) }
    init(kind: Kind) { self.kind = kind }

    var body: some View {
        HStack(spacing: HOSpace.xs) {
            switch kind {
            case .processing:
                ProgressView().controlSize(.mini)
            case .status(.unlisted):
                Image(systemName: "link").imageScale(.small)
            case .failed:
                Image(systemName: "xmark.circle.fill").imageScale(.small)
            default:
                Circle().fill(tone).frame(width: 6, height: 6)
            }
            Text(label)
        }
        .font(theme.fonts.badge)
        .foregroundStyle(text)
        .padding(.horizontal, HOSpace.s)
        .padding(.vertical, 3)
        .frame(minHeight: HOSize.badge)
        .background(fill, in: Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
    }

    private var label: String {
        switch kind {
        case .status(let s): s.title
        case .processing: "Processing"
        case .failed: "Failed"
        }
    }

    private var tone: Color {
        switch kind {
        case .status(.published): theme.colors.good
        case .failed: theme.colors.bad
        default: theme.colors.idle
        }
    }

    private var text: Color {
        switch kind {
        case .status(.published): theme.colors.good
        case .failed: theme.colors.bad
        default: theme.colors.ink2
        }
    }

    private var fill: Color {
        switch kind {
        case .status(.published): theme.colors.goodWash
        case .failed: theme.colors.badWash
        default: theme.colors.well
        }
    }
}

/// The cover on the stage color, 16:9, with a continuous corner.
struct CourseCover: View {
    var covers: [URL]
    var radius: CGFloat = HORadius.card

    var body: some View {
        HubImage(covers, symbol: "film")
            .aspectRatio(16 / 9, contentMode: .fit)
            .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

/// A Library card (SCREENS.md 5): cover, title, meta, badge, progress.
struct CourseCardView: View {
    var item: CourseCardItem
    var continueStyle = false
    @Environment(\.theme) private var theme

    var body: some View {
        VStack(alignment: .leading, spacing: HOSpace.s) {
            CourseCover(covers: item.covers, radius: HORadius.card)
                .overlay(alignment: .topTrailing) { corner.padding(HOSpace.s) }
                .overlay(alignment: .topLeading) {
                    if let badge = item.badge { CourseStatusBadge(badge).padding(HOSpace.s) }
                }
            Text(item.title)
                .font(theme.fonts.headline)
                .foregroundStyle(theme.colors.ink)
                .lineLimit(2, reservesSpace: true)
                .multilineTextAlignment(.leading)
            Text(metaLine)
                .font(theme.fonts.callout)
                .foregroundStyle(theme.colors.ink2)
                .lineLimit(1)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private var metaLine: String {
        if continueStyle, let p = item.progress {
            return "Step \(min(p.lastStepsDone + 1, max(1, p.total))) of \(p.total)"
        }
        return item.meta
    }

    @ViewBuilder private var corner: some View {
        if let p = item.progress, p.isInProgress, continueStyle {
            ProgressRing(fraction: p.fraction)
                .padding(5)
                .background(.ultraThinMaterial, in: Circle())
                .environment(\.colorScheme, .dark)
        } else if item.progress?.isCompleted == true {
            Image(systemName: "checkmark.circle.fill")
                .font(.title3)
                .symbolRenderingMode(.palette)
                .foregroundStyle(.white, theme.colors.good)
                .accessibilityLabel("Completed")
        }
    }
}

/// A Library row on iPhone (DESIGN.md 3.10 lesson row).
struct CourseRowView: View {
    var item: CourseCardItem
    @Environment(\.theme) private var theme

    var body: some View {
        HStack(spacing: HOSpace.m) {
            HubImage(item.covers, symbol: "film")
                .frame(width: 64, height: 40)
                .clipShape(RoundedRectangle(cornerRadius: HORadius.small, style: .continuous))
            VStack(alignment: .leading, spacing: HOSpace.xxs) {
                Text(item.title)
                    .font(theme.fonts.bodyMedium)
                    .foregroundStyle(theme.colors.ink)
                    .lineLimit(2)
                HStack(spacing: HOSpace.s) {
                    Text(item.meta)
                        .font(theme.fonts.callout)
                        .foregroundStyle(theme.colors.ink2)
                    if let badge = item.badge { CourseStatusBadge(badge) }
                }
            }
            Spacer(minLength: 0)
            if let p = item.progress {
                if p.isCompleted {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(theme.colors.good)
                        .accessibilityLabel("Completed")
                } else if p.isInProgress {
                    ProgressRing(fraction: p.fraction, size: 20)
                }
            }
        }
        .padding(.horizontal, HOSpace.l)
        .padding(.vertical, HOSpace.m)
        .frame(minHeight: 64)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}

/// Read-only stars with the average (SCREENS.md 6, item 7).
struct CourseRatingLine: View {
    var summary: RatingSummary
    @Environment(\.theme) private var theme

    var body: some View {
        if let line = summary.line, let average = summary.average {
            HStack(spacing: HOSpace.s) {
                HStack(spacing: 2) {
                    ForEach(1...5, id: \.self) { i in
                        Image(systemName: star(i, average))
                            .foregroundStyle(theme.isMono ? theme.colors.ink : theme.colors.accent)
                    }
                }
                .font(.system(size: 14))
                Text(line).font(theme.fonts.callout).foregroundStyle(theme.colors.ink2)
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel("Rated \(line)")
        }
    }

    private func star(_ i: Int, _ average: Double) -> String {
        if average >= Double(i) - 0.25 { return "star.fill" }
        if average >= Double(i) - 0.75 { return "star.leadinghalf.filled" }
        return "star"
    }
}

/// A padded card filling the width, on the design system's `hoCard` surface.
struct CourseRaisedCard: ViewModifier {
    var radius: CGFloat = HORadius.card
    var padding: CGFloat = HOSpace.l

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .hoCard(radius: radius)
    }
}

extension View {
    func raisedCard(radius: CGFloat = HORadius.card, padding: CGFloat = HOSpace.l) -> some View {
        modifier(CourseRaisedCard(radius: radius, padding: padding))
    }

    /// The section header style (DESIGN.md 2.2 `section`).
    func sectionHeaderStyle(_ theme: any Theme) -> some View {
        font(theme.fonts.section).foregroundStyle(theme.colors.ink2).textCase(nil)
    }
}
